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
{
    //  Cursor strips drawn by user; per-row in top-to-bottom order.
    //  0=Ranked, 1=Casual, 2=Private, 3=Online Competitions, 4=Battle Data.
    m_cursor_boxes[0] = ImageFloatBox(0.7103, 0.1990, 0.0192, 0.0341);
    m_cursor_boxes[1] = ImageFloatBox(0.7078, 0.3583, 0.0229, 0.0428);
    m_cursor_boxes[2] = ImageFloatBox(0.7004, 0.5044, 0.0253, 0.0527);
    m_cursor_boxes[3] = ImageFloatBox(0.7426, 0.6621, 0.0258, 0.0451);
    m_cursor_boxes[4] = ImageFloatBox(0.7240, 0.8227, 0.0284, 0.0504);
}


void BattleModeMenuDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_season_pill);
    items.add(COLOR_CYAN, m_top_row_burst);
    for (const ImageFloatBox& b : m_cursor_boxes){
        items.add(COLOR_YELLOW, b);
    }
}


//  (R+G)/2 - B; positive iff the strip skews yellow vs. blue/purple.
static double yellow_score(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return -1.0;
    ImageStats st = image_stats(crop);
    int r = (int)st.average.r;
    int g = (int)st.average.g;
    int b = (int)st.average.b;
    int score = (r + g) / 2 - b;
    return score > 0 ? double(score) : 0.0;
}


bool BattleModeMenuDetector::detect(const ImageViewRGB32& screen){
    m_selected_index = -1;
    const ImageStats pill = image_stats(extract_box_reference(screen, m_season_pill));
    if (pill.average.sum() < 500.0) return false;
    if (!is_solid(pill, SEASON_PILL_PINK, 0.06, 50)) return false;
    const ImageStats burst = image_stats(extract_box_reference(screen, m_top_row_burst));
    if (burst.average.sum() < 400.0) return false;
    if (!is_solid(burst, TOP_ROW_BURST, 0.06, 100)) return false;

    int best = -1;
    double best_score = 0.0;
    for (int i = 0; i < 5; i++){
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
