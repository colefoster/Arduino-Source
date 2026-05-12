/*  Pokemon Champions "Preparing for Battle" Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the "Preparing for Battle" screen by checking for
 *  bright green selection highlights on the player's team card slots.
 *  On this screen, selected Pokemon (3 in singles, 4 in doubles) show
 *  a vivid green number badge. Requiring 3+ green slots out of 6 is
 *  a strong, unique signature — no other screen has this pattern.
 *
 *  Measured from inspector on 20260423-183259675247 (1920x1080 doubles).
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_PreparingForBattleDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Selected card green: vivid lime-green (R~140, G~245, B~0).
//  Color ratio ~(0.365, 0.635, 0.000).
static const FloatPixel SELECTED_GREEN{0.37, 0.63, 0.00};


PreparingForBattleDetector::PreparingForBattleDetector()
    //  6 boxes on the player's team card number badges (left column).
    //  These land on the green number indicator for selected cards,
    //  or on the blue-purple card body for unselected cards.
    : m_left_standing_by (0.2875, 0.1475, 0.0122, 0.0076)   // slot 0 (top)
    , m_right_standing_by(0.2840, 0.7333, 0.0146, 0.0054)   // slot 5 (bottom, placeholder for overlay)
{
    m_card_slots[0] = ImageFloatBox(0.2875, 0.1475, 0.0122, 0.0076);
    m_card_slots[1] = ImageFloatBox(0.2837, 0.2656, 0.0155, 0.0080);
    m_card_slots[2] = ImageFloatBox(0.2806, 0.3827, 0.0191, 0.0073);
    m_card_slots[3] = ImageFloatBox(0.2806, 0.4978, 0.0192, 0.0088);
    m_card_slots[4] = ImageFloatBox(0.2839, 0.6151, 0.0138, 0.0075);
    m_card_slots[5] = ImageFloatBox(0.2840, 0.7333, 0.0146, 0.0054);
}

void PreparingForBattleDetector::make_overlays(VideoOverlaySet& items) const{
    for (int i = 0; i < 6; i++){
        items.add(COLOR_CYAN, m_card_slots[i]);
    }
}

bool PreparingForBattleDetector::detect(const ImageViewRGB32& screen){
    int green_count = 0;
    for (int i = 0; i < 6; i++){
        const ImageStats stats = image_stats(extract_box_reference(screen, m_card_slots[i]));
        //  Check for vivid green: high G ratio, near-zero B ratio.
        if (is_solid(stats, SELECTED_GREEN, 0.15, 80)){
            green_count++;
        }
    }
    //  3+ green = singles (3 selected) or doubles (4 selected).
    return green_count >= 3;
}


}
}
}
