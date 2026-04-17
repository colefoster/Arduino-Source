/*  Pokemon Champions Panels
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include "CommonFramework/GlobalSettingsPanel.h"
#include "Pokemon/Pokemon_Strings.h"
#include "PokemonChampions_Panels.h"

#include "PokemonChampions_Settings.h"

//  Ladder / Battle
#include "Programs/PokemonChampions_AutoLadder.h"

//  Dev Tools
#include "Programs/PokemonChampions_DetectorTest.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{



PanelListFactory::PanelListFactory()
    : PanelListDescriptor(Pokemon::STRING_POKEMON + " Champions")
{}

std::vector<PanelEntry> PanelListFactory::make_panels() const{
    std::vector<PanelEntry> ret;

    ret.emplace_back("---- Settings ----");
    ret.emplace_back(make_settings<GameSettings_Descriptor, GameSettingsPanel>());

    ret.emplace_back("---- Ladder ----");
    ret.emplace_back(make_single_switch_program<AutoLadder_Descriptor, AutoLadder>());

    ret.emplace_back("---- Dev Tools ----");
    ret.emplace_back(make_single_switch_program<DetectorTest_Descriptor, DetectorTest>());

    return ret;
}



}
}
}
