/*  Pokemon Champions Casual Format Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Measured colors (1920x1080, screenshot-20260508-153628218227.png):
 *    casual_detect  (band)     RGB (98, 90, 208)   ratio (0.247, 0.227, 0.525)
 *    casual_singles (cursored) RGB (210, 255, 21)  ratio (0.432, 0.524, 0.044)
 *    casual_doubles (unsel.)   RGB (116, 104, 236) ratio (0.255, 0.228, 0.517)
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_CasualFormatSelectDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Dark blue-purple band behind the "Casual Battles" header pill. Stable
//  whether cursor is on Singles or Doubles.
static const FloatPixel ANCHOR_PURPLE{0.247, 0.227, 0.525};


CasualFormatSelectDetector::CasualFormatSelectDetector()
    : m_anchor(0.6544, 0.1806, 0.2542, 0.0355)
{
    m_pill_boxes[0] = ImageFloatBox(0.6828, 0.3375, 0.0410, 0.1587);  //  Singles
    m_pill_boxes[1] = ImageFloatBox(0.6849, 0.5822, 0.0389, 0.1662);  //  Doubles
}


void CasualFormatSelectDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_anchor);
    items.add(COLOR_YELLOW, m_pill_boxes[0]);
    items.add(COLOR_YELLOW, m_pill_boxes[1]);
}


//  (R+G)/2 - B; positive iff the pill renders the cursored bright-yellow.
static double yellow_score(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return -1.0;
    ImageStats st = image_stats(crop);
    int r = (int)st.average.r;
    int g = (int)st.average.g;
    int b = (int)st.average.b;
    int score = (r + g) / 2 - b;
    return score > 0 ? double(score) : 0.0;
}


bool CasualFormatSelectDetector::detect(const ImageViewRGB32& screen){
    m_selected_index = -1;

    //  Anchor: blue-purple band must be solidly that color.
    const ImageStats anchor = image_stats(extract_box_reference(screen, m_anchor));
    if (anchor.average.b < 150.0) return false;
    if (!is_solid(anchor, ANCHOR_PURPLE, 0.06, 100)) return false;

    //  Cursor read: only the cursored pill renders bright yellow. Whichever
    //  pill scores yellow above the floor wins; if neither does, leave -1.
    double s0 = yellow_score(extract_box_reference(screen, m_pill_boxes[0]));
    double s1 = yellow_score(extract_box_reference(screen, m_pill_boxes[1]));
    if (s0 >= 60.0 && s0 > s1){
        m_selected_index = 0;
    }else if (s1 >= 60.0 && s1 > s0){
        m_selected_index = 1;
    }
    return true;
}


}
}
}
