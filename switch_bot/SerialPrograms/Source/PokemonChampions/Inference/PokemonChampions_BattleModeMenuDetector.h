/*  Pokemon Champions Battle Mode Menu Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the 5-row Battle Mode list (Ranked Battles / Casual Battles /
 *  Private Battles / Online Competitions / Battle Data). Cursor-independent.
 *
 *  Note: a separate `BattleModeDetector` (legacy) reads Single/Double from
 *  the pre-match format banner. Different screen, similar name — keep apart.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_BattleModeMenuDetector_H
#define PokemonAutomation_PokemonChampions_BattleModeMenuDetector_H

#include <array>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class BattleModeMenuDetector : public StaticScreenDetector{
public:
    BattleModeMenuDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true. -1 if no cursor scored above the
    //  floor (e.g. animation frame). Indexes match top-to-bottom row order:
    //  0=Ranked, 1=Casual, 2=Private, 3=Online Competitions, 4=Battle Data.
    int selected_index() const{ return m_selected_index; }

private:
    ImageFloatBox m_season_pill;
    ImageFloatBox m_top_row_burst;
    std::array<ImageFloatBox, 5> m_cursor_boxes;
    int m_selected_index = -1;
};


class BattleModeMenuWatcher : public DetectorToFinder<BattleModeMenuDetector>{
public:
    BattleModeMenuWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("BattleModeMenuWatcher", hold_duration)
    {}
};


}
}
}
#endif
