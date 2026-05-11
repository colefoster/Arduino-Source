/*  Pokemon Champions Input Suggester
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include "PokemonChampions_InputSuggester.h"
#include "PokemonChampions_BattleStateTracker.h"

namespace {
//  Resolve the on-field own slots: prefer the BattleSnapshot when ctx
//  carries one (canonical), fall back to ctx.own_active_slots for
//  legacy callers (tests, contexts built without a tracker).
inline std::array<int, 2> resolve_own_active(
    const PokemonAutomation::NintendoSwitch::PokemonChampions::LiveContext& ctx
){
    if (ctx.snapshot != nullptr){
        return ctx.snapshot->own_active_slots;
    }
    return ctx.own_active_slots;
}
}  //  anon

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
    const BattleStateTracker& tracker,
    const LiveContext& ctx
){
    //  Random-slot picker: target slot is rolled once per turn by the
    //  trace (m_target_move_slot) and surfaced via ctx.target_move_slot.
    //  Move panel is a vertical 4-slot list, so nav is Up/Down toward
    //  the target then A. Falls back to A if the cursor is unread or
    //  already on target.
    (void)tracker;
    //  Always mega-evolve as soon as the toggle is available. Fire R once
    //  per turn before the move pick — the per-turn guard is keyed on
    //  battle_action_menu_visits so we don't re-toggle within the same
    //  turn (which would un-mega).
    if (ctx.can_mega_evolve && !ctx.mega_toggled_this_turn){
        InputSuggestion s;
        s.button = "R";
        s.label = "R - Mega Evolve";
        s.reason = "mega: toggle on while available";
        return s;
    }
    const int target = ctx.target_move_slot;
    const int cursor = ctx.move_select_cursor;
    if (cursor >= 0 && cursor < target){
        InputSuggestion s;
        s.button = "Down";
        s.label = "Down — to Move " + std::to_string(target + 1);
        s.reason = "random pick: cursor=" + std::to_string(cursor)
                 + " target=" + std::to_string(target);
        s.highlights.push_back(move_slot_overlay_box(target));
        return s;
    }
    if (cursor > target){
        InputSuggestion s;
        s.button = "Up";
        s.label = "Up — to Move " + std::to_string(target + 1);
        s.reason = "random pick: cursor=" + std::to_string(cursor)
                 + " target=" + std::to_string(target);
        s.highlights.push_back(move_slot_overlay_box(target));
        return s;
    }
    InputSuggestion s;
    s.button = "A";
    s.label = "A — Move " + std::to_string(target + 1);
    s.reason = (cursor < 0)
        ? "cursor unread; pressing A on default slot 0"
        : "cursor on target slot " + std::to_string(target);
    s.highlights.push_back(move_slot_overlay_box(target));
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
    //  Random-among-alive picker: collect all alive lead slots (0-3),
    //  pick the one whose index matches the pre-rolled switch_target_slot
    //  modulo the count. The trace rolls switch_target_slot once per
    //  pokemon_switch entry so the choice is consistent across polls in
    //  the same switch attempt — re-entering the screen in a later turn
    //  re-rolls.
    std::array<int, 4> alive_slots{};
    int alive_count = 0;
    for (int i = 0; i < 4; i++){    //  Only leads (0-3) are pickable.
        if (!ctx.switch_alive[i]) continue;
        //  Skip mons currently on field — selecting one of them on the
        //  switch screen tries to swap a mon with itself and the game
        //  rejects it. Filter only when we actually have active info;
        //  if both slots are -1 (no HUD read yet), keep the permissive
        //  behavior so we don't strand on an empty pool.
        bool is_on_field = false;
        for (int a : resolve_own_active(ctx)){
            if (a == i){ is_on_field = true; break; }
        }
        if (is_on_field) continue;
        alive_slots[alive_count++] = i;
    }
    if (alive_count == 0){
        //  No bench candidate. Either OCR missed both alive slots, or every
        //  alive lead is currently on the field (singles+1 alive bench is
        //  the normal case; this means we shouldn't be on the switch
        //  screen at all). Wait a poll.
        return std::nullopt;
    }
    const int pick_idx = ((ctx.switch_target_slot % alive_count) + alive_count) % alive_count;
    const int target = alive_slots[pick_idx];
    int cursor = ctx.switch_cursor;
    if (cursor < 0){
        //  No yellow highlight read. On a forced switch the highlight can
        //  land on a fainted slot whose row suppresses the cursor color —
        //  nudging Down moves it onto the next (alive) slot. Bounded
        //  retry: up to 3 nudges, ~1s apart. After that give up so the
        //  caller can log an error rather than mash Down forever.
        if (ctx.switch_blind_attempts >= 3){
            return std::nullopt;
        }
        if (ctx.switch_blind_last_press_ms != 0
            && ctx.now_ms - ctx.switch_blind_last_press_ms < 1000){
            //  Too soon since last nudge — wait for the next poll.
            return std::nullopt;
        }
        InputSuggestion s;
        s.button = "Down";
        s.label = "Down — no highlight, nudging";
        s.reason = "cursor unread (attempt "
                 + std::to_string(ctx.switch_blind_attempts + 1) + "/3)";
        return s;
    }
    //  Nav-loop guard: if the cursor reads but isn't moving despite us
    //  pressing Up/Down, stop. Likely means the reader's cursor boxes
    //  are mistuned for the current layout (singles 3-row vs the
    //  reader's 4-row tuning) — keep mashing Down and we just spam
    //  forever. Cap at 5 navs since the cursor last changed.
    if (cursor != target && ctx.switch_nav_since_change >= 5){
        return std::nullopt;
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
        return suggest_move_select(tracker, ctx);
    }
    if (screen == "action_menu"){
        //  Strategy: every third action_menu visit (visits 3, 6, 9, ...)
        //  pick POKEMON to force a switch — gives the auto-queuer
        //  variety instead of always firing slot-0 of the lead. The
        //  intermediate two visits go FIGHT (which then routes through
        //  move_select with a randomly-chosen slot).
        const int visits = ctx.battle_action_menu_visits;
        const bool switch_turn = (visits > 0 && visits % 3 == 0);
        const int cursor = ctx.action_menu_cursor;  //  0=FIGHT, 1=POKEMON
        const int target = switch_turn ? 1 : 0;
        const char* target_label = switch_turn ? "Pokemon" : "Fight";
        if (cursor < 0){
            //  Cursor unread (mid-animation). Press A on the default
            //  cursored button (FIGHT). If this is supposed to be a
            //  switch turn, the next poll will see POKEMON cursor and
            //  Down us toward it.
            return press_a(std::string("A — ") + target_label,
                           std::string("default cursor; visits=")
                           + std::to_string(visits));
        }
        if (cursor < target){
            InputSuggestion s; s.button = "Down";
            s.label = std::string("Down — to ") + target_label;
            s.reason = "switch turn (visits=" + std::to_string(visits)
                     + ", cursor=FIGHT)";
            return s;
        }
        if (cursor > target){
            InputSuggestion s; s.button = "Up";
            s.label = std::string("Up — to ") + target_label;
            s.reason = "fight turn (visits=" + std::to_string(visits)
                     + ", cursor=POKEMON)";
            return s;
        }
        return press_a(std::string("A — ") + target_label,
                       std::string("on target; visits=")
                       + std::to_string(visits));
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
    //  Scan-and-pick sub-flow has priority over screen-specific suggestions
    //  because the modal that opens after step 0 partially covers the
    //  team_select carousel cursors and can flicker the screen
    //  classification to "unknown". Steps 1, 2, 3, 6, 7 are modal-only
    //  presses that don't depend on the underlying tab strip being seen,
    //  so we issue them even when classify_screen returns "unknown".
    //  Steps 4 (R on Moves & More) and 5 (B on Stats) still gate on their
    //  info screens — the wrong screen would mean the prior step's effect
    //  hasn't landed yet and we should wait.
    //  Helper: nav within the team-select modal toward a target option
    //  (0..3 = Select / Edit / View / Cancel). Cursor wraps top-to-bottom
    //  on the Switch, so pick the shorter of Down vs Up; ties go Down.
    //  Returns nullopt only if the caller passes a non-modal screen —
    //  that case is handled by per-step gating below.
    auto modal_nav_toward = [&](int target_opt, int step_label,
                                const char* arrival_button,
                                const char* arrival_label,
                                const char* arrival_reason)
        -> std::optional<InputSuggestion>
    {
        const int cur = ctx.menu_selected_index;  //  0..3 from modal detector
        if (cur < 0) return std::nullopt;
        if (cur == target_opt){
            InputSuggestion s; s.button = arrival_button;
            s.label = arrival_label;
            s.reason = std::string("scan step ") + std::to_string(step_label)
                     + "/7 (modal cur=" + std::to_string(cur)
                     + " == target) — " + arrival_reason;
            return s;
        }
        const int down_dist = ((target_opt - cur) % 4 + 4) % 4;  //  1..3
        const int up_dist   = 4 - down_dist;                      //  3..1
        const bool go_down = (down_dist <= up_dist);
        InputSuggestion s;
        s.button = go_down ? "Down" : "Up";
        s.label = std::string(go_down ? "Down" : "Up") + " — modal toward "
                + (target_opt == 0 ? "Select"
                 : target_opt == 1 ? "Edit"
                 : target_opt == 2 ? "View details" : "Cancel");
        s.reason = std::string("scan step ") + std::to_string(step_label)
                 + "/7 (modal cur=" + std::to_string(cur)
                 + " target=" + std::to_string(target_opt) + ")";
        return s;
    };

    //  Scan-and-pick sub-flow has priority over screen-specific suggestions.
    //  Renumbered to 5 steps (was 7) since the modal detector lets us walk
    //  to View details with a single decision-driven step instead of
    //  blind "Down, Down, A":
    //    0  team_select        A      open modal
    //    1  team_select_modal  Down/A walk to View details, then A
    //    2  moves_and_more     R      tab to Stats
    //    3  team_stats         B      back out of info screen
    //    4  team_select        A      open modal again (back-to-back match)
    //    5  team_select_modal  A/Up   confirm Select this team
    if (ctx.team_scan_step >= 0){
        switch (ctx.team_scan_step){
        case 0:
            if (screen == "team_select"){
                InputSuggestion s; s.button = "A";
                s.label = "A — open team modal";
                s.reason = "scan step 0/7"; return s;
            }
            return std::nullopt;
        case 1:
            //  Walk modal cursor to option 2 (View details), confirm with A.
            if (screen == "team_select_modal"){
                return modal_nav_toward(2, 1, "A", "A — enter View details",
                                        "press A");
            }
            return std::nullopt;
        case 2:
            if (screen == "moves_and_more"){
                InputSuggestion s; s.button = "R";
                s.label = "R — tab to Stats";
                s.reason = "scan step 2/7 (M&M loaded)"; return s;
            }
            return std::nullopt;
        case 3:
            if (screen == "team_stats"){
                InputSuggestion s; s.button = "B";
                s.label = "B — back out of info";
                s.reason = "scan step 3/7 (Stats loaded)"; return s;
            }
            return std::nullopt;
        case 4:
            //  B from team_stats lands the cursor back on whichever team
            //  was last *confirmed* (e.g. Team 1), NOT the team we just
            //  inspected — so we have to re-home + re-navigate to the
            //  scan target before the A that opens the modal again.
            //  All suggestions emitted here keep the "scan step 4/7"
            //  reason prefix so the press hook still advances scan_step
            //  when the final A fires.
            if (screen == "team_select"){
                const int target_n = ctx.team_index_target + 1;  //  1..18
                const int known_n  = ctx.team_select_known_n;
                const int cursor   = ctx.team_select_cursor_col;
                if (cursor < 0) return std::nullopt;
                if (known_n <= 0){
                    InputSuggestion s; s.button = "Left";
                    s.label = "Left — home to an edge";
                    s.reason = "scan step 4/7 (re-home after B; cursor col="
                             + std::to_string(cursor) + ")";
                    return s;
                }
                if (known_n != target_n){
                    const int forward  = ((target_n - known_n) % 18 + 18) % 18;
                    const int backward = 18 - forward;
                    const bool go_right = (forward <= backward);
                    InputSuggestion s;
                    s.button = go_right ? "Right" : "Left";
                    s.label = std::string(go_right ? "Right" : "Left")
                            + " — to Team " + std::to_string(target_n);
                    s.reason = "scan step 4/7 (re-nav: known=Team "
                             + std::to_string(known_n)
                             + " target=Team " + std::to_string(target_n) + ")";
                    return s;
                }
                if (!ctx.team_select_settle_ok) return std::nullopt;
                InputSuggestion s; s.button = "A";
                s.label = "A — open team modal";
                s.reason = "scan step 4/7 (on target Team "
                         + std::to_string(target_n) + ")";
                return s;
            }
            return std::nullopt;
        case 5:
            //  Walk modal cursor to option 0 (Select this team), confirm.
            if (screen == "team_select_modal"){
                return modal_nav_toward(0, 5, "A", "A — Select this team",
                                        "confirm");
            }
            return std::nullopt;
        default: return std::nullopt;
        }
    }

    if (screen == "team_select"){
        //  Normal nav-then-confirm path (no scan needed this match).
        //  The carousel wraps (Right at 18 -> 1, Left at 1 -> 18) and hides
        //  absolute team index for cols 1..3, so cursor col alone is
        //  ambiguous mid-carousel. Strategy:
        //    1. While known_n == 0, press Left repeatedly. Cursor MUST
        //       eventually land on col 0 (Team 1) or col 4 (Team 18) —
        //       the trace tick latches known_n on either edge, including
        //       Team 18 if Left wraps us to it from Team 1 first.
        //    2. Once anchored, pick the shorter wrap-aware direction to
        //       the target (forward / backward distance modulo 18).
        //    3. When known_n == target_n, confirm with A.
        const int target_n = ctx.team_index_target + 1;  //  1..18
        const int known_n  = ctx.team_select_known_n;    //  0 unknown, else 1..18
        const int cursor   = ctx.team_select_cursor_col; //  0..4 or -1
        if (cursor < 0) return std::nullopt;
        if (known_n <= 0){
            //  Homing: drive cursor toward an edge. Leftward homing always
            //  terminates because the carousel cycles through every team.
            InputSuggestion s;
            s.button = "Left";
            s.label = "Left — home to an edge";
            s.reason = "absolute team unknown (cursor col=" + std::to_string(cursor)
                     + "); homing left until col 0 or col 4";
            return s;
        }
        if (known_n == target_n){
            //  Wait for the most recent nav press to actually register on
            //  the Switch before opening any modal. Otherwise an
            //  in-flight Right would mean the cursor visually still sits
            //  on the previous team when A fires.
            if (!ctx.team_select_settle_ok) return std::nullopt;
            return press_a("A — Confirm Team " + std::to_string(target_n),
                           "known=target=Team " + std::to_string(target_n));
        }
        //  Shorter-direction nav with wrap. forward = #Rights to reach target;
        //  backward = #Lefts. Prefer Right on ties (arbitrary, deterministic).
        const int forward  = ((target_n - known_n) % 18 + 18) % 18;  //  1..17
        const int backward = 18 - forward;                            //  17..1
        const bool go_right = (forward <= backward);
        InputSuggestion s;
        s.button = go_right ? "Right" : "Left";
        s.label = std::string(go_right ? "Right" : "Left")
                + " — to Team " + std::to_string(target_n);
        s.reason = "known=Team " + std::to_string(known_n)
                 + " target=Team " + std::to_string(target_n)
                 + " (" + std::to_string(go_right ? forward : backward) + " step"
                 + ((go_right ? forward : backward) == 1 ? "" : "s")
                 + (go_right ? " right" : " left") + ")";
        return s;
    }
    if (screen == "moves_and_more")  return std::nullopt;
    if (screen == "team_stats")      return std::nullopt;
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
