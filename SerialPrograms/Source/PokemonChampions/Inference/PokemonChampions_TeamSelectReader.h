/*  Pokemon Champions Team Select Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  OCR reader for the team select screen (pre-battle).
 *  Reads species names and held items for all 6 team slots.
 *
 *  NOTE: The team select screen shows NICKNAMES, not species names.
 *  The species OCR will attempt to match nicknames against the species
 *  dictionary — this works when the nickname matches the species name
 *  (common case) but will fail for custom nicknames.
 *  For custom nicknames, the item name (especially Mega Stones like
 *  "Victreebelite") can be used to infer the species.
 *
 *  Crop boxes are PLACEHOLDERS — must be tuned with pixel_inspector
 *  against actual team select screenshots.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamSelectReader_H
#define PokemonAutomation_PokemonChampions_TeamSelectReader_H

#include <array>
#include <string>
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


struct TeamSelectSlotInfo{
    std::string species;    //  Matched slug, or "" if OCR failed / nickname didn't match.
    std::string item;       //  Matched item slug, or "" if OCR failed.
};


class TeamSelectReader{
public:
    TeamSelectReader(Language language = Language::English);

    void make_overlays(VideoOverlaySet& items) const;

    //  Read a single team slot (0-5). Returns species + item slugs.
    TeamSelectSlotInfo read_slot(Logger& logger, const ImageViewRGB32& screen, uint8_t slot) const;

    //  Read all 6 team slots.
    std::array<TeamSelectSlotInfo, 6> read_all_slots(Logger& logger, const ImageViewRGB32& screen) const;

private:
    Language m_language;
    std::array<ImageFloatBox, 6> m_species_boxes;
    std::array<ImageFloatBox, 6> m_item_boxes;
};


}
}
}
#endif
