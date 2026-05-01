/*  Pokemon Champions Mega Evolve Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the Mega Evolve toggle/button on the move-select screen.
 *  Returns true when the toggle is visible (i.e., the active mon can
 *  Mega Evolve and the option hasn't been used yet this battle).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_MegaEvolveDetector_H
#define PokemonAutomation_PokemonChampions_MegaEvolveDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class MegaEvolveDetector : public StaticScreenDetector{
public:
    MegaEvolveDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    //  Region around the Mega Evolve toggle on the move-select screen.
    //  Initial estimate — tune via the inspector.
    ImageFloatBox m_toggle_region;
};


class MegaEvolveWatcher : public DetectorToFinder<MegaEvolveDetector>{
public:
    MegaEvolveWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(500))
        : DetectorToFinder("MegaEvolveWatcher", hold_duration)
    {}
};


}
}
}
#endif
