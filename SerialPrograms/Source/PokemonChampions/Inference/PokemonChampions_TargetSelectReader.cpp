/*  Pokemon Champions Target Select Reader
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include "PokemonChampions_TargetSelectReader.h"
#include "PokemonChampions_MoveNameReader.h"

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "CommonTools/OCR/OCR_Routines.h"

#include <algorithm>
#include <cctype>

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


TargetSelectReader::TargetSelectReader(Language language)
    : m_language(language)
{
    //  Mirror dashboard CROP_DEFS["TargetSelectReader"]. Coords saved
    //  via Inspector + extrapolation.
    m_opp_is_targeted[0]   = ImageFloatBox(0.4741, 0.2355, 0.0062, 0.1172);
    m_opp_is_targeted[1]   = ImageFloatBox(0.7338, 0.2340, 0.0045, 0.1228);
    m_own_is_targeted[0]   = ImageFloatBox(0.4741, 0.5832, 0.0053, 0.1030);
    m_own_is_targeted[1]   = ImageFloatBox(0.7334, 0.5714, 0.0053, 0.1117);
    m_opp_effectiveness[0] = ImageFloatBox(0.3083, 0.2308, 0.1190, 0.0269);
    m_opp_effectiveness[1] = ImageFloatBox(0.5658, 0.2300, 0.1056, 0.0285);
    m_own_effectiveness[0] = ImageFloatBox(0.3083, 0.5785, 0.1190, 0.0269);
    m_own_effectiveness[1] = ImageFloatBox(0.5658, 0.5667, 0.1056, 0.0285);
    m_own_move_name[0]     = ImageFloatBox(0.3203, 0.4914, 0.1096, 0.0317);
    m_own_move_name[1]     = ImageFloatBox(0.5778, 0.4914, 0.1096, 0.0317);
}


//  Yellow/green selector vs red/blue not-selected.
//  Empirically the targeted strip reads bright yellow-green (high R + G,
//  low B). Untargeted reads either red-orange (high R, low G/B) or
//  blue-cyan (low R, high B). Discriminator: g >= 150 AND g >= b.
static bool is_color_targeted(const ImageStats& stats){
    return stats.average.g >= 150.0 && stats.average.g >= stats.average.b;
}


//  Same white-text binarization + 3x scale as raw_ocr_numbers, but
//  returns text not digits. Used for effectiveness + move_name strips.
static std::string ocr_text_strip(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return "";
    size_t w = crop.width();
    size_t h = crop.height();
    size_t scale = 3;
    ImageRGB32 bw(w * scale, h * scale);
    size_t white = 0;
    for (size_t y = 0; y < h; y++){
        for (size_t x = 0; x < w; x++){
            uint32_t px = crop.pixel(x, y);
            uint8_t r = (px >> 0)  & 0xFF;
            uint8_t g = (px >> 8)  & 0xFF;
            uint8_t b = (px >> 16) & 0xFF;
            uint8_t mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
            uint8_t mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
            bool is_white = (mn > 180) && (mx - mn < 50);
            if (is_white) white++;
            uint32_t out = is_white ? 0xFF000000 : 0xFFFFFFFF;
            for (size_t sy = 0; sy < scale; sy++){
                for (size_t sx = 0; sx < scale; sx++){
                    bw.pixel(x * scale + sx, y * scale + sy) = out;
                }
            }
        }
    }
    if ((double)white / (double)(w * h) < 0.005) return "";
    return OCR::ocr_read(Language::English, bw, OCR::PageSegMode::SINGLE_LINE);
}


//  Normalize Tesseract text and look up an effectiveness label.
//  Returns one of: "super-effective", "not-very-effective", "no-effect",
//  "neutral", or "" if unrecognized.
static std::string classify_effectiveness(const std::string& raw){
    std::string s;
    s.reserve(raw.size());
    for (char c : raw){
        if (c == '\n' || c == '\r' || c == '\t') s += ' ';
        else s += (char)std::tolower((unsigned char)c);
    }
    auto contains = [&](const char* needle){
        return s.find(needle) != std::string::npos;
    };
    if (contains("super") || contains("effective"))     return "super-effective";
    if (contains("not very") || contains("notvery"))    return "not-very-effective";
    if (contains("no effect") || contains("noeffect"))  return "no-effect";
    //  "Normal" damage on the target select screen sometimes shows no label
    //  at all, sometimes shows "Normal" or similar. Treat any non-empty
    //  read that didn't match the others as neutral.
    if (!s.empty()){
        //  Strip whitespace to detect "no label" reads.
        bool any_alpha = false;
        for (char c : s) if (std::isalpha((unsigned char)c)) { any_alpha = true; break; }
        if (any_alpha) return "neutral";
    }
    return "";
}


static std::string slugify_move(const std::string& text){
    std::string out;
    out.reserve(text.size());
    bool last_dash = true;
    for (char c : text){
        if (std::isalnum((unsigned char)c)){
            out += (char)std::tolower((unsigned char)c);
            last_dash = false;
        }else if (!last_dash && (unsigned char)c < 0x80){
            //  Skip non-ASCII (Tesseract sometimes returns UTF-8 multibyte
            //  sequences from sprite/icon fragments — treat as no-text).
            out += '-';
            last_dash = true;
        }
    }
    while (!out.empty() && out.back() == '-') out.pop_back();
    //  Reject garbage-only outputs (e.g. very short or no alpha).
    bool has_alpha = false;
    for (char c : out) if (std::isalpha((unsigned char)c)) { has_alpha = true; break; }
    if (!has_alpha || out.size() < 3) return "";
    return out;
}


TargetSelectReadout TargetSelectReader::read(Logger& logger, const ImageViewRGB32& screen) const{
    TargetSelectReadout out;

    //  is_targeted: color-classify the selector strips.
    for (size_t i = 0; i < 2; i++){
        const ImageStats opp = image_stats(extract_box_reference(screen, m_opp_is_targeted[i]));
        const ImageStats own = image_stats(extract_box_reference(screen, m_own_is_targeted[i]));
        out.opp_targeted[i] = is_color_targeted(opp);
        out.own_targeted[i] = is_color_targeted(own);
    }

    //  Effectiveness: OCR + classify.
    for (size_t i = 0; i < 2; i++){
        out.opp_effectiveness[i] = classify_effectiveness(
            ocr_text_strip(extract_box_reference(screen, m_opp_effectiveness[i]))
        );
        out.own_effectiveness[i] = classify_effectiveness(
            ocr_text_strip(extract_box_reference(screen, m_own_effectiveness[i]))
        );
    }

    //  Move names: dictionary-matched against the Champions move vocab.
    for (size_t i = 0; i < 2; i++){
        ImageViewRGB32 crop = extract_box_reference(screen, m_own_move_name[i]);
        OCR::StringMatchResult res = MoveNameOCR::instance().read_substring(
            logger, m_language, crop, OCR::WHITE_TEXT_FILTERS()
        );
        if (!res.results.empty()){
            out.own_moves[i] = res.results.begin()->second.token;
        }else{
            //  Fallback: emit raw slug; better than nothing for unknown moves.
            std::string raw = ocr_text_strip(crop);
            out.own_moves[i] = slugify_move(raw);
        }
    }

    logger.log(
        "TargetSelectReader: own_moves=[" + out.own_moves[0] + "," + out.own_moves[1] +
        "] opp_targeted=[" + (out.opp_targeted[0]?"1":"0") + "," + (out.opp_targeted[1]?"1":"0") +
        "] own_targeted=[" + (out.own_targeted[0]?"1":"0") + "," + (out.own_targeted[1]?"1":"0") +
        "] opp_eff=[" + out.opp_effectiveness[0] + "," + out.opp_effectiveness[1] +
        "] own_eff=[" + out.own_effectiveness[0] + "," + out.own_effectiveness[1] + "]"
    );
    return out;
}


}}}
