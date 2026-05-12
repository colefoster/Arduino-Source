/*  Pokemon Champions Casual Format Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the Casual battles format-select screen (Single / Double pills).
 *  Visually distinct from RankedFormatSelectDetector — uses horizontal pill
 *  buttons in yellow / purple instead of stacked tiles with cyan / pink
 *  burst accents.
 *
 *  Anchor: dark blue-purple band behind the "Casual Battles" header pill.
 *  Cursor: yellow_score on each option pill — Singles pill renders bright
 *  yellow when cursored, dim/different when not.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_CasualFormatSelectDetector_H
#define PokemonAutomation_PokemonChampions_CasualFormatSelectDetector_H

#include <array>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class CasualFormatSelectDetector : public StaticScreenDetector{
public:
    CasualFormatSelectDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true. 0=Singles, 1=Doubles.
    int selected_index() const{ return m_selected_index; }

private:
    ImageFloatBox m_anchor;
    std::array<ImageFloatBox, 2> m_pill_boxes;
    int m_selected_index = -1;
};


class CasualFormatSelectWatcher : public DetectorToFinder<CasualFormatSelectDetector>{
public:
    CasualFormatSelectWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("CasualFormatSelectWatcher", hold_duration)
    {}
};


}
}
}
#endif
