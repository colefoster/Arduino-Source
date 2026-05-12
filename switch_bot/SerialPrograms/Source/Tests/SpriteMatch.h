/*  Sprite Match
 *
 *  Run the Pokemon Champions sprite matcher on an arbitrary box of an
 *  image and print top-N matches as JSON.
 */

#ifndef PokemonAutomation_Tests_SpriteMatch_H
#define PokemonAutomation_Tests_SpriteMatch_H

#include <string>
#include <vector>

namespace PokemonAutomation{

int run_sprite_match(
    const std::string& image_path,
    double x, double y, double w, double h,
    int top_n = 5
);

//  Same as run_sprite_match, but also writes the auto-cropped candidate
//  image (what the matcher actually compares to the atlas, after pill-bg
//  removal) to <out_png_path>. Lets the dashboard show what the C++ side
//  sees post-trim, to debug whether mismatches are alignment / bg-removal
//  vs. genuine atlas mismatch.
//
//  Background paint pre-pass: any pixel within `dist` Euclidean RGB
//  distance of (r, g, b) is repainted white before the matcher sees the
//  crop. Pass multiple colors to paint several HUD chromes (e.g. pill
//  purple + active-turn lime-green glow). Use when border-sample bg
//  detection is fooled by HUD chrome.
struct BgColor{ int r, g, b; double dist; };

int run_sprite_match_debug(
    const std::string& image_path,
    double x, double y, double w, double h,
    const std::string& out_png_path,
    int top_n = 5,
    const std::vector<BgColor>& bg_colors = {}
);

}
#endif
