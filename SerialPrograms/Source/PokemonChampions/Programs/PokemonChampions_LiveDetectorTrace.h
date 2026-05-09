/*  Pokemon Champions Live Detector Trace
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Passive video-only watcher. Cole plays the game manually with a real
 *  controller; this program watches the capture card, runs the same
 *  ingest pipeline AutoLadder uses (minus team-scan navigation, action
 *  decision, and controller commands), and POSTs rich snapshots to
 *  mac_dev_runner so the dashboard can render the engine's-eye view AND
 *  per-reader pipeline status.
 *
 *  Design goal: dashboard should see "everything we can possibly know
 *  about the current game state right now" plus "which detectors and
 *  readers are wired up vs. WIP / unavailable so I can see at a glance
 *  what's left to build."
 *
 */

#ifndef PokemonAutomation_PokemonChampions_LiveDetectorTrace_H
#define PokemonAutomation_PokemonChampions_LiveDetectorTrace_H

#include <array>
#include <deque>
#include <map>
#include <optional>
#include <set>
#include <string>

#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "Common/Cpp/Options/BooleanCheckBoxOption.h"
#include "Common/Cpp/Options/EnumDropdownOption.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/StringOption.h"
#include "Common/Cpp/Options/TextEditOption.h"
#include "NintendoSwitch/NintendoSwitch_SingleSwitchProgram.h"
#include "NintendoSwitch/Options/NintendoSwitch_StartInGripMenuOption.h"
#include "PokemonChampions_BattleStateTracker.h"
#include "PokemonChampions_InputSuggester.h"

namespace PokemonAutomation{

template <typename Type> class ControllerContext;
class Logger;
class ImageViewRGB32;

namespace NintendoSwitch{

class ProController;
using ProControllerContext = ControllerContext<ProController>;

namespace PokemonChampions{


//  Status of one reader/detector at the most recent poll.
//    "ok"       - fired this poll, returned a useful read
//    "stale"    - last fired N seconds ago; sticky value still in tracker
//    "skipped"  - not applicable to current screen; not run this poll
//    "wip"      - declared in the registry but no implementation yet
//    "n/a"      - cannot run in passive mode (e.g. Moves & More needs nav)
//    "error"    - fired but produced no useful data (empty OCR, etc.)
struct PipelineEntry{
    std::string name;
    std::string category;       //  "detector" / "reader"
    std::string status = "wip";
    int64_t last_fire_ms = 0;   //  monotonic ms time of last "ok"
    int64_t last_check_ms = 0;  //  last time it was even attempted (any status)
    std::string note;           //  freeform description / WIP rationale
    JsonValue last_output;      //  most recent raw output (or summary)
};


class LiveDetectorTrace_Descriptor : public SingleSwitchProgramDescriptor{
public:
    LiveDetectorTrace_Descriptor();
};


class LiveDetectorTrace : public SingleSwitchProgramInstance{
public:
    LiveDetectorTrace();

    virtual void program(SingleSwitchProgramEnvironment& env, ProControllerContext& context) override;

private:
    //  ── Pipeline registry helpers ──
    void init_pipeline_registry();
    void mark(const std::string& name, const std::string& status, JsonValue output = JsonValue());
    void mark_skipped(const std::string& name);

    //  ── Per-poll work ──
    //  Cascade through the screen detectors. Returns a slug:
    //    "team_preview" / "preparing" / "action_menu" / "move_select" /
    //    "result_screen" / "post_match" / "main_menu" / "unknown".
    //  Marks each detector's pipeline status as it goes.
    std::string classify_screen(Logger& logger, const ImageViewRGB32& screen);

    //  Run battle-mode reader (rarely changes; refreshed when on a screen
    //  that exposes the format label).
    void try_battle_mode(Logger& logger, const ImageViewRGB32& screen);

