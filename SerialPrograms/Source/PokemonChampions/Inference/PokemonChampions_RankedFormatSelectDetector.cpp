/*  Pokemon Champions Ranked Format Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Two cursor-independent samples on cosmetic burst-graphic accents inside
 *  the two big stacked tiles (Single Battle / Double Battle). The accents
 *  are part of the tile artwork — not the highlight ring — so they hold
 *  whether cursor is on the top tile or the bottom tile.
 *
 *  Pixel measurements (1920x1080):
 *    Top-tile cyan accent:    x=1480, y=360, w=15, h=15
 *      RGB (180, 255, 255), ratio (0.26, 0.37, 0.37), sd ≤ 3
 *    Bottom-tile pink accent: x=1600, y=600, w=15, h=15
 *      RGB (239, 170, 255), ratio (0.36, 0.25, 0.39), sd ≤ 7
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_RankedFormatSelectDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


static const FloatPixel TOP_TILE_CYAN{0.26, 0.37, 0.37};
static const FloatPixel BTM_TILE_PINK{0.36, 0.25, 0.39};


RankedFormatSelectDetector::RankedFormatSelectDetector()
    //  x=1480, y=360, w=15, h=15
    : m_top_tile_cyan(0.7708, 0.3333, 0.0078, 0.0139)
    //  x=1600, y=600, w=15, h=15
    , m_btm_tile_pink(0.8333, 0.5556, 0.0078, 0.0139)
{}


void RankedFormatSelectDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_top_tile_cyan);
    items.add(COLOR_CYAN, m_btm_tile_pink);
}


bool RankedFormatSelectDetector::detect(const ImageViewRGB32& screen){
    const ImageStats top = image_stats(extract_box_reference(screen, m_top_tile_cyan));
    if (top.average.sum() < 500.0) return false;
    if (!is_solid(top, TOP_TILE_CYAN, 0.06, 30)) return false;
    const ImageStats btm = image_stats(extract_box_reference(screen, m_btm_tile_pink));
    if (btm.average.sum() < 500.0) return false;
    if (!is_solid(btm, BTM_TILE_PINK, 0.06, 50)) return false;
    return true;
}


}
}
}
