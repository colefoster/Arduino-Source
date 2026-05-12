/*  Discord Trade Bot Program (UI panel)
 *
 *  SingleSwitchProgram that connects to the Python discord_driver over TCP,
 *  consumes TRADE_READY events, and runs one Link Trade per code via
 *  run_one_discord_trade().
 */

#ifndef PokemonAutomation_PokemonSV_DiscordTradeBotProgram_H
#define PokemonAutomation_PokemonSV_DiscordTradeBotProgram_H

#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/StringOption.h"
#include "CommonFramework/Notifications/EventNotificationsTable.h"
#include "NintendoSwitch/Options/NintendoSwitch_StartInGripMenuOption.h"
#include "NintendoSwitch/NintendoSwitch_SingleSwitchProgram.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonSV{


class DiscordTradeBotProgram_Descriptor : public SingleSwitchProgramDescriptor{
public:
    DiscordTradeBotProgram_Descriptor();
    struct Stats;
    virtual std::unique_ptr<StatsTracker> make_stats() const override;
};


class DiscordTradeBotProgram : public SingleSwitchProgramInstance{
public:
    DiscordTradeBotProgram();

    virtual void program(SingleSwitchProgramEnvironment& env, ProControllerContext& context) override;

private:
    StartInGripOrGameOption START_LOCATION;
    StringOption BRIDGE_HOST;
    SimpleIntegerOption<uint16_t> BRIDGE_PORT;
    SimpleIntegerOption<uint16_t> TRADE_READY_TIMEOUT_SECONDS;
    EventNotificationOption NOTIFICATION_STATUS_UPDATE;
    EventNotificationsOption NOTIFICATIONS;
};


}
}
}
#endif
