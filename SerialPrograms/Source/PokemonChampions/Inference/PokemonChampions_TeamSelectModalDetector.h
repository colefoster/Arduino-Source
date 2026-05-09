/*  Pokemon Champions Team Select Modal Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the four-option popup that opens when A is pressed on a team
 *  in the team_select carousel. Options stack top-to-bottom:
 *    0 = Select this team   (default cursor when modal opens)
 *    1 = Edit team
 *    2 = View details
 *    3 = Cancel
 *
 *  The currently-cursored option's pill turns solid yellow. The modal's
 *  X position varies — it opens beside the cursored team's column rather
 *  than at a fixed location — so we sweep multiple X candidates per
 *  option Y row and take the first solid-yellow hit. Y positions are
 *  consistent across modal placements; only X shifts.
 *
 *  Coordinates measured 2026-05-08 from the four 22:35 reference images
 *  (modal at center) and the 22:54 image (modal at right) in
 *  test_images/team_select/.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamSelectModalDetector_H
#define PokemonAutomation_PokemonChampions_TeamSelectModalDetector_H

#include <array>
#include <cstdint>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class TeamSelectModalDetector : public StaticScreenDetector{
public:
    //  Number of X-candidate samples per option row. Sweeps from x=0.300
    //  to x=0.850 in 0.025 steps so any modal placement gets a hit on
    //  its highlighted pill — the modal opens beside the cursored team
    //  column, so its pill x-range can be anywhere from ~0.31 (Team 1
    //  cursored, modal opens right) to ~0.87 (Team 3+ cursored, modal
    //  opens further right). Caller MUST gate on TeamSelectDetector
    //  also firing — the wide sweep otherwise picks up battle-UI yellow
    //  blobs (notably main_menu BATTLE button glow at x=0.6).
    static constexpr size_t X_CANDIDATES = 23;

    TeamSelectModalDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true: 0..3 = Select / Edit / View / Cancel.
    uint8_t selected_option() const{ return m_selected_option; }

    //  Standalone: returns 0..3 if any pill is highlighted, -1 otherwise.
    int selected_option(const ImageViewRGB32& screen) const;

private:
    //  4 rows × 15 X-candidates per row. Each box samples a small swatch
    //  of yellow pill background; the first one to read solid yellow at
    //  a row identifies that option as cursored.
    std::array<std::array<ImageFloatBox, X_CANDIDATES>, 4> m_option_boxes;
    uint8_t m_selected_option = 0;
};


}
}
}
#endif
