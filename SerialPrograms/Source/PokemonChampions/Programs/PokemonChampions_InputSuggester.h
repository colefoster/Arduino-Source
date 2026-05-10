/*  Pokemon Champions Input Suggester
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Suggest-only mapping from "current screen + battle state" to "what
 *  button I would press if I were autoladdering right now". No controller
 *  writes — the suggestion is purely advisory and is rendered as:
 *    (a) a green box on the SerialPrograms video overlay, and
 *    (b) a `suggested_input` field in the LiveDetectorTrace event JSON
 *        so the dashboard can mirror it.
 *
 *  Action picks are intentionally dumb (first move, first alive bench,
 *  etc.) — the goal is to validate the screen→decision→button mapping
 *  end-to-end while Cole keeps playing the game manually. Real action
 *  selection (battle model) lands later.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_InputSuggester_H
#define PokemonAutomation_PokemonChampions_InputSuggester_H

#include <array>
#include <optional>
#include <string>
#include <vector>
#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class BattleStateTracker;
struct BattleSituation;


//  Live-pipeline state that doesn't belong in BattleStateTracker (per-poll
//  reader output, screen-local counters). Passed by value to the suggester.
struct LiveContext{
    //  Last-known cursor slot on team_preview_selecting (0..5, -1 = unread
    //  / cursor on Done area).
    int tp_cursor_slot = -1;
    //  Per-slot lead-mark digit on the team_preview_selecting screen.
    //  '1'..'4' if marked at that lead-order, 0 if unmarked / unread.
    //  Read from screen each poll — robust to mid-stream auto-press
    //  toggle, missed presses, manual interventions.
    std::array<char, 6> tp_marks_per_slot = {};
    //  selected_index() output from whichever menu detector last fired.
    //  Drives nav-then-A in the menu suggester. -1 = unread.
    int menu_selected_index = -1;

    //  Target on the ranked_format_select screen. 0=Singles, 1=Doubles.
    int format_target = 1;

    //  Target on the battle_mode_menu screen. 0=Ranked, 1=Casual.
    int battle_mode_target = 0;

    //  Target on the team_select screen. 0..17 = Team 1..18.
    int team_index_target = 0;

    //  Carousel-aware team_select state.
    //    team_select_known_n: 1..18 once we've identified the absolute
    //                         team (cursor seen at col 0 = Team 1, or
    //                         col 4 = Team 18). 0 = still homing.
    //    team_select_cursor_col: 0..4 (visible cursor column), -1 if unread.
    int team_select_known_n = 0;
    int team_select_cursor_col = -1;
    //  True when known_n has been stable long enough (~400ms) for the
    //  most recent press to have landed on the Switch. Gates the
    //  Confirm-A so we don't open a modal on the team the cursor was on
    //  *before* the in-flight Right press registered.
    bool team_select_settle_ok = true;

    //  Scan-and-pick step on team_select. -1 = inactive (skip the scan
    //  sub-flow and just confirm the team). See LiveDetectorTrace.h for
    //  the 8-step sequence.
    int team_scan_step = -1;

    //  True once the team scan has run this program session. Drives
    //  pre_match nav: target Team Select (0) until done, then Begin
    //  Matchmaking (2).
    bool team_scan_complete = false;

    //  Indices into m_own_team for the mons currently on field. Mirrors
    //  BattleStateTracker::own_active_slot_indices(). Used by the
    //  pokemon_switch suggester to exclude the on-field mon(s) from
    //  switch candidates — without this we keep trying to "switch" to
    //  the lead that's already out. -1 = unknown / not on field.
    //  Superseded by `situation->own_active_slots` when a situation
    //  pointer is set; kept for callers that construct LiveContext
    //  without a tracker on hand (tests, fallback paths).
    std::array<int, 2> own_active_slots = {-1, -1};

    //  Live tactical-state snapshot (see BattleSituation in
    //  BattleStateTracker.h). Optional — when set, suggesters and the
    //  action model read field state, alive bitmaps, and active slots
    //  through this single struct instead of poking at LiveContext
    //  fields piecemeal. Lifetime: borrowed for the duration of one
    //  suggest_for_screen call; trace owns the snapshot on its stack.
    const BattleSituation* situation = nullptr;

    //  pokemon_switch screen.
    int switch_cursor = -1;                //  -1 if unread.
    std::array<bool, 6> switch_alive = {}; //  hp_max > 0 && hp_current > 0.
    //  Random pick among alive bench slots — index INTO the alive list
    //  (modulo'd by the count in the suggester). Rolled once per
    //  pokemon_switch entry by the trace so the cursor doesn't oscillate
    //  across polls within the same switch attempt.
    int switch_target_slot = 0;
    //  How many times we've fired Down on pokemon_switch with cursor unread
    //  (no yellow highlight). Used to bound the blind-nudge retry loop
    //  when the forced-switch screen lands on a fainted slot whose
    //  highlight is suppressed. After 3 attempts we give up.
    int switch_blind_attempts = 0;
    //  Wall-clock ms of the last blind nudge, so the suggester can throttle
    //  retries to ~1s apart (give the cursor time to land + the reader to
    //  re-OCR). 0 = no nudge fired yet.
    int64_t switch_blind_last_press_ms = 0;
    //  Wall-clock now() in ms — supplied by the trace each poll so the
    //  suggester can make time-based decisions without a global clock.
    int64_t now_ms = 0;

    //  In-battle dummy strategy state. Strategy: alternate "two random
    //  moves, then a manual switch" so the auto-queuer cycles through
    //  the team instead of always firing slot-0 of the lead.
    //    battle_action_menu_visits: number of times we've entered
    //        action_menu this match (1 = first turn). Switches happen
    //        on every visit where (visits > 0 && visits % 3 == 0).
    //    action_menu_cursor: 0 = FIGHT, 1 = POKEMON, -1 = unread.
    //    move_select_cursor: 0..3 = currently-cursored slot, -1 = unread.
    //    target_move_slot: which 0..3 slot to pick this turn (random).
    int battle_action_menu_visits = 0;
    int action_menu_cursor = -1;
    int move_select_cursor = -1;
    int target_move_slot = 0;

    //  Mega Evolve toggle state on move_select.
    //    can_mega_evolve: MegaEvolveDetector said the toggle pill is up.
    //    mega_toggled_this_turn: we've already fired R for this turn's
    //        action_menu visit, so don't keep re-toggling.
    bool can_mega_evolve = false;
    bool mega_toggled_this_turn = false;
};


struct InputSuggestion{
    std::string button;     //  "A", "B", "X", "Up", "Down", "Left", "Right", "Plus", ""
    std::string label;      //  short HUD label, e.g. "A — Move 1"
    std::string reason;     //  longer note, e.g. "first move (dummy picker)"
    std::vector<ImageFloatBox> highlights;  //  overlay boxes to draw (may be empty)
    Color color = COLOR_GREEN;
};


//  Returns std::nullopt when we don't (yet) have a suggestion for this
//  screen — caller should clear the overlay and omit the field from JSON.
std::optional<InputSuggestion> suggest_for_screen(
    const std::string& screen,
    const BattleStateTracker& tracker,
    const LiveContext& ctx = {}
);


}
}
}
#endif
