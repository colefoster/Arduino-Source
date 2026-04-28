/*  Pokemon Champions Detector Test
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Runs all PokemonChampions detectors in a loop, drawing overlay boxes and
 *  logging which detectors fire on each frame. Infers a "current screen"
 *  label from the combination of detectors that fire.
 *
 *  When the MOVE_SELECT screen is detected, also runs OCR on:
 *    - Move names (4 slots)
 *    - Opponent species name + HP%
 *    - Own HP (current/max)
 *    - PP counts (4 slots)
 *
 *  When no specific screen is detected, checks for the battle log text bar
 *  and runs OCR + parse on it.
 *
 *  Does NOT send any controller input.
 *
 */

#include "Common/Cpp/PrettyPrint.h"
#include "CommonFramework/Globals.h"
#include "CommonFramework/VideoPipeline/VideoFeed.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "Pokemon/Pokemon_Strings.h"

#include "PokemonChampions/Inference/PokemonChampions_ActionMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreparingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PostMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleModeDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_CommunicatingDetector.h"
#include "PokemonChampions_DetectorTest.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{

using namespace Pokemon;


DetectorTest_Descriptor::DetectorTest_Descriptor()
    : SingleSwitchProgramDescriptor(
        "PokemonChampions:DetectorTest",
        STRING_POKEMON + " Champions", "Detector Test",
        "Programs/PokemonChampions/DetectorTest.html",
        "Dev tool: visualise all detector overlays and log which ones fire. "
        "Also runs OCR on move names, species, HP, PP, and battle log text. "
        "Does NOT press any buttons.",
        ProgramControllerClass::StandardController_NoRestrictions,
        FeedbackType::REQUIRED,
        AllowCommandsWhenRunning::DISABLE_COMMANDS
    )
{}


DetectorTest::DetectorTest()
    : AUTO_SCREENSHOT(
        "<b>Auto-Screenshot:</b><br>"
        "Automatically save a screenshot every N milliseconds, classified by screen type. "
        "Saves to the Screenshots folder, organized by type (move_select/, battle_log/, etc.).",
        LockMode::UNLOCK_WHILE_RUNNING,
        false
    )
    , SCREENSHOT_INTERVAL_MS(
        "<b>Screenshot Interval (ms):</b><br>"
        "Milliseconds between auto-screenshots. Only saves on screen transitions or "
        "at this interval within the same screen type.",
        LockMode::UNLOCK_WHILE_RUNNING,
        500,
        100
    )
    , SAVE_LABELED_TESTS(
        "<b>Save Labeled Test Images:</b><br>"
        "On screen transitions, save screenshots with OCR results encoded in the "
        "filename (e.g. MoveNameReader/power-whip_sucker-punch_...). These drop "
        "directly into CommandLineTests for regression testing.",
        LockMode::UNLOCK_WHILE_RUNNING,
        false
    )
{
    PA_ADD_OPTION(AUTO_SCREENSHOT);
    PA_ADD_OPTION(SCREENSHOT_INTERVAL_MS);
    PA_ADD_OPTION(SAVE_LABELED_TESTS);
}


//  Helper: format a move slug for display, replacing hyphens with spaces.
static std::string slug_display(const std::string& slug){
    if (slug.empty()) return "(unreadable)";
    std::string out = slug;
    for (char& c : out){
        if (c == '-') c = ' ';
    }
    return out;
}