    //  Per-screen reader fan-out. Each marks its own pipeline entries.
    void run_team_preview_screen(Logger& logger, const ImageViewRGB32& screen);
    void run_battle_screen(Logger& logger, const ImageViewRGB32& screen);
    void run_move_select_screen(Logger& logger, const ImageViewRGB32& screen);
    void run_target_select_screen(Logger& logger, const ImageViewRGB32& screen);
    void run_moves_and_more_screen(Logger& logger, const ImageViewRGB32& screen);
    void run_team_stats_screen(Logger& logger, const ImageViewRGB32& screen);
    void run_locked_in_screen(Logger& logger, const ImageViewRGB32& screen);
    void run_battle_info_screen(Logger& logger, const ImageViewRGB32& screen);
    void run_pokemon_switch_screen(Logger& logger, const ImageViewRGB32& screen);

    //  Detects the in-battle text bar; OCRs + parses; deduplicates against
    //  the prior poll's raw text so a single log line (which sticks for
    //  several poll periods) only updates the tracker once.
    void run_battle_log_reader(Logger& logger, const ImageViewRGB32& screen);

    //  Reads the mid-battle ability/item reveal overlay ("Garchomp's Rough
    //  Skin!"). Self-gates on its own visual detection; deduped against the
    //  prior raw text so a single overlay only fires once.
    void run_ability_item_reader(Logger& logger, const ImageViewRGB32& screen);

    //  ── Auto-capture helpers ──
    //  Snapshot the current frame to AUTO_CAPTURE_DIR with a sidecar JSON
    //  if (a) auto-capture is on, (b) we're under the hourly cap, and
    //  (c) the reason isn't already in the dedup set for that channel.
    //  Returns true iff a file was written.
    bool maybe_capture(
        Logger& logger,
        const ImageViewRGB32& screen,
        const std::string& reason,
        const std::string& dedup_key,
        std::set<std::string>& dedup_set,
        JsonObject metadata
    );

    //  Cheap, OCR-noise-resistant fingerprint for raw battle-log text.
    //  Lowercase, ASCII-alnum only, first 60 chars.
    static std::string fingerprint_raw_text(const std::string& raw);

    //  Mark every WIP / unavailable entry with its declared status (called
    //  once at registry init; thereafter their status is preserved).
    void declare_wip_entries();

    //  Build the JSON event for the dashboard.
    JsonObject build_event(const std::string& screen, int64_t ts_ms, uint64_t seq);

    //  Mark all "ok" entries that haven't fired in the last N seconds as
    //  "stale" (so the dashboard can show fresh-vs-cached signal).
    void age_pipeline_entries(int64_t now_ms);

    //  ── Options ──
    //  Start-in-grip-menu dance — required for Switch 2 (and any setup
    //  where a real controller is paired). Without this, the console keeps
    //  the user's physical controller paired and SP's virtual controller's
    //  button writes are silently ignored. With this on, the program
    //  presses L+R via the virtual controller to trigger console pairing,
    //  then exits grip menu via Home. Detach all physical controllers
    //  BEFORE starting the program.
    StartInGripOrGameOption START_LOCATION;

    //  Which format to queue for. Drives the ranked_format_select suggester
    //  target. 0 = Singles (top tile), 1 = Doubles (bottom tile).
    IntegerEnumDropdownOption FORMAT_TARGET;

    //  Battle Mode Menu target. 0=Ranked, 1=Casual, 2=Private, 3=Online
    //  Comp, 4=Battle Data. Only Ranked and Casual lead to a queueable
    //  ladder run.
    IntegerEnumDropdownOption BATTLE_MODE_TARGET;

    //  Team Select target. 0..17 = Team 1..18. Drives horizontal nav on
    //  the team_select screen — the screen is a 5-column carousel that
    //  hides which absolute team is selected, so we left-home to Team 1
    //  before stepping Right to the target.
    IntegerEnumDropdownOption TEAM_INDEX;

    SimpleIntegerOption<uint32_t> POLL_PERIOD_MILLISECONDS;
    SimpleIntegerOption<uint32_t> STALE_AFTER_MILLISECONDS;
    StringOption SINK_URL;

    //  ── Auto-press options ──
    //  Off by default. When on, the program presses the suggested button
    //  for screens on the safe allowlist (menu nav, result/post-match) —
    //  IN-BATTLE screens (action/move/target/switch) and the
    //  team_preview_selecting screen are NEVER auto-pressed even when this
    //  is on. Per-(screen, button) dedup with a 10s retry window so a
    //  press that didn't register fires again, but we don't burst.
    BooleanCheckBoxOption ENABLE_AUTO_PRESS;

