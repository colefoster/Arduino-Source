/*  Discord-driven Trade Bot (SV)
 *
 *  See PokemonSV_DiscordTradeBot.h and plans/sv-home-discord-trade-bot.md.
 *
 *  Pre-trade nav modeled on PokemonSV_TeraRoutines::join_raid().
 *  Mid-trade flow reuses PokemonSV_TradeRoutines::trade_current_pokemon().
 */

#include <string>
#include "Common/Cpp/Time.h"
#include "CommonFramework/Exceptions/OperationFailedException.h"
#include "CommonFramework/Tools/VideoStream.h"
#include "CommonTools/Async/InferenceRoutines.h"
#include "CommonTools/VisualDetectors/BlackScreenDetector.h"
#include "NintendoSwitch/Commands/NintendoSwitch_Commands_PushButtons.h"
#include "NintendoSwitch/Controllers/Procon/NintendoSwitch_ProController.h"
#include "NintendoSwitch/NintendoSwitch_ConsoleHandle.h"
#include "PokemonSV/Inference/Dialogs/PokemonSV_DialogDetector.h"
#include "PokemonSV/Inference/PokemonSV_MainMenuDetector.h"
#include "PokemonSV/Inference/PokemonSV_PokePortalDetector.h"
#include "PokemonSV/Inference/Tera/PokemonSV_TeraRaidSearchDetector.h"
#include "PokemonSV/Inference/Overworld/PokemonSV_OverworldDetector.h"
#include "PokemonSV/Programs/PokemonSV_ConnectToInternet.h"
#include "PokemonSV/Inference/Boxes/PokemonSV_BoxDetection.h"
#include "PokemonSV/Programs/Boxes/PokemonSV_BoxRoutines.h"
#include "PokemonSV/Programs/FastCodeEntry/PokemonSV_CodeEntry.h"
#include "PokemonSV_DiscordTradeBot.h"
#include "PokemonSV_DiscordTradeBridge.h"
#include "PokemonSV_TradeRoutines.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonSV{


//  Row indices inside the Poké Portal menu (verified from screenshot 2026-05-02).
//  0: Union Circle, 1: Tera Raid Battle, 2: Link Trade, 3: Surprise Trade,
//  4: Link Battle, 5: Battle Stadium, 6: Mystery Gift.
static constexpr int POKE_PORTAL_ROW_LINK_TRADE = 2;

//  Position of "Poké Portal" in the right column of the main (X) menu —
//  same as the Tera-raid path; verified by PokemonSV_TeraRoutines::enter_tera_search.
static constexpr int MAIN_MENU_RIGHT_ROW_POKE_PORTAL = 3;


[[noreturn]] static void fail(ConsoleHandle& stream, const std::string& msg){
    OperationFailedException::fire(ErrorReport::SEND_ERROR_REPORT, msg, stream);
}


