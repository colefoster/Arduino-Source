/*  Pokemon Champions Auto Ladder
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  State machine for grinding Pokemon Champions ranked battles. Assumes the
 *  program starts with the user parked on the Battle Mode Select screen
 *  with the cursor on "Ranked Battles".
 *
 *  Flow:
 *     Battle Mode Select  -- A -->  Team Select (bring 6, pick 3)
 *     Team Select         -- picks + Done -->  Preparing For Battle
 *     Preparing For Battle  -- (wait) -->  Action Menu (FIGHT / POKE)
 *     Action Menu  -- A on FIGHT -->  Move Select
 *     Move Select  -- slot + A -->  (animations) ->  Action Menu OR Result
 *     Result Screen  -- (wait) -->  Post-Match Screen
 *     Post-Match Screen  -- A on Continue --> back to Team Select
 *
 */

#include <algorithm>
#include <random>
#include <vector>

#include "CommonFramework/Notifications/ProgramNotifications.h"
#include "CommonFramework/ProgramStats/StatsTracking.h"
#include "CommonFramework/VideoPipeline/VideoFeed.h"
#include "CommonTools/Async/InferenceRoutines.h"
#include "NintendoSwitch/Commands/NintendoSwitch_Commands_PushButtons.h"
#include "Pokemon/Pokemon_Strings.h"

#include "PokemonChampions/PokemonChampions_Settings.h"
#include "PokemonChampions/Inference/PokemonChampions_ActionMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreparingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PostMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleModeDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions/Programs/PokemonChampions_AutoLadder.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{

using namespace Pokemon;



AutoLadder_Descriptor::AutoLadder_Descriptor()
    : SingleSwitchProgramDescriptor(
        "PokemonChampions:AutoLadder",
        STRING_POKEMON + " Champions", "Auto Ladder",
        "Programs/PokemonChampions/AutoLadder.html",
        "Queue into Ranked Battles repeatedly and play them out with a "
        "configurable move-selection strategy. Start with the cursor on "
        "'Ranked Battles' in the Battle Mode Select screen.",
        ProgramControllerClass::StandardController_NoRestrictions,
        FeedbackType::REQUIRED,
        AllowCommandsWhenRunning::DISABLE_COMMANDS
    )
{}
class AutoLadder_Descriptor::Stats : public StatsTracker{
public:
    Stats()
        : matches(m_stats["Matches"])
        , wins(m_stats["Wins"])
        , losses(m_stats["Losses"])
        , unknown_results(m_stats["Unknown Results"])
        , errors(m_stats["Errors"])
    {
        m_display_order.emplace_back("Matches");
        m_display_order.emplace_back("Wins");
        m_display_order.emplace_back("Losses");
        m_display_order.emplace_back("Unknown Results", HIDDEN_IF_ZERO);
        m_display_order.emplace_back("Errors", HIDDEN_IF_ZERO);
    }

    std::atomic<uint64_t>& matches;
    std::atomic<uint64_t>& wins;
    std::atomic<uint64_t>& losses;
    std::atomic<uint64_t>& unknown_results;
    std::atomic<uint64_t>& errors;
};
std::unique_ptr<StatsTracker> AutoLadder_Descriptor::make_stats() const{
    return std::unique_ptr<StatsTracker>(new Stats());
}


