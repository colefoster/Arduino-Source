/*  Pokemon Champions Searching For Battle Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Two co-evidence samples on the modal interior. The modal spans most of
 *  the screen width, so we sample one spot well-left of center and one
 *  well-right — a small purple UI element elsewhere can't satisfy both.
 *
 *  Pixel measurements (1920x1080):
 *    Modal left:   x=620, y=480, w=30, h=30  → RGB ≈ (100, 94, 235)
 *    Modal right:  x=1280, y=480, w=30, h=30 → RGB ≈ (100, 94, 235)
 *    Ratio       ≈ (0.23, 0.22, 0.55)
 *    stddev_sum  ≤ 6 (very flat fill)
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_SearchingForBattleDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Saturated modal purple.
static const FloatPixel MODAL_PURPLE{0.23, 0.22, 0.55};


SearchingForBattleDetector::SearchingForBattleDetector()
    //  x=620, y=480, w=30, h=30 in 1920x1080.
    : m_modal_left (0.3229, 0.4444, 0.0156, 0.0278)
    //  x=1280, y=480, w=30, h=30 in 1920x1080.
    , m_modal_right(0.6667, 0.4444, 0.0156, 0.0278)
{}


void SearchingForBattleDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_modal_left);
    items.add(COLOR_CYAN, m_modal_right);
}


static bool is_modal_purple(const ImageStats& stats){
    //  Brightness floor: dimmest corpus sample sums to ~409.
    if (stats.average.sum() < 350.0) return false;
    return is_solid(stats, MODAL_PURPLE, 0.10, 50);
}


bool SearchingForBattleDetector::detect(const ImageViewRGB32& screen){
    const ImageStats left = image_stats(extract_box_reference(screen, m_modal_left));
    if (!is_modal_purple(left)) return false;
    const ImageStats right = image_stats(extract_box_reference(screen, m_modal_right));
    if (!is_modal_purple(right)) return false;
    return true;
}


}
}
}
