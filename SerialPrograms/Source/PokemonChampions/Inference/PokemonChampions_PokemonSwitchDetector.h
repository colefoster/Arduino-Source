/*  Pokemon Champions Pokemon Switch Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the Switch / Pokemon menu — left column showing all six own
 *  mons with HP bars + center "Moves & More" detail panel + right column
 *  showing opponent mons. Cursor-independent.
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
    ImageFloatBox m_tab_lime;       //  active "Moves & More" tab
    ImageFloatBox m_left_col_top;   //  left mon-list column purple
    ImageFloatBox m_left_col_bot;   //  same column, lower y
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