//  Drive the Switch from wherever-we-are into "Searching for a trade partner..."
//  with the bot's code entered. Returns once the trade has actually started
//  (black screen detected). Throws OperationFailedException on no progress.
//
//  Mirrors join_raid()'s state-machine style so we recover from any unexpected
//  screen rather than blind-navigating with sleeps.
static void enter_link_trade_with_code(
    const ProgramInfo& info, ConsoleHandle& stream, ProControllerContext& context,
    KeyboardLayout keyboard_layout,
    const std::string& code
){
    using namespace std::chrono;
    WallClock start = current_time();
    bool connected = false;
    bool code_entered = false;
    bool searching = false;

    while (true){
        if (current_time() - start > minutes(3)){
            fail(stream, "enter_link_trade_with_code(): timed out (3 min) before reaching searching state.");
        }

        OverworldWatcher overworld(stream.logger(), COLOR_RED);
        MainMenuWatcher main_menu(COLOR_YELLOW);
        PokePortalWatcher poke_portal(COLOR_GREEN);
        CodeEntryWatcher code_entry(COLOR_PURPLE);
        AdvanceDialogWatcher dialog(COLOR_BLUE);
        BlackScreenOverWatcher black_screen(COLOR_CYAN);

        context.wait_for_all_requests();
        //  Order matters: more specific UI states first. In SV the overworld
        //  is still visible behind the main menu sidebar, so we'd loop forever
        //  if overworld were checked first.
        int ret = wait_until(
            stream, context, seconds(30),
            {code_entry, poke_portal, main_menu, dialog, black_screen, overworld}
        );
        context.wait_for(milliseconds(100));

        switch (ret){
        case 0:  //  Code entry keyboard.
            stream.log("Detected code entry. Typing code.");
            if (code_entered){
                fail(stream, "enter_link_trade_with_code(): code entry reappeared after typing.");
            }
            enter_code(
                stream, context,
                /*assume_console_type_is_ready=*/false,
                keyboard_layout,
                code,
                /*force_keyboard_mode=*/false,
                /*include_plus=*/false,
                /*connect_controller_press=*/false
            );
            code_entered = true;
            //  enter_code returns us to the "Start a Link Trade" sub-screen with
            //  cursor on Set Link Code. Up → Begin Searching. A → start search.
            pbf_press_dpad(context, DPAD_UP, 160ms, 480ms);
            pbf_press_button(context, BUTTON_A, 160ms, 1840ms);
            searching = true;
            continue;

        case 1:  //  Poké Portal → select Link Trade, then nav into code entry.
            stream.log("Detected Poké Portal.");
            if (!poke_portal.move_cursor(info, stream, context, POKE_PORTAL_ROW_LINK_TRADE)){
                continue;
            }
            //  A → "Start a Link Trade" sub-screen (cursor on Begin Searching).
            //  Down → cursor on Set Link Code. A → opens keyboard.
            pbf_press_button(context, BUTTON_A, 160ms, 1840ms);
            pbf_press_dpad(context, DPAD_DOWN, 160ms, 480ms);
            pbf_press_button(context, BUTTON_A, 160ms, 1840ms);
            continue;

        case 2:  //  Main menu → ensure online, then move to Poké Portal.
            stream.log("Detected main menu.");
            if (!connected){
                connect_to_internet_from_menu(info, stream, context);
                connected = true;
                continue;
            }
            if (main_menu.move_cursor(info, stream, context, MenuSide::RIGHT, MAIN_MENU_RIGHT_ROW_POKE_PORTAL)){
                pbf_press_button(context, BUTTON_A, 160ms, 1840ms);
            }
            continue;

        case 3:  //  Stray dialog. Mash B.
            stream.log("Detected dialog. Pressing B.");
            pbf_press_button(context, BUTTON_B, 160ms, 840ms);
            continue;

        case 4:  //  Black screen — trade is starting. Done with pre-trade nav.
            if (!searching){
                stream.log("Black screen before searching — unexpected, returning anyway.");
            }
            stream.log("Detected trade start (black screen). Handing off to trade_current_pokemon.");
            return;

        case 5:  //  Overworld → press X to open the main menu.
            stream.log("Detected overworld. Opening main menu.");
            pbf_press_button(context, BUTTON_X, 160ms, 840ms);
            continue;

        default:
            fail(stream, "enter_link_trade_with_code(): no recognized state after 30s.");
        }
    }
}


//  Best-effort recovery: hammer B until we see overworld again. Used after a
//  pre-trade failure so the next trade starts from a known state.
static void escape_to_overworld(ConsoleHandle& stream, ProControllerContext& context){
    using namespace std::chrono;
    for (int i = 0; i < 20; i++){
        OverworldWatcher overworld(stream.logger(), COLOR_RED);
        context.wait_for_all_requests();
        int ret = wait_until(
            stream, context, seconds(3),
            {overworld}
        );
        if (ret == 0){
            stream.log("escape_to_overworld(): back at overworld.");
            return;
        }
        pbf_press_button(context, BUTTON_B, 160ms, 1500ms);
    }
    stream.log("escape_to_overworld(): gave up after 20 B-presses.", COLOR_RED);
}


