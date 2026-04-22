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


//  Selected move pill — bright green on the cursored slot.
static const FloatPixel SELECTED_MOVE_GREEN{0.30, 0.47, 0.23};

//  Unselected move pill background — purple-blue.
//  Measured from live capture: avg RGB ~(135, 120, 215), ratio (0.28, 0.25, 0.46)
static const FloatPixel UNSELECTED_PILL_PURPLE{0.28, 0.25, 0.46};


MoveSelectDetector::MoveSelectDetector(){
    //  Thin strips on the far-left of each pill — for green-selection check.
    //  Y values updated from live capture (were ~30px too high from video estimates).
    const double X_SEL     = 0.7292;   // x = 1400/1920
    const double W_SEL     = 0.0156;   // 30/1920
    const double HEIGHT    = 0.0278;   // 30/1080
    const double Y_SLOTS[4] = {
        0.5000,   //  slot 0: y = 540/1080
        0.6204,   //  slot 1: y = 670/1080
        0.7361,   //  slot 2: y = 795/1080
        0.8519,   //  slot 3: y = 920/1080
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

    //  Method 1: Check for the green selected-pill highlight.
    for (int i = 0; i < 4; i++){
        if (is_slot_selected(screen, m_slots[i])){
            m_cursor_slot = i;
            return true;
        }
    }

    //  Method 2: Check for unselected purple-blue pill backgrounds.
    //  If 2+ pills match the purple background color, the move panel is up
    //  (even if we can't tell which slot is selected — the cursor may be on
    //  a slot whose type color overwhelms the green).
    int pill_count = 0;
    for (int i = 0; i < 4; i++){
        const ImageStats stats = image_stats(extract_box_reference(screen, m_slots[i]));
        if (is_solid(stats, UNSELECTED_PILL_PURPLE, 0.15, 150)){
            pill_count++;
        }
    }
    if (pill_count >= 2){
        //  Move panel detected but we don't know which slot is cursored.
        m_cursor_slot = -1;
        return true;
    }

    return false;
}


}
}
}
