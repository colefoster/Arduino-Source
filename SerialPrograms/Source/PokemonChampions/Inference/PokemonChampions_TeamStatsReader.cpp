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

//  All values are deltas from (COL_X[col], ROW_Y[row]) to box origin.
//  Source rows: subtract slot 0 species (0.1391, 0.2778) from
//  tools/box_definitions.json mon_0_*_* boxes.

//  HP — left col, top row of stats
static constexpr StatBox HP_ACTUAL  {0.0704, 0.0450, 0.0277, 0.0261};
static constexpr StatBox HP_EVS     {0.1238, 0.0465, 0.0205, 0.0231};
static constexpr StatBox HP_NATURE  {0.0381, 0.0898, 0.0127, 0.0216}; // unused (HP has no nature)

//  ATK — left col, mid row
static constexpr StatBox ATK_NATURE {0.0381, 0.0898, 0.0127, 0.0216};
static constexpr StatBox ATK_ACTUAL {0.0743, 0.0819, 0.0224, 0.0369};
static constexpr StatBox ATK_EVS    {0.1241, 0.0868, 0.0160, 0.0290};

//  DEF — left col, bot row
static constexpr StatBox DEF_NATURE {0.0483, 0.1360, 0.0113, 0.0182};
static constexpr StatBox DEF_ACTUAL {0.0706, 0.1274, 0.0272, 0.0292};
static constexpr StatBox DEF_EVS    {0.1247, 0.1261, 0.0144, 0.0290};

//  SPA — right col, top row of stats
static constexpr StatBox SPA_NATURE {0.2256, 0.0494, 0.0091, 0.0187};
static constexpr StatBox SPA_ACTUAL {0.2541, 0.0450, 0.0271, 0.0266};
static constexpr StatBox SPA_EVS    {0.3072, 0.0455, 0.0158, 0.0256};

//  SPD — right col, mid row
static constexpr StatBox SPD_NATURE {0.2265, 0.0907, 0.0111, 0.0202};
static constexpr StatBox SPD_ACTUAL {0.2577, 0.0878, 0.0230, 0.0275};
static constexpr StatBox SPD_EVS    {0.3061, 0.0873, 0.0158, 0.0266};

//  SPE — right col, bot row
static constexpr StatBox SPE_NATURE {0.2204, 0.1311, 0.0122, 0.0211};
static constexpr StatBox SPE_ACTUAL {0.2552, 0.1286, 0.0255, 0.0270};
static constexpr StatBox SPE_EVS    {0.3075, 0.1281, 0.0177, 0.0280};


static const StatBox* ACTUAL_BOXES[6] = {
    &HP_ACTUAL, &ATK_ACTUAL, &DEF_ACTUAL, &SPA_ACTUAL, &SPD_ACTUAL, &SPE_ACTUAL
};
static const StatBox* EVS_BOXES[6] = {
    &HP_EVS, &ATK_EVS, &DEF_EVS, &SPA_EVS, &SPD_EVS, &SPE_EVS
};
static const StatBox* NATURE_BOXES[6] = {
    &HP_NATURE, &ATK_NATURE, &DEF_NATURE, &SPA_NATURE, &SPD_NATURE, &SPE_NATURE
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
            const StatBox& a = *ACTUAL_BOXES[s];
            const StatBox& e = *EVS_BOXES[s];
            const StatBox& n = *NATURE_BOXES[s];
            m_actual_boxes[slot][s] = ImageFloatBox(sx + a.dx, sy + a.dy, a.w, a.h);
            m_evs_boxes[slot][s]    = ImageFloatBox(sx + e.dx, sy + e.dy, e.w, e.h);
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


//  Parse the first integer found in OCR text. Returns 0 if none.
static int parse_first_int(const std::string& s){
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