AutoLadder::AutoLadder()
    : STOP_AFTER_CURRENT("Match")
    , NUM_MATCHES(
        "<b>Number of Matches to Run:</b><br>"
        "Zero will run until 'Stop after Current Match' is pressed or the program is manually stopped.",
        LockMode::UNLOCK_WHILE_RUNNING,
        100,
        0
    )
    , TEAM_STRATEGY(
        "<b>Team Selection Strategy:</b><br>"
        "Which 3 of your 6 Pokémon to send into each match.",
        {
            {TeamStrategy::FirstThree,  "first-three",  "Always pick slots 1, 2, 3"},
            {TeamStrategy::LastThree,   "last-three",   "Always pick slots 4, 5, 6"},
            {TeamStrategy::RandomThree, "random-three", "Pick 3 random slots each match"},
        },
        LockMode::LOCK_WHILE_RUNNING,
        TeamStrategy::FirstThree
    )
    , MOVE_STRATEGY(
        "<b>Move Selection Strategy:</b><br>"
        "How to pick a move each turn.",
        {
            {MoveStrategy::AlwaysFirstMove, "first",       "Always pick the first move"},
            {MoveStrategy::RoundRobin,      "round-robin", "Cycle through moves 1-2-3-4"},
            {MoveStrategy::RandomMove,      "random",      "Pick a random move each turn"},
            {MoveStrategy::MashA,           "mash-a",      "Mash A (fastest; relies on default cursor)"},
            {MoveStrategy::AI,             "ai",          "AI (query inference server for move decisions)"},
        },
        LockMode::LOCK_WHILE_RUNNING,
        MoveStrategy::AlwaysFirstMove
    )
    , ALLOW_MEGA(
        "<b>Allow Mega Evolve:</b><br>"
        "If enabled, press R to toggle Mega Evolve before confirming the move on the first eligible turn.",
        LockMode::LOCK_WHILE_RUNNING,
        false
    )
    , AI_SERVER_URL(
        false,
        "<b>AI Inference Server URL:</b><br>"
        "URL of the Python inference server. Only used when Move Strategy is AI.",
        LockMode::LOCK_WHILE_RUNNING,
        "http://localhost:8265",
        "http://localhost:8265"
    )
    , AI_SCAN_TEAM_FROM_GAME(
        "<b>Scan Team from Game:</b><br>"
        "If enabled, read your team directly from the 'View Details -> Moves & More' "
        "screen at program start instead of requiring a Showdown paste. "
        "Before pressing Start, navigate to that screen for the team you want to use. "
        "If the screen is not detected, the Showdown paste below is used as a fallback.",
        LockMode::LOCK_WHILE_RUNNING,
        false
    )
    , AI_TEAM_PASTE(
        "<b>Team (Showdown Paste):</b><br>"
        "Paste your team in Showdown format. Used by the AI to know your own team's moves, items, and abilities. "
        "Export from the team builder or copy from Showdown. "
        "Ignored if 'Scan Team from Game' is enabled and succeeds.",
        LockMode::LOCK_WHILE_RUNNING,
        "",
        "Kingambit @ Bright Powder\nAbility: Defiant\n- Sucker Punch\n- Iron Head\n- Swords Dance\n- Protect\n\n..."
    )
    , GO_HOME_WHEN_DONE(false)
    , NOTIFICATION_STATUS_UPDATE("Status Update", true, false, std::chrono::seconds(3600))
    , NOTIFICATION_MATCH_FINISHED("Match Finished", true, false, std::chrono::seconds(0))
    , NOTIFICATIONS({
        &NOTIFICATION_STATUS_UPDATE,
        &NOTIFICATION_MATCH_FINISHED,
        &NOTIFICATION_PROGRAM_FINISH,
        &NOTIFICATION_ERROR_FATAL,
    })
{
    PA_ADD_OPTION(STOP_AFTER_CURRENT);
    PA_ADD_OPTION(NUM_MATCHES);
    PA_ADD_OPTION(TEAM_STRATEGY);
    PA_ADD_OPTION(MOVE_STRATEGY);
    PA_ADD_OPTION(ALLOW_MEGA);
    PA_ADD_OPTION(AI_SERVER_URL);
    PA_ADD_OPTION(AI_SCAN_TEAM_FROM_GAME);
    PA_ADD_OPTION(AI_TEAM_PASTE);
    PA_ADD_OPTION(GO_HOME_WHEN_DONE);
    PA_ADD_OPTION(NOTIFICATIONS);
}


void AutoLadder::compute_team_picks(uint8_t picks[3]){
    switch (TEAM_STRATEGY){
    case TeamStrategy::FirstThree:
        picks[0] = 0; picks[1] = 1; picks[2] = 2;
        return;
    case TeamStrategy::LastThree:
        picks[0] = 3; picks[1] = 4; picks[2] = 5;
        return;
    case TeamStrategy::RandomThree:{
        std::random_device rd;
        std::mt19937 rng(rd());
        std::vector<uint8_t> pool = {0, 1, 2, 3, 4, 5};
        std::shuffle(pool.begin(), pool.end(), rng);
        picks[0] = pool[0]; picks[1] = pool[1]; picks[2] = pool[2];
        //  Sort ascending so cursor navigation is top-down (always moves down).
        std::sort(picks, picks + 3);
        return;
    }
    default:
        picks[0] = 0; picks[1] = 1; picks[2] = 2;
    }
}


