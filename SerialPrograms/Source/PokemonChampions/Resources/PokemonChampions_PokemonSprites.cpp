/*  Pokemon Champions Pokemon Sprites
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include <QImageReader>
#include "CommonFramework/Globals.h"
#include "PokemonChampions_PokemonSprites.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


const SpriteDatabase& ALL_POKEMON_SPRITES(){
#if QT_VERSION_MAJOR == 6
    QImageReader::setAllocationLimit(0);
#endif
    static const SpriteDatabase database(
        "PokemonChampions/PokemonSprites.png",
        "PokemonChampions/PokemonSprites.json"
    );
    return database;
}


}
}
}
