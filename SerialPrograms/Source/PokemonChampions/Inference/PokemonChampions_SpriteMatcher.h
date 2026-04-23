/*  Pokemon Champions Sprite Matcher
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Template-matches a cropped in-game sprite region against all ~272
 *  Pokemon Champions reference menu sprites, returning the best-matching
 *  species slug.
 *
 *  Uses the existing ExactImageDictionaryMatcher (RMSD with brightness
 *  compensation). Templates are 128x128 at load time; input is resized to
 *  match before comparison, so the matcher handles differing screen sizes
 *  (Moves & More thumbnail, Team Preview sprite column, etc.).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_SpriteMatcher_H
#define PokemonAutomation_PokemonChampions_SpriteMatcher_H

#include "CommonTools/ImageMatch/ExactImageDictionaryMatcher.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class PokemonSpriteMatcher : public ImageMatch::ExactImageDictionaryMatcher{
public:
    static const PokemonSpriteMatcher& instance();

private:
    PokemonSpriteMatcher();
};


}
}
}
#endif
