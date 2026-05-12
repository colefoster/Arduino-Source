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

#include <sstream>
#include <iomanip>
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
    //  5 visible-column cursor positions for the 18-team carousel.
    //  Measured 2026-05-08 (tools/box_definitions.json: very-first /
    //  1st-main / middle / 3rd-main / last team-spot-cursor entries).
    //  selected_team() returns the cursor *column* (0..4), NOT the
    //  absolute team index — col 0 is reachable only on Team 1, col 4
    //  only on Team 18; cols 1..3 are ambiguous mid-carousel and need
    //  the homing logic in LiveDetectorTrace to pin the absolute team.
    : m_tab_slots{
          ImageFloatBox(0.0981, 0.1385, 0.0316, 0.0364),  //  col 0 (Team 1)
          ImageFloatBox(0.2870, 0.1395, 0.0201, 0.0327),  //  col 1
          ImageFloatBox(0.4049, 0.1376, 0.0233, 0.0345),  //  col 2 (middle)
          ImageFloatBox(0.5922, 0.1387, 0.0206, 0.0353),  //  col 3
          ImageFloatBox(0.7846, 0.1373, 0.0211, 0.0314),  //  col 4 (Team 18)
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
        //  Brightness floor: real selected tab reads avg ~ (255, 255, 3),
        //  channel-sum ~ 510. Battle FPs (mid-animation green flashes etc.)
        //  read ratio-similar yellow but max out around sum ~ 312.
        if (stats.average.r + stats.average.g < 400.0) continue;
        //  Modest tolerance: stored carousel screenshots read sd 5-10
        //  with ratios well inside 0.10 of the target, but live capture
        //  adds compression / sub-pixel noise that can push either past
        //  the 0.10 / 40 bar that worked on the static 5-tab layout.
        if (is_solid(stats, SELECTED_TAB_YELLOW, 0.12, 60)){
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


std::string TeamSelectDetector::debug_dump(const ImageViewRGB32& screen) const{
    std::ostringstream os;
    os << std::fixed << std::setprecision(1);
    os << "TeamSelectDetector boxes:";
    static const char* labels[5] = {
        "col0(very-first)", "col1(1st-main)", "col2(middle)",
        "col3(3rd-main)",   "col4(last)"
    };
    for (size_t i = 0; i < m_tab_slots.size(); i++){
        const ImageStats stats = image_stats(extract_box_reference(screen, m_tab_slots[i]));
        const double s = stats.average.r + stats.average.g + stats.average.b;
        const double rr = s > 0 ? stats.average.r / s : 0.0;
        const double gr = s > 0 ? stats.average.g / s : 0.0;
        const double br = s > 0 ? stats.average.b / s : 0.0;
        const double sd = stats.stddev.r + stats.stddev.g + stats.stddev.b;
        const bool floor = (stats.average.r + stats.average.g) >= 400.0;
        const bool solid = is_solid(stats, SELECTED_TAB_YELLOW, 0.12, 60);
        os << " | " << labels[i]
           << " avg=(" << stats.average.r << "," << stats.average.g << "," << stats.average.b << ")"
           << " ratio=(" << std::setprecision(3) << rr << "," << gr << "," << br << ")"
           << std::setprecision(1)
           << " sd=" << sd
           << (floor ? " floor=ok" : " floor=NO")
           << (solid ? " is_solid=YES" : " is_solid=no");
    }
    return os.str();
}


}
}
}
