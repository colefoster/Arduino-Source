/*  Pokemon Champions Target Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the doubles target-select modal. Fires iff all 4 candidate
 *  selector strips (opp_a, opp_b, own_a, own_b) read as a saturated
 *  red/blue/yellow/green strip color AND exactly one of them reads as
 *  the selected (yellow/green) variant. The other 3 are unselected
 *  (red/blue).
 *
 *  Reuses TargetSelectReader's box geometry verbatim so the two cannot
 *  drift. The targeted-vs-untargeted color classifier is also shared.
 *
 *  Singles never shows this screen. On non-target-select screens, those
 *  4 positions read as HUD chrome / background and fail the "all 4 are
 *  saturated strip colors" gate.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TargetSelectDetector_H
#define PokemonAutomation_PokemonChampions_TargetSelectDetector_H

#include <array>
#include <cstdint>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class TargetSelectDetector : public StaticScreenDetector{
public:
    TargetSelectDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true. For single-target moves this
    //  is the sole highlighted strip (0..3); for spread/field moves
    //  multiple strips light up and this is the last one scanned —
    //  callers that care should check selected_count().
    //    0 = opp_a, 1 = opp_b, 2 = own_a, 3 = own_b
    int8_t selected_index() const{ return m_selected; }

    //  Number of strips in the selected (yellow/green) state. 1 for
    //  single-target, 2 for spread (e.g. Heat Wave), 3 for AoE
    //  (e.g. Earthquake), 4 for field (e.g. Trick Room).
    int selected_count() const{ return m_selected_count; }

private:
    //  Same 4 boxes TargetSelectReader uses for is-targeted classification.
    //  Order: opp_a, opp_b, own_a, own_b.
    std::array<ImageFloatBox, 4> m_strips;

    int8_t m_selected = -1;
    int m_selected_count = 0;
};


class TargetSelectWatcher : public DetectorToFinder<TargetSelectDetector>{
public:
    TargetSelectWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(250))
        : DetectorToFinder("TargetSelectWatcher", hold_duration)
    {}
};


}
}
}
#endif
