/*  Pokemon Champions Team Select Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads species (nickname) and item names from the 6-slot team select
 *  screen that appears after matchmaking finds an opponent.
 *
 *  The team select screen layout (left side, 1920x1080):
 *    6 Pokemon slots stacked vertically on the left half of the screen.
 *    Each slot contains: [sprite] [nickname text] [item name] [gender icon]
 *
 *  Pixel measurements — PLACEHOLDER, must be tuned with pixel_inspector:
 *    Species name text: x~180-380, ~30px tall, ~120px vertical spacing
 *    Item name text:    x~180-380, below species in each slot
 *    First slot y: ~200
 *    Slot spacing: ~115px vertical
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_TeamSelectReader.h"
#include "PokemonChampions_ItemNameReader.h"
#include "PokemonChampions_BattleHUDReader.h"  //  SpeciesNameOCR

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


TeamSelectReader::TeamSelectReader(Language language)
    : m_language(language)
{
    //  Team select slot layout — left side of screen, 6 stacked slots.
    //
    //  PLACEHOLDER coordinates — must be measured from actual screenshots
    //  using pixel_inspector.py. These are rough estimates based on the
    //  screen description (6 slots on left half, ~115px vertical spacing).
    //
    //  Species/nickname text region per slot:
    //    x: ~180-380 (after sprite, before item area)
    //    width: ~200px  →  0.1042 normalized
    //    height: ~28px  →  0.0259 normalized
    //
    //  Item text region per slot:
    //    x: ~180-380 (same horizontal band, below species)
    //    width: ~200px
    //    height: ~24px

    const double SPECIES_X     = 0.0938;   //  ~180/1920
    const double SPECIES_WIDTH = 0.1042;   //  ~200/1920
    const double SPECIES_HEIGHT = 0.0259;  //  ~28/1080

    const double ITEM_X     = 0.0938;
    const double ITEM_WIDTH = 0.1042;
    const double ITEM_HEIGHT = 0.0222;     //  ~24/1080

    //  Y positions for each slot (species and item are offset within each slot).
    //  First slot starts at y~200/1080, spacing ~115px.
    const double SLOT_Y[6] = {
        0.1852,   //  slot 0: y = 200/1080
        0.2917,   //  slot 1: y = 315/1080
        0.3981,   //  slot 2: y = 430/1080
        0.5046,   //  slot 3: y = 545/1080
        0.6111,   //  slot 4: y = 660/1080
        0.7176,   //  slot 5: y = 775/1080
    };

    //  Item text is ~35px below species text in each slot.
    const double ITEM_Y_OFFSET = 0.0324;   //  ~35/1080

    for (size_t i = 0; i < 6; i++){
        m_species_boxes[i] = ImageFloatBox(SPECIES_X, SLOT_Y[i], SPECIES_WIDTH, SPECIES_HEIGHT);
        m_item_boxes[i] = ImageFloatBox(ITEM_X, SLOT_Y[i] + ITEM_Y_OFFSET, ITEM_WIDTH, ITEM_HEIGHT);
    }
}


void TeamSelectReader::make_overlays(VideoOverlaySet& items) const{
    for (size_t i = 0; i < 6; i++){
        items.add(COLOR_GREEN, m_species_boxes[i]);
        items.add(COLOR_YELLOW, m_item_boxes[i]);
    }
}


TeamSelectSlotInfo TeamSelectReader::read_slot(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    TeamSelectSlotInfo info;
    if (slot >= 6){
        return info;
    }

    //  Read species/nickname.
    {
        ImageViewRGB32 cropped = extract_box_reference(screen, m_species_boxes[slot]);
        OCR::StringMatchResult result = SpeciesNameOCR::instance().read_substring(
            logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
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
                " species OCR failed (nickname may not match dictionary)", COLOR_YELLOW
            );
        }
    }

    //  Read item.
    {
        ImageViewRGB32 cropped = extract_box_reference(screen, m_item_boxes[slot]);
        OCR::StringMatchResult result = ItemNameOCR::instance().read_substring(
            logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
        );
        if (!result.results.empty()){
            info.item = result.results.begin()->second.token;
            logger.log(
                "TeamSelectReader: slot " + std::to_string(slot) +
                " item = \"" + info.item + "\"", COLOR_GREEN
            );
        }
    }

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
