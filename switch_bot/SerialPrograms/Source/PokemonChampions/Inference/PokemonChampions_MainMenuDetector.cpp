/*  Pokemon Champions Main Menu Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates derived from live 1920x1080 captures via pixel_inspector.
 *
 *  The main menu has selectable items (Battle, Box, etc.) that display a
 *  bright yellow glow when highlighted. We sample a small region inside
 *  each button's yellow highlight area.
 *
 *  Measured colors:
 *    Battle (selected)  avg RGB (240, 250, 21)  ratio (0.47, 0.49, 0.04)
 *    Box (selected)     avg RGB (255, 255,  6)  ratio (0.49, 0.49, 0.01)
 *
 */

#include <algorithm>
#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "PokemonChampions_MainMenuDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Bright yellow highlight on selected menu item.
static const FloatPixel SELECTED_YELLOW{0.48, 0.49, 0.03};

//  Recruit tile interior: saturated brown panel. Cursor-independent —
//  the cursor adds a yellow ring around the tile but doesn't alter its fill.
//  Measured: avg RGB (153, 104, 8), ratio (0.58, 0.39, 0.03)
static const FloatPixel RECRUIT_BROWN{0.58, 0.39, 0.03};


MainMenuDetector::MainMenuDetector()
    //  Small sample regions inside the yellow glow of each menu button.
    //  Battle:  x ~1056, y ~568  (center of the button's yellow area)
    : m_battle_button(0.5500, 0.5259, 0.0016, 0.0028)
    //  Box:     x ~1470, y ~373
    , m_box_button   (0.7656, 0.3454, 0.0021, 0.0037)
    //  Menu chrome: cyan-blue wallpaper in the upper-left corner.
    //  x=100, y=80, w=30, h=30 in 1920x1080. Chosen above the NPC dialog
    //  region — the prior position at (576, 486) was occluded by the
    //  Tatora speech bubble in 6/10 corpus frames.
    , m_chrome       (0.0521, 0.0741, 0.0156, 0.0278)
    //  Recruit tile interior: x=1100, y=410, w=25, h=25 in 1920x1080.
    //  Cursor-independent screen-presence cue — the brown panel fill is
    //  stable across all cursor positions in the corpus.
    , m_recruit_tile (0.5729, 0.3796, 0.0130, 0.0231)
    //  Top-right gold/yellow icon — drawn 2026-05-09. Verified across all
    //  11 main_menu corpus shots; zero hits across 70+ non-menu screens.
    //  Brightness varies session-to-session (210..254 on R), so we do a
    //  loose "yellowish" check rather than a tight ratio match.
    , m_yellow_anchor(0.9094, 0.1447, 0.0485, 0.0268)
    //  Neutral mid-grey panel near the top of the screen — drawn
    //  2026-05-09. Reads ~(86, 89, 88) sd~10 across every main_menu shot
    //  in the corpus; nothing else in the corpus reads neutral grey at
    //  this position. Strict gate.
    , m_grey_anchor  (0.3113, 0.0177, 0.1101, 0.0699)
{
    //  Per-option cursor strips drawn by user.
    m_cursor_boxes[0] = ImageFloatBox(0.5403, 0.3214, 0.0083, 0.1857);  //  Battle
    m_cursor_boxes[1] = ImageFloatBox(0.9807, 0.1817, 0.0045, 0.1337);  //  Box
    m_cursor_boxes[2] = ImageFloatBox(0.9801, 0.5813, 0.0054, 0.1341);  //  Train
    m_cursor_boxes[3] = ImageFloatBox(0.5451, 0.6028, 0.0052, 0.0824);  //  Recruit
    m_cursor_boxes[4] = ImageFloatBox(0.2169, 0.9295, 0.0231, 0.0175);  //  Missions
    m_cursor_boxes[5] = ImageFloatBox(0.3761, 0.9268, 0.0188, 0.0221);  //  Mailbox
    m_cursor_boxes[6] = ImageFloatBox(0.5308, 0.9265, 0.0256, 0.0211);  //  Style
    m_cursor_boxes[7] = ImageFloatBox(0.6844, 0.9269, 0.0239, 0.0241);  //  SubMenu
}

void MainMenuDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_battle_button);
    items.add(COLOR_CYAN, m_box_button);
    items.add(COLOR_CYAN, m_chrome);
    items.add(COLOR_YELLOW, m_recruit_tile);
    items.add(COLOR_YELLOW, m_yellow_anchor);
    items.add(COLOR_WHITE, m_grey_anchor);
    for (const ImageFloatBox& b : m_cursor_boxes){
        items.add(COLOR_YELLOW, b);
    }
}


//  Tight neutral-grey check for m_grey_anchor. Measured: avg~(86, 89, 88),
//  sd~9-12 across all corpus shots. Channel-balanced (no dominant color)
//  in the dark-grey range.
static bool is_neutral_grey(const ImageStats& stats){
    const double r = stats.average.r;
    const double g = stats.average.g;
    const double b = stats.average.b;
    if (r < 60.0 || r > 130.0) return false;
    if (g < 60.0 || g > 130.0) return false;
    if (b < 60.0 || b > 130.0) return false;
    //  Channel imbalance ≤ 12 keeps this off any tinted dark surface.
    const double max_c = std::max({r, g, b});
    const double min_c = std::min({r, g, b});
    if (max_c - min_c > 12.0) return false;
    //  Internal variance must be low — kills textured / noisy regions.
    return (stats.stddev.r + stats.stddev.g + stats.stddev.b) <= 25.0;
}

