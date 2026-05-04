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
    int batch_size = 1;     //  >1 means run_one_discord_batch with N throwaways
                            //  pre-staged at row 0, columns 0..N-1.
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


//  Forward declaration — keeps the cyclic include between bot and bridge headers
//  out of the public surface. Defined in PokemonSV_DiscordTradeBridge.h.
class DiscordTradeBridge;


//  Run an N-trade batch against a single partner. The bot sends one Link Code,
//  partner connects once, and we trade N throwaways back-to-back without leaving
//  Link Trade.
//
//  PRECONDITION:  Switch is at the SV box screen with N throwaways pre-staged
//                 at row 0, columns 0..N-1. Cursor anywhere is fine — we move
//                 to (0, 0) before trade 1.
//  POSTCONDITION: Switch is back at the SV box screen after trade N.
//
//  Between trades the bot DMs "Trade N completed! Preparing M/N..." then
//  "Trade M/N: Ready!" — we MUST wait for the latter (delivered as a
//  NEXT_TRADE_READY event over the bridge) before offering the next mon.
//  Offering early triggers a partner-side error.
DiscordTradeResult run_one_discord_batch(
    const ProgramInfo& info,
    ConsoleHandle& stream, ProControllerContext& context,
    MultiConsoleErrorState& tracker,
    TradeStats& stats,
    const DiscordTradeRequest& request,
    DiscordTradeBridge& bridge
);


}
}
}
#endif
