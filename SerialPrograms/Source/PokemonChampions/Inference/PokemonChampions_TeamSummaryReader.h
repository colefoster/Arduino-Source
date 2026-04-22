/*  Pokemon Champions Team Summary Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  OCR reader for the "Moves & More" tab on the View Details screen.
 *  This screen displays all 6 team Pokemon in a 2x3 grid with:
 *    - Species name (top of each card)
 *    - Ability name (below species)
 *    - 4 move names (stacked on the right half of each card)
 *
 *  One OCR pass reads the entire team at once — no L/R cycling required.
 *  Items are NOT shown on this screen; they must be read elsewhere.
 *
 *  Grid layout:
 *    Card 0: top-left     Card 1: top-right
 *    Card 2: mid-left     Card 3: mid-right
 *    Card 4: bot-left     Card 5: bot-right
 *
 *  Card-to-slot mapping matches the Team Registration list order.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamSummaryReader_H
#define PokemonAutomation_PokemonChampions_TeamSummaryReader_H

#include <array>
#include <cstdint>
#include <string>
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"
#include "PokemonChampions/Programs/PokemonChampions_BattleStateTracker.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Result for a single Pokemon card on the Moves & More tab.
struct TeamSummaryInfo{
    std::string species;                //  Matched slug, "" on failure.
    std::string ability;                //  Matched slug, "" on failure.
    std::array<std::string, 4> moves;   //  Matched slugs; "" for any failed slot.
    //  Item is not read from this screen (not displayed).

    //  Convert to ConfiguredPokemon for BattleStateTracker. Item will be "".
    ConfiguredPokemon to_configured() const{
        ConfiguredPokemon p;
        p.species = species;
        p.ability = ability;
        p.moves = moves;
        p.item = "";
        return p;
    }
};


//  Detector for the Moves & More tab. Uses a color-gate on a solid
//  purple card background region — a very cheap pre-OCR check.
class MovesMoreDetector : public StaticScreenDetector{
public:
    MovesMoreDetector();
    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    ImageFloatBox m_card_bg;
    ImageFloatBox m_tab_label;
};


class TeamSummaryReader{
public:
    TeamSummaryReader(Language language = Language::English);

    void make_overlays(VideoOverlaySet& items) const;

    //  Read one card (0..5). Returns species + ability + 4 moves.
    TeamSummaryInfo read_card(Logger& logger, const ImageViewRGB32& screen, uint8_t slot) const;

    //  Read all 6 cards in one pass.
    std::array<TeamSummaryInfo, 6> read_team(Logger& logger, const ImageViewRGB32& screen) const;

private:
    Language m_language;

    std::array<ImageFloatBox, 6> m_species_boxes;
    std::array<ImageFloatBox, 6> m_ability_boxes;
    //  [slot][move_idx] — 6 slots x 4 moves = 24 boxes.
    std::array<std::array<ImageFloatBox, 4>, 6> m_move_boxes;
};


}
}
}
#endif
