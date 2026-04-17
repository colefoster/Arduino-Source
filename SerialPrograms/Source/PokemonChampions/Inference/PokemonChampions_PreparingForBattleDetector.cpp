/*  Pokemon Champions "Preparing for Battle" Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates derived from ref_frames/1/labeled/preparing_for_battle_live.png.
 *
 *  Both teams display a "Standing By" pill at the bottom of their column.
 *  The player's pill is a blue-purple gradient (matches the player theme
 *  color across the game UI). The opponent's pill is pink (opponent theme).
 *  Detecting both simultaneously is a strong signature — neither color
 *  appears paired with the other on any other screen we've cataloged.
 *
 *  Measured:
 *    Left (player)   x 400-500, y 920-950  avg RGB (~85,~100,~220)  blue-purple
 *    Right (opponent) x 1430-1560, y 925-955  avg RGB (~245, ~90,~180)  pink
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


//  Player pill: blue-purple gradient. Dark portion has high B, low R+G.
static const FloatPixel STANDING_BY_PLAYER_BLUE {0.14, 0.19, 0.67};
//  Opponent pill: pink. High R, mid B, low G.
static const FloatPixel STANDING_BY_OPPONENT_PINK{0.48, 0.17, 0.35};


PreparingForBattleDetector::PreparingForBattleDetector()
    //  Box sized to sit inside each pill. In 1920x1080:
    //    Left pill:  x 400-500, y 920-950
    //    Right pill: x 1430-1560, y 925-955
    : m_left_standing_by (0.2083, 0.8519, 0.0521, 0.0278)
    , m_right_standing_by(0.7448, 0.8565, 0.0677, 0.0278)
{}

void PreparingForBattleDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_left_standing_by);
    items.add(COLOR_CYAN, m_right_standing_by);
}

bool PreparingForBattleDetector::detect(const ImageViewRGB32& screen){
    const ImageStats left_stats  = image_stats(extract_box_reference(screen, m_left_standing_by));
    const ImageStats right_stats = image_stats(extract_box_reference(screen, m_right_standing_by));

    //  Require BOTH pills to show their respective colors. A single pill in
    //  isolation could be anything — the pair is the strong signature.
    return is_solid(left_stats,  STANDING_BY_PLAYER_BLUE,    0.18, 150)
        && is_solid(right_stats, STANDING_BY_OPPONENT_PINK,  0.18, 120);
}


}
}
}
