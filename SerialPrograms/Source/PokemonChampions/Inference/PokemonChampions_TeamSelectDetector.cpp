/*  Pokemon Champions Team Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the "Team Registration" screen — the menu accessed via
 *  Main Menu -> Battle -> Ranked -> Doubles -> Change Team.
 *
 *  This screen shows:
 *    - 5 team tabs at the top (Team 1 .. Team 5). One is highlighted YELLOW.
 *    - The selected team's 6 Pokemon listed in the left column with sprites.
 *    - Other teams' columns (often empty) to the right.
 *
 *  Detection strategy (assumes user is scrolled to the leftmost page):
 *    Color-gate: check the 5 known tab positions; if ANY of them has the
 *    solid yellow highlight color, we're on this screen with a selected
 *    team. Very cheap (no OCR, no allocations).
 *
 *  Coordinates measured via tools/pixel_inspector.py --measure.
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_TeamSelectDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Selected tab highlight: pure yellow, RGB(255, 255, 3).
//  Ratio (0.4972, 0.4972, 0.0056), stddev_sum=1.4 (extremely clean).
static const FloatPixel SELECTED_TAB_YELLOW{0.4972, 0.4972, 0.0056};


TeamSelectDetector::TeamSelectDetector()
    //  5 team tab positions (left to right), measured 2026-04-22 from
    //  screenshot-20260422-160451227419.png (Team 2 selected).
    //  Positions are fixed regardless of which team is highlighted.
    : m_tab_slots{
          ImageFloatBox(0.1005, 0.1435, 0.0318, 0.0194),  //  Team 1
          ImageFloatBox(0.2844, 0.1426, 0.0276, 0.0222),  //  Team 2
          ImageFloatBox(0.4755, 0.1407, 0.0359, 0.0213),  //  Team 3
          ImageFloatBox(0.6646, 0.1380, 0.0370, 0.0222),  //  Team 4
          ImageFloatBox(0.8562, 0.1426, 0.0359, 0.0185),  //  Team 5
      }
    //  Scroll-position indicator at the bottom. Used to confirm the user
    //  is scrolled to the leftmost page (teams 1-5 visible).
    , m_scroll_indicator(0.0661, 0.9176, 0.1724, 0.0093)
{}


void TeamSelectDetector::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& tab : m_tab_slots){
        items.add(COLOR_YELLOW, tab);
    }
    items.add(COLOR_CYAN, m_scroll_indicator);
}


int TeamSelectDetector::selected_tab(const ImageViewRGB32& screen) const{
    for (size_t i = 0; i < m_tab_slots.size(); i++){
        const ImageStats stats = image_stats(extract_box_reference(screen, m_tab_slots[i]));
        //  Tight thresholds: the selected color is very clean (sd~1.4).
        if (is_solid(stats, SELECTED_TAB_YELLOW, 0.10, 40)){
            return static_cast<int>(i);
        }
    }
    return -1;
}


bool TeamSelectDetector::detect(const ImageViewRGB32& screen){
    int tab = selected_tab(screen);
    if (tab < 0){
        return false;
    }
    m_selected_tab = static_cast<uint8_t>(tab);
    return true;
}


}
}
}
