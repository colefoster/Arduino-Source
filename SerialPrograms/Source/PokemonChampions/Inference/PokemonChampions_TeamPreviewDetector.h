/*  Pokemon Champions Team Preview Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the pre-battle Team Preview ("Select 4 Pokemon to send into
 *  battle") screen. On this screen:
 *    - Own team appears on the left as 6 rows with species + item text.
 *    - Opponent team appears on the right as 6 sprite-only rows.
 *
 *  Detection uses OCR on the central title text, looking for "Select".
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamPreviewDetector_H
#define PokemonAutomation_PokemonChampions_TeamPreviewDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class TeamPreviewDetector : public StaticScreenDetector{
public:
    TeamPreviewDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    ImageFloatBox m_title_text;
};


class TeamPreviewWatcher : public DetectorToFinder<TeamPreviewDetector>{
public:
    TeamPreviewWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(250))
        : DetectorToFinder("TeamPreviewWatcher", hold_duration)
    {}
};


}
}
}
#endif
