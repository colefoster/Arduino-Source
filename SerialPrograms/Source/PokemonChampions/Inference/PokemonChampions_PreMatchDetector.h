/*  Pokemon Champions Pre-Match Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the pre-match staging screen (Team N row + Begin Matchmaking).
 *  Cursor-independent — does not rely on which row is highlighted.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_PreMatchDetector_H
#define PokemonAutomation_PokemonChampions_PreMatchDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class PreMatchDetector : public StaticScreenDetector{
public:
    PreMatchDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    ImageFloatBox m_team_card;
    ImageFloatBox m_format_band;
};


class PreMatchWatcher : public DetectorToFinder<PreMatchDetector>{
public:
    PreMatchWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("PreMatchWatcher", hold_duration)
    {}
};


}
}
}
#endif
