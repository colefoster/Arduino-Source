/*  Pokemon Champions Team Summary Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads full Pokemon details from the summary screen:
 *    - Species name (left panel, top)
 *    - 4 moves (right panel, stacked)
 *    - Ability (right panel, below moves)
 *    - Held item (right panel, below ability)
 *
 *  Pixel measurements — PLACEHOLDER, must be tuned with pixel_inspector:
 *    Species name: left panel, near top (~x=100, y=150, w=250, h=35)
 *    Move names:   right panel, 4 stacked (~x=1100, y=300..600, w=250, h=30)
 *    Ability:      right panel, below moves (~x=1100, y=680, w=250, h=30)
 *    Held item:    right panel, below ability (~x=1100, y=750, w=250, h=30)
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions_BattleHUDReader.h"     //  SpeciesNameOCR
#include "PokemonChampions_MoveNameReader.h"       //  MoveNameOCR
#include "PokemonChampions_AbilityNameReader.h"    //  AbilityNameOCR
#include "PokemonChampions_ItemNameReader.h"       //  ItemNameOCR

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


TeamSummaryReader::TeamSummaryReader(Language language)
    : m_language(language)
{
    //  PLACEHOLDER coordinates — must be measured from actual summary
    //  screenshots using pixel_inspector.py.

    //  Species name — left panel, near top.
    //  Placeholder: x=100, y=150, w=250, h=35 (1920x1080)
    m_species_box = ImageFloatBox(0.0521, 0.1389, 0.1302, 0.0324);

    //  Move names — right panel, 4 stacked.
    //  Placeholder: x=1100, y varies, w=250, h=30 (1920x1080)
    const double MOVE_X     = 0.5729;   //  1100/1920
    const double MOVE_WIDTH = 0.1302;   //  250/1920
    const double MOVE_HEIGHT = 0.0278;  //  30/1080
    const double MOVE_Y[4] = {
        0.2778,   //  slot 0: y = 300/1080
        0.3611,   //  slot 1: y = 390/1080
        0.4444,   //  slot 2: y = 480/1080
        0.5278,   //  slot 3: y = 570/1080
    };
    for (size_t i = 0; i < 4; i++){
        m_move_boxes[i] = ImageFloatBox(MOVE_X, MOVE_Y[i], MOVE_WIDTH, MOVE_HEIGHT);
    }

    //  Ability — right panel, below moves.
    //  Placeholder: x=1100, y=680, w=250, h=30 (1920x1080)
    m_ability_box = ImageFloatBox(0.5729, 0.6296, 0.1302, 0.0278);

    //  Held item — right panel, below ability.
    //  Placeholder: x=1100, y=750, w=250, h=30 (1920x1080)
    m_item_box = ImageFloatBox(0.5729, 0.6944, 0.1302, 0.0278);
}


void TeamSummaryReader::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_species_box);
    for (const ImageFloatBox& box : m_move_boxes){
        items.add(COLOR_GREEN, box);
    }
    items.add(COLOR_MAGENTA, m_ability_box);
    items.add(COLOR_YELLOW, m_item_box);
}


std::string TeamSummaryReader::read_species(
    Logger& logger, const ImageViewRGB32& screen
) const{
    ImageViewRGB32 cropped = extract_box_reference(screen, m_species_box);
    OCR::StringMatchResult result = SpeciesNameOCR::instance().read_substring(
        logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
    );
    if (result.results.empty()){
        return "";
    }
    return result.results.begin()->second.token;
}


std::array<std::string, 4> TeamSummaryReader::read_moves(
    Logger& logger, const ImageViewRGB32& screen
) const{
    std::array<std::string, 4> moves;
    for (uint8_t i = 0; i < 4; i++){
        ImageViewRGB32 cropped = extract_box_reference(screen, m_move_boxes[i]);
        OCR::StringMatchResult result = MoveNameOCR::instance().read_substring(
            logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
        );
        if (!result.results.empty()){
            moves[i] = result.results.begin()->second.token;
        }
    }
    return moves;
}


std::string TeamSummaryReader::read_ability(
    Logger& logger, const ImageViewRGB32& screen
) const{
    ImageViewRGB32 cropped = extract_box_reference(screen, m_ability_box);
    OCR::StringMatchResult result = AbilityNameOCR::instance().read_substring(
        logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
    );
    if (result.results.empty()){
        return "";
    }
    return result.results.begin()->second.token;
}


std::string TeamSummaryReader::read_item(
    Logger& logger, const ImageViewRGB32& screen
) const{
    ImageViewRGB32 cropped = extract_box_reference(screen, m_item_box);
    OCR::StringMatchResult result = ItemNameOCR::instance().read_substring(
        logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
    );
    if (result.results.empty()){
        return "";
    }
    return result.results.begin()->second.token;
}


TeamSummaryInfo TeamSummaryReader::read_all(
    Logger& logger, const ImageViewRGB32& screen
) const{
    TeamSummaryInfo info;
    info.species = read_species(logger, screen);
    info.moves = read_moves(logger, screen);
    info.ability = read_ability(logger, screen);
    info.item = read_item(logger, screen);

    logger.log(
        "TeamSummaryReader: species=\"" + info.species +
        "\" ability=\"" + info.ability +
        "\" item=\"" + info.item +
        "\" moves=[" +
        info.moves[0] + ", " + info.moves[1] + ", " +
        info.moves[2] + ", " + info.moves[3] + "]"
    );

    return info;
}


}
}
}