int AutoLadder::scan_team_from_game(SingleSwitchProgramEnvironment& env){
    VideoSnapshot snapshot = env.console.video().snapshot();
    if (!snapshot){
        env.console.log("[ScanTeam] Could not grab video frame.", COLOR_RED);
        return -1;
    }

    MovesMoreDetector detector;
    if (!detector.detect(snapshot)){
        env.console.log(
            "[ScanTeam] 'Moves & More' screen not detected. "
            "Navigate to View Details -> Moves & More for the team to scan.",
            COLOR_RED
        );
        return -1;
    }

    TeamSummaryReader reader(Language::English);
    auto team = reader.read_team(env.console, snapshot);

    std::array<ConfiguredPokemon, 6> configured;
    int loaded = 0;
    for (uint8_t i = 0; i < 6; i++){
        configured[i] = team[i].to_configured();
        if (!configured[i].species.empty()){
            loaded++;
        }
    }

    if (loaded == 0){
        env.console.log("[ScanTeam] Screen detected but no Pokemon OCR'd.", COLOR_RED);
        return 0;
    }

    m_state_tracker.set_own_team(configured);

    env.console.log(
        "[ScanTeam] Loaded " + std::to_string(loaded) + "/6 Pokemon from game.",
        COLOR_GREEN
    );
    for (uint8_t i = 0; i < 6; i++){
        const auto& c = configured[i];
        if (c.species.empty()) continue;
        std::string moves_str;
        for (const auto& m : c.moves){
            if (!m.empty()){
                if (!moves_str.empty()) moves_str += ", ";
                moves_str += m;
            }
        }
        env.console.log(
            "  " + c.species + " [" + c.ability + "] {" + moves_str + "}",
            COLOR_BLUE
        );
    }
    return loaded;
}


void AutoLadder::enter_matchmaking(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    env.console.log("Entering matchmaking (pressing A on Ranked Battles).");
    pbf_press_button(context, BUTTON_A, 80ms, 160ms);

    //  Wait for the opponent to be found. Max ~5 minutes of matchmaking;
    //  some Champions queues are slow at off-peak times.
    //  Until we have a TeamSelectScreenDetector, we rely on a timed wait +
    //  the subsequent do_team_select() cursor-driven assumptions.
    context.wait_for(std::chrono::seconds(60));
}


void AutoLadder::do_team_select(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    GameSettings& settings = GameSettings::instance();

    uint8_t picks[3];
    compute_team_picks(picks);
    env.console.log(
        "Team select: sending slots " +
        std::to_string(picks[0] + 1) + ", " +
        std::to_string(picks[1] + 1) + ", " +
        std::to_string(picks[2] + 1) + "."
    );

    //  Cursor starts on slot 1 (top). Move down then press A for each pick.
    //  Cursor position tracked manually so we move by deltas.
    uint8_t cursor = 0;
    for (int i = 0; i < 3; i++){
        while (cursor < picks[i]){
            pbf_press_dpad(context, DPAD_DOWN, 80ms, 160ms);
            cursor++;
        }
        //  Press A to mark this slot as chosen.
        pbf_press_button(context, BUTTON_A, 80ms, 320ms);
    }

    //  Navigate to the "Done" button (below slot 6). We assume it's one
    //  press down from slot 6. If the current cursor isn't on slot 6, walk
    //  down until we're at the bottom, then one more press to reach Done.
    while (cursor < 5){
        pbf_press_dpad(context, DPAD_DOWN, 80ms, 160ms);
        cursor++;
    }
    pbf_press_dpad(context, DPAD_DOWN, 80ms, 160ms);
    pbf_press_button(context, BUTTON_A, 80ms, 160ms);

    context.wait_for(settings.TEAM_SELECT_DELAY0);
}


void AutoLadder::wait_for_battle_start(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    env.console.log("Waiting for Preparing-for-Battle screen.");
    PreparingForBattleWatcher preparing_watcher;
    int ret = wait_until(
        env.console, context,
        std::chrono::seconds(90),
        {preparing_watcher}
    );
    if (ret < 0){
        env.console.log("Preparing-for-Battle screen never fired; continuing anyway.", COLOR_RED);
    }

    //  Now wait for the action menu to appear (battle begins for real).
    env.console.log("Waiting for action menu.");
    ActionMenuWatcher action_watcher;
    ret = wait_until(
        env.console, context,
        std::chrono::seconds(90),
        {action_watcher}
    );
    if (ret < 0){
        env.console.log("Action menu never appeared.", COLOR_RED);
    }
}


