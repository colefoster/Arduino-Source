/*  Pokemon Champions Settings
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include "Pokemon/Pokemon_Strings.h"
#include "PokemonChampions_Settings.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{

using namespace Pokemon;



GameSettings& GameSettings::instance(){
    static GameSettings settings;
    return settings;
}
GameSettings::GameSettings()
    : BatchOption(LockMode::LOCK_WHILE_RUNNING)
    , m_general("<font size=4><b>General Timings:</b></font>")
    , TEAM_SELECT_DELAY0(
        "<b>Team Select Delay:</b><br>"
        "Time to wait after confirming team selection before the match begins.",
        LockMode::LOCK_WHILE_RUNNING,
        "5000 ms"
    )
    , BATTLE_START_DELAY0(
        "<b>Battle Start Delay:</b><br>"
        "Time to wait from match begin to when input is accepted on the move menu.",
        LockMode::LOCK_WHILE_RUNNING,
        "8000 ms"
    )
    , TURN_ANIMATION_DELAY0(
        "<b>Turn Animation Delay:</b><br>"
        "Estimated wait for move + switch animations to resolve before the next decision.",
        LockMode::LOCK_WHILE_RUNNING,
        "12000 ms"
    )
    , BETWEEN_MATCHES_DELAY0(
        "<b>Between Matches Delay:</b><br>"
        "Delay between match end and starting another queue attempt.",
        LockMode::LOCK_WHILE_RUNNING,
        "6000 ms"
    )
    , m_advanced_options(
        "<font size=4><b>Advanced Options:</b> You should not need to touch anything below here.</font>"
    )
{
    PA_ADD_STATIC(m_general);
    PA_ADD_OPTION(TEAM_SELECT_DELAY0);
    PA_ADD_OPTION(BATTLE_START_DELAY0);
    PA_ADD_OPTION(TURN_ANIMATION_DELAY0);
    PA_ADD_OPTION(BETWEEN_MATCHES_DELAY0);
    PA_ADD_STATIC(m_advanced_options);
}




GameSettings_Descriptor::GameSettings_Descriptor()
    : PanelDescriptor(
        Color(),
        "PokemonChampions:GlobalSettings",
        STRING_POKEMON + " Champions", "Game Settings",
        "Programs/PokemonChampions/PokemonSettings.html",
        "Global " + STRING_POKEMON + " Champions Settings"
    )
{}



GameSettingsPanel::GameSettingsPanel(const GameSettings_Descriptor& descriptor)
    : SettingsPanelInstance(descriptor)
    , settings(GameSettings::instance())
{
    PA_ADD_OPTION(settings);
}



}
}
}
