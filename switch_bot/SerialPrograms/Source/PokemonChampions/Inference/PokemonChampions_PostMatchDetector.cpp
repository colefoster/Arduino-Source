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
    //  Narrow strips inside each button, above-the-text region.
    //  In 1920x1080: Quit @ x 200-280, Edit @ x 800-880, Continue @ x 1290-1330.
    //  The Edit position was previously at x=600-680 — that turned out to
    //  sit on Quit's right edge, not Edit, so when Quit was cursored the
    //  Edit sample read yellow and the "exactly 1 green + 2 purple" rule
    //  rejected legitimate post-match frames.
    : m_buttons{
        ImageFloatBox(0.1042, 0.9222, 0.0417, 0.0222),   // Quit Battling
        ImageFloatBox(0.4167, 0.9222, 0.0417, 0.0222),   // Edit Team
        ImageFloatBox(0.6719, 0.9222, 0.0208, 0.0222),   // Continue Battling
      }
{}

void PostMatchScreenDetector::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& b : m_buttons){
        items.add(COLOR_CYAN, b);
    }
}

//  Real selected pill is bright green/yellow. Continue-selected reads
//  r+g ~= 400; Quit-selected (more saturated yellow tint mid-animation)
//  drops to ~310. Dim FPs at the same ratio max out around r+g ~= 220.
//  Floor at 280 cleanly separates them.
static constexpr double MIN_GREEN_BRIGHTNESS = 280.0;

//  Unselected button fill is purple-blue (~RGB 23, 10, 202). Co-evidence
//  used to reject battle-screen FPs where multiple button positions
//  happen to land on bright move-tile yellow.
static bool is_unselected_purple(const ImageStats& stats){
    return stats.average.b > 100.0
        && stats.average.b > stats.average.r + stats.average.g;
}

bool PostMatchScreenDetector::detect(const ImageViewRGB32& screen){
    ImageStats button_stats[3];
    for (int i = 0; i < 3; i++){
        button_stats[i] = image_stats(extract_box_reference(screen, m_buttons[i]));
    }
    //  Strict signature: exactly one green-pill (selected) + two purple-blue
    //  (unselected). The earlier "1 green + ≥1 purple" rule fired on
    //  move_select where two of the three sampled bottom-strip positions
    //  read green from Pokémon HP pills — only Continue (mid-screen)
    //  landed on the dark backdrop and read purple.
    int selected = -1;
    int n_purple = 0;
    for (int i = 0; i < 3; i++){
        const ImageStats& stats = button_stats[i];
        bool is_green =
            (stats.average.r + stats.average.g >= MIN_GREEN_BRIGHTNESS)
            && is_solid(stats, SELECTED_GREEN_PILL, 0.18, 100);
        if (is_green){
            if (selected != -1) return false;  //  more than one selected → not post-match
            selected = i;
        }else if (is_unselected_purple(stats)){
            n_purple++;
        }
    }
    if (selected == -1 || n_purple != 2) return false;
    m_cursored = static_cast<PostMatchButton>(selected);
    return true;
}


}
}
}
