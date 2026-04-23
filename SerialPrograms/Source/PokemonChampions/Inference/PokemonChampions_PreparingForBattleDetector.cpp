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

#include <iostream>
#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_PreparingForBattleDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Both pills sample white text from "Standing By" label.
//  Tightened boxes land on letter strokes — near-white in both cases.
static const FloatPixel STANDING_BY_WHITE{0.333, 0.333, 0.333};


PreparingForBattleDetector::PreparingForBattleDetector()
    //  Box sized to sit inside each pill. In 1920x1080:
    //    Left pill:  x 400-500, y 920-950
    //    Right pill: x 1430-1560, y 925-955
    : m_left_standing_by (0.2280, 0.8695, 0.0016, 0.0204)
    , m_right_standing_by(0.7656, 0.8695, 0.0016, 0.0204)
{}

void PreparingForBattleDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_left_standing_by);
    items.add(COLOR_CYAN, m_right_standing_by);
}

bool PreparingForBattleDetector::detect(const ImageViewRGB32& screen){
    const ImageStats left_stats  = image_stats(extract_box_reference(screen, m_left_standing_by));
    const ImageStats right_stats = image_stats(extract_box_reference(screen, m_right_standing_by));

    //  Debug: print what we see
    double ls = left_stats.average.r + left_stats.average.g + left_stats.average.b;
    double rs = right_stats.average.r + right_stats.average.g + right_stats.average.b;
    std::cout << "PreparingDebug LEFT:  avg=(" << left_stats.average.r << "," << left_stats.average.g << "," << left_stats.average.b
              << ") ratio=(" << (ls>0?left_stats.average.r/ls:0) << "," << (ls>0?left_stats.average.g/ls:0) << "," << (ls>0?left_stats.average.b/ls:0)
              << ") sdsum=" << (left_stats.stddev.r + left_stats.stddev.g + left_stats.stddev.b) << std::endl;
    std::cout << "PreparingDebug RIGHT: avg=(" << right_stats.average.r << "," << right_stats.average.g << "," << right_stats.average.b
              << ") ratio=(" << (rs>0?right_stats.average.r/rs:0) << "," << (rs>0?right_stats.average.g/rs:0) << "," << (rs>0?right_stats.average.b/rs:0)
              << ") sdsum=" << (right_stats.stddev.r + right_stats.stddev.g + right_stats.stddev.b) << std::endl;

    //  Require BOTH pills to show their respective colors. A single pill in
    //  isolation could be anything — the pair is the strong signature.
    return is_solid(left_stats,  STANDING_BY_WHITE, 0.08, 100)
        && is_solid(right_stats, STANDING_BY_WHITE, 0.08, 100);
}


}
}
}
