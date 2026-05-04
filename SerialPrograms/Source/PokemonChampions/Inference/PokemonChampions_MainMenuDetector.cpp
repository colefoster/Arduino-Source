/*  Pokemon Champions Main Menu Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates derived from live 1920x1080 captures via pixel_inspector.
 *
 *  The main menu has selectable items (Battle, Box, etc.) that display a
 *  bright yellow glow when highlighted. We sample a small region inside
 *  each button's yellow highlight area.
 *
 *  Measured colors:
 *    Battle (selected)  avg RGB (240, 250, 21)  ratio (0.47, 0.49, 0.04)
 *    Box (selected)     avg RGB (255, 255,  6)  ratio (0.49, 0.49, 0.01)
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_MainMenuDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Bright yellow highlight on selected menu item.
static const FloatPixel SELECTED_YELLOW{0.48, 0.49, 0.03};


MainMenuDetector::MainMenuDetector()
    //  Small sample regions inside the yellow glow of each menu button.
    //  Battle:  x ~1056, y ~568  (center of the button's yellow area)
    : m_battle_button(0.5500, 0.5259, 0.0016, 0.0028)
    //  Box:     x ~1470, y ~373
    , m_box_button   (0.7656, 0.3454, 0.0021, 0.0037)
    //  Menu chrome: TV/character backdrop. Reads bright cyan-blue on the
    //  real menu (avg b ≈ 254) and warm/dim on every battle FP we sampled.
    //  Required co-evidence — without it, isolated yellow pixels in battle
    //  HUDs (status icons, move tiles, etc.) trigger false positives.
    , m_chrome       (0.30,   0.45,   0.05,   0.05)
{}

void MainMenuDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_battle_button);
    items.add(COLOR_CYAN, m_box_button);
    items.add(COLOR_CYAN, m_chrome);
}

//  is_solid alone (ratio-based) accepts dim brownish-yellow pixels at the
//  same ratio as bright menu-yellow. Real selected yellow is ~RGB(240, 250, 20),
//  so r+g >= 400 cleanly rejects all the dim FPs (which max out at r+g ~ 200
//  in measured action_menu / move_select / overlay frames).
static constexpr double MIN_YELLOW_BRIGHTNESS = 400.0;

static bool is_bright_yellow(const ImageStats& stats){
    if (stats.average.r + stats.average.g < MIN_YELLOW_BRIGHTNESS) return false;
    //  Tightened from 0.15 to 0.05: rejects orange/red-tinted yellows that
    //  appear on battle HUDs while keeping the saturated menu yellow.
    return is_solid(stats, SELECTED_YELLOW, 0.05, 100);
}

//  Chrome sample must be cyan-blue (TV backdrop) — kills the rest of the FPs
//  where battle UI happens to contain a saturated-yellow pixel at the button
//  sample coords. Thresholds chosen with margin: real menu reads b≈254,
//  worst FP at this position has b=127.
static bool is_menu_chrome_blue(const ImageStats& stats){
    return stats.average.b >= 150.0
        && stats.average.b > stats.average.r + 50.0;
}

bool MainMenuDetector::is_battle_selected(const ImageViewRGB32& screen) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, m_battle_button));
    return is_bright_yellow(stats);
}
bool MainMenuDetector::is_box_selected(const ImageViewRGB32& screen) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, m_box_button));
    return is_bright_yellow(stats);
}

bool MainMenuDetector::detect(const ImageViewRGB32& screen){
    const ImageStats chrome = image_stats(extract_box_reference(screen, m_chrome));
    if (!is_menu_chrome_blue(chrome)) return false;
    if (is_battle_selected(screen)){
        m_cursored = MainMenuButton::BATTLE;
        return true;
    }
    if (is_box_selected(screen)){
        m_cursored = MainMenuButton::BOX;
        return true;
    }
    return false;
}


}
}
}
