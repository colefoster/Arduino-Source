/*  Discord-driven Trade Bot (SV)
 *
 *  Receives Link Codes from an external Discord watcher process and runs one
 *  full Link Trade per code, leaving the Switch back at the SV box screen.
 *
 *  See plans/sv-home-discord-trade-bot.md for the full state machine.
 */

#ifndef PokemonAutomation_PokemonSV_DiscordTradeBot_H
#define PokemonAutomation_PokemonSV_DiscordTradeBot_H

#include <string>
#include "CommonFramework/Tools/VideoStream.h"
#include "CommonTools/MultiConsoleErrors.h"
#include "NintendoSwitch/Controllers/Procon/NintendoSwitch_ProController.h"
#include "NintendoSwitch/NintendoSwitch_ConsoleHandle.h"
#include "PokemonSV/Programs/Trading/PokemonSV_TradeRoutines.h"

namespace PokemonAutomation{
    struct ProgramInfo;
namespace NintendoSwitch{
namespace PokemonSV{


enum class DiscordTradeResult{
    SUCCESS,
    PARTNER_NO_SHOW,        //  Code accepted but no partner connected within timeout.
    TRADE_INTERRUPTED,      //  Black screen reached but trade did not complete.
    NETWORK_ERROR,          //  Y-Comm / portal failed to open or report online.
    UNRECOVERABLE,          //  Anything that needs human intervention.
};

struct DiscordTradeRequest{
    std::string set_id;     //  Opaque ID echoed back in the result message.
    std::string code;       //  8-digit Link Code as displayed by the gen bot.
};


//  Run one full Discord-driven trade.
//
//  PRECONDITION:  Switch is at the SV box screen with the throwaway mon
//                 selected (cursor on the slot to be offered).
//  POSTCONDITION: Switch is back at the SV box screen, with the freshly
//                 received mon now occupying the offered slot.
DiscordTradeResult run_one_discord_trade(
    const ProgramInfo& info,
    ConsoleHandle& stream, ProControllerContext& context,
    MultiConsoleErrorState& tracker,
    TradeStats& stats,
    const DiscordTradeRequest& request
);


}
}
}
#endif
