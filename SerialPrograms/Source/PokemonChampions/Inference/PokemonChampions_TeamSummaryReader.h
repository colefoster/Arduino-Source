/*  Pokemon Champions Team Summary Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  OCR reader for the team summary screen (accessed via Y → "Show Summary"
 *  from the team select screen, or from the box).
 *
 *  This screen shows one Pokemon at a time with full details:
 *    Left panel:  species name (actual, not nickname), stats, nature
 *    Right panel: 4 moves with PP, ability, held item
 *
 *  Navigate between team members with L/R buttons.
 *
 *  Crop boxes are PLACEHOLDERS — must be tuned with pixel_inspector.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamSummaryReader_H
#define PokemonAutomation_PokemonChampions_TeamSummaryReader_H

#include <array>
#include <string>
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "PokemonChampions/Programs/PokemonChampions_BattleStateTracker.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Result from reading a single summary screen.
struct TeamSummaryInfo{
    std::string species;                //  Matched slug.
    std::array<std::string, 4> moves;   //  Matched slugs; "" for failed reads.
    std::string ability;                //  Matched slug.
    std::string item;                   //  Matched slug.

    //  Convert to ConfiguredPokemon for BattleStateTracker.
    ConfiguredPokemon to_configured() const{
        ConfiguredPokemon p;
        p.species = species;
        p.moves = moves;
        p.ability = ability;
        p.item = item;
        return p;
    }
};


class TeamSummaryReader{
public:
    TeamSummaryReader(Language language = Language::English);

    void make_overlays(VideoOverlaySet& items) const;

    //  Read the species name from the left panel.
    std::string read_species(Logger& logger, const ImageViewRGB32& screen) const;

    //  Read all 4 moves from the right panel.
    std::array<std::string, 4> read_moves(Logger& logger, const ImageViewRGB32& screen) const;

    //  Read the ability from the right panel.
    std::string read_ability(Logger& logger, const ImageViewRGB32& screen) const;

    //  Read the held item from the right panel.
    std::string read_item(Logger& logger, const ImageViewRGB32& screen) const;

    //  Read everything at once.
    TeamSummaryInfo read_all(Logger& logger, const ImageViewRGB32& screen) const;

private:
    Language m_language;

    //  Left panel: species name.
    ImageFloatBox m_species_box;

    //  Right panel: 4 move name boxes.
    std::array<ImageFloatBox, 4> m_move_boxes;

    //  Right panel: ability name.
    ImageFloatBox m_ability_box;

    //  Right panel: held item name.
    ImageFloatBox m_item_box;
};


}
}
}
#endif
