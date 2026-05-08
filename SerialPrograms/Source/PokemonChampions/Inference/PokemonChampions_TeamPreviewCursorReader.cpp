/*  Pokemon Champions Team Preview Cursor Reader
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "Common/Cpp/Color.h"
#include "PokemonChampions_TeamPreviewCursorReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Per-slot cursor boxes drawn by user on
//  team_preview_selecting/20260505-game2-video-20260505-153202484050_0032.png.
//  The cursor (NOT the lead-mark ▶) is a small bright tab on the far left
//  of each card. Per-slot anchors — the cards wobble slightly so a global
//  delta + per-slot anchor extrapolation drifts.
TeamPreviewCursorReader::TeamPreviewCursorReader(){
    m_highlight[0] = ImageFloatBox(0.0235, 0.1821, 0.0143, 0.0235);
    m_highlight[1] = ImageFloatBox(0.0279, 0.3011, 0.0115, 0.0213);
    m_highlight[2] = ImageFloatBox(0.0239, 0.4165, 0.0163, 0.0222);
    m_highlight[3] = ImageFloatBox(0.0299, 0.5300, 0.0108, 0.0268);
    m_highlight[4] = ImageFloatBox(0.0318, 0.6513, 0.0093, 0.0237);
    m_highlight[5] = ImageFloatBox(0.0335, 0.7654, 0.0069, 0.0300);
    //  Index 6 = Done button (bottom of left column).
    m_highlight[6] = ImageFloatBox(0.1324, 0.8572, 0.0146, 0.0428);
}


void TeamPreviewCursorReader::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& box : m_highlight){
        items.add(COLOR_YELLOW, box);
    }
}


//  (R+G)/2 - B; positive iff the strip skews yellow vs. blue/purple.
static double yellow_score(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return -1.0;
    ImageStats st = image_stats(crop);
    int r = (int)st.average.r;
    int g = (int)st.average.g;
    int b = (int)st.average.b;
    int score = (r + g) / 2 - b;
    return score > 0 ? double(score) : 0.0;
}


int TeamPreviewCursorReader::read(Logger& logger, const ImageViewRGB32& screen) const{
    (void)logger;
    int best = -1;
    double best_score = 0.0;
    for (uint8_t i = 0; i < 7; i++){
        double s = yellow_score(extract_box_reference(screen, m_highlight[i]));
        if (s > best_score && s >= 30.0){
            best_score = s;
            best = (int)i;
        }
    }
    return best;
}


}
}
}
