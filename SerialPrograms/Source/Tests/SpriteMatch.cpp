/*  Sprite Match
 *
 *  Run the Pokemon Champions sprite matcher on an arbitrary box and print
 *  the top-N matches (slug + alpha) as JSON to stdout.
 */

#include "SpriteMatch.h"
#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/ImageMatch/ImageCropper.h"
#include "CommonTools/ImageMatch/ImageMatchResult.h"
#include "PokemonChampions/Inference/PokemonChampions_SpriteMatcher.h"

#include <array>
#include <iostream>
#include <string>
#include <vector>

namespace PokemonAutomation{

using namespace NintendoSwitch::PokemonChampions;


static void emit_matches_json(const ImageMatch::ImageMatchResult& result, int top_n){
    std::cout << "\"matches\":[";
    int written = 0;
    for (const auto& kv : result.results){
        if (written >= top_n) break;
        if (written > 0) std::cout << ",";
        std::cout << "{\"slug\":\"" << kv.second
                  << "\",\"alpha\":" << kv.first << "}";
        written++;
    }
    std::cout << "]";
}

int run_sprite_match(
    const std::string& image_path,
    double x, double y, double w, double h,
    int top_n
){
    try{
        ImageRGB32 image(image_path);
        ImageFloatBox box(x, y, w, h);
        ImageViewRGB32 cropped = extract_box_reference(image, box);

        const PokemonSpriteMatcher& matcher = PokemonSpriteMatcher::instance();
        ImageMatch::ImageMatchResult result = matcher.match(cropped, /* alpha_spread */ 10.0);

        std::cout << "{";
        emit_matches_json(result, top_n);
        std::cout << "}" << std::endl;
        return 0;
    }catch (const std::exception& e){
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
}

int run_sprite_match_debug(
    const std::string& image_path,
    double x, double y, double w, double h,
    const std::string& out_png_path,
    int top_n,
    const std::vector<BgColor>& bg_colors
){
    try{
        ImageRGB32 image(image_path);
        ImageFloatBox box(x, y, w, h);
        ImageViewRGB32 cropped = extract_box_reference(image, box);

        //  Multi-color bg paint pre-pass. For each (r,g,b,dist), pixels
        //  within `dist` Euclidean RGB distance of (r,g,b) are repainted
        //  white. This both (a) lets the matcher's own border-sample
        //  auto-crop tighten to the mon (white edges sample correctly as
        //  bg) and (b) prevents bg pixels inside the bbox from poisoning
        //  RMSD against atlas refs.
        ImageRGB32 painted;
        ImageViewRGB32 to_match = cropped;
        bool used_fixed_bg = !bg_colors.empty();
        if (used_fixed_bg){
            painted = cropped.copy();
            const size_t W = painted.width();
            const size_t H = painted.height();
            const uint32_t WHITE = 0xFFFFFFFF;
            //  Pre-square the distances.
            std::vector<std::array<double, 4>> bgs;
            bgs.reserve(bg_colors.size());
            for (const auto& c : bg_colors){
                bgs.push_back({(double)c.r, (double)c.g, (double)c.b,
                               c.dist * c.dist});
            }
            for (size_t y = 0; y < H; y++){
                for (size_t x = 0; x < W; x++){
                    uint32_t px = painted.pixel(x, y);
                    double r = (double)((px >> 16) & 0xFF);
                    double g = (double)((px >> 8)  & 0xFF);
                    double b = (double)( px        & 0xFF);
                    for (const auto& c : bgs){
                        double dr = r - c[0], dg = g - c[1], db = b - c[2];
                        if (dr*dr + dg*dg + db*db < c[3]){
                            painted.pixel(x, y) = WHITE;
                            break;
                        }
                    }
                }
            }
            to_match = painted;
        }

        const PokemonSpriteMatcher& matcher = PokemonSpriteMatcher::instance();
        auto candidates = matcher.debug_crop_candidates(to_match);
        bool saved = false;
        if (!candidates.empty()){
            saved = candidates[0].save(out_png_path);
        } else {
            //  Fall back to saving the pre-trimmed (or raw) input so the
            //  user always sees what was fed to match().
            saved = to_match.save(out_png_path);
        }

        ImageMatch::ImageMatchResult result = matcher.match(to_match, /* alpha_spread */ 10.0);

        std::cout << "{"
                  << "\"auto_crop_saved\":" << (saved ? "true" : "false") << ","
                  << "\"auto_crop_count\":" << candidates.size() << ","
                  << "\"used_fixed_bg\":" << (used_fixed_bg ? "true" : "false") << ",";
        emit_matches_json(result, top_n);
        std::cout << "}" << std::endl;
        return 0;
    }catch (const std::exception& e){
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
}


}