DiscordTradeResult run_one_discord_trade(
    const ProgramInfo& info, ConsoleHandle& stream, ProControllerContext& context,
    MultiConsoleErrorState& tracker,
    TradeStats& stats,
    const DiscordTradeRequest& request
){
    using namespace std::chrono;

    //  Validate code before doing anything on the Switch.
    if (request.code.size() != 8 ||
        request.code.find_first_not_of("0123456789") != std::string::npos)
    {
        stats.m_errors++;
        stream.log("run_one_discord_trade(): invalid code, must be 8 digits.", COLOR_RED);
        return DiscordTradeResult::UNRECOVERABLE;
    }

    try {
        //  Wherever we are (box, menu, dialog), B our way to overworld first
        //  so the state machine has a known starting point.
        stream.log("Walking to overworld before navigation.");
        escape_to_overworld(stream, context);

        enter_link_trade_with_code(
            info, stream, context,
            KeyboardLayout::QWERTY,
            request.code
        );

        //  trade_current_pokemon assumes A-mash starts the trade and waits for
        //  the trade-done detector. By the time we get here, we've already seen
        //  the black screen — trade_current_pokemon's first action is also to
        //  A-mash until a black screen appears, which is harmless: it sees the
        //  in-progress black screen and proceeds.
        trade_current_pokemon(stream, context, tracker, stats);

        return DiscordTradeResult::SUCCESS;

    } catch (OperationFailedException&){
        stats.m_errors++;
        stream.log("run_one_discord_trade(): operation failed, escaping to overworld.", COLOR_RED);
        escape_to_overworld(stream, context);
        return DiscordTradeResult::PARTNER_NO_SHOW;
    }
}


DiscordTradeResult run_one_discord_batch(
    const ProgramInfo& info, ConsoleHandle& stream, ProControllerContext& context,
    MultiConsoleErrorState& tracker,
    TradeStats& stats,
    const DiscordTradeRequest& request,
    DiscordTradeBridge& bridge
){
    using namespace std::chrono;

    if (request.code.size() != 8 ||
        request.code.find_first_not_of("0123456789") != std::string::npos)
    {
        stats.m_errors++;
        stream.log("run_one_discord_batch(): invalid code, must be 8 digits.", COLOR_RED);
        return DiscordTradeResult::UNRECOVERABLE;
    }
    const int N = request.batch_size;
    if (N < 1 || N > 6){
        stats.m_errors++;
        stream.log("run_one_discord_batch(): batch_size must be 1..6, got "
                   + std::to_string(N), COLOR_RED);
        return DiscordTradeResult::UNRECOVERABLE;
    }

    try {
        stream.log("Walking to overworld before batch navigation.");
        escape_to_overworld(stream, context);

        //  One Link Trade entry serves the entire batch — partner stays
        //  connected, we just feed it N mons in a row.
        enter_link_trade_with_code(
            info, stream, context,
            KeyboardLayout::QWERTY,
            request.code
        );

        //  Pre-stage assumption: throwaways occupy row 0, columns 0..N-1.
        //  The trade flow drops us at the box screen between trades; we move
        //  the cursor to the next slot and let trade_current_pokemon's A-mash
        //  handle the offer-confirm-trade animation cycle.
        for (int i = 0; i < N; i++){
            move_box_cursor(
                info, stream, context,
                BoxCursorLocation::SLOTS, /*row=*/0, /*col=*/(uint8_t)i
            );

            trade_current_pokemon(stream, context, tracker, stats);
            stats.m_trades++;
            stream.log("Batch trade " + std::to_string(i + 1) + "/"
                       + std::to_string(N) + " complete.");

            if (i + 1 < N){
                //  Bot says "DO NOT OFFER YET - Preparing your next Pokémon"
                //  immediately, then "Trade M/N: Ready!" once the partner
                //  side has staged the next mon. Python forwards the latter
                //  as NEXT_TRADE_READY. Wait up to 3 minutes — Klawf usually
                //  takes 10–30s but we don't want to bail early.
                stream.log("Waiting for NEXT_TRADE_READY from Python (trade "
                           + std::to_string(i + 2) + "/" + std::to_string(N) + ").");
                if (!bridge.wait_for_next_trade_ready(minutes(3))){
                    stats.m_errors++;
                    stream.log("Batch wait timed out after trade "
                               + std::to_string(i + 1) + "/" + std::to_string(N)
                               + ". Escaping.", COLOR_RED);
                    escape_to_overworld(stream, context);
                    return DiscordTradeResult::TRADE_INTERRUPTED;
                }
            }
        }

        return DiscordTradeResult::SUCCESS;

    } catch (OperationFailedException&){
        stats.m_errors++;
        stream.log("run_one_discord_batch(): operation failed mid-batch, escaping.", COLOR_RED);
        escape_to_overworld(stream, context);
        return DiscordTradeResult::PARTNER_NO_SHOW;
    }
}


}
}
}
