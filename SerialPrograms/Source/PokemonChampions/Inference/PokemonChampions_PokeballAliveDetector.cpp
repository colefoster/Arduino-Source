/*  Pokemon Champions Pokeball Alive Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Box anchors measured via the dashboard Inspector and saved to
 *  tools/box_definitions.json. Linear extrapolation between anchors gives
 *  the full 6-slot row per side.
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "PokemonChampions_PokeballAliveDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


const char* pokeball_state_name(PokeballState s){
    switch (s){
        case PokeballState::ALIVE:          return "alive";
        case PokeballState::ALIVE_STATUSED: return "alive_statused";
        case PokeballState::FAINTED:        return "fainted";
        case PokeballState::EMPTY:          return "empty";
    }
    return "unknown";
}


//  ALIVE_STATUSED is still "alive" for the purposes of who's-still-in-the-
//  battle counting. The status condition affects play but the mon hasn't
//  been KO'd. Both states are counted.
static bool is_alive_state(PokeballState s){
    return s == PokeballState::ALIVE || s == PokeballState::ALIVE_STATUSED;
}

uint8_t PokeballAliveResult::own_alive_count() const{
    uint8_t n = 0;
    for (auto s : own) if (is_alive_state(s)) n++;
    return n;
}
uint8_t PokeballAliveResult::opp_alive_count() const{
    uint8_t n = 0;
    for (auto s : opp) if (is_alive_state(s)) n++;
    return n;
}


PokeballAliveDetector::PokeballAliveDetector(){
    init_boxes();
}


//  Anchors saved by the user in the Inspector (2026-05-02). The other
//  slots are linearly interpolated from these.
//    own_0:  (0.0518, 0.8155, 0.0085, 0.0155)
//    own_3:  (0.0943, 0.8151, 0.0092, 0.0146)
//    opp_0:  (0.8665, 0.1664, 0.0110, 0.0125)
//    opp_1:  (0.8809, 0.1677, 0.0106, 0.0113)
//    opp_3:  (0.9097, 0.1677, 0.0099, 0.0109)
void PokeballAliveDetector::init_boxes(){
    static const ImageFloatBox OWN[6] = {
        ImageFloatBox(0.0518, 0.8155, 0.0085, 0.0155),
        ImageFloatBox(0.0660, 0.8154, 0.0087, 0.0152),
        ImageFloatBox(0.0801, 0.8152, 0.0090, 0.0149),
        ImageFloatBox(0.0943, 0.8151, 0.0092, 0.0146),
        ImageFloatBox(0.1085, 0.8150, 0.0094, 0.0143),
        ImageFloatBox(0.1226, 0.8148, 0.0097, 0.0140),
    };
    static const ImageFloatBox OPP[6] = {
        ImageFloatBox(0.8665, 0.1664, 0.0110, 0.0125),
        ImageFloatBox(0.8809, 0.1677, 0.0106, 0.0113),
        ImageFloatBox(0.8953, 0.1677, 0.0103, 0.0111),
        ImageFloatBox(0.9097, 0.1677, 0.0099, 0.0109),
        ImageFloatBox(0.9241, 0.1677, 0.0099, 0.0109),
        ImageFloatBox(0.9385, 0.1677, 0.0099, 0.0109),
    };
    for (size_t i = 0; i < 6; i++){
        m_own_boxes[i] = OWN[i];
        m_opp_boxes[i] = OPP[i];
    }
}


void PokeballAliveDetector::make_overlays(VideoOverlaySet& items) const{
    for (const auto& box : m_own_boxes) items.add(COLOR_GREEN, box);
    for (const auto& box : m_opp_boxes) items.add(COLOR_GREEN, box);
}


//  Threshold-based four-way classifier on per-slot mean RGB.
//  Measured (action_menu/20260423-150354427178.png + move_select/20260423-183917790913.png):
//    alive (green):       r~108, g~185, b~57   (r/g ~ 0.59, r-g = -77)
//    alive_statused (org): r~229, g~167, b~5   (r/g ~ 1.37, r-g = +62)
//    fainted (grey):      r~77,  g~77,  b~70   (r ≈ g)
//    empty:               r~37,  g~37,  b~34   (r ≈ g, dim)
//  Within the bright "g >= 150" branch, r > g cleanly separates orange
//  (statused) from green (healthy). Margin on labeled samples is huge.
//  Fainted vs empty gap is narrow (~20 G units); cutoff at 67 sits midway.
static PokeballState classify(const ImageViewRGB32& slot){
    FloatPixel avg = image_average(slot);
    if (avg.g < 67.0)  return PokeballState::EMPTY;
    if (avg.g < 150.0) return PokeballState::FAINTED;
    //  Bright ball: green-healthy vs orange-statused.
    if (avg.r > avg.g) return PokeballState::ALIVE_STATUSED;
    return PokeballState::ALIVE;
}


PokeballAliveResult PokeballAliveDetector::read(const ImageViewRGB32& screen) const{
    PokeballAliveResult result;
    for (size_t i = 0; i < 6; i++){
        result.own[i] = classify(extract_box_reference(screen, m_own_boxes[i]));
        result.opp[i] = classify(extract_box_reference(screen, m_opp_boxes[i]));
    }
    return result;
}


}
}
}
