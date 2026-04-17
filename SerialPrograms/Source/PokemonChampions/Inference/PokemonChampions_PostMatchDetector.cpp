/*  Pokemon Champions Post-Match Screen Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates derived from ref_frames/1/labeled/post_match_screen_live.png.
 *
 *  The three pill buttons (Quit | Edit | Continue) sit across the bottom of
 *  the screen at y ~996-1020. Unselected buttons are solid purple-blue with
 *  white text; the cursored button is a bright green-to-yellow pill.
 *
 *  Sampling a narrow strip on the left side of each button (before the text
 *  starts) — this catches the pill fill color cleanly without hitting the
 *  white glyphs in the middle.
 *
 *  Measured (Continue cursored):
 *    Quit / Edit  left-edge  avg RGB (~30, ~15, ~205)  purple-blue
 *    Continue      left-edge  avg RGB (162,255,  0)   ratio (0.40,0.60,0.00)
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_PostMatchDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Bright green pill fill of the selected button.
static const FloatPixel SELECTED_GREEN_PILL{0.40, 0.60, 0.00};


PostMatchScreenDetector::PostMatchScreenDetector()
    //  Narrow strips at the left edge of each button, above-the-text region.
    //  In 1920x1080: Quit @ x 200-280, Edit @ x 600-680, Continue @ x 1290-1330.
    : m_buttons{
        ImageFloatBox(0.1042, 0.9222, 0.0417, 0.0222),   // Quit Battling
        ImageFloatBox(0.3125, 0.9222, 0.0417, 0.0222),   // Edit Team
        ImageFloatBox(0.6719, 0.9222, 0.0208, 0.0222),   // Continue Battling
      }
{}

void PostMatchScreenDetector::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& b : m_buttons){
        items.add(COLOR_CYAN, b);
    }
}

bool PostMatchScreenDetector::detect(const ImageViewRGB32& screen){
    for (int i = 0; i < 3; i++){
        const ImageStats stats = image_stats(extract_box_reference(screen, m_buttons[i]));
        //  The green pill is nearly saturated in R+G with B ~ 0, so tight
        //  tolerance is fine and actually helps reject false positives on
        //  the blue arena floor that shows through between buttons.
        if (is_solid(stats, SELECTED_GREEN_PILL, 0.18, 100)){
            m_cursored = static_cast<PostMatchButton>(i);
            return true;
        }
    }
    return false;
}


}
}
}