    //  ── Auto-capture options ──
    //  Off by default. When on, the program drops PNG + sidecar JSON into
    //  AUTO_CAPTURE_DIR for screens / readouts that look novel relative to
    //  what's already been seen this session. Designed for live play —
    //  feeds the dashboard inbox triage flow instead of the video-dump
    //  pipeline.
    BooleanCheckBoxOption ENABLE_AUTO_CAPTURE;
    StringOption AUTO_CAPTURE_DIR;
    SimpleIntegerOption<uint32_t> AUTO_CAPTURE_MAX_PER_HOUR;

    //  ── State ──
    BattleStateTracker m_tracker;
    BattleMode m_mode = BattleMode::UNKNOWN;
    std::map<std::string, PipelineEntry> m_pipeline;

    //  Track screen transitions so we can wipe the tracker when a fresh
    //  match begins (TeamPreview entered after we were on PostMatch /
    //  MainMenu / Result).
    std::string m_prev_screen;
    bool m_match_in_progress = false;

    //  Last raw battle-log OCR text. Used to dedupe: a single log line stays
    //  on screen for many poll periods, so we only feed update_from_log()
    //  once per distinct line.
    std::string m_prev_log_text;

    //  Same dedup pattern for the ability/item reveal overlay.
    std::string m_prev_ability_item_text;

    //  Dedup signatures for the team-scan readers — prevents writing the
    //  tracker every poll while we sit on the screen. Signature is a
    //  concat of per-slot key fields (species|item for M&M, nature|EVs
    //  for Stats); when it changes, we re-fire update_from_*.
    std::string m_prev_team_summary_sig;
    std::string m_prev_team_stats_sig;
    std::string m_prev_leads_sig;
    std::string m_prev_battle_info_sig;

    //  ── Auto-capture state ──
    //  Per-channel "seen this session" sets so each novel readout fires at
    //  most one capture. Keys are channel-specific:
    //    log:   "<event_type>"  (one capture per first occurrence of each
    //                            BattleLogEventType this session)
    //    opp:   "<species>"     (HUDReader.opponent_species)
    //    abil:  "<kind>:<name>" (AbilityItemReader)
    //    enter: "<screen>"      (one capture per screen entry, reset per match)
    std::set<std::string> m_seen_log_event_types;
    std::set<std::string> m_seen_opp_species;
    std::set<std::string> m_seen_ability_items;
    std::set<std::string> m_captured_screen_entries;

    //  Sliding hourly window for the rate cap.
    std::deque<int64_t> m_capture_window_ms;

    //  Latest input suggestion (consumed by build_event each poll).
    std::optional<InputSuggestion> m_last_suggestion;

    //  Auto-press dedup state.
    std::string m_last_pressed_screen;
    std::string m_last_pressed_button;
    int64_t m_last_press_ms = 0;
    int64_t m_last_screen_change_ms = 0;

    //  Live context fed to the suggester (per-poll reader output that
    //  doesn't belong on BattleStateTracker).
    int m_tp_cursor_slot = -1;                //  Set by run_team_preview_screen.
    std::array<char, 6> m_tp_marks_per_slot = {};  //  Lead-order digit per slot
                                                   //  ('1'..'4' or 0). Read each
                                                   //  poll on team_preview.
    int m_menu_selected_index = -1;  //  Set by classify_screen when one of
                                     //  the menu detectors fires.

    //  team_select scan-and-pick sequence (load M&M + Stats before queueing).
    //  -1 = inactive. 0..7 = current step in the canonical sequence:
    //    0  team_select  A     open team modal
    //    1  team_select  Down  to "Edit this team"
    //    2  team_select  Down  to "View Info"
    //    3  team_select  A     enter info screen (-> moves_and_more)
    //    4  moves_and_more  R  tab to Stats (-> team_stats)
    //    5  team_stats     B  back to team_select
    //    6  team_select  A     open team modal again
    //    7  team_select  A     confirm "Select this team" (default cursor)
    //  Activated when entering team_select with cursor on target team and
    //  scan not yet complete. Reset on match-end.
    int m_team_scan_step = -1;
    bool m_team_scan_complete = false;

