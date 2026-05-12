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
{
    //  0=Singles, 1=Doubles. Drawn by user.
    m_cursor_boxes[0] = ImageFloatBox(0.7027, 0.4299, 0.0340, 0.0409);
    m_cursor_boxes[1] = ImageFloatBox(0.6962, 0.6637, 0.0310, 0.0427);
}


void RankedFormatSelectDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_top_tile_cyan);
    items.add(COLOR_CYAN, m_btm_tile_pink);
    for (const ImageFloatBox& b : m_cursor_boxes){
        items.add(COLOR_YELLOW, b);
    }
}


static double yellow_score(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return -1.0;
    ImageStats st = image_stats(crop);
    int r = (int)st.average.r;
    int g = (int)st.average.g;
    int b = (int)st.average.b;
    int score = (r + g) / 2 - b;
    return score > 0 ? double(score) : 0.0;
}


bool RankedFormatSelectDetector::detect(const ImageViewRGB32& screen){
    m_selected_index = -1;
    const ImageStats top = image_stats(extract_box_reference(screen, m_top_tile_cyan));
    if (top.average.sum() < 500.0) return false;
    if (!is_solid(top, TOP_TILE_CYAN, 0.06, 30)) return false;
    const ImageStats btm = image_stats(extract_box_reference(screen, m_btm_tile_pink));
    if (btm.average.sum() < 500.0) return false;
    if (!is_solid(btm, BTM_TILE_PINK, 0.06, 50)) return false;

    int best = -1;
    double best_score = 0.0;
    for (int i = 0; i < 2; i++){
        double s = yellow_score(extract_box_reference(screen, m_cursor_boxes[i]));
        if (s > best_score && s >= 30.0){
            best_score = s;
            best = i;
        }
    }
    m_selected_index = best;
    return true;
}


}
}
}
