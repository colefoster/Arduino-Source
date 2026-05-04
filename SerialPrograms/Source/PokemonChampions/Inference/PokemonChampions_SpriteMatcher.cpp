/*  Pokemon Champions Sprite Matcher
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/ImageMatch/ImageCropper.h"
#include "PokemonChampions/Resources/PokemonChampions_PokemonSprites.h"
#include "PokemonChampions_SpriteMatcher.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


PokemonSpriteMatcher::PokemonSpriteMatcher(double min_euclidean_distance)
    //  Weight tuning borrowed from PokemonSwSh_PokemonSpriteReader:
    //  {min_weight, max_weight} for stddev-based weighting during RMSD.
    : CroppedImageDictionaryMatcher({1, 256})
    , m_min_euclidean_distance_squared(min_euclidean_distance * min_euclidean_distance)
{
    //  Load 272 unique species templates from the atlas. SpriteDatabase's
    //  "icon" field already has 0-alpha boundaries trimmed on load, which
    //  keeps the reference and the auto-cropped input at comparable
    //  content fractions when scaled for RMSD.
    for (const auto& item : ALL_POKEMON_SPRITES()){
        add(item.first, item.second.icon.copy());
    }
    //  Shiny variants are loaded with a "-shiny" slug suffix so callers
    //  that don't care can ignore it, while callers that need to know
    //  whether the match was a shiny can check for the suffix. Suffix is
    //  stripped via base_slug() above for downstream consumers.
    for (const auto& item : ALL_POKEMON_SPRITES_SHINY()){
        add(item.first + "-shiny", item.second.icon.copy());
    }
}


std::string PokemonSpriteMatcher::base_slug(const std::string& slug){
    static const std::string SUFFIX = "-shiny";
    if (slug.size() > SUFFIX.size() &&
        slug.compare(slug.size() - SUFFIX.size(), SUFFIX.size(), SUFFIX) == 0)
    {
        return slug.substr(0, slug.size() - SUFFIX.size());
    }
    return slug;
}


std::vector<ImageViewRGB32> PokemonSpriteMatcher::get_crop_candidates(
    const ImageViewRGB32& image
) const{
    //  Measure the 1-pixel border of the input to estimate the pill
    //  background color (pink/red for opponent preview, or any solid
    //  color in other contexts), then trim to the bounding box of
    //  pixels that differ from that color by more than the distance
    //  threshold.
    ImageStats border = image_border_stats(image);
    ImagePixelBox box = ImageMatch::enclosing_rectangle_with_pixel_filter(
        image,
        [&](Color pixel){
            double r = (double)pixel.red()   - border.average.r;
            double g = (double)pixel.green() - border.average.g;
            double b = (double)pixel.blue()  - border.average.b;
            return r * r + g * g + b * b >= m_min_euclidean_distance_squared;
        }
    );
    std::vector<ImageViewRGB32> ret;
    ret.emplace_back(extract_box_reference(image, box));
    return ret;
}


const PokemonSpriteMatcher& PokemonSpriteMatcher::instance(){
    static PokemonSpriteMatcher matcher;
    return matcher;
}


}
}
}
