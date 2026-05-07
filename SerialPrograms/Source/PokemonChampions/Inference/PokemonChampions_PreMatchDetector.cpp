/*  Pokemon Champions Pre-Match Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Two cursor-independent cues:
 *    1. White card behind the 6-sprite "Team N" row (uniquely pre_match —
 *       ranked_format_select shows a purple Double-Battle tile at the same
 *       y, not a white sprite strip).
 *    2. Blue-purple "Single/Double Battle" format band at top-right.
 *
 *  Pixel measurements (1920x1080):
 *    Team-card sample:  x=1520, y=600, w=15, h=15  → RGB ≥ (243, 242, 255)
 *    Format band:       x=1200, y=180, w=25, h=25  → ratio ≈ (0.25, 0.24, 0.51)
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_PreMatchDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Saturated blue-purple format band (Single/Double Battle pill).
static const FloatPixel FORMAT_BAND_PURPLE{0.25, 0.24, 0.51};


PreMatchDetector::PreMatchDetector()
    //  White sprite-strip card. x=1520, y=600, w=15, h=15 in 1920x1080.
    : m_team_card  (0.7917, 0.5556, 0.0078, 0.0139)
    //  Format band. x=1200, y=180, w=25, h=25 in 1920x1080.
    , m_format_band(0.6250, 0.1667, 0.0130, 0.0231)
{}


void PreMatchDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_team_card);
    items.add(COLOR_CYAN, m_format_band);
}


bool PreMatchDetector::detect(const ImageViewRGB32& screen){
    //  Co-evidence #1: white sprite-strip card. Pure white card between the
    //  six small Pokémon icons in the Team N row.
    const ImageStats team = image_stats(extract_box_reference(screen, m_team_card));
    if (team.average.r < 230.0 || team.average.g < 230.0 || team.average.b < 230.0){
        return false;
    }
    //  Co-evidence #2: blue-purple format band. Ratio ~(0.25, 0.24, 0.51).
    //  stddev_sum ≈ 80-90 in the corpus — anti-aliased text on solid fill.
    const ImageStats band = image_stats(extract_box_reference(screen, m_format_band));
    if (band.average.b < 180.0) return false;
    if (!is_solid(band, FORMAT_BAND_PURPLE, 0.10, 200)) return false;
    return true;
}


}
}
}
