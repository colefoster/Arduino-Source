/*  Pokemon Champions Pokemon Switch Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Three cursor-independent samples:
 *    1. Lime active "Moves & More" tab at top of center panel.
 *    2. Purple left mon-list column at upper y.
 *    3. Same column at lower y — both must read purple to confirm the
 *       full vertical stripe (not just one mon row that happened to
 *       land there).
 *
 *  Pixel measurements (1920x1080):
 *    Tab lime:        x=380, y=260  RGB ≈ (200, 254, 9), ratio (0.43, 0.55, 0.02)
 *    Left col upper:  x=260, y=410  RGB ≈ (106, 96, 242), ratio (0.24, 0.22, 0.55)
 *    Left col lower:  x=260, y=650  RGB ≈ (107, 96, 242), same purple
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_PokemonSwitchDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


static const FloatPixel TAB_LIME{0.43, 0.55, 0.02};
static const FloatPixel LEFT_COL_PURPLE{0.24, 0.22, 0.55};


PokemonSwitchDetector::PokemonSwitchDetector()
    //  x=380, y=260, w=15, h=15
    : m_tab_lime    (0.1979, 0.2407, 0.0078, 0.0139)
    //  x=260, y=410, w=15, h=15
    , m_left_col_top(0.1354, 0.3796, 0.0078, 0.0139)
    //  x=260, y=650, w=15, h=15
    , m_left_col_bot(0.1354, 0.6019, 0.0078, 0.0139)
{}


void PokemonSwitchDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_tab_lime);
    items.add(COLOR_CYAN, m_left_col_top);
    items.add(COLOR_CYAN, m_left_col_bot);
}


bool PokemonSwitchDetector::detect(const ImageViewRGB32& screen){
    //  Co-evidence #1: lime active Moves & More tab.
    const ImageStats tab = image_stats(extract_box_reference(screen, m_tab_lime));
    if (tab.average.r + tab.average.g < 350.0) return false;
    if (!is_solid(tab, TAB_LIME, 0.10, 30)) return false;
    //  Co-evidence #2 & #3: left mon-list column purple at two y values.
    //  The moves_and_more screen has a similar lime tab but no left mon
    //  list — so this pair is the discriminator.
    const ImageStats top = image_stats(extract_box_reference(screen, m_left_col_top));
    if (top.average.b < 180.0) return false;
    if (!is_solid(top, LEFT_COL_PURPLE, 0.10, 50)) return false;
    const ImageStats bot = image_stats(extract_box_reference(screen, m_left_col_bot));
    if (bot.average.b < 180.0) return false;
    if (!is_solid(bot, LEFT_COL_PURPLE, 0.10, 50)) return false;
    return true;
}


}
}
}
