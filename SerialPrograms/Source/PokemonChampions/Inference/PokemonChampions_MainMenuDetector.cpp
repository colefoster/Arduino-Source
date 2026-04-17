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
{}

void MainMenuDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_battle_button);
    items.add(COLOR_CYAN, m_box_button);
}

bool MainMenuDetector::is_battle_selected(const ImageViewRGB32& screen) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, m_battle_button));
    return is_solid(stats, SELECTED_YELLOW, 0.15, 100);
}
bool MainMenuDetector::is_box_selected(const ImageViewRGB32& screen) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, m_box_button));
    return is_solid(stats, SELECTED_YELLOW, 0.15, 100);
}

bool MainMenuDetector::detect(const ImageViewRGB32& screen){
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
