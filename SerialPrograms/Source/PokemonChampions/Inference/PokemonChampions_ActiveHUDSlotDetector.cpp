/*  Pokemon Champions Active HUD Slot Detector
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_ActiveHUDSlotDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Lime green outline that appears on the active HUD pill's top edge.
//  Measured RGB ~(167, 255, 0); normalized to sum=1: 167/422, 255/422, 0.
static const FloatPixel ACTIVE_LIME{0.396, 0.604, 0.000};


ActiveHUDSlotDetector::ActiveHUDSlotDetector()
    //  Thin horizontal strips along the top edge of each own HUD pill.
    //  Kept tight (3px tall on 1080) so we sample only the lime band, not
    //  the lighter background above or the darker pill body below.
    //  Strip widths span the full pill so partial occlusion still works.
    : m_slot_strips{
        ImageFloatBox(0.0527, 0.8530, 0.1728, 0.0030),  //  slot 0 (left)
        ImageFloatBox(0.2628, 0.8530, 0.1728, 0.0030),  //  slot 1 (right)
    }
{}

void ActiveHUDSlotDetector::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& strip : m_slot_strips){
        items.add(COLOR_CYAN, strip);
    }
}

bool ActiveHUDSlotDetector::detect(const ImageViewRGB32& screen){
    m_active_slot = -1;
    int hits = 0;

    for (int i = 0; i < 2; i++){
        const ImageStats stats = image_stats(extract_box_reference(screen, m_slot_strips[i]));
        if (is_solid(stats, ACTIVE_LIME, 0.15, 80)){
            m_active_slot = i;
            hits++;
        }
    }

    //  Exactly one slot must match — both active or none means the screen
    //  isn't a doubles move select (or rendering is mid-transition).
    return hits == 1;
}


}
}
}
