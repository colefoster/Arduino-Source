/*  Pokemon Champions Battle End / Result Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates derived from ref_frames/1/labeled/result_won_lost_split.png.
 *
 *  The result screen is a split: one half shows the winner with a yellow/gold
 *  "WON!" emblem and a blue nameplate; the other half shows the loser with a
 *  faded gray "LOST..." and a red nameplate. We only need to know whether
 *  the PLAYER (always on the left) won — so we check the left side for
 *  either the yellow-gold winner glow OR the gray loser fade.
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_BattleEndDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Winner nameplate is solid blue. RGB approx (58, 78, 220) -> ratio
//  (0.16, 0.22, 0.62). Strong B dominance.
static const FloatPixel WINNER_BLUE_NAMEPLATE{0.16, 0.22, 0.62};
//  Loser nameplate is solid red. RGB approx (185, 22, 62) -> ratio
//  (0.69, 0.08, 0.23). Strong R dominance.
static const FloatPixel LOSER_RED_NAMEPLATE{0.69, 0.08, 0.23};


ResultScreenDetector::ResultScreenDetector()
    //  Player always on the left, opponent on the right. Sampling the
    //  nameplate bar that sits beneath the trainer portrait on each side.
    //  The nameplate color (blue vs red) cleanly distinguishes winner/loser.
    : m_left_won_glow  (0.160, 0.870, 0.180, 0.040)   // left nameplate bar
    , m_right_lost_glow(0.660, 0.870, 0.180, 0.040)   // right nameplate bar
    //  These two are unused in the current split-screen implementation but
    //  kept in the header for forward compat (single-side result views, etc.)
    , m_left_lost_banner (0.000, 0.000, 0.000, 0.000)
    , m_right_won_glow   (0.000, 0.000, 0.000, 0.000)
{}

void ResultScreenDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_left_won_glow);
    items.add(COLOR_CYAN, m_right_lost_glow);
}

bool ResultScreenDetector::detect(const ImageViewRGB32& screen){
    const ImageStats left  = image_stats(extract_box_reference(screen, m_left_won_glow));
    const ImageStats right = image_stats(extract_box_reference(screen, m_right_lost_glow));

    //  stddev_max=200 absorbs the white-text-on-color spread within the
    //  nameplate (text bumps right-red stddev sum up to ~167 in measured
    //  frames). The 0.15 ratio tolerance still rejects all non-result
    //  frames (dark transitions, light HUD overlays, etc.).
    const bool left_blue  = is_solid(left,  WINNER_BLUE_NAMEPLATE, 0.15, 200);
    const bool left_red   = is_solid(left,  LOSER_RED_NAMEPLATE,   0.15, 200);
    const bool right_blue = is_solid(right, WINNER_BLUE_NAMEPLATE, 0.15, 200);
    const bool right_red  = is_solid(right, LOSER_RED_NAMEPLATE,   0.15, 200);

    //  Valid result screen: one side blue nameplate (winner), other red (loser).
    //  Player is always on the left, so left-blue = won, left-red = lost.
    if (left_blue && right_red){
        m_won = true;
        return true;
    }
    if (left_red && right_blue){
        m_won = false;
        return true;
    }
    return false;
}


}
}
}
