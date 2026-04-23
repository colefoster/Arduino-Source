/*  Pokemon Champions Move Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the 4-move pill panel on the right side of the screen.
 *  Works for both Singles and Doubles — the move pill layout is identical.
 *
 *  Two detection methods (either triggers a match):
 *
 *  Method 1 (selected-green): Check each pill's left edge for the bright
 *  green highlight that appears on the cursored slot. This is the original
 *  singles approach and still works when the green color is visible.
 *
 *  Method 2 (pill-presence): Check each pill region for the purple-blue
 *  unselected pill background color. If 2+ pills match, the move panel
 *  is on screen. This catches the doubles case where the selected pill
 *  shows the move's type color (yellow/pink/blue) instead of green.
 *
 *  Pixel measurements from live capture (1920x1080):
 *    Selected pill left edge: x=1430, 20px wide (same as before)
 *    Unselected pill strip:   x=1400-1430, 30px wide
 *    Pill Y positions:        540, 670, 795, 920 (from live doubles frame_229)
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


//  Selected move pill — yellow-green highlight on the cursored slot.
//  Measured from tightened pill strip (upper-left core of highlight).
static const FloatPixel SELECTED_MOVE_GREEN{0.44, 0.45, 0.10};

//  Unselected move pill background — purple-blue.
//  Measured from live capture: avg RGB ~(135, 120, 215), ratio (0.28, 0.25, 0.46)
static const FloatPixel UNSELECTED_PILL_PURPLE{0.28, 0.25, 0.46};


MoveSelectDetector::MoveSelectDetector(){
    //  Thin strips on the far-left of each pill — for green-selection check.
    //  Vertically centered on the pill body, avoiding top/bottom borders.
    //  Measured from labeled/move_select_slot1.png (1920x1080).
    const double X_SEL     = 0.7292;
    const double W_SEL     = 0.0101;
    const double HEIGHT    = 0.0139;
    const double Y_SLOTS[4] = {
        0.5116,   //  slot 0
        0.6338,   //  slot 1
        0.7542,   //  slot 2
        0.8746,   //  slot 3
    };

    for (size_t i = 0; i < 4; i++){
        m_slots[i] = ImageFloatBox(X_SEL, Y_SLOTS[i], W_SEL, HEIGHT);
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
    return is_solid(stats, SELECTED_MOVE_GREEN, 0.18, 120);
}

bool MoveSelectDetector::detect(const ImageViewRGB32& screen){
    m_cursor_slot = -1;

    //  Count green (selected) and purple (unselected) pill strips.
    //  Require BOTH: exactly 1 green + at least 2 purple to confirm
    //  the move select panel is on screen.
    int green_slot = -1;
    int purple_count = 0;
    for (int i = 0; i < 4; i++){
        const ImageStats stats = image_stats(extract_box_reference(screen, m_slots[i]));
        if (is_solid(stats, SELECTED_MOVE_GREEN, 0.18, 120)){
            green_slot = i;
        }else if (is_solid(stats, UNSELECTED_PILL_PURPLE, 0.15, 150)){
            purple_count++;
        }
    }

    if (green_slot >= 0 && purple_count >= 2){
        m_cursor_slot = green_slot;
        return true;
    }

    return false;
}


}
}
}
