/*  Pokemon Champions Action Menu Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates derived from live 1920x1080 captures
 *  (ref_frames/1/labeled/action_menu_{fight,pokemon}_live.png).
 *
 *  The two circular buttons have a distinctive bright yellow-green GLOW that
 *  appears on the outside edge when selected. The interior is mostly
 *  purple/gray with Poke Ball icons, so sampling inside the button doesn't
 *  distinguish states well. Instead we sample a thin strip just *above* each
 *  button's top edge, where the selected glow is at its brightest.
 *
 *  Measured colors:
 *    FIGHT glow (selected)   avg RGB (236,254, 81)  ratio (0.413,0.446,0.141)
 *    POKE  glow (selected)   avg RGB (212,242, 54)  ratio (0.417,0.477,0.107)
 *    either glow (not sel.)  avg RGB (~150, ~140, ~235)  purple-ish
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_ActionMenuDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Yellow-green halo around the selected round button.
static const FloatPixel SELECTED_GLOW_RATIO{0.41, 0.46, 0.13};


ActionMenuDetector::ActionMenuDetector()
    //  Thin horizontal strips sitting directly above the top edge of each
    //  circular button. Size chosen to stay *inside* the glow halo and NOT
    //  extend into the background (arena floor / locker wall).
    //  x 1740-1790, y 615-635 (FIGHT top glow in 1920x1080)
    : m_fight_button  (0.9062, 0.5694, 0.0260, 0.0213)
    //  x 1740-1790, y 862-885 (POKE top glow)
    , m_pokemon_button(0.9062, 0.7981, 0.0260, 0.0213)
{}

void ActionMenuDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_fight_button);
    items.add(COLOR_CYAN, m_pokemon_button);
}

bool ActionMenuDetector::is_fight_selected(const ImageViewRGB32& screen) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, m_fight_button));
    return is_solid(stats, SELECTED_GLOW_RATIO, 0.15, 120);
}
bool ActionMenuDetector::is_pokemon_selected(const ImageViewRGB32& screen) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, m_pokemon_button));
    return is_solid(stats, SELECTED_GLOW_RATIO, 0.15, 120);
}

bool ActionMenuDetector::detect(const ImageViewRGB32& screen){
    if (is_fight_selected(screen)){
        m_cursored = ActionMenuButton::FIGHT;
        return true;
    }
    if (is_pokemon_selected(screen)){
        m_cursored = ActionMenuButton::POKEMON;
        return true;
    }
    return false;
}


}
}
}
