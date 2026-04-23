/*  Pokemon Champions Sprite Matcher
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include "PokemonChampions/Resources/PokemonChampions_PokemonSprites.h"
#include "PokemonChampions_SpriteMatcher.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


PokemonSpriteMatcher::PokemonSpriteMatcher()
    //  Weight tuning borrowed from PokemonSwSh_PokemonSpriteReader.
    //  {min_weight, max_weight} for stddev-based weighting.
    : ExactImageDictionaryMatcher({1, 256})
{
    for (const auto& item : ALL_POKEMON_SPRITES()){
        add(item.first, item.second.sprite.copy());
    }
}


const PokemonSpriteMatcher& PokemonSpriteMatcher::instance(){
    static PokemonSpriteMatcher matcher;
    return matcher;
}


}
}
}
