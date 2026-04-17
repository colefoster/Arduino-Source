/*  Pokemon Champions Settings
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#ifndef PokemonAutomation_PokemonChampions_Settings_H
#define PokemonAutomation_PokemonChampions_Settings_H

#include "Common/Cpp/Options/StaticTextOption.h"
#include "Common/Cpp/Options/TimeDurationOption.h"
#include "CommonFramework/Panels/SettingsPanel.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class GameSettings : public BatchOption{
    GameSettings();
public:
    static GameSettings& instance();

    SectionDividerOption m_general;

    //  Timings that will almost certainly need tuning once the game ships.
    //  Exposed here so individual programs can read them rather than hardcoding.
    MillisecondsOption TEAM_SELECT_DELAY0;
    MillisecondsOption BATTLE_START_DELAY0;
    MillisecondsOption TURN_ANIMATION_DELAY0;
    MillisecondsOption BETWEEN_MATCHES_DELAY0;

    SectionDividerOption m_advanced_options;
};


class GameSettings_Descriptor : public PanelDescriptor{
public:
    GameSettings_Descriptor();
};


class GameSettingsPanel : public SettingsPanelInstance{
public:
    GameSettingsPanel(const GameSettings_Descriptor& descriptor);
private:
    GameSettings& settings;
};


}
}
}
#endif
