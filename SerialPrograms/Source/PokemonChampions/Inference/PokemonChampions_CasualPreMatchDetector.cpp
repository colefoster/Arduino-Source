/*  Pokemon Champions Casual Pre-Match Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Measured on screenshot-20260508-155224154854.png (cursor on Begin):
 *    team_select        avg (224, 219, 255)  white-ish
 *    change_music       avg (253, 252, 255)  near-pure white
 *    begin_matchmaking  avg (230, 255,  33)  bright yellow (cursored)
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "PokemonChampions_CasualPreMatchDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


CasualPreMatchDetector::CasualPreMatchDetector(){
    m_pill_boxes[0] = ImageFloatBox(0.5236, 0.2909, 0.1409, 0.0391);  //  Team Select
    m_pill_boxes[1] = ImageFloatBox(0.5126, 0.5059, 0.1359, 0.0426);  //  Change Music
    m_pill_boxes[2] = ImageFloatBox(0.5036, 0.8399, 0.1319, 0.0551);  //  Begin Matchmaking
}


void CasualPreMatchDetector::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& b : m_pill_boxes){
        items.add(COLOR_YELLOW, b);
    }
}


bool CasualPreMatchDetector::detect(const ImageViewRGB32& screen){
    m_selected_index = -1;
    int yellow_count = 0;
    int white_count = 0;
    int yellow_idx = -1;
    for (int i = 0; i < 3; i++){
        ImageStats st = image_stats(extract_box_reference(screen, m_pill_boxes[i]));
        double r = st.average.r, g = st.average.g, b = st.average.b;
        double yscore = (r + g) / 2.0 - b;
        if (yscore >= 60.0){
            yellow_count++;
            yellow_idx = i;
        }else if (r > 200.0 && g > 200.0 && b > 200.0){
            white_count++;
        }
    }
    //  All three pill regions must be bright (yellow OR white) and at most
    //  one cursored. If cursor is on a footer button, all three read white;
    //  detector still fires with selected_index = -1.
    if (yellow_count + white_count < 3) return false;
    if (yellow_count > 1) return false;
    m_selected_index = yellow_idx;
    return true;
}


}
}
}
