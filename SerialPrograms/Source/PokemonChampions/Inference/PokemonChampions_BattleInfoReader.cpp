/*  Pokemon Champions Battle Info Tab Reader
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include <cmath>
#include <cstdint>
#include <vector>
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "PokemonChampions_AbilityNameReader.h"   //  AbilityNameOCR
#include "PokemonChampions_BattleHUDReader.h"     //  SpeciesNameOCR + raw_ocr_numbers + parse_fraction
#include "PokemonChampions_ItemNameReader.h"      //  ItemNameOCR
#include "PokemonChampions_BattleInfoReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


// ─── Type pill color → slug ─────────────────────────────────────────
//
//  Pokemon type color palette (PS canonical). Pixel-mean classifier:
//  pick the entry with smallest squared distance.

struct TypeRef{
    const char* slug;
    int r, g, b;
};

static const TypeRef TYPE_REFS[] = {
    {"normal",   168, 168, 120},
    {"fire",     240, 128,  48},
    {"water",    104, 144, 240},
    {"electric", 248, 208,  48},
    {"grass",    120, 200,  80},
    {"ice",      152, 216, 216},
    {"fighting", 192,  48,  40},
    {"poison",   160,  64, 160},
    {"ground",   224, 192, 104},
    {"flying",   168, 144, 240},
    {"psychic",  248,  88, 136},
    {"bug",      168, 184,  32},
    {"rock",     184, 160,  56},
    {"ghost",    112,  88, 152},
    {"dragon",   112,  56, 248},
    {"dark",      96,  72,  64},
    {"steel",    184, 184, 208},
    {"fairy",    232, 152, 232},
};

static std::string classify_type(int r, int g, int b){
    int best_idx = -1;
    long best_d = 0;
    for (size_t i = 0; i < sizeof(TYPE_REFS)/sizeof(TYPE_REFS[0]); i++){
        long dr = r - TYPE_REFS[i].r;
        long dg = g - TYPE_REFS[i].g;
        long db = b - TYPE_REFS[i].b;
        long d = dr*dr + dg*dg + db*db;
        if (best_idx < 0 || d < best_d){ best_idx = (int)i; best_d = d; }
    }
    return best_idx >= 0 ? TYPE_REFS[best_idx].slug : "";
}


// ─── Multiplier text → boost stage ──────────────────────────────────
//
//  Pokemon stat multipliers per stage (canonical):
//    +6 = 4.0   +5 = 3.5   +4 = 3.0   +3 = 2.5   +2 = 2.0   +1 = 1.5
//     0 = 1.0
//    -1 = 0.67  -2 = 0.5   -3 = 0.4   -4 = 0.33  -5 = 0.29  -6 = 0.25
//
//  Accuracy/Evasion use a slightly different table but the OCR'd numbers
//  follow the same "decimal between 0.25 and 4.0" pattern, so a nearest-
//  match works for the 5 main stats too. The 7th decimal place varies
//  across game truncations (×0.66 vs ×0.67), so we round and snap.

static int8_t multiplier_to_stage(double mult){
    if (mult <= 0) return 0;
    struct Pair { double mult; int8_t stage; };
    static const Pair table[] = {
        {4.00,  6}, {3.50,  5}, {3.00,  4}, {2.50,  3}, {2.00,  2},
        {1.50,  1}, {1.00,  0}, {0.67, -1}, {0.50, -2}, {0.40, -3},
        {0.33, -4}, {0.29, -5}, {0.25, -6},
    };
    int best = 6;
    double best_d = 1e9;
    for (const auto& p : table){
        double d = std::fabs(mult - p.mult);
        if (d < best_d){ best_d = d; best = p.stage; }
    }
    return (int8_t)best;
}

//  Parse "x1.0", "X0.67", "*1.5" etc. -> stage. Tesseract often reads the
//  '×' glyph as 'x' / 'X' / '*'; we strip everything but digits and '.'.
static int8_t parse_multiplier_stage(const std::string& raw){
    std::string clean;
    for (char c : raw){
        if ((c >= '0' && c <= '9') || c == '.') clean += c;
    }
    if (clean.empty()) return 0;
    try {
        return multiplier_to_stage(std::stod(clean));
    } catch (...) {
        return 0;
    }
}


// ─── Icon-bar selected-slot detector ────────────────────────────────
//
//  When an icon is the focused mon, its background pill is bright yellow
//  (R+G high, B low). When it's a non-selected slot, the bg is purple
//  (R high, G low, B high). Score "yellowness" per box; pick the highest.

static double yellow_score(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return -1.0;
    ImageStats st = image_stats(crop);
    int r = (int)st.average.r;
    int g = (int)st.average.g;
    int b = (int)st.average.b;
    //  Yellow: R and G high, B low. Score = (R+G)/2 - B, clipped to 0.
    int score = (r + g) / 2 - b;
    return score > 0 ? double(score) : 0.0;
}


// ─── Reader impl ────────────────────────────────────────────────────

BattleInfoReader::BattleInfoReader(Language language)
    : m_language(language)
{
    //  Boxes mirror dashboard CROP_DEFS["BattleInfoReader"] — keep in sync
    //  with dashboard/server.py.

    //  Top icon row.
    m_own_icon[0]   = ImageFloatBox(0.3423, 0.0722, 0.0404, 0.0728);
    m_own_icon[1]   = ImageFloatBox(0.4238, 0.0722, 0.0404, 0.0728);
    m_own_icon_solo = ImageFloatBox(0.3821, 0.0706, 0.0411, 0.0814);
    m_opp_icon[0]   = ImageFloatBox(0.5358, 0.0722, 0.0404, 0.0728);
    m_opp_icon[1]   = ImageFloatBox(0.6169, 0.0716, 0.0408, 0.0743);

    m_species_name = ImageFloatBox(0.1973, 0.2228, 0.1582, 0.0408);
    m_hp_text      = ImageFloatBox(0.3372, 0.2772, 0.0782, 0.0377);
    m_type[0]      = ImageFloatBox(0.2280, 0.3336, 0.0670, 0.0383);
    m_type[1]      = ImageFloatBox(0.3393, 0.3353, 0.0655, 0.0364);
    m_ability      = ImageFloatBox(0.3125, 0.3881, 0.1101, 0.0431);
    m_item         = ImageFloatBox(0.2887, 0.4394, 0.1351, 0.0449);

    //  atk, def, spa, spd, spe, accuracy, evasiveness.
    m_multiplier[0] = ImageFloatBox(0.3840, 0.5190, 0.0272, 0.0352);
    m_multiplier[1] = ImageFloatBox(0.3839, 0.5657, 0.0257, 0.0348);
    m_multiplier[2] = ImageFloatBox(0.3848, 0.6074, 0.0311, 0.0357);
    m_multiplier[3] = ImageFloatBox(0.3853, 0.6495, 0.0299, 0.0418);
    m_multiplier[4] = ImageFloatBox(0.3847, 0.6942, 0.0269, 0.0383);
    m_multiplier[5] = ImageFloatBox(0.3849, 0.7620, 0.0272, 0.0393);
    m_multiplier[6] = ImageFloatBox(0.3848, 0.8060, 0.0249, 0.0405);

    m_status_first          = ImageFloatBox(0.5275, 0.3138, 0.2084, 0.0471);
    m_status_first_duration = ImageFloatBox(0.7350, 0.3138, 0.0850, 0.0471);
}


BattleInfoResult BattleInfoReader::read(
    Logger& logger, const ImageViewRGB32& screen
) const{
    BattleInfoResult out;

    //  ── Selected slot via yellow-pill score ──
    //
    //  We score the 4 doubles icons + the singles-center icon. The two
    //  highest plausible candidates are checked; the single best wins. If
    //  the SOLO box wins by a margin over both own_icon[0/1], we treat it
    //  as singles (own slot 0).
    struct Candidate{ const char* tag; double score; };
    Candidate cands[5] = {
        {"own_0", yellow_score(extract_box_reference(screen, m_own_icon[0]))},
        {"own_1", yellow_score(extract_box_reference(screen, m_own_icon[1]))},
        {"own_solo", yellow_score(extract_box_reference(screen, m_own_icon_solo))},
        {"opp_0", yellow_score(extract_box_reference(screen, m_opp_icon[0]))},
        {"opp_1", yellow_score(extract_box_reference(screen, m_opp_icon[1]))},
    };
    int best = 0;
    for (int i = 1; i < 5; i++){
        if (cands[i].score > cands[best].score) best = i;
    }
    //  Floor: yellow score must clear ~30 to count as "highlighted" (the
    //  unselected purple pill yields ~0–10 typically).
    if (cands[best].score >= 30.0){
        out.focused.valid = true;
        std::string tag = cands[best].tag;
        if (tag == "own_solo"){ out.focused.side = "own"; out.focused.slot = 0; }
        else if (tag == "own_0"){ out.focused.side = "own"; out.focused.slot = 0; }
        else if (tag == "own_1"){ out.focused.side = "own"; out.focused.slot = 1; }
        else if (tag == "opp_0"){ out.focused.side = "opp"; out.focused.slot = 0; }
        else if (tag == "opp_1"){ out.focused.side = "opp"; out.focused.slot = 1; }
    }

    bool is_own = out.focused.valid && out.focused.side == "own";

    //  ── Species ──
    {
        ImageViewRGB32 cropped = extract_box_reference(screen, m_species_name);
        OCR::StringMatchResult result = SpeciesNameOCR::instance().read_substring(
            logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
        );
        if (!result.results.empty()){
            out.species = result.results.begin()->second.token;
        }
    }

    //  ── HP ──
    //
    //  Own panel: "X/Y"; opp panel: "NN%". Both go through raw_ocr_numbers.
    {
        ImageViewRGB32 cropped = extract_box_reference(screen, m_hp_text);
        std::string raw = raw_ocr_numbers(cropped);
        if (raw.find('/') != std::string::npos){
            auto frac = parse_fraction(raw);
            out.hp_current = frac.first;
            out.hp_max = frac.second;
        }else{
            //  Strip everything but digits, parse as percent.
            std::string digits;
            for (char c : raw){ if (c >= '0' && c <= '9') digits += c; }
            if (!digits.empty()){
                try { int n = std::stoi(digits); if (n >= 0 && n <= 100) out.hp_pct = n; }
                catch (...) {}
            }
        }
    }

    //  ── Types ──
    for (size_t i = 0; i < 2; i++){
        ImageStats st = image_stats(extract_box_reference(screen, m_type[i]));
        out.types[i] = classify_type(
            (int)st.average.r, (int)st.average.g, (int)st.average.b
        );
    }

    //  ── Ability + Item (own only) ──
    if (is_own){
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, m_ability);
            OCR::StringMatchResult result = AbilityNameOCR::instance().read_substring(
                logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
            );
            if (!result.results.empty()){
                out.ability = result.results.begin()->second.token;
            }
        }
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, m_item);
            OCR::StringMatchResult result = ItemNameOCR::instance().read_substring(
                logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
            );
            if (!result.results.empty()){
                out.item = result.results.begin()->second.token;
            }
        }
    }

    //  ── Boost stages from multiplier text (5 main stats) ──
    for (size_t i = 0; i < 5; i++){
        ImageViewRGB32 cropped = extract_box_reference(screen, m_multiplier[i]);
        std::string raw = raw_ocr_numbers(cropped);
        out.boosts[i] = parse_multiplier_stage(raw);
    }
    //  Accuracy/Evasion (indices 5/6) read but currently discarded — the
    //  tracker has no slots for them. Could add later.

    //  ── First active status row ──
    {
        ImageViewRGB32 cropped = extract_box_reference(screen, m_status_first);
        std::string raw = OCR::ocr_read(
            Language::English, cropped, OCR::PageSegMode::SINGLE_LINE
        );
        //  Trim trailing whitespace; treat anything starting with non-letter as empty.
        while (!raw.empty() && (raw.back() == ' ' || raw.back() == '\n' ||
                                raw.back() == '\r' || raw.back() == '\t')){
            raw.pop_back();
        }
        if (!raw.empty()){
            out.status_text = raw;
        }
    }
    {
        ImageViewRGB32 cropped = extract_box_reference(screen, m_status_first_duration);
        std::string raw = raw_ocr_numbers(cropped);
        auto frac = parse_fraction(raw);
        out.status_turns_current = frac.first;
        out.status_turns_max = frac.second;
    }

    return out;
}


}}}
