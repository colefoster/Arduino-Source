/*  Pokemon Champions Pokemon Sprites
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Loads the shared sprite atlas (Resources/PokemonChampions/PokemonSprites.png
 *  + PokemonSprites.json) containing ~272 Pokemon Champions menu sprites at
 *  128x128 each. Sourced from Bulbapedia's Category:Champions_menu_sprites;
 *  see tools/download_bulbapedia_sprites.py.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_PokemonSprites_H
#define PokemonAutomation_PokemonChampions_PokemonSprites_H

#include "CommonTools/Resources/SpriteDatabase.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


const SpriteDatabase& ALL_POKEMON_SPRITES();
//  Shiny variants of the same atlas. Loaded lazily; if the resource files
//  are missing, returns an empty database so the matcher can fall back to
//  normal-only matching without crashing.
const SpriteDatabase& ALL_POKEMON_SPRITES_SHINY();


}
}
}
#endif