void AutoLadder::select_next_move(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    GameSettings& settings = GameSettings::instance();

    //  Action menu is on screen with cursor on FIGHT (default). Press A to enter Move Select.
    pbf_press_button(context, BUTTON_A, 80ms, 320ms);

    //  Wait for the Move Select menu to render.
    MoveSelectWatcher move_menu_watcher;
    int ret = wait_until(
        env.console, context,
        std::chrono::seconds(10),
        {move_menu_watcher}
    );
    if (ret < 0){
        env.console.log("Move Select menu didn't appear after FIGHT; recovering via B.", COLOR_RED);
        pbf_press_button(context, BUTTON_B, 80ms, 320ms);
        return;
    }

    //  Optional Mega toggle. In Champions the prompt is R (seen in ref_frames).
    if (ALLOW_MEGA){
        pbf_press_button(context, BUTTON_R, 80ms, 160ms);
    }

    //  AI strategy: delegate entirely to select_move_ai().
    if (MOVE_STRATEGY == MoveStrategy::AI){
        select_move_ai(env, context);
        return;
    }

    //  Decide which slot to pick.
    uint8_t slot = 0;
    switch (MOVE_STRATEGY){
    case MoveStrategy::MashA:
        //  Just press A on whatever cursor is on and let animations play out.
        pbf_mash_button(context, BUTTON_A, settings.TURN_ANIMATION_DELAY0);
        return;
    case MoveStrategy::AlwaysFirstMove:
        slot = 0;
        break;
    case MoveStrategy::RoundRobin:
        slot = m_rr_cursor;
        m_rr_cursor = (m_rr_cursor + 1) % 4;
        break;
    case MoveStrategy::RandomMove:{
        std::random_device rd;
        std::mt19937 rng(rd());
        slot = static_cast<uint8_t>(std::uniform_int_distribution<uint32_t>(0, 3)(rng));
        break;
    }
    }

    //  Move Select menu opens with cursor on slot 0. Walk down to our target.
    //  We could also read cursor_slot() off the detector for accuracy — useful
    //  once we observe the game's real cursor-reset behavior.
    for (uint8_t i = 0; i < slot; i++){
        pbf_press_dpad(context, DPAD_DOWN, 80ms, 160ms);
    }
    pbf_press_button(context, BUTTON_A, 80ms, 160ms);
    //  Confirm any target/confirmation prompt.
    pbf_press_button(context, BUTTON_A, 80ms, 160ms);
}


bool AutoLadder::run_battle_loop(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    GameSettings& settings = GameSettings::instance();

    //  Max safety cap so a hung match doesn't spin forever.
    constexpr uint32_t MAX_TURNS = 40;

    m_rr_cursor = 0;
    for (uint32_t turn = 0; turn < MAX_TURNS; turn++){
        env.console.log("Turn " + std::to_string(turn + 1));
        select_next_move(env, context);

        //  After a move, wait for one of three outcomes:
        //    - Action menu reappears  (next turn)
        //    - Result screen appears  (battle ended)
        ActionMenuWatcher action_watcher;
        ResultScreenWatcher result_watcher;

        int ret = wait_until(
            env.console, context,
            std::chrono::seconds(60),
            {action_watcher, result_watcher}
        );
        if (ret == 1){
            env.console.log("Result screen detected -> match finished.");
            return result_watcher.won();
        }
        if (ret == 0){
            //  Next turn; loop continues.
            continue;
        }

        //  Neither detector fired in 60s. Something went wrong.
        env.console.log("Neither action menu nor result screen appeared in 60s.", COLOR_RED);
        //  Mash B to try to dismiss anything interrupting and continue.
        pbf_mash_button(context, BUTTON_B, settings.TURN_ANIMATION_DELAY0);
    }

    env.console.log("Hit MAX_TURNS without seeing a result screen. Bailing.", COLOR_RED);
    return false;
}


