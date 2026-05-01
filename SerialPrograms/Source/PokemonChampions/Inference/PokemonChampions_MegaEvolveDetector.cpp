/*  Pokemon Champions Mega Evolve Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  The Mega Evolve toggle appears on the move-select screen when the
 *  active mon is capable of Mega Evolution and hasn't done so yet this
 *  battle. Visually it's a small icon near the move panel.
 *
 *  Detection method: stddev-based brightness check inside a tuned box
 *  (mirrors the CommunicatingDetector pattern). When the toggle is
 *  visible there's a bright, high-contrast cluster; when absent the
 *  region is part of the dark battle field.
 *
 *  Initial coords + thresholds are placeholders — retune via inspector
 *  against move_select frames that do/don't show the toggle.
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "PokemonChampions_MegaEvolveDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


MegaEvolveDetector::MegaEvolveDetector()
    //  Placeholder coords — retune via inspector.
    : m_toggle_region(0.850, 0.420, 0.060, 0.060)
{}

void MegaEvolveDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_YELLOW, m_toggle_region);
}

bool MegaEvolveDetector::detect(const ImageViewRGB32& screen){
    ImageStats stats = image_stats(extract_box_reference(screen, m_toggle_region));
    return stats.stddev.sum() > 120 && stats.average.sum() > 200;
}


}
}
}
