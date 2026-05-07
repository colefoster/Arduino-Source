/*  Pokemon Champions Team Stats Reader
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include <algorithm>
#include <cctype>

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_BattleHUDReader.h"   //  raw_ocr_numbers
#include "PokemonChampions_TeamStatsReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


const char* nature_mod_name(NatureMod m){
    switch (m){
    case NatureMod::NEUTRAL: return "neutral";
    case NatureMod::BOOST:   return "boost";
    case NatureMod::DROP:    return "drop";
    }
    return "?";
}


const char* stat_slot_name(StatSlot s){
    switch (s){
    case StatSlot::HP:  return "hp";
    case StatSlot::ATK: return "atk";
    case StatSlot::DEF: return "def";
    case StatSlot::SPA: return "spa";
    case StatSlot::SPD: return "spd";
    case StatSlot::SPE: return "spe";
    }
    return "?";
}


//  Per-slot anchors (top-left card corner = species/name box origin).
//  Hardcoded from the user-drawn mon_<i>_name boxes in
//  tools/box_definitions.json so any per-slot pixel-tweaks the user made
//  are honored (the parameterized 2×3 grid was off by ~0.011 on row 2).
struct SlotAnchor{ double x, y; };
static constexpr SlotAnchor SLOT_ANCHORS[6] = {
    {0.1391, 0.2778},  //  slot 0 — top-left
    {0.5557, 0.2796},  //  slot 1 — top-right
    {0.1395, 0.4805},  //  slot 2 — mid-left
    {0.5545, 0.4805},  //  slot 3 — mid-right
    {0.1385, 0.6841},  //  slot 4 — bot-left
    {0.5568, 0.6832},  //  slot 5 — bot-right
};

//  Per-stat sub-region offsets relative to the card's species (col_x, row_y)
//  anchor. These come from the user-drawn slot 0 boxes in
//  tools/box_definitions.json, then transposed to the card-local frame.
//
//  Layout per card:
//    col-A: HP / Atk / Def    col-B: SpA / SpD / Spe
//
//  Each stat has 3 boxes: nature (chevron icon), actual (final value), evs
//  (small EV count). HP has nature=neutral always (drawn box but never
//  classified as boost/drop).

struct StatBox{
    double dx, dy, w, h;
};

//  Nature-box deltas relative to each card's name anchor. The user only
//  drew nature chevrons for slot 0; the same constants apply to all
//  slots since the per-card pixel-wobble doesn't materially shift them
//  (the chevron icons are large enough to absorb a few px of drift).
static constexpr StatBox HP_NATURE  {0.0381, 0.0898, 0.0127, 0.0216}; // unused (HP has no nature)
static constexpr StatBox ATK_NATURE {0.0381, 0.0898, 0.0127, 0.0216};
static constexpr StatBox DEF_NATURE {0.0483, 0.1360, 0.0113, 0.0182};
static constexpr StatBox SPA_NATURE {0.2276, 0.0494, 0.0091, 0.0187};
static constexpr StatBox SPD_NATURE {0.2285, 0.0907, 0.0111, 0.0202};
static constexpr StatBox SPE_NATURE {0.2224, 0.1311, 0.0122, 0.0211};

static const StatBox* NATURE_BOXES[6] = {
    &HP_NATURE, &ATK_NATURE, &DEF_NATURE, &SPA_NATURE, &SPD_NATURE, &SPE_NATURE
};

//  Per-slot, per-stat ABSOLUTE boxes for actual + evs fields. Hand-drawn
//  for all 6 slots — extrapolation introduced too much OCR noise because
//  the cards aren't on a perfect grid. Layout: STAT_ABS[slot][stat][sub]
//  where stat = HP/ATK/DEF/SPA/SPD/SPE (0..5), sub = ACTUAL(0)/EVS(1).
//  Generated from tools/box_definitions.json mon_*_*_* entries.
struct AbsBox{ double x, y, w, h; };
static constexpr AbsBox STAT_ABS[6][6][2] = {
    //  ── slot 0 (user-drawn mon_0_* originals — verified 0/34 misreads) ──
    {
        { { 0.2095, 0.3228, 0.0277, 0.0261 }, { 0.2629, 0.3243, 0.0205, 0.0231 } },  // hp
        { { 0.2134, 0.3597, 0.0224, 0.0369 }, { 0.2632, 0.3646, 0.0160, 0.0290 } },  // atk
        { { 0.2097, 0.4052, 0.0272, 0.0292 }, { 0.2638, 0.4039, 0.0144, 0.0290 } },  // def
        { { 0.3952, 0.3228, 0.0271, 0.0266 }, { 0.4483, 0.3233, 0.0158, 0.0256 } },  // spa
        { { 0.3988, 0.3656, 0.0230, 0.0275 }, { 0.4472, 0.3651, 0.0158, 0.0266 } },  // spd
        { { 0.3963, 0.4064, 0.0255, 0.0270 }, { 0.4486, 0.4059, 0.0177, 0.0280 } },  // spe
    },
    //  ── slot 1 (user-drawn poke_1_* originals; def_actual/evs extrapolated
    //         since user only drew SpDef-position "def" — see below) ──
    {
        { { 0.6301, 0.3250, 0.0246, 0.0243 }, { 0.6807, 0.3237, 0.0170, 0.0248 } },  // hp
        { { 0.6293, 0.3636, 0.0249, 0.0280 }, { 0.6807, 0.3631, 0.0154, 0.0277 } },  // atk
        { { 0.6263, 0.4070, 0.0272, 0.0292 }, { 0.6804, 0.4057, 0.0144, 0.0290 } },  // def  (extrapolated)
        { { 0.8153, 0.3212, 0.0218, 0.0298 }, { 0.8632, 0.3227, 0.0179, 0.0259 } },  // spa
        { { 0.8111, 0.3641, 0.0259, 0.0290 }, { 0.8638, 0.3657, 0.0212, 0.0248 } },  // spd  (user labeled "def" but coords = SpDef position; evs widened +0.0015 on right edge ~3px)
        { { 0.8150, 0.4050, 0.0213, 0.0272 }, { 0.8627, 0.4063, 0.0172, 0.0261 } },  // spe
    },
    //  ── slot 2 (user-drawn poke_2_* originals — all 12 fields covered) ──
    {
        { { 0.2123, 0.5247, 0.0246, 0.0261 }, { 0.2628, 0.5249, 0.0167, 0.0259 } },  // hp
        { { 0.2131, 0.5674, 0.0233, 0.0250 }, { 0.2632, 0.5654, 0.0163, 0.0292 } },  // atk
        { { 0.2116, 0.6052, 0.0251, 0.0300 }, { 0.2631, 0.6069, 0.0120, 0.0284 } },  // def
        { { 0.3983, 0.5241, 0.0212, 0.0275 }, { 0.4462, 0.5207, 0.0150, 0.0307 } },  // spa
        { { 0.3957, 0.5643, 0.0241, 0.0298 }, { 0.4453, 0.5670, 0.0158, 0.0257 } },  // spd
        { { 0.3968, 0.6071, 0.0231, 0.0269 }, { 0.4462, 0.6081, 0.0154, 0.0259 } },  // spe
    },
    //  ── slot 3 ──
    {
        { { 0.6251, 0.5220, 0.0287, 0.0293 }, { 0.6801, 0.5235, 0.0213, 0.0291 } },  // hp
        { { 0.6285, 0.5636, 0.0260, 0.0311 }, { 0.6800, 0.5628, 0.0177, 0.0308 } },  // atk
        { { 0.6306, 0.6058, 0.0239, 0.0294 }, { 0.6798, 0.6075, 0.0190, 0.0267 } },  // def
        { { 0.8106, 0.5196, 0.0264, 0.0348 }, { 0.8631, 0.5233, 0.0203, 0.0295 } },  // spa
        { { 0.8107, 0.5651, 0.0267, 0.0290 }, { 0.8631, 0.5646, 0.0176, 0.0293 } },  // spd
        { { 0.8091, 0.6059, 0.0284, 0.0318 }, { 0.8631, 0.6069, 0.0167, 0.0280 } },  // spe
    },
    //  ── slot 4 ──
    {
        { { 0.2102, 0.7231, 0.0266, 0.0321 }, { 0.2628, 0.7246, 0.0180, 0.0303 } },  // hp
        { { 0.2104, 0.7630, 0.0263, 0.0349 }, { 0.2629, 0.7676, 0.0186, 0.0279 } },  // atk
        { { 0.2128, 0.8070, 0.0245, 0.0291 }, { 0.2633, 0.8064, 0.0172, 0.0297 } },  // def
        { { 0.3965, 0.7245, 0.0236, 0.0293 }, { 0.4459, 0.7262, 0.0164, 0.0266 } },  // spa
        { { 0.3943, 0.7683, 0.0250, 0.0294 }, { 0.4464, 0.7674, 0.0151, 0.0266 } },  // spd  (extrapolated — user didn't redraw)
        { { 0.3926, 0.8078, 0.0276, 0.0296 }, { 0.4456, 0.8090, 0.0198, 0.0279 } },  // spe
    },
    //  ── slot 5 ──
    {
        { { 0.6304, 0.7280, 0.0246, 0.0252 }, { 0.6803, 0.7248, 0.0162, 0.0277 } },  // hp  (actual extrapolated — user didn't redraw)
        { { 0.6258, 0.7662, 0.0287, 0.0286 }, { 0.6801, 0.7682, 0.0189, 0.0248 } },  // atk
        { { 0.6300, 0.8084, 0.0243, 0.0285 }, { 0.6802, 0.8102, 0.0150, 0.0258 } },  // def
        { { 0.8127, 0.7252, 0.0246, 0.0268 }, { 0.8631, 0.7259, 0.0174, 0.0273 } },  // spa
        { { 0.8108, 0.7661, 0.0263, 0.0284 }, { 0.8627, 0.7659, 0.0168, 0.0273 } },  // spd
        { { 0.8119, 0.8065, 0.0257, 0.0312 }, { 0.8634, 0.8072, 0.0201, 0.0303 } },  // spe
    },
};


// ─── TeamStatsTabDetector ──────────────────────────────────────────────

//  Same purple as MovesMoreDetector — same card backgrounds.
static const FloatPixel CARD_BG_PURPLE{0.24, 0.20, 0.56};


TeamStatsTabDetector::TeamStatsTabDetector()
    //  Same card-bg sample as MovesMoreDetector.
    : m_card_bg(0.2260, 0.3000, 0.0339, 0.0111)
    //  "Stats" tab label sits to the right of the "Moves & More" tab.
    //  Measured from the team_stats screenshot.
    , m_tab_label(0.4943, 0.2074, 0.0700, 0.0333)
{}


void TeamStatsTabDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_MAGENTA, m_card_bg);
    items.add(COLOR_YELLOW, m_tab_label);
}


bool TeamStatsTabDetector::detect(const ImageViewRGB32& screen){
    //  Same shape as MovesMoreDetector. Active tab is yellow-green; card
    //  background is purple.
    const ImageStats tab = image_stats(extract_box_reference(screen, m_tab_label));
    if (tab.average.g < 150.0 || tab.average.g < tab.average.r) return false;

    const ImageStats stats = image_stats(extract_box_reference(screen, m_card_bg));
    if (stats.average.r + stats.average.g + stats.average.b < 200.0) return false;
    return is_solid(stats, CARD_BG_PURPLE, 0.10, 50);
}


// ─── TeamStatsReader ───────────────────────────────────────────────────

TeamStatsReader::TeamStatsReader(){
    for (uint8_t slot = 0; slot < 6; slot++){
        double sx = SLOT_ANCHORS[slot].x;
        double sy = SLOT_ANCHORS[slot].y;

        for (uint8_t s = 0; s < 6; s++){
            //  Actual + EVs use ABSOLUTE per-slot boxes (hand-drawn).
            const AbsBox& a = STAT_ABS[slot][s][0];
            const AbsBox& e = STAT_ABS[slot][s][1];
            m_actual_boxes[slot][s] = ImageFloatBox(a.x, a.y, a.w, a.h);
            m_evs_boxes[slot][s]    = ImageFloatBox(e.x, e.y, e.w, e.h);
            //  Nature still uses anchor + delta (user didn't redraw chevrons
            //  per slot; the same offsets work on all 6).
            const StatBox& n = *NATURE_BOXES[s];
            m_nature_boxes[slot][s] = ImageFloatBox(sx + n.dx, sy + n.dy, n.w, n.h);
        }
    }
}


void TeamStatsReader::make_overlays(VideoOverlaySet& items) const{
    for (uint8_t slot = 0; slot < 6; slot++){
        for (uint8_t s = 0; s < 6; s++){
            items.add(COLOR_GREEN,   m_actual_boxes[slot][s]);
            items.add(COLOR_CYAN,    m_evs_boxes[slot][s]);
            items.add(COLOR_MAGENTA, m_nature_boxes[slot][s]);
        }
    }
}


//  Map common Tesseract digit-confusable glyphs back to digits, with the
//  same sandwich-drop rule BattleHUDReader uses: a confusable BETWEEN two
//  real digits is segmentation noise (drop it); otherwise it's a real
//  misread (map it).
//
//  Includes 'a' → '9' beyond BattleHUD's set — observed on stat values
//  in italic-ish stat font ("90" → "a0" for Basculegion SpA).
static std::string apply_digit_confusables(const std::string& text){
    auto digit_for = [](char c) -> char {
        switch (c){
            case 'O': case 'o': case 'D': case 'Q': case '(': case ')': return '0';
            case 'I': case 'l': case '|': case '!':                     return '1';
            case 'Z': case '>': case '?':                               return '2';
            case 'B': case 'E':                                         return '8';
            case 'S': case '$':                                         return '5';
            case 'g': case 'q': case 'a': case 'A':                     return '9';
            default: return 0;
        }
    };
    auto is_digit = [](char c){ return c >= '0' && c <= '9'; };
    std::string out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size(); i++){
        char c = text[i];
        char dig = digit_for(c);
        if (dig == 0){
            out += c;
            continue;
        }
        char prev = (i > 0) ? text[i - 1] : 0;
        char next = (i + 1 < text.size()) ? text[i + 1] : 0;
        if (is_digit(prev) && is_digit(next)){
            //  Sandwiched between digits: segmentation noise, drop.
            continue;
        }
        out += dig;
    }
    return out;
}

//  Parse the first integer found in OCR text after the digit-confusable
//  fixup. Returns 0 if none parseable.
static int parse_first_int(const std::string& raw){
    std::string s = apply_digit_confusables(raw);
    int n = 0;
    bool any = false;
    for (char c : s){
        if (std::isdigit((unsigned char)c)){
            n = n * 10 + (c - '0');
            any = true;
        }else if (any){
            break;
        }
    }
    return any ? n : 0;
}


//  Classify a nature chevron crop. Returns BOOST/DROP/NEUTRAL based on
//  bright-pixel counts. Thresholds calibrated 2026-05-06 against
//  Whimsicott (Atk drop, Spe boost):
//    blue chevron pixels: b > 200 AND g > 150 AND r < 120
//    red  chevron pixels: r > 180 AND g < 130 AND b < 160
//  Either count >= 3% of crop pixels triggers; otherwise neutral.
static NatureMod classify_nature(
    const ImageViewRGB32& crop, int& blue_out, int& red_out)
{
    blue_out = 0; red_out = 0;
    size_t w = crop.width();
    size_t h = crop.height();
    if (w == 0 || h == 0) return NatureMod::NEUTRAL;
    size_t total = w * h;
    for (size_t y = 0; y < h; y++){
        for (size_t x = 0; x < w; x++){
            //  Use Color() to access channels — codebase stores ARGB with
            //  R at bit 16, G at bit 8, B at bit 0 (NOT the (px>>0)=R that
            //  raw_ocr_numbers happens to use; that one's symmetric on
            //  min/max so it still works for white-pixel detection).
            Color c(crop.pixel(x, y));
            uint8_t r = c.red(), g = c.green(), b = c.blue();
            if (b > 200 && g > 150 && r < 120) blue_out++;
            if (r > 180 && g < 130 && b < 160) red_out++;
        }
    }
    double thresh = 0.03 * (double)total;
    if (blue_out > red_out && (double)blue_out >= thresh) return NatureMod::DROP;
    if ((double)red_out >= thresh)                        return NatureMod::BOOST;
    return NatureMod::NEUTRAL;
}


TeamStatsInfo TeamStatsReader::read_card(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    TeamStatsInfo info;
    if (slot >= 6) return info;

    for (uint8_t s = 0; s < 6; s++){
        StatRead& r = info.stats[s];

        //  Actual stat (digit OCR).
        {
            ImageViewRGB32 crop = extract_box_reference(screen, m_actual_boxes[slot][s]);
            r.raw_actual = raw_ocr_numbers(crop);
            r.actual = parse_first_int(r.raw_actual);
        }
        //  EVs.
        {
            ImageViewRGB32 crop = extract_box_reference(screen, m_evs_boxes[slot][s]);
            r.raw_evs = raw_ocr_numbers(crop);
            r.evs = parse_first_int(r.raw_evs);
        }
        //  Nature direction (HP always neutral — there's no HP-affecting
        //  nature in the canonical Pokemon nature table).
        if ((StatSlot)s == StatSlot::HP){
            r.nature = NatureMod::NEUTRAL;
        }else{
            ImageViewRGB32 crop = extract_box_reference(screen, m_nature_boxes[slot][s]);
            r.nature = classify_nature(crop, r.blue_pixel_count, r.red_pixel_count);
        }
    }

    info.nature_slug = infer_nature(info.stats);

    logger.log(
        "TeamStatsReader: slot " + std::to_string(slot) +
        " hp=" + std::to_string(info.stats[0].actual) + "/" + std::to_string(info.stats[0].evs) +
        " atk=" + std::to_string(info.stats[1].actual) + "/" + std::to_string(info.stats[1].evs) +
        " def=" + std::to_string(info.stats[2].actual) + "/" + std::to_string(info.stats[2].evs) +
        " spa=" + std::to_string(info.stats[3].actual) + "/" + std::to_string(info.stats[3].evs) +
        " spd=" + std::to_string(info.stats[4].actual) + "/" + std::to_string(info.stats[4].evs) +
        " spe=" + std::to_string(info.stats[5].actual) + "/" + std::to_string(info.stats[5].evs) +
        " nature=" + info.nature_slug
    );

    return info;
}


std::array<TeamStatsInfo, 6> TeamStatsReader::read_team(
    Logger& logger, const ImageViewRGB32& screen
) const{
    std::array<TeamStatsInfo, 6> team;
    for (uint8_t slot = 0; slot < 6; slot++){
        team[slot] = read_card(logger, screen, slot);
    }
    return team;
}


//  Nature lookup keyed by (boost_stat, drop_stat). Both are 1..5
//  (skipping HP=0). Source: Bulbapedia nature table.
//  Diagonal (boost == drop) → neutral nature.
//  Pokemon Champions follows the canonical mapping unchanged.
static const char* NATURE_TABLE[6][6] = {
    //              Atk          Def          SpA          SpD          Spe
    /*HP -> */     {"",          "",          "",          "",          "",          ""},
    /*Atk*/        {"",          "Hardy",     "Lonely",    "Adamant",   "Naughty",   "Brave"},
    /*Def*/        {"",          "Bold",      "Docile",    "Impish",    "Lax",       "Relaxed"},
    /*SpA*/        {"",          "Modest",    "Mild",      "Bashful",   "Rash",      "Quiet"},
    /*SpD*/        {"",          "Calm",      "Gentle",    "Careful",   "Quirky",    "Sassy"},
    /*Spe*/        {"",          "Timid",     "Hasty",     "Jolly",     "Naive",     "Serious"},
};


std::string TeamStatsReader::infer_nature(const std::array<StatRead, 6>& stats){
    int boost = -1;
    int drop  = -1;
    for (uint8_t i = 1; i < 6; i++){   //  skip HP
        if (stats[i].nature == NatureMod::BOOST){
            if (boost >= 0) return "";   //  multiple boosts — invalid
            boost = i;
        }else if (stats[i].nature == NatureMod::DROP){
            if (drop >= 0) return "";    //  multiple drops — invalid
            drop = i;
        }
    }
    if (boost < 0 && drop < 0) return "Hardy";     //  All neutral
    if (boost < 0 || drop < 0) return "";          //  One side only — invalid
    return NATURE_TABLE[boost][drop];
}


}
}
}
