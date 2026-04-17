/*  Pokemon Champions Move Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates derived from ref_frames/1/labeled/move_select_slot1.png
 *  (1920x1080 extraction from the Japanese VGC match video). The UI is
 *  identical across arenas — the only differences between the ranked red
 *  dome and casual gym are backgrounds, not the move panel itself.
 *
 *  Measured on Power Whip (selected slot 1):
 *    Left pill fill  avg RGB (117,173,104)  ratio (0.30, 0.44, 0.26)
 *
 *  Cursor reveals itself via a bright green pill with a yellow ► arrow at
 *  the left. Unselected slots are a dim purple. We sample a narrow vertical
 *  strip on the far-left of each slot to read the pill color without
 *  hitting the move name/PP text.
 *
 *  NOTE: once Cole captures a live battle move-select frame we should
 *  re-tune these to pixel-accurate coords; current slot Y values were
 *  measured from video, which is close but not proven 1:1 to live capture.
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_MoveSelectDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Selected move pill (softer green than post-match pill due to gradient).
static const FloatPixel SELECTED_MOVE_GREEN{0.30, 0.47, 0.23};


MoveSelectDetector::MoveSelectDetector(){
    //  Four stacked pill slots on the right side of the screen.
    //  In 1920x1080: x ~ 1420-1900, height ~75px, spacing ~130px.
    //  Sampling a thin 20px-wide strip on the far-left of each pill.
    const double X      = 0.7448;   // x = 1430/1920
    const double WIDTH  = 0.0104;   // 20/1920 — stays left of text
    const double HEIGHT = 0.0500;   // 54/1080
    const double Y_SLOTS[4] = {
        0.5278,   //  slot 1 center top @ y=570
        0.6481,   //  slot 2 @ y=700
        0.7685,   //  slot 3 @ y=830
        0.8889,   //  slot 4 @ y=960
    };

    for (size_t i = 0; i < 4; i++){
        m_slots[i] = ImageFloatBox(X, Y_SLOTS[i], WIDTH, HEIGHT);
    }
}

void MoveSelectDetector::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& slot : m_slots){
        items.add(COLOR_CYAN, slot);
    }
}

bool MoveSelectDetector::is_slot_selected(
    const ImageViewRGB32& screen, const ImageFloatBox& slot
) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, slot));
    //  Generous tolerance — the pill has a gradient (lighter green at top,
    //  darker at bottom) so stddev can be high within the sample strip.
    return is_solid(stats, SELECTED_MOVE_GREEN, 0.18, 120);
}

bool MoveSelectDetector::detect(const ImageViewRGB32& screen){
    m_cursor_slot = -1;
    for (int i = 0; i < 4; i++){
        if (is_slot_selected(screen, m_slots[i])){
            m_cursor_slot = i;
            return true;
        }
    }
    return false;
}


}
}
}