bool AutoLadder::handle_post_match(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    GameSettings& settings = GameSettings::instance();

    //  After the result screen there's a brief animation into the post-match
    //  summary. Mash A until the post-match screen is on-screen.
    PostMatchScreenWatcher post_match_watcher;
    int ret = run_until<ProControllerContext>(
        env.console, context,
        [&](ProControllerContext& context){
            pbf_mash_button(context, BUTTON_A, std::chrono::seconds(30));
        },
        {post_match_watcher}
    );
    if (ret < 0){
        env.console.log("Post-match screen never appeared; fallback delay.", COLOR_RED);
        context.wait_for(settings.BETWEEN_MATCHES_DELAY0);
        return true;
    }

    if (STOP_AFTER_CURRENT.should_stop()){
        env.console.log("Stop-after-current requested. Navigating to 'Quit Battling'.");
        //  Cursor defaults on "Continue Battling" (right). "Quit Battling" is
        //  two slots to the left.
        pbf_press_dpad(context, DPAD_LEFT, 80ms, 160ms);
        pbf_press_dpad(context, DPAD_LEFT, 80ms, 160ms);
        pbf_press_button(context, BUTTON_A, 80ms, 160ms);
        return false;
    }

    env.console.log("Post-match screen up; pressing A on 'Continue Battling'.");
    pbf_press_button(context, BUTTON_A, 80ms, 160ms);
    return true;
}


bool AutoLadder::run_one_match(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    AutoLadder_Descriptor::Stats& stats = env.current_stats<AutoLadder_Descriptor::Stats>();

    env.console.log("--- New match ---");

    //  For the first match only: enter matchmaking from the Battle Mode
    //  Select screen. Subsequent matches start from the post-match screen
    //  having already pressed "Continue Battling", which loops back into a
    //  new team-select, so we can skip enter_matchmaking() after match 1.
    if (stats.matches == 0){
        enter_matchmaking(env, context);
    }

    do_team_select(env, context);
    wait_for_battle_start(env, context);

    bool won = run_battle_loop(env, context);
    if (won){
        stats.wins++;
    }else{
        //  Could be a loss OR an uncertain state. For now, count as loss
        //  unless the Result detector explicitly said otherwise — a more
        //  precise split is a TODO once we add a dedicated loss path.
        stats.losses++;
    }
    stats.matches++;
    env.update_stats();
    send_program_status_notification(env, NOTIFICATION_MATCH_FINISHED);

    return handle_post_match(env, context);
}


void AutoLadder::program(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    AutoLadder_Descriptor::Stats& stats = env.current_stats<AutoLadder_Descriptor::Stats>();

    DeferredStopButtonOption::ResetOnExit reset_on_exit(STOP_AFTER_CURRENT);

    //  Initialize AI components if using AI strategy.
    if (MOVE_STRATEGY == MoveStrategy::AI){
        //  Populate own team. Priority:
        //    1. In-game team scan (if enabled and Moves & More screen visible).
        //    2. Fallback to Showdown paste.
        int scanned = -1;
        if (AI_SCAN_TEAM_FROM_GAME){
            scanned = scan_team_from_game(env);
        }

        if (scanned <= 0){
            //  Fall back to Showdown paste.
            std::string paste = AI_TEAM_PASTE;
            if (!paste.empty()){
                int parsed = m_state_tracker.load_team_from_showdown_paste(paste);
                env.console.log(
                    "[AI] Loaded " + std::to_string(parsed) + " Pokemon from team paste.",
                    COLOR_GREEN
                );
                for (uint8_t i = 0; i < parsed; i++){
                    const auto& mon = m_state_tracker.own(i);
                    std::string moves_str;
                    for (const auto& m : mon.known_moves){
                        if (!moves_str.empty()) moves_str += ", ";
                        moves_str += m;
                    }
                    env.console.log(
                        "  " + mon.species + " @ " + mon.item +
                        " [" + mon.ability + "] {" + moves_str + "}",
                        COLOR_BLUE
                    );
                }
            }else if (!AI_SCAN_TEAM_FROM_GAME){
                env.console.log("[AI] No team paste provided. Own team info will be incomplete.", COLOR_RED);
            }else{
                env.console.log("[AI] In-game team scan failed and no paste provided. Own team info will be incomplete.", COLOR_RED);
            }
        }

        //  Connect to inference server.
        m_inference_client = std::make_unique<InferenceClient>(AI_SERVER_URL);
        if (!m_inference_client->health_check(env.console)){
            env.console.log("AI inference server not reachable. Falling back to AlwaysFirstMove.", COLOR_RED);
            m_inference_client.reset();
        }else{
            env.console.log("AI inference server connected.", COLOR_GREEN);
        }
    }

    while (NUM_MATCHES == 0 || stats.matches < NUM_MATCHES){
        bool should_continue = run_one_match(env, context);
        if (!should_continue){
            env.console.log("Post-match 'Quit Battling' selected. Exiting loop.");
            break;
        }
    }

    send_program_finished_notification(env, NOTIFICATION_PROGRAM_FINISH);
    GO_HOME_WHEN_DONE.run_end_of_program(context);
}


