/*  Pokemon Champions Pokemon Switch Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the Switch / Pokemon menu — left column showing all six own
 *  mons with HP bars + center "Moves & More" / "Stats" tab panel + right
 *  column showing opponent mons. Cursor-independent.
 *
 *  Co-evidence: the center panel has two side-by-side tabs ("Moves & More"
 *  on the left, "Stats" on the right). Exactly one is active at any time —
 *  the active one is filled lime/yellow, the inactive one dark blue. We
 *  sample two points inside each tab (left + right) and accept only when
 *  one tab is fully active and the other fully inactive.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_PokemonSwitchDetector_H
#define PokemonAutomation_PokemonChampions_PokemonSwitchDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class PokemonSwitchDetector : public StaticScreenDetector{
public:
    PokemonSwitchDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    ImageFloatBox m_moves_left;
    ImageFloatBox m_moves_right;
    ImageFloatBox m_stats_left;
    ImageFloatBox m_stats_right;
};


class PokemonSwitchWatcher : public DetectorToFinder<PokemonSwitchDetector>{
public:
    PokemonSwitchWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("PokemonSwitchWatcher", hold_duration)
    {}
};


}
}
}
#endif
