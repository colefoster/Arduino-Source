/*  Pokemon Champions Ranked Format Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the Single Battle / Double Battle format-pick screen. Two
 *  cursor-independent samples on the tile burst graphics (one in the top
 *  tile, one in the bottom tile).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_RankedFormatSelectDetector_H
#define PokemonAutomation_PokemonChampions_RankedFormatSelectDetector_H

#include <array>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class RankedFormatSelectDetector : public StaticScreenDetector{
public:
    RankedFormatSelectDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true. -1 if no cursor scored above
    //  the floor. 0=Singles, 1=Doubles.
    int selected_index() const{ return m_selected_index; }

private:
    ImageFloatBox m_top_tile_cyan;
    ImageFloatBox m_btm_tile_pink;
    std::array<ImageFloatBox, 2> m_cursor_boxes;
    int m_selected_index = -1;
};


class RankedFormatSelectWatcher : public DetectorToFinder<RankedFormatSelectDetector>{
public:
    RankedFormatSelectWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("RankedFormatSelectWatcher", hold_duration)
    {}
};


}
}
}
#endif