//  Loose "yellowish" check for m_yellow_anchor. The icon shade varies
//  session-to-session (R 210..254, G 179..215, B 15..57), but is always
//  yellow-leaning: r and g both bright, b small.
static bool is_yellowish_icon(const ImageStats& stats){
    const double r = stats.average.r;
    const double g = stats.average.g;
    const double b = stats.average.b;
    if (r + g < 360.0) return false;        //  brightness floor on (r+g)
    if (b > 90.0)      return false;        //  blue must be subdued
    if (r < 180.0 || g < 150.0) return false;
    //  Internal variance: the anchor lands on icon + uniform background,
    //  sd~17-45 in the corpus.
    return (stats.stddev.r + stats.stddev.g + stats.stddev.b) <= 70.0;
}


//  (R+G)/2 - B; positive iff the strip skews yellow.
static double yellow_score(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return -1.0;
    ImageStats st = image_stats(crop);
    int r = (int)st.average.r;
    int g = (int)st.average.g;
    int b = (int)st.average.b;
    int score = (r + g) / 2 - b;
    return score > 0 ? double(score) : 0.0;
}

//  is_solid alone (ratio-based) accepts dim brownish-yellow pixels at the
//  same ratio as bright menu-yellow. Real selected yellow is ~RGB(240, 250, 20),
//  so r+g >= 400 cleanly rejects all the dim FPs (which max out at r+g ~ 200
//  in measured action_menu / move_select / overlay frames).
static constexpr double MIN_YELLOW_BRIGHTNESS = 400.0;

static bool is_bright_yellow(const ImageStats& stats){
    if (stats.average.r + stats.average.g < MIN_YELLOW_BRIGHTNESS) return false;
    //  Tightened from 0.15 to 0.05: rejects orange/red-tinted yellows that
    //  appear on battle HUDs while keeping the saturated menu yellow.
    return is_solid(stats, SELECTED_YELLOW, 0.05, 100);
}

//  Chrome sample must be cyan-blue (TV backdrop) — kills the rest of the FPs
//  where battle UI happens to contain a saturated-yellow pixel at the button
//  sample coords. Thresholds chosen with margin: real menu reads b≈254,
//  worst FP at this position has b=127.
static bool is_menu_chrome_blue(const ImageStats& stats){
    return stats.average.b >= 150.0
        && stats.average.b > stats.average.r + 50.0;
}

bool MainMenuDetector::is_battle_selected(const ImageViewRGB32& screen) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, m_battle_button));
    return is_bright_yellow(stats);
}
bool MainMenuDetector::is_box_selected(const ImageViewRGB32& screen) const{
    const ImageStats stats = image_stats(extract_box_reference(screen, m_box_button));
    return is_bright_yellow(stats);
}

bool MainMenuDetector::detect(const ImageViewRGB32& screen){
    //  Strict co-evidence #1: neutral-grey panel near the top of the
    //  screen. Reads ~(86, 89, 88) sd~10 on every main_menu corpus
    //  shot; nothing else in the corpus reads neutral grey at this
    //  position. Cheapest reject.
    const ImageStats grey = image_stats(extract_box_reference(screen, m_grey_anchor));
    if (!is_neutral_grey(grey)) return false;
    //  Strict co-evidence #2: top-right yellow icon. Verified across
    //  all 11 main_menu corpus shots; zero hits across the rest.
    const ImageStats yel = image_stats(extract_box_reference(screen, m_yellow_anchor));
    if (!is_yellowish_icon(yel)) return false;
    //  Co-evidence #3: cyan-blue wallpaper in upper-left corner.
    const ImageStats chrome = image_stats(extract_box_reference(screen, m_chrome));
    if (!is_menu_chrome_blue(chrome)) return false;
    //  Co-evidence #4: Recruit tile brown fill — cursor-independent.
    //  Saturated brown (r:g:b ≈ 0.58:0.39:0.03) with brightness floor.
    //  stddev_sum ≈ 165-175 across the corpus — tile has internal texture/gradient.
    const ImageStats brown = image_stats(extract_box_reference(screen, m_recruit_tile));
    if (brown.average.r + brown.average.g < 200.0) return false;
    if (!is_solid(brown, RECRUIT_BROWN, 0.10, 250)) return false;
    //  Score all 8 cursor strips and pick the highest yellow above the floor.
    //  Falls back to UNKNOWN if nothing scores high enough — the suggester
    //  treats that as "wait a poll".
    int best = -1;
    double best_score = 0.0;
    for (int i = 0; i < 8; i++){
        double s = yellow_score(extract_box_reference(screen, m_cursor_boxes[i]));
        if (s > best_score && s >= 30.0){
            best_score = s;
            best = i;
        }
    }
    m_cursored = best >= 0 ? (MainMenuButton)best : MainMenuButton::UNKNOWN;
    return true;
}


}
}
}
