/*  Pokemon Champions Team Select Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the 6-species left column on the Team Registration screen.
 *  Each slot shows a species name and sprite; only species is read here
 *  (no item text is shown on this screen).
 *
 *  Coordinates measured via tools/pixel_inspector.py --measure from
 *  screenshot-20260422-160451227419.png (1920x1080).
 *
 *  Pixel layout (1920x1080):
 *    species_0: x=154, y=237  (Garchomp)
 *    species_5: x=154, y=836  (Incineroar)
 *    Row spacing: ~120px / 1080 = 0.1109 normalized
 *    Text size:   ~158 x 36 px  ->  0.082 x 0.034 normalized
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_TeamSelectReader.h"
#include "PokemonChampions_BattleHUDReader.h"  //  SpeciesNameOCR

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Team Registration screen uses dark-navy text (~RGB 5,45,124) on a pale
//  lavender pill. BLACK_TEXT_FILTERS fails because the B channel is high.
//  These custom ranges accept pixels where all channels are darker than a
//  progressively looser ceiling, with the blue ceiling higher than RG.
static const std::vector<OCR::TextColorRange>& dark_navy_text_filters(){
    static const std::vector<OCR::TextColorRange> filters{
        {0xff000000, 0xff6080a0},  //  tight: R<=96 G<=128 B<=160
        {0xff000000, 0xff8099b0},  //  medium
        {0xff000000, 0xffa0b0c0},  //  loose (anti-aliased edges)
    };
    return filters;
}


TeamSelectReader::TeamSelectReader(Language language)
    : m_language(language)
{
    //  Species text boxes in the left column of the Team Registration screen.
    //  Derived from species_0 (slot 0) and species_5 (slot 5); rows 1-4 are
    //  interpolated with equal spacing.

    const double X      = 0.0807;    //  Left edge of species text
    const double WIDTH  = 0.0849;    //  ~163 px
    const double HEIGHT = 0.0343;    //  ~37 px
    const double Y_START = 0.2194;   //  slot 0 y
    const double Y_END   = 0.7741;   //  slot 5 y
    const double Y_STEP  = (Y_END - Y_START) / 5.0;  //  ~0.1109

    for (size_t i = 0; i < 6; i++){
        double y = Y_START + i * Y_STEP;
        m_species_boxes[i] = ImageFloatBox(X, y, WIDTH, HEIGHT);
        //  No item text on this screen — leave item boxes empty.
        m_item_boxes[i] = ImageFloatBox(0, 0, 0, 0);
    }
}


void TeamSelectReader::make_overlays(VideoOverlaySet& items) const{
    for (size_t i = 0; i < 6; i++){
        items.add(COLOR_GREEN, m_species_boxes[i]);
    }
}


TeamSelectSlotInfo TeamSelectReader::read_slot(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    TeamSelectSlotInfo info;
    if (slot >= 6){
        return info;
    }

    ImageViewRGB32 cropped = extract_box_reference(screen, m_species_boxes[slot]);
    OCR::StringMatchResult result = SpeciesNameOCR::instance().read_substring(
        logger, m_language, cropped, dark_navy_text_filters()
    );
    if (!result.results.empty()){
        info.species = result.results.begin()->second.token;
        logger.log(
            "TeamSelectReader: slot " + std::to_string(slot) +
            " species = \"" + info.species + "\"", COLOR_GREEN
        );
    } else {
        logger.log(
            "TeamSelectReader: slot " + std::to_string(slot) +
            " species OCR failed", COLOR_YELLOW
        );
    }

    //  item left blank — not shown on this screen.
    return info;
}


std::array<TeamSelectSlotInfo, 6> TeamSelectReader::read_all_slots(
    Logger& logger, const ImageViewRGB32& screen
) const{
    std::array<TeamSelectSlotInfo, 6> slots;
    for (uint8_t i = 0; i < 6; i++){
        slots[i] = read_slot(logger, screen, i);
    }
    return slots;
}


}
}
}
