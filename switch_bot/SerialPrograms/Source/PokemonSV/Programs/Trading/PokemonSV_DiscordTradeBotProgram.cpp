/*  Discord Trade Bot Program */

#include <chrono>
#include <optional>
#include "CommonFramework/Notifications/ProgramNotifications.h"
#include "CommonFramework/ProgramStats/StatsTracking.h"
#include "CommonFramework/Tools/ProgramEnvironment.h"
#include "CommonTools/MultiConsoleErrors.h"
#include "NintendoSwitch/Commands/NintendoSwitch_Commands_PushButtons.h"
#include "NintendoSwitch/NintendoSwitch_Settings.h"
#include "Pokemon/Pokemon_Strings.h"
#include "PokemonSwSh/Programs/PokemonSwSh_GameEntry.h"
#include "PokemonSV_DiscordTradeBot.h"
#include "PokemonSV_DiscordTradeBridge.h"
#include "PokemonSV_DiscordTradeBotProgram.h"
#include "PokemonSV_TradeRoutines.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonSV{
    using namespace Pokemon;


DiscordTradeBotProgram_Descriptor::DiscordTradeBotProgram_Descriptor()
    : SingleSwitchProgramDescriptor(
        "PokemonSV:DiscordTradeBot",
        STRING_POKEMON + " SV", "Discord Trade Bot",
        "",
        "Loop trades against a public Discord gen-bot. Codes are received over "
        "TCP from an external Python driver (see discord_driver/).",
        ProgramControllerClass::StandardController_NoRestrictions,
        //  NONE skips the framework's pre-flight black-border / video check —
        //  required for the grip-menu start path, which has black borders by design.
        //  We still use video detectors inside program().
        FeedbackType::NONE,
        AllowCommandsWhenRunning::DISABLE_COMMANDS
    )
{}

struct DiscordTradeBotProgram_Descriptor::Stats : public TradeStats{
    Stats() : TradeStats() {}
};
std::unique_ptr<StatsTracker> DiscordTradeBotProgram_Descriptor::make_stats() const{
    return std::unique_ptr<StatsTracker>(new Stats());
}


DiscordTradeBotProgram::DiscordTradeBotProgram()
    : START_LOCATION()
    , BRIDGE_HOST(
        false,
        "<b>Bridge Host:</b><br>Hostname or IP of the Python discord_driver TCP server.",
        LockMode::LOCK_WHILE_RUNNING,
        "127.0.0.1",
        "127.0.0.1"
    )
    , BRIDGE_PORT(
        "<b>Bridge Port:</b>",
        LockMode::LOCK_WHILE_RUNNING,
        9988, 1, 65535
    )
    , TRADE_READY_TIMEOUT_SECONDS(
        "<b>Trade-Ready Wait Timeout (seconds):</b><br>"
        "How long to block waiting for the Python side to send a TRADE_READY "
        "before re-checking for shutdown.",
        LockMode::UNLOCK_WHILE_RUNNING,
        300, 10, 3600
    )
    , NOTIFICATION_STATUS_UPDATE("Status Update", true, false, std::chrono::seconds(3600))
    , NOTIFICATIONS({
        &NOTIFICATION_STATUS_UPDATE,
        &NOTIFICATION_PROGRAM_FINISH,
        &NOTIFICATION_ERROR_RECOVERABLE,
        &NOTIFICATION_ERROR_FATAL,
    })
{
    PA_ADD_OPTION(START_LOCATION);
    PA_ADD_OPTION(BRIDGE_HOST);
    PA_ADD_OPTION(BRIDGE_PORT);
    PA_ADD_OPTION(TRADE_READY_TIMEOUT_SECONDS);
    PA_ADD_OPTION(NOTIFICATIONS);
}


void DiscordTradeBotProgram::program(
    SingleSwitchProgramEnvironment& env, ProControllerContext& context
){
    using Stats = DiscordTradeBotProgram_Descriptor::Stats;
    Stats& stats = env.current_stats<Stats>();
    env.update_stats();

    if (START_LOCATION.start_in_grip_menu()){
        grip_menu_connect_go_home(context);
        PokemonSwSh::resume_game_back_out(
            env.console,
            context,
            ConsoleSettings::instance().TOLERATE_SYSTEM_UPDATE_MENU_FAST,
            std::chrono::milliseconds(1600)
        );
    }

    DiscordTradeBridge bridge(BRIDGE_HOST, BRIDGE_PORT);
    if (!bridge.wait_until_connected(std::chrono::seconds(10))){
        env.log("Failed to connect to Discord bridge.", COLOR_RED);
        return;
    }
    env.log("Connected to Discord bridge.");

    auto deadline = std::chrono::steady_clock::now()
                  + std::chrono::seconds(TRADE_READY_TIMEOUT_SECONDS);

    while (std::chrono::steady_clock::now() < deadline){
        env.update_stats();
        //  Notification suppressed: the framework rate-limits to once per hour,
        //  so calling it every loop iteration just spams "dropped due to rate
        //  limit" lines. Stats are visible in the GUI stats display anyway.

        //  Short-poll the bridge so Stop is responsive — without this the
        //  program loop blocks here and beachballs the GUI on cancel.
        std::optional<DiscordTradeRequest> req;
        for (int i = 0; i < 5 && !req; i++){
            context.wait_for(std::chrono::seconds(1));  //  honors cancellation
            req = bridge.wait_for_trade_ready(std::chrono::milliseconds(100));
        }
        if (!req){
            continue;
        }
        deadline = std::chrono::steady_clock::now()
                 + std::chrono::seconds(TRADE_READY_TIMEOUT_SECONDS);

        env.log("Got TRADE_READY for set " + req->set_id + " code " + req->code
                + (req->batch_size > 1
                   ? " (batch of " + std::to_string(req->batch_size) + ")"
                   : std::string()));
        MultiConsoleErrorState tracker;

        DiscordTradeResult result = (req->batch_size > 1)
            ? run_one_discord_batch(
                env.program_info(),
                env.console, context,
                tracker, stats,
                *req,
                bridge
            )
            : run_one_discord_trade(
                env.program_info(),
                env.console, context,
                tracker, stats,
                *req
            );

        switch (result){
        case DiscordTradeResult::SUCCESS:
            stats.m_trades++;
            bridge.send_trade_complete(req->set_id);
            break;
        case DiscordTradeResult::PARTNER_NO_SHOW:
            bridge.send_trade_failed(req->set_id, "partner_no_show");
            break;
        case DiscordTradeResult::TRADE_INTERRUPTED:
            bridge.send_trade_failed(req->set_id, "trade_interrupted");
            break;
        case DiscordTradeResult::NETWORK_ERROR:
            bridge.send_trade_failed(req->set_id, "network_error");
            break;
        case DiscordTradeResult::UNRECOVERABLE:
            bridge.send_trade_failed(req->set_id, "unrecoverable");
            return;
        }
    }
}


}
}
}
