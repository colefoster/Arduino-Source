/*  Pokemon Champions Communicating Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the "Communicating..." text that appears center-screen while
 *  waiting for the opponent to choose their action. The text is white with
 *  a thin black outline on a semi-transparent dark overlay.
 *
 *  Also detects the opponent timer countdown that appears in the same area.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_CommunicatingDetector_H
#define PokemonAutomation_PokemonChampions_CommunicatingDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class CommunicatingDetector : public StaticScreenDetector{
public:
    CommunicatingDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    //  Center-screen region where "Communicating..." text appears.
    //  Measured from bellibolt VOD frame_00545 (1920x1080).
    ImageFloatBox m_text_region;
};


class CommunicatingWatcher : public DetectorToFinder<CommunicatingDetector>{
public:
    CommunicatingWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(500))
        : DetectorToFinder("CommunicatingWatcher", hold_duration)
    {}
};


}
}
}
#endif
