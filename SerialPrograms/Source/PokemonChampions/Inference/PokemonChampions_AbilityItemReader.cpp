/*  Pokemon Champions Ability/Item Overlay Reader
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include "PokemonChampions_AbilityItemReader.h"
#include "PokemonChampions_AbilityItemTable.h"

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/Language.h"
#include "CommonTools/OCR/OCR_RawOCR.h"

#include <algorithm>
#include <cctype>
#include <cstring>

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Box coords saved by the user via the Inspector on
//  _overlays/ability_item/20260423-183505998294.png. At most one side fires
//  per overlay; singles uses the same boxes as doubles.
AbilityItemReader::AbilityItemReader()
    : m_box_left (0.0805, 0.4349, 0.1023, 0.0754)
    , m_box_right(0.8283, 0.4280, 0.0933, 0.0903)
{}


//  Slugify: lowercase, collapse non-alphanumeric runs into '-', trim '-'.
//  "Rough Skin"   -> "rough-skin"
//  "Sitrus Berry" -> "sitrus-berry"
//  "Choice Specs" -> "choice-specs"
static std::string slugify(const std::string& text){
    std::string out;
    out.reserve(text.size());
    bool last_dash = true;  //  treat leading position as if just emitted dash, to skip leading dashes
    for (char c : text){
        if (std::isalnum((unsigned char)c)){
            out += (char)std::tolower((unsigned char)c);
            last_dash = false;
        }else{
            if (!last_dash){
                out += '-';
                last_dash = true;
            }
        }
    }
    while (!out.empty() && out.back() == '-') out.pop_back();
    return out;
}


//  Same white-text binarization + 3x scale + Tesseract pattern as the HP
//  reader. The overlay text is white on a translucent dark-blue ribbon, so
//  a "max channel high, low saturation" filter works.
std::string AbilityItemReader::ocr_crop(const ImageViewRGB32& crop) const{
    if (crop.width() == 0 || crop.height() == 0) return "";
    size_t w = crop.width();
    size_t h = crop.height();
    size_t scale = 3;
    ImageRGB32 bw(w * scale, h * scale);
    size_t white_pixels = 0;
    size_t total = w * h;
    for (size_t y = 0; y < h; y++){
        for (size_t x = 0; x < w; x++){
            uint32_t pixel = crop.pixel(x, y);
            uint8_t r = (pixel >> 0)  & 0xFF;
            uint8_t g = (pixel >> 8)  & 0xFF;
            uint8_t b = (pixel >> 16) & 0xFF;
            uint8_t mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
            uint8_t mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
            bool is_white = (mn > 180) && (mx - mn < 50);
            if (is_white) white_pixels++;
            uint32_t out = is_white ? 0xFF000000 : 0xFFFFFFFF;
            for (size_t sy = 0; sy < scale; sy++){
                for (size_t sx = 0; sx < scale; sx++){
                    bw.pixel(x * scale + sx, y * scale + sy) = out;
                }
            }
        }
    }

    //  Quick reject: if fewer than 1% of pixels are white, the box is empty.
    //  Real text frames usually have 5-15% white pixels.
    double white_frac = (double)white_pixels / (double)total;
    if (white_frac < 0.01) return "";

    //  Multi-line text — overlay can wrap to 2 lines for longer item names.
    return OCR::ocr_read(Language::English, bw, OCR::PageSegMode::SINGLE_BLOCK);
}


//  Strip whitespace + trailing punctuation; collapse internal whitespace
//  (including newlines) to single spaces.
static std::string normalize(const std::string& s){
    std::string trimmed;
    trimmed.reserve(s.size());
    bool in_space = true;
    for (char c : s){
        if (c == '\n' || c == '\r' || c == '\t' || c == ' '){
            if (!in_space){
                trimmed += ' ';
                in_space = true;
            }
        }else{
            trimmed += c;
            in_space = false;
        }
    }
    while (!trimmed.empty() && (trimmed.back() == ' ' || trimmed.back() == '!'
            || trimmed.back() == '.' || trimmed.back() == '?')){
        trimmed.pop_back();
    }
    while (!trimmed.empty() && trimmed.front() == ' '){
        trimmed.erase(trimmed.begin());
    }
    return trimmed;
}


//  Find the "'s " split, tolerating common OCR variants of the apostrophe:
//    - ASCII '         (single quote)
//    - U+2019 (' )      (curly right quote, UTF-8 0xE2 0x80 0x99)
//    - "                (Tesseract sometimes reads "'s" as just `"`)
//  After the apostrophe, accept an optional 's' and require whitespace.
//  Returns (pokemon_slug, name_slug). Both empty if no split found.
static std::pair<std::string, std::string> split_possessive(const std::string& text){
    auto starts_with_at = [&](size_t i, const char* s) -> size_t {
        size_t n = std::strlen(s);
        if (i + n > text.size()) return 0;
        return text.compare(i, n, s) == 0 ? n : 0;
    };
    static const char* APOS_TOKENS[] = {
        "'", "\xE2\x80\x99",       //  ASCII ' and U+2019 '
        "\"", "\xE2\x80\x9D",      //  ASCII " and U+201D "
        "\xE2\x80\x98", "\xE2\x80\x9C",  //  U+2018 ' and U+201C "
    };
    for (size_t i = 0; i < text.size(); i++){
        size_t apos_len = 0;
        for (const char* tok : APOS_TOKENS){
            apos_len = starts_with_at(i, tok);
            if (apos_len) break;
        }
        if (!apos_len) continue;
        size_t after = i + apos_len;
        //  Optional 's' (handles "Garchomp's" + the OCR variant where the
        //  's' is missing entirely).
        if (after < text.size() && (text[after] == 's' || text[after] == 'S')) after++;
        //  Require whitespace before the rest of the phrase, so we don't
        //  misinterpret e.g. an apostrophe inside the name itself.
        if (after >= text.size() || (text[after] != ' ' && text[after] != '\n'
                && text[after] != '\t')) continue;
        std::string pokemon = text.substr(0, i);
        std::string name = text.substr(after);
        return {slugify(pokemon), slugify(name)};
    }
    return {"", ""};
}


AbilityItemReadout AbilityItemReader::read(Logger& logger, const ImageViewRGB32& screen) const{
    AbilityItemReadout out;

    //  Try left first, then right. Whichever has real text wins.
    ImageViewRGB32 crop_l = extract_box_reference(screen, m_box_left);
    ImageViewRGB32 crop_r = extract_box_reference(screen, m_box_right);

    std::string text_l = ocr_crop(crop_l);
    std::string text_r = ocr_crop(crop_r);

    std::string raw;
    if (!text_l.empty() && text_l.size() >= text_r.size()){
        raw = text_l;
        out.side = "left";
    }else if (!text_r.empty()){
        raw = text_r;
        out.side = "right";
    }else{
        return out;  //  detected stays false
    }

    out.raw_text = normalize(raw);
    auto [poke_slug, name_slug] = split_possessive(out.raw_text);
    if (name_slug.empty()){
        return out;  //  text present but couldn't parse — leave detected=false
    }
    out.pokemon = poke_slug;
    out.name = name_slug;
    AbilityItemKind k = lookup_ability_item_kind(name_slug);
    if (k == AbilityItemKind::UNKNOWN){
        //  Fallback: OCR likely garbled the name (e.g. "Skin" -> "Skir").
        //  Look for the closest known slug within 1 edit. Keep the original
        //  slug in raw_text so the misread is auditable.
        std::string corrected;
        AbilityItemKind fk = fuzzy_lookup_ability_item_kind(name_slug, &corrected, 1);
        if (fk != AbilityItemKind::UNKNOWN && !corrected.empty()){
            out.name = corrected;
            k = fk;
        }
    }
    switch (k){
        case AbilityItemKind::ABILITY: out.kind = "ability"; break;
        case AbilityItemKind::ITEM:    out.kind = "item";    break;
        default:                       out.kind = "unknown"; break;
    }
    out.detected = (k != AbilityItemKind::UNKNOWN);
    logger.log(
        "AbilityItemReader: side=" + out.side + " raw='" + out.raw_text +
        "' -> pokemon='" + out.pokemon + "' name='" + out.name +
        "' kind=" + out.kind
    );
    return out;
}


}}}