// ─── AI Move Selection ───────────────────────────────────────────

void AutoLadder::select_move_ai(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    //  If inference client isn't available, fall back to first move.
    if (!m_inference_client){
        env.console.log("[AI] No inference server. Falling back to first move.", COLOR_RED);
        //  Press A on FIGHT, then A on first move.
        pbf_press_button(context, BUTTON_A, 80ms, 320ms);
        context.wait_for(std::chrono::milliseconds(500));
        pbf_press_button(context, BUTTON_A, 80ms, 160ms);
        pbf_press_button(context, BUTTON_A, 80ms, 160ms);
        return;
    }

    //  1. Take a snapshot and run HUD OCR.
    VideoSnapshot snapshot = env.console.video().snapshot();
    if (snapshot){
        BattleHUDReader hud_reader(Language::English, m_state_tracker.mode());
        BattleHUDState hud = hud_reader.read_all(env.console, snapshot);
        m_state_tracker.update_from_hud(hud);
    }

    //  2. Query the inference server.
    JsonObject game_state = m_state_tracker.to_predict_json();
    ActionPrediction prediction = m_inference_client->predict(env.console, game_state);

    if (!prediction.success){
        env.console.log("[AI] Prediction failed. Falling back to first move.", COLOR_RED);
        pbf_press_button(context, BUTTON_A, 80ms, 320ms);
        context.wait_for(std::chrono::milliseconds(500));
        pbf_press_button(context, BUTTON_A, 80ms, 160ms);
        pbf_press_button(context, BUTTON_A, 80ms, 160ms);
        return;
    }

    //  3. Execute the predicted action.
    env.console.log(
        "[AI] Action: " + action_name(prediction.action_a) +
        " (p=" + std::to_string(static_cast<int>(prediction.probs_a[prediction.action_a] * 100)) + "%)",
        COLOR_BLUE
    );

    execute_action(env, context, prediction.action_a);
    m_state_tracker.advance_turn();
}


void AutoLadder::execute_action(
    SingleSwitchProgramEnvironment& env, ProControllerContext& context, uint8_t action_idx
){
    if (action_idx >= 12){
        //  Switch action: press down to POKEMON button, then navigate to bench slot.
        uint8_t switch_slot = action_idx - 12;  //  0 or 1

        //  Press down to move cursor from FIGHT to POKEMON.
        pbf_press_dpad(context, DPAD_DOWN, 80ms, 160ms);
        pbf_press_button(context, BUTTON_A, 80ms, 320ms);

        //  Navigate to the bench slot (slot 0 is first, slot 1 is second).
        for (uint8_t i = 0; i < switch_slot; i++){
            pbf_press_dpad(context, DPAD_DOWN, 80ms, 160ms);
        }
        pbf_press_button(context, BUTTON_A, 80ms, 160ms);
        return;
    }

    //  Move action: action_idx = move_slot * 3 + target
    uint8_t move_slot = static_cast<uint8_t>(action_idx / 3);
    //  uint8_t target = static_cast<uint8_t>(action_idx % 3);  //  TODO: handle target selection for doubles

    //  Press A on FIGHT to enter move select.
    pbf_press_button(context, BUTTON_A, 80ms, 320ms);

    //  Wait for move select menu.
    MoveSelectWatcher move_menu_watcher;
    int ret = wait_until(
        env.console, context,
        std::chrono::seconds(10),
        {move_menu_watcher}
    );
    if (ret < 0){
        env.console.log("[AI] Move select didn't appear. Recovering.", COLOR_RED);
        pbf_press_button(context, BUTTON_B, 80ms, 320ms);
        return;
    }

    //  Optional Mega toggle.
    if (ALLOW_MEGA){
        pbf_press_button(context, BUTTON_R, 80ms, 160ms);
    }

    //  Navigate to the move slot.
    for (uint8_t i = 0; i < move_slot; i++){
        pbf_press_dpad(context, DPAD_DOWN, 80ms, 160ms);
    }
    pbf_press_button(context, BUTTON_A, 80ms, 160ms);

    //  Confirm target (for doubles, just press A — default target for now).
    pbf_press_button(context, BUTTON_A, 80ms, 160ms);
}


}
}
}
