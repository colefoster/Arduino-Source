/*  Pokemon Champions Input Suggester
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include "PokemonChampions_InputSuggester.h"
#include "PokemonChampions_BattleStateTracker.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Slot 0 move-name box. Mirrors MoveNameReader (X=0.776, WIDTH=0.120,
//  HEIGHT=0.031, slot-0 Y=0.536). Slightly inflated so the highlight box
//  visually wraps the move pill, not just the text.
static ImageFloatBox move_slot_overlay_box(int slot){
    const double X      = 0.770;
    const double WIDTH  = 0.140;
    const double HEIGHT = 0.080;
    const double Y_SLOTS[4] = { 0.515, 0.634, 0.754, 0.873 };
    if (slot < 0 || slot > 3) slot = 0;
    return ImageFloatBox(X, Y_SLOTS[slot], WIDTH, HEIGHT);
}


static std::optional<InputSuggestion> suggest_move_select(
    const BattleStateTracker& tracker
){
    //  Dummy picker: always suggest move slot 0. If we know its name from
    //  the tracker (active mon's first known move), include it in the
    //  label; otherwise fall back to "Move 1".
    (void)tracker;
    InputSuggestion s;
    s.button = "A";
    s.label = "A — Move 1";
    s.reason = "dummy picker: always slot 0";
    s.highlights.push_back(move_slot_overlay_box(0));
    return s;
}


//  Trivial "press A" suggestion. Used for menu screens where the dummy
//  flow is "advance to the next screen". No highlight box — the user can
//  just see the green pill on the dashboard.
static InputSuggestion press_a(std::string label, std::string reason){
    InputSuggestion s;
    s.button = "A";
    s.label = std::move(label);
    s.reason = std::move(reason);
    return s;
}


//  ── team_preview_selecting state machine ──────────────────────────────────
//  Strategy: dummy "first 4 unmarked slots" picker. Reads the digit badges
//  each poll to get ground-truth state (which slots are already marked, by
//  which lead-order digit). Robust to mid-stream auto-press toggle, missed
//  presses, and manual interventions — the screen IS the state.
//
//    marks_count == count of slots with a 1-4 digit
//    target = first slot WITHOUT a digit (or -1 if all marked)
//    if marks_count >= 4 && cursor unread: assume cursor on Done -> A
//    else: nav cursor to target, then A on it.
static std::optional<InputSuggestion> suggest_team_preview_selecting(
    const BattleStateTracker& tracker,
    const LiveContext& ctx
){
    (void)tracker;
    int marks_count = 0;
    int first_unmarked = -1;
    for (int i = 0; i < 6; i++){
        char d = ctx.tp_marks_per_slot[i];
        if (d >= '1' && d <= '4'){
            marks_count++;
        }else if (first_unmarked < 0){
            first_unmarked = i;
        }
    }

    //  Singles brings 3, Doubles brings 4.
    const int needed = (ctx.format_target == 0) ? 3 : 4;
    if (marks_count >= needed){
        //  All marks made. Need cursor on Done (index 6). If still on a slot,
        //  Down advances toward Done.
        int cursor = ctx.tp_cursor_slot;
        if (cursor == 6){
            InputSuggestion s;
            s.button = "A";
            s.label = "A — Done";
            s.reason = std::to_string(needed) + " marks; cursor on Done";
            return s;
        }
        if (cursor < 0){
            return std::nullopt;  //  cursor unread; wait
        }
        InputSuggestion s;
        s.button = "Down";
        s.label = "Down — to Done";
        s.reason = std::to_string(needed) + " marks; cursor=" + std::to_string(cursor) + " advancing to Done";
        return s;
    }

    if (first_unmarked < 0){
        //  Defensive: marks_count<4 but no unmarked slot? Shouldn't happen
        //  unless OCR is mis-reading. Wait a poll.
        return std::nullopt;
    }

    int target = first_unmarked;
    int cursor = ctx.tp_cursor_slot;

    if (cursor < 0){
        return std::nullopt;  //  cursor unread; wait
    }
    if (cursor < target){
        InputSuggestion s;
        s.button = "Down";
        s.label = "Down — to slot " + std::to_string(target);
        s.reason = "cursor=" + std::to_string(cursor)
                 + " target=" + std::to_string(target)
                 + " marks=" + std::to_string(marks_count) + "/" + std::to_string(needed);
        return s;
    }
    if (cursor > target){
        InputSuggestion s;
        s.button = "Up";
        s.label = "Up — to slot " + std::to_string(target);
        s.reason = "cursor=" + std::to_string(cursor)
                 + " target=" + std::to_string(target)
                 + " marks=" + std::to_string(marks_count) + "/" + std::to_string(needed);
        return s;
    }
    InputSuggestion s;
    s.button = "A";
    s.label = "A — mark slot " + std::to_string(target);
    s.reason = "marks=" + std::to_string(marks_count) + "/" + std::to_string(needed);
    return s;
}


//  Vertical menu nav: emit Down/Up to walk cursor toward target, A on hit,
//  std::nullopt while cursor unread (wait a poll). Generic across any
//  vertically-stacked menu where selected_index increases top-to-bottom.
static std::optional<InputSuggestion> suggest_vertical_menu(
    int cursor, int target,
    const std::string& target_label,
    int max_index
){
    if (cursor < 0){
        return std::nullopt;  //  unread; wait
    }
    if (cursor < 0 || cursor >= max_index){
        return std::nullopt;  //  out of range; wait
    }
    if (cursor < target){
        InputSuggestion s;
        s.button = "Down";
        s.label = "Down — to " + target_label;
        s.reason = "cursor at " + std::to_string(cursor)
                 + ", target " + std::to_string(target);
        return s;
    }
    if (cursor > target){
        InputSuggestion s;
        s.button = "Up";
        s.label = "Up — to " + target_label;
        s.reason = "cursor at " + std::to_string(cursor)
                 + ", target " + std::to_string(target);
        return s;
    }
    InputSuggestion s;
    s.button = "A";
    s.label = "A — " + target_label;
    s.reason = "cursor on target";
    return s;
}


//  ── pokemon_switch (forced switch after faint) ────────────────────────────
//  Strategy: pick first alive lead slot (0-3), navigate cursor there, A.
//  Pressing A on a slot opens a context modal (Switch In / Info / Cancel) —
//  cursor on column reads as -1 then because the highlight is on the modal,
//  not the column. We just press A again to confirm Switch In (default
//  cursored). The dedup window is short enough to allow this.
static std::optional<InputSuggestion> suggest_pokemon_switch(
    const LiveContext& ctx
){
    int target = -1;
    for (int i = 0; i < 4; i++){    //  Only leads (0-3) are pickable.
        if (ctx.switch_alive[i]){ target = i; break; }
    }
    if (target < 0){
        //  No alive lead read. Either OCR missed, or all 4 leads are KO'd
        //  (match should have ended). Wait a poll.
        return std::nullopt;
    }
    int cursor = ctx.switch_cursor;
    if (cursor < 0){
        //  Cursor unread. Most common reason on this screen: a context
        //  modal is currently open (cursor moved off the column onto the
        //  modal). Press A to confirm Switch In (default cursored).
        InputSuggestion s;
        s.button = "A";
        s.label = "A — confirm Switch In";
        s.reason = "context modal open (cursor off column)";
        return s;
    }
    if (cursor < target){
        InputSuggestion s;
        s.button = "Down";
        s.label = "Down — to slot " + std::to_string(target);
        s.reason = "switch to first alive (cursor=" + std::to_string(cursor)
                 + ", target=" + std::to_string(target) + ")";
        return s;
    }
    if (cursor > target){
        InputSuggestion s;
        s.button = "Up";
        s.label = "Up — to slot " + std::to_string(target);
        s.reason = "switch to first alive (cursor=" + std::to_string(cursor)
                 + ", target=" + std::to_string(target) + ")";
        return s;
    }
    InputSuggestion s;
    s.button = "A";
    s.label = "A — open modal on slot " + std::to_string(target);
    s.reason = "first alive lead";
    return s;
}


std::optional<InputSuggestion> suggest_for_screen(
    const std::string& screen,
    const BattleStateTracker& tracker,
    const LiveContext& ctx
){
    if (screen == "move_select"){
        return suggest_move_select(tracker);
    }
    if (screen == "action_menu"){
        //  Cursor defaults to Fight after every turn; just press A.
        //  ActionMenuDetector::cursored() exposes FIGHT/POKEMON if we ever
        //  need to gate on it.
        return press_a("A — Fight", "open move menu (default cursor)");
    }
    if (screen == "target_select"){
        //  Doubles target pick. Cursor defaults to opp_a; just A. Could
        //  consult TargetSelectDetector::selected_index() if needed.
        return press_a("A — first target", "default target (opp_a)");
    }
    if (screen == "pokemon_switch"){
        return suggest_pokemon_switch(ctx);
    }
    if (screen == "team_preview" || screen == "team_preview_selecting"){
        return suggest_team_preview_selecting(tracker, ctx);
    }
    //  ── Menu nav chain — auto-nav to target option, then A. ──
    if (screen == "main_menu"){
        //  2D-ish layout. Indexes:
        //    0 Battle (target)        center-left, big tile
        //    1 Box                    top-right
        //    2 Train                  middle-right
        //    3 Recruit                middle, below Battle
        //    4-7 bottom bar (Missions/Mailbox/Style/SubMenu)
        //  Step-toward-target heuristic: Up to escape bottom bar / Recruit,
        //  Left from the right column. Eventually lands on Battle, then A.
        int cursor = ctx.menu_selected_index;
        if (cursor < 0) return std::nullopt;
        if (cursor == 0){
            return press_a("A — Battle", "open Battle menu");
        }
        if (cursor >= 4){
            //  Bottom bar — Up escapes back into the main grid.
            InputSuggestion s;
            s.button = "Up";
            s.label = "Up — leave bottom bar";
            s.reason = "cursor in bottom bar (idx=" + std::to_string(cursor) + ")";
            return s;
        }
        if (cursor == 1 || cursor == 2){
            //  Box / Train are right-column. Left moves toward Battle column.
            InputSuggestion s;
            s.button = "Left";
            s.label = "Left — toward Battle";
            s.reason = "cursor on " + std::string(cursor == 1 ? "Box" : "Train");
            return s;
        }
        //  cursor == 3 (Recruit): Up to Battle.
        InputSuggestion s;
        s.button = "Up";
        s.label = "Up — to Battle";
        s.reason = "cursor on Recruit";
        return s;
    }
    if (screen == "battle_mode_menu"){
        const char* label = (ctx.battle_mode_target == 1) ? "Casual" : "Ranked";
        return suggest_vertical_menu(
            ctx.menu_selected_index, ctx.battle_mode_target, label, /*max=*/5);
    }
    if (screen == "ranked_format_select" || screen == "casual_format_select"){
        const char* label = (ctx.format_target == 1) ? "Doubles" : "Singles";
        return suggest_vertical_menu(ctx.menu_selected_index, ctx.format_target, label, /*max=*/2);
    }
    if (screen == "pre_match" || screen == "casual_pre_match"){
        //  Until the team-scan has completed once this program session,
        //  target Team Select (0) so we can run the M&M + Stats scan.
        //  Afterwards, target Begin Matchmaking (2) for the queue loop.
        const int target = ctx.team_scan_complete ? 2 : 0;
        const char* label = ctx.team_scan_complete ? "Begin Matchmaking" : "Team Select";
        return suggest_vertical_menu(ctx.menu_selected_index, target, label, /*max=*/3);
    }
    if (screen == "team_select"){
        //  Scan-and-pick sub-flow active? Steps 0,1,2,3,6,7 fire on
        //  team_select.
        if (ctx.team_scan_step >= 0){
            switch (ctx.team_scan_step){
            case 0: { InputSuggestion s; s.button = "A";
                s.label = "A — open team modal";
                s.reason = "scan step 0/7"; return s; }
            case 1: { InputSuggestion s; s.button = "Down";
                s.label = "Down — to Edit";
                s.reason = "scan step 1/7"; return s; }
            case 2: { InputSuggestion s; s.button = "Down";
                s.label = "Down — to View Info";
                s.reason = "scan step 2/7"; return s; }
            case 3: { InputSuggestion s; s.button = "A";
                s.label = "A — enter info screen";
                s.reason = "scan step 3/7"; return s; }
            case 6: { InputSuggestion s; s.button = "A";
                s.label = "A — open team modal";
                s.reason = "scan step 6/7"; return s; }
            case 7: { InputSuggestion s; s.button = "A";
                s.label = "A — Select this team";
                s.reason = "scan step 7/7 (confirm)"; return s; }
            //  Steps 4 and 5 belong to other screens — if we see them
            //  here it means a screen transition is mid-flight; wait.
            default: return std::nullopt;
            }
        }
        //  Normal nav-then-confirm path (no scan needed this match).
        const int target = ctx.team_index_target;
        int cursor = ctx.menu_selected_index;
        if (cursor < 0) return std::nullopt;
        if (cursor < target){
            InputSuggestion s;
            s.button = "Right";
            s.label = "Right — to Team " + std::to_string(target + 1);
            s.reason = "cursor=" + std::to_string(cursor)
                     + " target=Team " + std::to_string(target + 1);
            return s;
        }
        if (cursor > target){
            InputSuggestion s;
            s.button = "Left";
            s.label = "Left — to Team " + std::to_string(target + 1);
            s.reason = "cursor=" + std::to_string(cursor)
                     + " target=Team " + std::to_string(target + 1);
            return s;
        }
        return press_a("A — Confirm Team " + std::to_string(target + 1),
                       "cursor on target");
    }
    if (screen == "moves_and_more"){
        if (ctx.team_scan_step == 4){
            InputSuggestion s;
            s.button = "R";
            s.label = "R — tab to Stats";
            s.reason = "scan step 4/7 (M&M loaded)";
            return s;
        }
        return std::nullopt;
    }
    if (screen == "team_stats"){
        if (ctx.team_scan_step == 5){
            InputSuggestion s;
            s.button = "B";
            s.label = "B — back out of info";
            s.reason = "scan step 5/7 (Stats loaded)";
            return s;
        }
        return std::nullopt;
    }
    if (screen == "team_preview_locked_in" || screen == "preparing")
        return press_a("A — Confirm Leads", "confirm leads / continue");
    if (screen == "result_screen")        return press_a("A — Continue",     "dismiss result banner");
    if (screen == "post_match"){
        //  3 horizontal buttons: 0=Quit, 1=Edit, 2=Continue. Default cursor
        //  is Continue (2). We want Quit (0) — Left twice from Continue.
        const int target = 0;  //  QUIT_BATTLING
        int cursor = ctx.menu_selected_index;
        if (cursor < 0) return std::nullopt;
        if (cursor > target){
            InputSuggestion s;
            s.button = "Left";
            s.label = "Left — to Quit";
            s.reason = "cursor=" + std::to_string(cursor) + " target=Quit(0)";
            return s;
        }
        if (cursor < target){
            InputSuggestion s;
            s.button = "Right";
            s.label = "Right — to Quit";
            s.reason = "cursor=" + std::to_string(cursor) + " target=Quit(0)";
            return s;
        }
        return press_a("A — Quit Battling", "stop laddering after this match");
    }
    //  ── Wait screens — no suggestion (overlay clears, dashboard hides pill). ──
    if (screen == "searching_for_battle") return std::nullopt;
    if (screen == "match_intro")          return std::nullopt;
    return std::nullopt;
}


}
}
}
