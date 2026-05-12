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
    //  Cursor unread (just entered the screen, mid-animation, etc.) —
    //  wait a poll. Pressing A here used to fire on the default slot 0,
    //  which beat the random-target nav and "always picked move 1"
    //  whenever we entered move_select with the cursor still rendering.
    if (cursor < 0){
        return std::nullopt;
    }
    if (cursor < target){
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
    s.reason = "cursor on target slot " + std::to_string(target);
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
    const int needed = ctx.tp_lead_needed;  //  3 (singles) or 4 (doubles)

    //  Walk the configured lead order. For each position p, the slot
    //  ctx.tp_lead_order[p] should bear digit ('1'+p). If a position is
    //  wrong (someone else has the digit, or our target slot has a
    //  different digit), the fix at that position becomes our target.
    //  Pressing A on a marked slot in-game clears its mark AND
    //  renumbers higher digits down — so a single "unmark wrong slot"
    //  press lets the next poll re-mark in the correct order.
    int target_slot = -1;
    std::string reason;
    for (int p = 0; p < needed; p++){
        const char want_digit = (char)('1' + p);
        const int want_slot = ctx.tp_lead_order[p];
        if (want_slot < 0 || want_slot > 5){
            //  Unconfigured / invalid entry — fall through to "mark first
            //  unmarked slot" behavior at this position.
            int fallback = -1;
            for (int s = 0; s < 6; s++){
                if (ctx.tp_marks_per_slot[s] == 0){ fallback = s; break; }
            }
            if (fallback < 0) continue;
            target_slot = fallback;
            reason = "lead " + std::to_string(p+1) + " unconfigured; marking slot "
                   + std::to_string(fallback);
            break;
        }
        //  Who currently bears want_digit?
        int actual_slot = -1;
        for (int s = 0; s < 6; s++){
            if (ctx.tp_marks_per_slot[s] == want_digit){ actual_slot = s; break; }
        }
        if (actual_slot == want_slot){
            //  This lead position is already correct.
            continue;
        }
        if (actual_slot >= 0){
            //  Wrong slot bears this digit. Clear it (A on it) so the
            //  digits cascade down, then next poll re-marks correctly.
            target_slot = actual_slot;
            reason = "clearing wrong lead " + std::to_string(p+1) + " at slot "
                   + std::to_string(actual_slot) + " (expected slot "
                   + std::to_string(want_slot) + ")";
            break;
        }
        //  No slot bears this digit yet. The target slot must be empty
        //  to receive the mark — if it has a *higher* digit from a
        //  prior wrong placement, clear that first.
        char want_slot_mark = ctx.tp_marks_per_slot[want_slot];
        if (want_slot_mark >= '1' && want_slot_mark <= '4'){
            target_slot = want_slot;
            reason = "clearing stale digit at slot " + std::to_string(want_slot)
                   + " before placing lead " + std::to_string(p+1);
        }else{
            target_slot = want_slot;
            reason = "marking slot " + std::to_string(want_slot)
                   + " as lead " + std::to_string(p+1);
        }
        break;
    }

    //  All configured positions are correct — head to Done.
    if (target_slot < 0){
        target_slot = 6;
        reason = "all " + std::to_string(needed) + " leads correct; pressing Done";
    }

    const int cursor = ctx.tp_cursor_slot;

    //  Nav-loop guard for Done. The Done button's cursor strip
    //  occasionally fails to score (different x/y than per-slot
    //  strips) — without a bound we Down forever. After 6 navs
    //  without the cursor changing, fall back to A.
    if (target_slot == 6 && cursor >= 0 && cursor != 6
        && ctx.tp_nav_since_change >= 6){
        InputSuggestion s;
        s.button = "A";
        s.label = "A — Done (forced; cursor read stuck at " + std::to_string(cursor) + ")";
        s.reason = "tp nav-loop guard: " + std::to_string(ctx.tp_nav_since_change)
                 + " navs without cursor change; assuming cursor on Done";
        return s;
    }

    if (cursor < 0){
        return std::nullopt;  //  cursor unread; wait
    }
    if (cursor < target_slot){
        InputSuggestion s;
        s.button = "Down";
        s.label = "Down — to " + (target_slot == 6 ? std::string("Done")
                                                   : "slot " + std::to_string(target_slot));
        s.reason = reason + " (cursor=" + std::to_string(cursor) + ")";
        return s;
    }
    if (cursor > target_slot){
        InputSuggestion s;
        s.button = "Up";
        s.label = "Up — to " + (target_slot == 6 ? std::string("Done")
                                                 : "slot " + std::to_string(target_slot));
        s.reason = reason + " (cursor=" + std::to_string(cursor) + ")";
        return s;
    }
    //  cursor == target_slot
    InputSuggestion s;
    s.button = "A";
    s.label = (target_slot == 6)
        ? std::string("A — Done")
        : ("A — slot " + std::to_string(target_slot));
    s.reason = reason;
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
    //  Target is an absolute slot 0-3, pre-rolled by the trace from
    //  {alive AND not on-field} at the moment of entry to pokemon_switch.
    //  Trust it here — do NOT re-derive on-field per poll: the BattleHUD
    //  active-slot read flickers during the switch screen, and a
    //  per-poll-rebuilt candidate list made the target oscillate, which
    //  pinged the cursor Down/Up/Down/Up until the session timed out.
    int target = ctx.switch_target_slot;
    if (target < 0 || target >= 4 || !ctx.switch_alive[target]){
        //  No valid pre-rolled target yet (first-poll race, or the rolled
        //  slot's alive read got cleared). Pick deterministically: first
        //  alive lead. Stable across polls so the cursor can't oscillate
        //  even when the on-field filter would have flickered.
        target = -1;
        for (int i = 0; i < 4; i++){
            if (ctx.switch_alive[i]){ target = i; break; }
        }
        if (target < 0){
            //  No alive bench candidate visible. Wait for the reader to
            //  populate alive bits.
            return std::nullopt;
        }
    }
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
    //  Unreachable-target guard: cursor IS moving (so the above guard
    //  doesn't fire) but never lands on target. Caused by picking a
    //  target the in-game D-pad nav skips — usually the active mon when
    //  BattleHUD didn't populate before this entry so the pre-roll
    //  filter let it through. Accept the current cursor as the new
    //  target: any reachable alive bench mon is a legal switch.
    //  Threshold: ~8 navs (2x a single 3-row sweep) is more than enough
    //  to land on a reachable target. Beyond that, target is skipped.
    if (cursor != target
        && ctx.switch_nav_total >= 8
        && cursor >= 0 && cursor < 4 && ctx.switch_alive[cursor]){
        InputSuggestion s;
        s.button = "A";
        s.label = "A — fallback on slot " + std::to_string(cursor);
        s.reason = "target " + std::to_string(target) + " unreachable after "
                 + std::to_string(ctx.switch_nav_total)
                 + " navs (active mon skipped?); accepting cursor=" + std::to_string(cursor);
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
    //  Auto-collect: when the sub-flow is at step 2 (AT_MISSIONS) or
    //  step 4 (AT_MAILBOX) and we're NOT on main_menu, we presume we
    //  just opened the right sub-screen (missions or mailbox) — no
    //  need to detect it specifically. Run X → wait ~2.5s → A → B.
    //  Trace advances the step when the screen returns to main_menu.
    if ((ctx.collect_step == 2 || ctx.collect_step == 4)
        && screen != "main_menu"){
        const char* label_screen =
            (ctx.collect_step == 2) ? "missions" : "mailbox";
        if (ctx.collect_x_fired_at_ms == 0){
            InputSuggestion s;
            s.button = "X";
            s.label = "X — Claim All";
            s.reason = std::string("collect:") + label_screen + " — claim all";
            return s;
        }
        const int64_t ms_since_x = ctx.now_ms - ctx.collect_x_fired_at_ms;
        if (ms_since_x < 2500){
            return std::nullopt;  //  wait for claim animation
        }
        if (!ctx.collect_a_fired){
            InputSuggestion s;
            s.button = "A";
            s.label = "A — accept";
            s.reason = std::string("collect:") + label_screen + " — accept";
            return s;
        }
        InputSuggestion s;
        s.button = "B";
        s.label = "B — back to main_menu";
        s.reason = std::string("collect:") + label_screen + " — closing";
        return s;
    }

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
        //  Check we actually have an alive non-active mon to switch
        //  to. On a "switch turn" with no bench candidates (last mon
        //  standing in singles, or both bench fainted in doubles),
        //  POKEMON opens an empty switch screen and the suggester
        //  loops trying to nav. Fall back to FIGHT in that case.
        bool can_switch = true;
        if (ctx.snapshot != nullptr){
            can_switch = false;
            auto active = resolve_own_active(ctx);
            for (int i = 0; i < 6; i++){
                if (!ctx.snapshot->own_alive[i]) continue;
                bool on_field = false;
                for (int a : active){ if (a == i){ on_field = true; break; } }
                if (!on_field){ can_switch = true; break; }
            }
        }
        const bool switch_turn = (visits > 0 && visits % 3 == 0) && can_switch;
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
        //    0 Battle (default target)        center-left, big tile (2-tall)
        //    1 Box                            top-right
        //    2 Train                          middle-right
        //    3 Recruit                        directly BELOW Battle
        //    4 Missions                       bottom bar (left)
        //    5 Mailbox                        bottom bar
        //    6 Style                          bottom bar
        //    7 SubMenu                        bottom bar (right)
        //  Auto-collect sub-flow overrides target to Missions (4) or
        //  Mailbox (5) before the first queue. Otherwise target = Battle.
        int cursor = ctx.menu_selected_index;
        if (cursor < 0) return std::nullopt;
        int target = 0;
        const char* target_name = "Battle";
        if (ctx.collect_step == 1){ target = 4; target_name = "Missions"; }
        else if (ctx.collect_step == 3){ target = 5; target_name = "Mailbox"; }

        if (cursor == target){
            return press_a(std::string("A — ") + target_name,
                           std::string("open ") + target_name);
        }

        if (target == 0){
            //  Original hand-coded Battle nav. Recruit (3) is directly
            //  BELOW Battle so it's a single Up; Box / Train are
            //  right-column so Left; bottom bar Up to escape.
            if (cursor >= 4){
                InputSuggestion s;
                s.button = "Up";
                s.label = "Up — leave bottom bar";
                s.reason = "cursor in bottom bar (idx=" + std::to_string(cursor) + ")";
                return s;
            }
            if (cursor == 1 || cursor == 2){
                InputSuggestion s;
                s.button = "Left";
                s.label = "Left — toward Battle";
                s.reason = "cursor on " + std::string(cursor == 1 ? "Box" : "Train");
                return s;
            }
            //  cursor == 3 (Recruit): Up directly to Battle.
            InputSuggestion s;
            s.button = "Up";
            s.label = "Up — to Battle";
            s.reason = "cursor on Recruit";
            return s;
        }

        //  Target is Missions (4) or Mailbox (5) in the bottom bar.
        //  Strategy: get into the bottom bar first, then step Left/Right
        //  to the target index. From anywhere in the top grid, Down
        //  drops into the bar.
        if (cursor < 4){
            InputSuggestion s;
            s.button = "Down";
            s.label = std::string("Down — toward ") + target_name;
            s.reason = "cursor in top grid (idx=" + std::to_string(cursor)
                     + "), entering bottom bar";
            return s;
        }
        //  Now in bottom bar; step toward target.
        if (cursor < target){
            InputSuggestion s;
            s.button = "Right";
            s.label = std::string("Right — toward ") + target_name;
            s.reason = "cursor idx=" + std::to_string(cursor)
                     + ", target=" + std::to_string(target);
            return s;
        }
        //  cursor > target within bottom bar.
        InputSuggestion s;
        s.button = "Left";
        s.label = std::string("Left — toward ") + target_name;
        s.reason = "cursor idx=" + std::to_string(cursor)
                 + ", target=" + std::to_string(target);
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
