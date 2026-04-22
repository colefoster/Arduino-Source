/*  Pokemon Champions Team Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the "Team Registration" screen where 5 team tabs are visible
 *  and one is highlighted yellow. Also exposes which team is selected.
 *
 *  Assumes the user has not scrolled beyond the leftmost page (teams 1-5).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamSelectDetector_H
#define PokemonAutomation_PokemonChampions_TeamSelectDetector_H

#include <array>
#include <cstdint>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class TeamSelectDetector : public StaticScreenDetector{
public:
    TeamSelectDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true: 0-4 for team slot.
    uint8_t selected_team() const{ return m_selected_tab; }

    //  Standalone check: returns selected tab index (0-4) or -1 if none
    //  of the 5 tab positions shows the yellow highlight.
    int selected_tab(const ImageViewRGB32& screen) const;

private:
    std::array<ImageFloatBox, 5> m_tab_slots;
    ImageFloatBox m_scroll_indicator;
    uint8_t m_selected_tab = 0;
};


class TeamSelectWatcher : public DetectorToFinder<TeamSelectDetector>{
public:
    TeamSelectWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(250))
        : DetectorToFinder("TeamSelectWatcher", hold_duration)
    {}
};


}
}
}
#endif