void DetectorTest::program(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    //  Create all detectors.
    ActionMenuDetector       action_menu;
    MoveSelectDetector       move_select;
    PreparingForBattleDetector preparing;
    ResultScreenDetector     result_screen;
    PostMatchScreenDetector  post_match;
    BattleModeDetector       battle_mode_detector;
    CommunicatingDetector    communicating;

    //  Create OCR readers.
    MoveNameReader   move_reader(Language::English);
    BattleHUDReader  hud_reader(Language::English);
    BattleLogReader  log_reader;

    //  Register overlays so boxes appear on the video feed.
    VideoOverlaySet overlay_set(env.console.overlay());
    action_menu.make_overlays(overlay_set);
    move_select.make_overlays(overlay_set);
    preparing.make_overlays(overlay_set);
    result_screen.make_overlays(overlay_set);
    post_match.make_overlays(overlay_set);
    battle_mode_detector.make_overlays(overlay_set);
    communicating.make_overlays(overlay_set);
    move_reader.make_overlays(overlay_set);
    hud_reader.make_overlays(overlay_set);
    log_reader.make_overlays(overlay_set);

    env.console.log("Detector Test running. Navigate the game - watch overlays + log.");
    env.console.log("Press Stop to end.");
    env.console.log("");
    env.console.log("Screen labels:");
    env.console.log("  ACTION_MENU  = FIGHT/POKEMON buttons visible (start of turn)");
    env.console.log("  MOVE_SELECT  = 4-move panel visible (+ OCR runs on moves/HUD)");
    env.console.log("  PREPARING    = Both teams shown, Standing By pills visible");
    env.console.log("  RESULT       = WON!/LOST! split screen");
    env.console.log("  POST_MATCH   = Quit/Edit/Continue buttons");
    env.console.log("  BATTLE_LOG   = Text bar detected during animations (OCR runs)");
    env.console.log("  UNKNOWN      = No detector matched this frame");
    env.console.log("");

    if (AUTO_SCREENSHOT){
        env.console.log(
            "[Auto-Screenshot] ON — saving every " +
            std::to_string((uint32_t)SCREENSHOT_INTERVAL_MS) + "ms to " +
            SCREENSHOTS_PATH() + "detector_test/",
            COLOR_PURPLE
        );
    }

    std::string last_screen;
    std::string last_log_text;   //  Deduplicate repeated battle log messages.
    BattleMode current_mode = BattleMode::UNKNOWN;
    bool screen_changed_last_frame = true;  //  Start true so first frame checks mode.

    //  Auto-screenshot state.
    uint32_t screenshot_count = 0;
    auto last_screenshot_time = std::chrono::steady_clock::now();

    //  Poll loop.
    while (true){
        context.wait_for(std::chrono::milliseconds(250));

        VideoSnapshot snapshot = env.console.video().snapshot();
        if (!snapshot){
            continue;
        }
        const ImageViewRGB32& frame = snapshot;

        //  Check for battle mode (Singles vs Doubles).
        //  Only run OCR if we haven't detected a mode yet, or on screen
        //  transitions (to catch mode changes between matches).
        if (current_mode == BattleMode::UNKNOWN || screen_changed_last_frame){
            BattleMode detected_mode = battle_mode_detector.read_mode(env.console, frame);
            if (detected_mode != BattleMode::UNKNOWN && detected_mode != current_mode){
                current_mode = detected_mode;
                hud_reader.set_mode(current_mode);
                env.console.log(
                    "[Mode] Detected: " + std::string(battle_mode_str(current_mode)),
                    COLOR_BLUE
                );
            }
        }

        //  Run all detectors.
        bool d_action     = action_menu.detect(frame);
        bool d_move       = move_select.detect(frame);
        bool d_preparing  = preparing.detect(frame);
        bool d_result     = result_screen.detect(frame);
        bool d_post       = post_match.detect(frame);

        //  Determine screen label from priority order.
        std::string screen;
        std::string detail;

        if (d_post){
            screen = "POST_MATCH";
            switch (post_match.cursored()){
            case PostMatchButton::QUIT_BATTLING:     detail = "cursor=Quit"; break;
            case PostMatchButton::EDIT_TEAM:         detail = "cursor=Edit"; break;
            case PostMatchButton::CONTINUE_BATTLING: detail = "cursor=Continue"; break;
            }
        }else if (d_result){
            screen = "RESULT";
            detail = result_screen.won() ? "WON" : "LOST";
        }else if (d_preparing){
            screen = "PREPARING";
            detail = "both Standing By pills detected";
        }else if (d_move){
            screen = "MOVE_SELECT";
            detail = "cursor=slot" + std::to_string(move_select.cursor_slot());
        }else if (d_action){
            screen = "ACTION_MENU";
            detail = (action_menu.cursored() == ActionMenuButton::FIGHT)
                ? "cursor=FIGHT" : "cursor=POKEMON";
        }else{
            screen = "UNKNOWN";
            detail = "no detector matched";
        }

        //  Log screen transitions.
        std::string full_label = screen + " (" + detail + ")";
        bool screen_changed = (full_label != last_screen);
        if (screen_changed){
            Color color = (screen == "UNKNOWN") ? COLOR_RED : COLOR_GREEN;
            env.console.log("[Screen] " + full_label, color);
            last_screen = full_label;
        }
        screen_changed_last_frame = screen_changed;

        //  ── Auto-Screenshot ─────────────────────────────────────
        //
        //  Save on screen transitions (always) or at the configured
        //  interval within the same screen type.
        if (AUTO_SCREENSHOT){
            auto now = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                now - last_screenshot_time
            ).count();

            bool should_save = screen_changed
                || elapsed >= (int64_t)(uint32_t)SCREENSHOT_INTERVAL_MS;

            if (should_save){
                //  Build path:  Screenshots/detector_test/<screen_type>/NNNN_<detail>.png
                std::string type_dir = SCREENSHOTS_PATH() + "detector_test/" + screen + "/";
                std::string filename = type_dir +
                    std::to_string(screenshot_count) + "_" +
                    now_to_filestring() + ".png";

                if (frame.save(filename)){
                    screenshot_count++;
                    last_screenshot_time = now;
                    env.console.log(
                        "[Screenshot] " + screen + " -> " + filename,
                        COLOR_PURPLE
                    );
                }
            }
        }

        //  ── Save Labeled Test Images ──────────────────────────────
        //
        //  On screen transitions, save screenshots with OCR ground truth
        //  encoded in the filename for the regression test suite.
        if (SAVE_LABELED_TESTS && screen_changed && screen != "UNKNOWN"){
            std::string test_base = SCREENSHOTS_PATH() + "labeled_tests/PokemonChampions/";
            std::string ts = now_to_filestring();

            //  Bool detectors — save with True label.
            auto save_bool = [&](const std::string& reader_name){
                std::string path = test_base + reader_name + "/" +
                    ts + "_True.png";
                if (frame.save(path)){
                    env.console.log("[LabeledTest] " + path, COLOR_PURPLE);
                }
            };

            if (d_action)    save_bool("ActionMenuDetector");
            if (d_move)      save_bool("MoveSelectDetector");
            if (d_preparing) save_bool("PreparingForBattleDetector");
            if (d_result)    save_bool("ResultScreenDetector");
            if (d_post)      save_bool("PostMatchScreenDetector");

            //  MoveSelectCursorSlot — save with cursor index.
            if (d_move && move_select.cursor_slot() >= 0){
                std::string path = test_base + "MoveSelectCursorSlot/" +
                    ts + "_" + std::to_string(move_select.cursor_slot()) + ".png";
                if (frame.save(path)){
                    env.console.log("[LabeledTest] " + path, COLOR_PURPLE);
                }
            }

            //  MoveNameReader — save with 4 move slugs.
            if (d_move && current_mode != BattleMode::DOUBLES){
                auto moves = move_reader.read_all_moves(env.console, frame);
                bool any_read = false;
                for (size_t i = 0; i < 4; i++){
                    if (!moves[i].empty()) any_read = true;
                }
                if (any_read){
                    std::string slugs;
                    for (size_t i = 0; i < 4; i++){
                        if (i > 0) slugs += "_";
                        slugs += moves[i].empty() ? "NONE" : moves[i];
                    }
                    std::string path = test_base + "MoveNameReader/" +
                        ts + "_" + slugs + ".png";
                    if (frame.save(path)){
                        env.console.log("[LabeledTest] " + path, COLOR_PURPLE);
                    }
                }
            }

            //  SpeciesReader — save with opponent species slug.
            //  Mode-aware: saves to _doubles/ subdir when in doubles.
            if ((d_move || d_action) && current_mode != BattleMode::UNKNOWN){
                std::string mode_suffix = (current_mode == BattleMode::DOUBLES) ? "/_doubles/" : "/";
                std::string species = hud_reader.read_opponent_species(env.console, frame, 0);
                if (!species.empty()){
                    std::string path = test_base + "SpeciesReader" + mode_suffix +
                        ts + "_" + species + ".png";
                    if (frame.save(path)){
                        env.console.log("[LabeledTest] " + path, COLOR_PURPLE);
                    }
                }
            }

            //  OpponentHPReader — save with HP percentage.
            //  Mode-aware: saves to _doubles/ subdir when in doubles.
            if ((d_move || d_action) && current_mode != BattleMode::UNKNOWN){
                std::string mode_suffix = (current_mode == BattleMode::DOUBLES) ? "/_doubles/" : "/";
                int hp = hud_reader.read_opponent_hp_pct(env.console, frame, 0);
                if (hp >= 0){
                    std::string path = test_base + "OpponentHPReader" + mode_suffix +
                        ts + "_" + std::to_string(hp) + ".png";
                    if (frame.save(path)){
                        env.console.log("[LabeledTest] " + path, COLOR_PURPLE);
                    }
                }
            }
        }

        //  ── OCR: Move Select Screen ──────────────────────────────
        //
        //  When the move select panel is visible, run OCR on everything:
        //  move names, opponent species/HP, own HP, PP counts.
        //  We re-run OCR every time the screen is MOVE_SELECT so you can
        //  see if results are stable across frames.
        if (d_move){
            uint8_t slots = (current_mode == BattleMode::DOUBLES) ? 2 : 1;

            //  Move names (singles only — doubles shows them after FIGHT press).
            if (current_mode != BattleMode::DOUBLES){
                auto moves = move_reader.read_all_moves(env.console, frame);
                env.console.log(
                    "[OCR Moves] " +
                    slug_display(moves[0]) + " | " +
                    slug_display(moves[1]) + " | " +
                    slug_display(moves[2]) + " | " +
                    slug_display(moves[3]),
                    COLOR_BLUE
                );
            }

            //  Opponent species + HP.
            for (uint8_t i = 0; i < slots; i++){
                std::string opp = hud_reader.read_opponent_species(env.console, frame, i);
                int opp_hp = hud_reader.read_opponent_hp_pct(env.console, frame, i);
                std::string slot_label = (slots > 1) ? "[OCR Opp " + std::to_string(i) + "] " : "[OCR Opponent] ";
                env.console.log(
                    slot_label + slug_display(opp) +
                    "  HP=" + (opp_hp >= 0 ? std::to_string(opp_hp) + "%" : "??"),
                    COLOR_BLUE
                );
            }

            //  Own HP.
            for (uint8_t i = 0; i < slots; i++){
                auto own_hp = hud_reader.read_own_hp(env.console, frame, i);
                std::string slot_label = (slots > 1) ? "[OCR Own " + std::to_string(i) + " HP] " : "[OCR Own HP] ";
                env.console.log(
                    slot_label +
                    (own_hp.first >= 0
                        ? std::to_string(own_hp.first) + "/" + std::to_string(own_hp.second)
                        : "??"),
                    COLOR_BLUE
                );
            }

            //  PP (singles only).
            if (current_mode != BattleMode::DOUBLES){
                std::string pp_str = "[OCR PP]";
                for (uint8_t i = 0; i < 4; i++){
                    auto pp = hud_reader.read_move_pp(env.console, frame, i);
                    pp_str += " " + (pp.first >= 0
                        ? std::to_string(pp.first) + "/" + std::to_string(pp.second)
                        : "??");
                }
                env.console.log(pp_str, COLOR_BLUE);
            }
        }

        //  ── Communicating... Detection ──────────────────────────────
        //
        //  When no UI menu is detected, check for "Communicating..." text
        //  (appears center-screen while waiting for opponent).
        if (!d_move && !d_action && !d_post && !d_result && !d_preparing){
            if (communicating.detect(frame)){
                if (screen == "UNKNOWN"){
                    screen = "COMMUNICATING";
                    detail = "waiting for opponent";
                    Color color = COLOR_YELLOW;
                    if (screen != last_screen){
                        env.console.log("[Screen] COMMUNICATING (waiting for opponent)", color);
                    }
                }
            }
        }

        //  ── OCR: Battle Log Text Bar ─────────────────────────────
        //
        //  When no UI menu is detected, check for the battle log text
        //  bar (bottom of screen during animations). Deduplicate since
        //  the same message stays on screen for ~2 seconds.
        if (!d_move && !d_action && !d_post && !d_result && !d_preparing){
            if (log_reader.detect_text_bar(frame)){
                std::string raw = log_reader.read_raw(env.console, frame);
                if (!raw.empty() && raw != last_log_text){
                    last_log_text = raw;

                    BattleLogEvent event = BattleLogReader::parse(raw);
                    std::string event_str;
                    switch (event.type){
                    case BattleLogEventType::MOVE_USED:
                        event_str = (event.is_opponent ? "OPP " : "OWN ") +
                            event.pokemon + " used " + event.move;
                        break;
                    case BattleLogEventType::STAT_CHANGE:
                        event_str = (event.is_opponent ? "OPP " : "OWN ") +
                            event.pokemon + " " + event.stat + " " +
                            (event.boost_stages > 0 ? "+" : "") +
                            std::to_string(event.boost_stages);
                        break;
                    case BattleLogEventType::STATUS_INFLICTED:
                        event_str = (event.is_opponent ? "OPP " : "OWN ") +
                            event.pokemon + " " + event.stat;
                        break;
                    case BattleLogEventType::SWITCH_IN:
                        event_str = "SWITCH_IN " + event.pokemon;
                        break;
                    case BattleLogEventType::FAINTED:
                        event_str = (event.is_opponent ? "OPP " : "OWN ") +
                            event.pokemon + " FAINTED";
                        break;
                    case BattleLogEventType::WEATHER:
                        event_str = "WEATHER";
                        break;
                    case BattleLogEventType::TERRAIN:
                        event_str = "TERRAIN";
                        break;
                    case BattleLogEventType::TRICK_ROOM:
                        event_str = "TRICK_ROOM";
                        break;
                    case BattleLogEventType::SUPER_EFFECTIVE:
                        event_str = "SUPER EFFECTIVE";
                        break;
                    case BattleLogEventType::NOT_EFFECTIVE:
                        event_str = "NOT VERY EFFECTIVE";
                        break;
                    case BattleLogEventType::OTHER:
                        event_str = "OTHER: " + raw;
                        break;
                    default:
                        event_str = "UNKNOWN: " + raw;
                        break;
                    }

                    env.console.log("[Battle Log] " + event_str, COLOR_MAGENTA);
                }
            }else{
                //  Text bar gone — reset dedup so we catch the next message.
                last_log_text.clear();
            }
        }
    }
}


}
}
}
