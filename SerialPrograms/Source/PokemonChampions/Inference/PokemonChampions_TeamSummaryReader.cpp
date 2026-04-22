/*  Pokemon Champions Team Summary Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the full team roster (species + ability + 4 moves) from the
 *  "Moves & More" tab of the View Details screen.
 *
 *  Coordinates measured via tools/pixel_inspector.py --measure from
 *  screenshot-20260422-160514341816.png (1920x1080).
 *
 *  Measured reference points (normalized):
 *    species_0 (top-left):    (0.1391, 0.2769)   size 0.087 x 0.038
 *    species_1 (top-right):   (0.5552, 0.2769)   -> col offset = 0.4161
 *    species_2 (mid-left):    (0.1370, 0.4750)   -> row offset = 0.1981
 *    ability_0:               (0.1401, 0.3231)   -> dy from species = +0.0462
 *    move_0_0:                (0.3531, 0.2806)   size 0.097 x 0.033
 *    move_0_3:                (0.3536, 0.4065)   -> dy = +0.1259, avg step 0.042
 *
 *    Card background color: RGB(96, 80, 223), ratio (0.240, 0.202, 0.558)
 *    Tab label color:       RGB(193, 221, 112), ratio (0.367, 0.420, 0.213)
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions_BattleHUDReader.h"     //  SpeciesNameOCR
#include "PokemonChampions_MoveNameReader.h"       //  MoveNameOCR
#include "PokemonChampions_AbilityNameReader.h"    //  AbilityNameOCR

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Purple card background: RGB(96, 80, 223) / ratio (0.24, 0.20, 0.56).
//  Very solid (stddev_sum ~6.7) — tight threshold is safe.
static const FloatPixel CARD_BG_PURPLE{0.24, 0.20, 0.56};


// ─── Grid layout constants (from pixel_inspector measurements) ─────────

static constexpr double COL_X[2] = {0.1391, 0.5552};
static constexpr double ROW_Y[3] = {0.2769, 0.4750, 0.6731};  //  Row 2 extrapolated.

//  Species text region.
static constexpr double SPECIES_WIDTH  = 0.087;
static constexpr double SPECIES_HEIGHT = 0.038;

//  Ability text region — slightly shifted from species.
static constexpr double ABILITY_DX     = 0.0010;
static constexpr double ABILITY_DY     = 0.0462;
static constexpr double ABILITY_WIDTH  = 0.079;
static constexpr double ABILITY_HEIGHT = 0.034;

//  Move text region — right half of each card.
static constexpr double MOVE_X_COL[2]  = {0.3531, 0.7692};   //  Col 1 = Col 0 + 0.4161
static constexpr double MOVE_WIDTH     = 0.097;
static constexpr double MOVE_HEIGHT    = 0.034;
//  Y offsets of the 4 moves relative to the card's species Y.
static constexpr double MOVE_DY[4]     = {0.0037, 0.0444, 0.0861, 0.1296};


// ─── MovesMoreDetector ─────────────────────────────────────────────────

MovesMoreDetector::MovesMoreDetector()
    //  Solid purple region inside card 0 background — measured.
    : m_card_bg(0.2260, 0.3000, 0.0339, 0.0111)
    //  "Moves & More" tab label — active tab is yellow-green.
    , m_tab_label(0.3682, 0.2074, 0.0875, 0.0333)
{}


void MovesMoreDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_MAGENTA, m_card_bg);
    items.add(COLOR_YELLOW, m_tab_label);
}


bool MovesMoreDetector::detect(const ImageViewRGB32& screen){
    //  Single cheap color check: is the card background the expected purple?
    //  If yes, we're on a purple card grid (Moves & More is the only such
    //  screen in the menu flow we care about).
    const ImageStats stats = image_stats(extract_box_reference(screen, m_card_bg));
    return is_solid(stats, CARD_BG_PURPLE, 0.10, 50);
}


// ─── TeamSummaryReader ─────────────────────────────────────────────────

TeamSummaryReader::TeamSummaryReader(Language language)
    : m_language(language)
{
    //  Populate the 6 card regions. Cards are laid out:
    //    slot 0 = (row 0, col 0)  slot 1 = (row 0, col 1)
    //    slot 2 = (row 1, col 0)  slot 3 = (row 1, col 1)
    //    slot 4 = (row 2, col 0)  slot 5 = (row 2, col 1)
    for (uint8_t slot = 0; slot < 6; slot++){
        uint8_t row = slot / 2;
        uint8_t col = slot % 2;

        double sx = COL_X[col];
        double sy = ROW_Y[row];

        m_species_boxes[slot] = ImageFloatBox(sx, sy, SPECIES_WIDTH, SPECIES_HEIGHT);
        m_ability_boxes[slot] = ImageFloatBox(
            sx + ABILITY_DX, sy + ABILITY_DY, ABILITY_WIDTH, ABILITY_HEIGHT);

        double mx = MOVE_X_COL[col];
        for (uint8_t m = 0; m < 4; m++){
            m_move_boxes[slot][m] = ImageFloatBox(
                mx, sy + MOVE_DY[m], MOVE_WIDTH, MOVE_HEIGHT);
        }
    }
}


void TeamSummaryReader::make_overlays(VideoOverlaySet& items) const{
    for (uint8_t slot = 0; slot < 6; slot++){
        items.add(COLOR_CYAN, m_species_boxes[slot]);
        items.add(COLOR_MAGENTA, m_ability_boxes[slot]);
        for (uint8_t m = 0; m < 4; m++){
            items.add(COLOR_GREEN, m_move_boxes[slot][m]);
        }
    }
}


TeamSummaryInfo TeamSummaryReader::read_card(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    TeamSummaryInfo info;
    if (slot >= 6){
        return info;
    }

    //  Species.
    {
        ImageViewRGB32 cropped = extract_box_reference(screen, m_species_boxes[slot]);
        OCR::StringMatchResult result = SpeciesNameOCR::instance().read_substring(
            logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
        );
        if (!result.results.empty()){
            info.species = result.results.begin()->second.token;
        }
    }

    //  Ability.
    {
        ImageViewRGB32 cropped = extract_box_reference(screen, m_ability_boxes[slot]);
        OCR::StringMatchResult result = AbilityNameOCR::instance().read_substring(
            logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
        );
        if (!result.results.empty()){
            info.ability = result.results.begin()->second.token;
        }
    }

    //  4 moves.
    for (uint8_t m = 0; m < 4; m++){
        ImageViewRGB32 cropped = extract_box_reference(screen, m_move_boxes[slot][m]);
        OCR::StringMatchResult result = MoveNameOCR::instance().read_substring(
            logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
        );
        if (!result.results.empty()){
            info.moves[m] = result.results.begin()->second.token;
        }
    }

    logger.log(
        "TeamSummaryReader: slot " + std::to_string(slot) +
        " species=\"" + info.species +
        "\" ability=\"" + info.ability +
        "\" moves=[" +
        info.moves[0] + ", " + info.moves[1] + ", " +
        info.moves[2] + ", " + info.moves[3] + "]"
    );

    return info;
}


std::array<TeamSummaryInfo, 6> TeamSummaryReader::read_team(
    Logger& logger, const ImageViewRGB32& screen
) const{
    std::array<TeamSummaryInfo, 6> team;
    for (uint8_t slot = 0; slot < 6; slot++){
        team[slot] = read_card(logger, screen, slot);
    }
    return team;
}


}
}
}
