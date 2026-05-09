/*  Pokemon Champions Team Select Modal Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  See header for overview.
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_TeamSelectModalDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Modal pill yellow — slightly orange-tinted vs. the carousel tab's
//  pure yellow. Measured from the modal-position right-edge samples
//  on three reference screenshots (Team 1 / 3 / 5 cursored, modal at
//  varying x): avg RGB ≈ (224, 242, 45) → ratio (0.439, 0.474, 0.087).
//  Targeting the carousel's pure-yellow ratio (0.497, 0.497, 0.006)
//  put the sample's euclidean distance at ~0.108 — just past the 0.10
//  is_solid bar — so detection silently failed on every modal frame.
static const FloatPixel SELECTED_OPTION_YELLOW{0.4393, 0.4738, 0.0869};

//  Y centers of each option's pill highlight.
static constexpr double OPTION_Y_CENTERS[4] = {
    0.2370,  //  0  Select this team
    0.3056,  //  1  Edit team
    0.3778,  //  2  View details
    0.4500,  //  3  Cancel
};

//  Sample box size (norm). Narrow enough to fit between text glyphs at
//  any pill x-offset; tall enough to absorb 1-2 px sub-pixel rendering
//  noise.
static constexpr double BOX_W = 0.020;
static constexpr double BOX_H = 0.0185;

//  Sample x positions: 0.300, 0.325, ..., 0.850. Covers all observed
//  modal placements — when Team 1 is cursored the modal opens at
//  x≈0.31-0.50, when middle teams are cursored it can sit anywhere
//  out to x≈0.87.
static constexpr double X_BASE = 0.300;
static constexpr double X_STEP = 0.025;


TeamSelectModalDetector::TeamSelectModalDetector(){
    for (size_t opt = 0; opt < 4; opt++){
        const double y = OPTION_Y_CENTERS[opt] - BOX_H / 2.0;
        for (size_t i = 0; i < X_CANDIDATES; i++){
            const double x = X_BASE + X_STEP * (double)i;
            m_option_boxes[opt][i] = ImageFloatBox(x, y, BOX_W, BOX_H);
        }
    }
}


void TeamSelectModalDetector::make_overlays(VideoOverlaySet& items) const{
    for (const auto& row : m_option_boxes){
        for (const ImageFloatBox& b : row){
            items.add(COLOR_YELLOW, b);
        }
    }
}


int TeamSelectModalDetector::selected_option(const ImageViewRGB32& screen) const{
    for (size_t opt = 0; opt < 4; opt++){
        for (const ImageFloatBox& b : m_option_boxes[opt]){
            const ImageStats stats = image_stats(extract_box_reference(screen, b));
            //  Brightness floor — pure yellow pill reads ~(224, 242, 45),
            //  channel-sum > 510. Lavender background reads ~(110, 100, 210),
            //  channel-sum < 420.
            if (stats.average.r + stats.average.g < 400.0) continue;
            //  Tight thresholds: a clean yellow swatch (no overlap with
            //  text) reads sd ~ 3. Slight x-offsets that catch the start
            //  of a glyph push sd up; a solid hit at SOME x candidate
            //  per row is enough.
            if (is_solid(stats, SELECTED_OPTION_YELLOW, 0.10, 40)){
                return static_cast<int>(opt);
            }
        }
    }
    return -1;
}


bool TeamSelectModalDetector::detect(const ImageViewRGB32& screen){
    int opt = selected_option(screen);
    if (opt < 0){
        return false;
    }
    m_selected_option = static_cast<uint8_t>(opt);
    return true;
}


}
}
}
