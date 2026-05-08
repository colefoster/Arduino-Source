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

    //  Target on the team_select screen. 0..4 = Team 1..5.
    int team_index_target = 0;

    //  Scan-and-pick step on team_select. -1 = inactive (skip the scan
    //  sub-flow and just confirm the team). See LiveDetectorTrace.h for
    //  the 8-step sequence.
    int team_scan_step = -1;

    //  True once the team scan has run this program session. Drives
    //  pre_match nav: target Team Select (0) until done, then Begin
    //  Matchmaking (2).
    bool team_scan_complete = false;

    //  pokemon_switch screen.
    int switch_cursor = -1;                //  -1 if unread.
    std::array<bool, 6> switch_alive = {}; //  hp_max > 0 && hp_current > 0.
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
