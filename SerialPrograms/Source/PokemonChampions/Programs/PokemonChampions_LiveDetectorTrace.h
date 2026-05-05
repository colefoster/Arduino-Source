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

#include <map>
#include <string>

#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/StringOption.h"
#include "NintendoSwitch/NintendoSwitch_SingleSwitchProgram.h"
#include "PokemonChampions_BattleStateTracker.h"

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

    //  Mark every WIP / unavailable entry with its declared status (called
    //  once at registry init; thereafter their status is preserved).
    void declare_wip_entries();

    //  Build the JSON event for the dashboard.
    JsonObject build_event(const std::string& screen, int64_t ts_ms, uint64_t seq);

    //  Mark all "ok" entries that haven't fired in the last N seconds as
    //  "stale" (so the dashboard can show fresh-vs-cached signal).
    void age_pipeline_entries(int64_t now_ms);

    //  ── Options ──
    SimpleIntegerOption<uint32_t> POLL_PERIOD_MILLISECONDS;
    SimpleIntegerOption<uint32_t> STALE_AFTER_MILLISECONDS;
    StringOption SINK_URL;

    //  ── State ──
    BattleStateTracker m_tracker;
    BattleMode m_mode = BattleMode::UNKNOWN;
    std::map<std::string, PipelineEntry> m_pipeline;

    //  Track screen transitions so we can wipe the tracker when a fresh
    //  match begins (TeamPreview entered after we were on PostMatch /
    //  MainMenu / Result).
    std::string m_prev_screen;
    bool m_match_in_progress = false;
};


}
}
}
#endif
