/*  Pokemon Champions Team Preview Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the pre-battle Team Preview screen ("Select 4 Pokemon").
 *    - Own side (left): OCRs species name and item name for each of 6 slots.
 *    - Opp side (right): sprite-matches each of 6 opponent sprites against
 *      the Pokemon Champions sprite atlas.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamPreviewReader_H
#define PokemonAutomation_PokemonChampions_TeamPreviewReader_H

#include <array>
#include <cstdint>
#include <string>
#include "CommonFramework/Language.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


struct TeamPreviewOwnSlot{
    std::string species;   //  matched slug; "" on OCR failure
    std::string item;      //  matched slug; "" on OCR failure
};

struct TeamPreviewResult{
    std::array<TeamPreviewOwnSlot, 6> own;
    std::array<std::string, 6> opp_species;   //  "" on match failure
};


class TeamPreviewReader{
public:
    TeamPreviewReader(Language language = Language::English);

    void make_overlays(VideoOverlaySet& items) const;

    //  Reads all 12 slots. Opponent species come from sprite matching;
    //  opp_match_threshold is the max RMSD (lower = stricter). Default
    //  0.30 accepts confident matches and rejects ambiguous ones (better
    //  to return empty than wrong).
    TeamPreviewResult read(
        Logger& logger,
        const ImageViewRGB32& screen,
        double opp_match_threshold = 0.30
    ) const;

private:
    Language m_language;
    std::array<ImageFloatBox, 6> m_own_species_boxes;
    std::array<ImageFloatBox, 6> m_own_item_boxes;
    std::array<ImageFloatBox, 6> m_opp_sprite_boxes;
};


}
}
}
#endif
