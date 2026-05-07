/*  Pokemon Champions Battle Mode Menu Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Two cursor-independent samples:
 *    1. "Season Ends in" pink countdown pill — unique to this screen.
 *    2. Top-row Pokéball-burst graphic on the right edge of the
 *       Ranked Battles row.
 *
 *  Pixel measurements (1920x1080):
 *    Season pill:    x=1260, y=170, w=15, h=15
 *      RGB ≈ (240, 137, 247), ratio (0.39, 0.22, 0.40), sd ≤ 7
 *    Top-row burst:  x=1780, y=320, w=15, h=15
 *      RGB ≈ (200, 200, 135), ratio (0.37, 0.37, 0.26), sd ≤ 21
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_BattleModeMenuDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


static const FloatPixel SEASON_PILL_PINK{0.39, 0.22, 0.40};
static const FloatPixel TOP_ROW_BURST{0.37, 0.37, 0.26};


BattleModeMenuDetector::BattleModeMenuDetector()
    //  x=1260, y=170, w=15, h=15
    : m_season_pill   (0.6563, 0.1574, 0.0078, 0.0139)
    //  x=1780, y=320, w=15, h=15
    , m_top_row_burst (0.9271, 0.2963, 0.0078, 0.0139)
{}


void BattleModeMenuDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_season_pill);
    items.add(COLOR_CYAN, m_top_row_burst);
}


bool BattleModeMenuDetector::detect(const ImageViewRGB32& screen){
    const ImageStats pill = image_stats(extract_box_reference(screen, m_season_pill));
    if (pill.average.sum() < 500.0) return false;
    if (!is_solid(pill, SEASON_PILL_PINK, 0.06, 50)) return false;
    const ImageStats burst = image_stats(extract_box_reference(screen, m_top_row_burst));
    if (burst.average.sum() < 400.0) return false;
    if (!is_solid(burst, TOP_ROW_BURST, 0.06, 100)) return false;
    return true;
}


}
}
}
