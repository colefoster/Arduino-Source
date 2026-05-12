/*  Pokemon Champions Sprite Matcher
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Template-matches a cropped in-game sprite region against all ~272
 *  Pokemon Champions reference menu sprites, returning the best-matching
 *  species slug.
 *
 *  Uses CroppedImageDictionaryMatcher (from CommonTools) which auto-crops
 *  the input by measuring the border color and trimming to the bounding
 *  box of pixels that differ from that color. This removes the pink/red
 *  pill background that surrounds opponent sprites on the Team Preview
 *  screen, so the matcher compares actual sprite content against the
 *  transparent-bg Bulbapedia reference.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_SpriteMatcher_H
#define PokemonAutomation_PokemonChampions_SpriteMatcher_H

#include <string>
#include "CommonTools/ImageMatch/CroppedImageDictionaryMatcher.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class PokemonSpriteMatcher : public ImageMatch::CroppedImageDictionaryMatcher{
public:
    //  min_euclidean_distance: pixels with Euclidean RGB distance < this
    //  from the measured border color are treated as background and
    //  trimmed during auto-crop.
    static const PokemonSpriteMatcher& instance();

    //  Strip a "-shiny" suffix if present, otherwise return the slug
    //  unchanged. Lets callers ignore the shiny tag.
    static std::string base_slug(const std::string& slug);

    //  Expose the auto-cropped candidate(s) the matcher would compare
    //  against the atlas. Used by --sprite-match-debug to show what the
    //  C++ side actually sees after pill-bg removal.
    std::vector<ImageViewRGB32> debug_crop_candidates(const ImageViewRGB32& image) const{
        return get_crop_candidates(image);
    }

private:
    PokemonSpriteMatcher(double min_euclidean_distance = 100);
    virtual std::vector<ImageViewRGB32> get_crop_candidates(
        const ImageViewRGB32& image
    ) const override;

    double m_min_euclidean_distance_squared;
};


}
}
}
#endif