    //  Carousel-aware team-select navigation state. The team_select screen
    //  shows 5 columns of an 18-wide carousel; cursor sits at col 0 only
    //  on Team 1 and col 4 only on Team 18, so cursor column alone can't
    //  identify the absolute team. Strategy: left-home until cursor is
    //  observed at col 0 (=> Team 1), then step Right per fired press,
    //  tracking known_team_n. Reset on screen entry to team_select so a
    //  manual interruption re-homes cleanly.
    //    0  = unknown (homing)
    //    1..18 = known team index
    int m_team_select_known_n = 0;
    //  Stickiness for team_select classification. The cursor-marker
    //  boxes briefly read non-yellow during a Right/Left navigation
    //  animation, which would otherwise drop the screen to "unknown"
    //  for ~250ms — long enough for the recovery-B watchdog to start
    //  the unknown-grace timer and eventually bail us out. Holding the
    //  last-seen team_select tag for ~1500ms covers the gap without
    //  hiding a genuine screen exit (the modal/info screens take
    //  longer than that to settle).
    int64_t m_team_select_last_seen_ms = 0;
    //  Wall-clock ms of the last time m_team_select_known_n changed. Used
    //  by the scan-trigger gate: pressing Right takes ~340ms to land on
    //  the Switch (240ms pre-delay + 100ms hold), so an optimistic increment
    //  in the press hook can race the next poll and fire the scan A while
    //  the cursor hasn't moved yet. Requiring known_n to settle for >=
    //  400ms guarantees at least one poll observed cursor_col matches the
    //  presumed new known_n before we open a modal.
    int64_t m_team_select_known_n_changed_at_ms = 0;
    //  Tracks the TEAM_INDEX option's value across polls so we can detect
    //  a mid-run change and re-arm the scan flow (otherwise the queuer
    //  would skip team_select and queue whichever team was last picked).
    //  -1 sentinel = "not yet observed" (initialised on first poll).
    int m_team_index_last_seen = -1;
    //  Last-logged cursor column on team_select; suppresses the per-poll
    //  detector log line when nothing changed (we're idle on the screen).
    int m_team_select_logged_col = -2;
    //  Last-logged suggestion button on team_select; same throttle for
    //  the suggester-side log.
    std::string m_team_select_logged_suggestion;
    //  One-shot guard so the unknown-after-pre_match diagnostic dump
    //  fires at most once per stuck episode (cleared on screen change).
    bool m_team_select_unknown_dumped = false;

    //  Recovery: when stuck on "unknown" classification for > grace period,
    //  press B every 5s up to 4 times to back out to a known screen.
    //  Reset whenever we see a non-unknown screen.
    int64_t m_unknown_since_ms = 0;
    int m_recovery_b_count = 0;
    int64_t m_recovery_last_b_ms = 0;

    //  pokemon_switch screen state (forced switch suggester).
    int m_switch_cursor = -1;
    std::array<bool, 6> m_switch_alive = {};
    //  Random pick rolled once per pokemon_switch entry. m_switch_rolled_for
    //  is the action_menu visit number we last rolled for, so re-entering
    //  the screen on a different turn re-rolls but mid-attempt re-entries
    //  (after a context modal flicker) keep the same target.
    int m_switch_target_slot = 0;
    int m_switch_rolled_for = -1;

    //  In-battle dummy strategy: 2 fight turns then a manual switch.
    //  Counts entries to action_menu since the current match started
    //  (resets when a fresh team_preview kicks off a new match). The
    //  suggester targets POKEMON whenever (visits > 0 && visits % 3 == 0).
    int m_battle_action_menu_visits = 0;
    //  Per-action_menu cursor (0=FIGHT, 1=POKEMON) and per-move_select
    //  cursor (0..3), captured from their detectors. -1 = unread.
    int m_action_menu_cursor = -1;
    int m_move_select_cursor = -1;
    //  Random move slot rolled once per move_select visit. We only
    //  reroll when the visit-counter advances past m_move_slot_rolled_for
    //  so a single turn's nav is consistent across polls.
    int m_target_move_slot = 0;
    int m_move_slot_rolled_for = -1;
};


}
}
}
#endif
