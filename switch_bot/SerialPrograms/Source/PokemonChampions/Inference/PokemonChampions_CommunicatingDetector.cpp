/*  Pokemon Champions Communicating Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  The "Communicating..." text appears roughly center-screen at:
 *    x: 730-1190 / 1920, y: 490-540 / 1080
 *  Normalized: (0.380, 0.450, 0.240, 0.050)
 *
 *  Detection method: check for white text pixels (high brightness, low
 *  saturation) in the region. During normal gameplay this area is the
 *  battle field with dark/colored pixels. When "Communicating..." is
 *  shown, there's a cluster of bright white text.
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "PokemonChampions_CommunicatingDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


CommunicatingDetector::CommunicatingDetector()
    //  Center-screen region for "Communicating..." text.
    //  Measured from bellibolt VOD action_menu/frame_00545.
    : m_text_region(0.380, 0.450, 0.240, 0.050)
{}

void CommunicatingDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_YELLOW, m_text_region);
}

bool CommunicatingDetector::detect(const ImageViewRGB32& screen){
    //  The "Communicating..." text is white with black outline on a
    //  semi-transparent dark overlay. When visible:
    //  - Average brightness increases (white text)
    //  - Stddev increases (text vs dark background)
    //
    //  When no text is shown, this region is the 3D battle field
    //  with moderate, varied colors.
    //
    //  Detection: check that the stddev sum is elevated (white text
    //  creates high contrast) AND the region has some minimum brightness
    //  (rules out very dark battle arenas that might have high stddev
    //  from neon effects).
    ImageStats stats = image_stats(extract_box_reference(screen, m_text_region));

    //  Stddev threshold tuned from reference frames:
    //    Communicating... visible: stddev_sum ~180-250
    //    Normal battle field:      stddev_sum ~40-100
    return stats.stddev.sum() > 120 && stats.average.sum() > 200;
}


}
}
}
