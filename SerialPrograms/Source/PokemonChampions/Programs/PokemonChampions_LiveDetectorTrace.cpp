/*  Pokemon Champions Live Detector Trace
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include <algorithm>
#include <cctype>
#include <chrono>
#include <ctime>
#include <fstream>

#include <QByteArray>
#include <QEventLoop>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>

#include "Common/Cpp/Json/JsonArray.h"
#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoFeed.h"

#include "PokemonChampions/Inference/PokemonChampions_AbilityItemReader.h"
#include "PokemonChampions/Inference/PokemonChampions_ActionMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_ActiveHUDSlotDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleModeDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_CommunicatingDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MainMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MegaEvolveDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PokeballAliveDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PostMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreparingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamStatsReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TargetSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TargetSelectReader.h"

#include "PokemonChampions/Programs/PokemonChampions_LiveDetectorTrace.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


// ─── Descriptor + ctor ──────────────────────────────────────────────────────

LiveDetectorTrace_Descriptor::LiveDetectorTrace_Descriptor()
    : SingleSwitchProgramDescriptor(
        "PokemonChampions:LiveDetectorTrace",
        "Pokemon Champions", "Live Detector Trace",
        "Programs/PokemonChampions/LiveDetectorTrace.html",
        "Passive watcher: runs the full ingest pipeline against the live "
        "capture and POSTs engine view + per-reader pipeline status to "
        "mac_dev_runner. Cole plays manually with a real controller; this "
        "program does not send any inputs.",
        ProgramControllerClass::StandardController_NoRestrictions,
        FeedbackType::NONE,
        AllowCommandsWhenRunning::DISABLE_COMMANDS
    )
{}


LiveDetectorTrace::LiveDetectorTrace()
    : POLL_PERIOD_MILLISECONDS(
        "<b>Poll Period (ms):</b><br>How often to snapshot + run readers. 250ms = 4 Hz.",
        LockMode::UNLOCK_WHILE_RUNNING,
        250
    )
    , STALE_AFTER_MILLISECONDS(
        "<b>Stale-After (ms):</b><br>Pipeline entries that haven't fired ok within this window are downgraded from 'ok' to 'stale' for the dashboard.",
        LockMode::UNLOCK_WHILE_RUNNING,
        2000
    )
    , SINK_URL(
        false,
        "<b>Sink URL:</b><br>POST target for snapshot events.",
        LockMode::UNLOCK_WHILE_RUNNING,
        "http://127.0.0.1:9876/live-trace/event",
        "http://127.0.0.1:9876/live-trace/event"
    )
    , OWN_TEAM_PASTE(
        "<b>Own Team (Showdown Paste):</b><br>"
        "Pokemon Showdown formatted team paste. Canonical source for own-side "
        "state (species, moves, item, ability for all 6 slots). Visual own-side "
        "OCR is fallback / WIP only. Loaded once at program start.",
        LockMode::LOCK_WHILE_RUNNING,
        "",
        "Paste your Showdown team here..."
    )
    , ENABLE_AUTO_CAPTURE(
        "<b>Enable Auto-Capture:</b><br>"
        "Save a PNG + sidecar JSON to AUTO_CAPTURE_DIR whenever the trace sees "
        "something novel: an under-labeled screen entry (target_select, team_select), "
        "a never-before-seen BattleLogEventType this session, a new opp species "
        "from the HUD, or a new ability/item reveal. Capped at MAX_PER_HOUR. "
        "Skips already-seen content so you don't accumulate dupes. After a "
        "session, rsync AUTO_CAPTURE_DIR up to ash to triage on the dashboard.",
        LockMode::UNLOCK_WHILE_RUNNING,
        false
    )
    , AUTO_CAPTURE_DIR(
        false,
        "<b>Auto-Capture Dir:</b><br>"
        "Where to drop captured PNG + JSON sidecars. Defaults to the dashboard "
        "inbox path so the existing triage flow picks them up after sync.",
        LockMode::UNLOCK_WHILE_RUNNING,
        "/Users/cole/Dev/pokemon-champions/test_images/_inbox",
        "/Users/cole/Dev/pokemon-champions/test_images/_inbox"
    )
    , AUTO_CAPTURE_MAX_PER_HOUR(
        "<b>Max Captures / Hour:</b><br>"
        "Sliding hourly cap; older captures fall out of the window automatically. "
        "0 = no cap (not recommended).",
        LockMode::UNLOCK_WHILE_RUNNING,
        60
    )
{
    PA_ADD_OPTION(POLL_PERIOD_MILLISECONDS);
    PA_ADD_OPTION(STALE_AFTER_MILLISECONDS);
    PA_ADD_OPTION(SINK_URL);
    PA_ADD_OPTION(OWN_TEAM_PASTE);
    PA_ADD_OPTION(ENABLE_AUTO_CAPTURE);
    PA_ADD_OPTION(AUTO_CAPTURE_DIR);
    PA_ADD_OPTION(AUTO_CAPTURE_MAX_PER_HOUR);
}


// ─── HTTP POST helper ───────────────────────────────────────────────────────

static bool post_event(Logger& logger, const std::string& url, const std::string& body){
    QNetworkRequest request{QUrl(QString::fromStdString(url))};
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    request.setTransferTimeout(1000);

    QNetworkAccessManager manager;
    QEventLoop loop;
    QObject::connect(&manager, &QNetworkAccessManager::finished, &loop, &QEventLoop::quit);

    std::unique_ptr<QNetworkReply> reply(
        manager.post(request, QByteArray::fromStdString(body))
    );
    loop.exec();

    if (reply->error() != QNetworkReply::NoError){
        logger.log(
            "LiveDetectorTrace: POST failed: " + reply->errorString().toStdString(),
            COLOR_RED
        );
        return false;
    }
    return true;
}


// ─── Pipeline registry ──────────────────────────────────────────────────────

static int64_t now_ms(){
    return (int64_t)std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();
}


// ─── Auto-capture helpers ───────────────────────────────────────────────────

static std::string ts_filename_part(){
    auto t = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    auto ms = (int64_t)std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count() % 1000;
    std::tm tm_buf{};
    localtime_r(&t, &tm_buf);
    char buf[32];
    std::snprintf(buf, sizeof(buf),
        "%04d%02d%02d-%02d%02d%02d%03d",
        tm_buf.tm_year + 1900, tm_buf.tm_mon + 1, tm_buf.tm_mday,
        tm_buf.tm_hour, tm_buf.tm_min, tm_buf.tm_sec, (int)ms
    );
    return std::string(buf);
}


static std::string slugify_for_filename(const std::string& s){
    std::string out;
    out.reserve(s.size());
    for (char c : s){
        if (std::isalnum((unsigned char)c)) out += (char)std::tolower((unsigned char)c);
        else if (c == '_' || c == '-' || c == ':') out += '-';
        else if (!out.empty() && out.back() != '-') out += '-';
    }
    while (!out.empty() && out.back() == '-') out.pop_back();
    if (out.size() > 60) out.resize(60);
    return out;
}


std::string LiveDetectorTrace::fingerprint_raw_text(const std::string& raw){
    std::string out;
    out.reserve(raw.size());
    for (char c : raw){
        if (std::isalnum((unsigned char)c)){
            out += (char)std::tolower((unsigned char)c);
        }
    }
    if (out.size() > 60) out.resize(60);
    return out;
}


bool LiveDetectorTrace::maybe_capture(
    Logger& logger,
    const ImageViewRGB32& screen,
    const std::string& reason,
    const std::string& dedup_key,
    std::set<std::string>& dedup_set,
    JsonObject metadata
){
    if (!ENABLE_AUTO_CAPTURE) return false;

    //  Per-channel dedup — first occurrence per session for novelty
    //  channels, first occurrence per match for screen-entry.
    if (!dedup_set.insert(dedup_key).second) return false;

    //  Hourly rate cap (sliding window).
    int64_t now = now_ms();
    while (!m_capture_window_ms.empty() && now - m_capture_window_ms.front() > 3'600'000){
        m_capture_window_ms.pop_front();
    }
    uint32_t cap = AUTO_CAPTURE_MAX_PER_HOUR;
    if (cap > 0 && m_capture_window_ms.size() >= cap){
        logger.log(
            "auto-capture: hourly cap (" + std::to_string(cap) + ") hit; skipping " + reason,
            COLOR_ORANGE
        );
        //  Roll back the dedup add so we'll try again next time the window
        //  has room. Otherwise a one-time burst would burn this slot forever.
        dedup_set.erase(dedup_key);
        return false;
    }

    std::string dir = AUTO_CAPTURE_DIR;
    if (dir.empty()){
        logger.log("auto-capture: AUTO_CAPTURE_DIR empty; skipping", COLOR_RED);
        dedup_set.erase(dedup_key);
        return false;
    }
    if (dir.back() == '/') dir.pop_back();

    std::string base = ts_filename_part() + "-" + slugify_for_filename(reason + "-" + dedup_key);
    std::string png_path = dir + "/" + base + ".png";
    std::string json_path = dir + "/" + base + ".json";

    if (!screen.save(png_path)){
        logger.log("auto-capture: failed to save " + png_path, COLOR_RED);
        dedup_set.erase(dedup_key);
        return false;
    }

    metadata["reason"] = reason;
    metadata["dedup_key"] = dedup_key;
    metadata["ts_ms"] = (int64_t)now;
    {
        std::ofstream js(json_path);
        if (js){
            js << metadata.dump();
        }
    }

    m_capture_window_ms.push_back(now);
    logger.log("auto-capture: " + base + ".png", COLOR_GREEN);
    return true;
}


void LiveDetectorTrace::init_pipeline_registry(){
    m_pipeline.clear();
    auto add = [this](const std::string& name, const std::string& cat, const std::string& status, const std::string& note){
        PipelineEntry e;
        e.name = name;
        e.category = cat;
        e.status = status;
        e.note = note;
        m_pipeline.emplace(name, std::move(e));
    };

    //  ── Wired screen detectors (we run these every poll in classify_screen) ──
    add("TeamPreviewDetector",       "detector", "skipped", "Detects pre-battle Team Preview screen.");
    add("PreparingForBattleDetector","detector", "skipped", "Detects 'Preparing for Battle' lock-in screen.");
    add("ActionMenuDetector",        "detector", "skipped", "Detects FIGHT/POKE action menu (in-battle).");
    add("MoveSelectDetector",        "detector", "skipped", "Detects move-pick menu (4 move pills visible).");
    add("ResultScreenDetector",      "detector", "skipped", "Detects 'Win!' / 'Lose...' result banner.");
    add("PostMatchScreenDetector",   "detector", "skipped", "Detects 'Continue Battling?' post-match prompt.");
    add("MainMenuDetector",          "detector", "skipped", "Detects the Pokemon Champions main menu (out of battle).");
    add("ActiveHUDSlotDetector",     "detector", "skipped", "Reads which own slot has the lime-green active outline (doubles).");
    add("TeamSelectDetector",        "detector", "skipped", "Detects the team-select tab strip (the screen before Team Preview where you pick which 4 to bring); also reports selected_tab.");
    add("TargetSelectDetector",      "detector", "skipped", "Detects the doubles target-select modal: 4 selector strips visible with exactly one in the selected (yellow/green) state. Reports selected_index 0..3 (opp_a/opp_b/own_a/own_b).");
    add("CommunicatingDetector",     "detector", "skipped", "Detects the 'syncing with opponent' transitional overlay; co-fires with whatever screen is underneath.");
    add("MovesMoreDetector",         "detector", "skipped", "Detects the 'View Details — Moves & More' tab. Shows species/ability/item/4 moves per slot.");
    add("TeamStatsTabDetector",      "detector", "skipped", "Detects the 'View Details — Stats' tab. Shows 6 stats × {actual, EVs, nature direction} per slot.");

    //  ── Wired readers ──
    add("BattleModeDetector",        "reader", "skipped", "Reads format label: Singles vs Doubles. Refreshed on TeamPreview / matchmaking screens.");
    add("TeamPreviewReader",         "reader", "skipped",
        "Sprite-matches all 6 opp species (CANONICAL for opp side). "
        "Also OCR's own species/items but those are NOT applied to the "
        "tracker — own state comes from OWN_TEAM_PASTE. The own-side OCR "
        "result is shown in last_output as a confirmation/diff signal only.");
    add("BattleHUDReader",           "reader", "skipped", "Reads opp active species (text), opp + own active HPs. Fires on action_menu / move_select / preparing screens.");
    add("MoveNameReader",            "reader", "skipped", "Reads the 4 move-name pills on Move Select. Fires only on move_select.");
    add("PokeballAliveDetector",     "reader", "skipped", "Reads alive/fainted/empty for all 6 slots per side from the HUD pokeball strip. Fires whenever the HUD is visible.");
    add("TargetSelectReader",        "reader", "skipped",
        "Reads the doubles target-select modal: which move each own active mon picked, "
        "which target is highlighted, and per-target effectiveness label. Fires only on the "
        "target_select screen.");
    add("TeamSummaryReader",         "reader", "skipped",
        "Reads the Moves & More tab — species/ability/item/4 moves for all 6 slots in one OCR pass. "
        "Fires only on moves_and_more screens. Feeds BattleStateTracker::update_from_team_summary "
        "(merges with existing own-team data; partial reads don't clobber).");
    add("TeamStatsReader",           "reader", "skipped",
        "Reads the Stats tab — 6 stats per slot (final value + EVs + nature direction). "
        "Infers nature slug (Adamant/Timid/...) from the boost/drop pair. "
        "Fires only on team_stats screens. Feeds BattleStateTracker::update_from_team_stats.");
    add("AbilityItemReader",         "reader", "skipped",
        "OCRs the mid-battle ability/item reveal overlay (\"Garchomp's Rough Skin!\"). Self-gates on its "
        "own visual detection; deduped against the prior raw text so a single overlay only fires once.");
    add("OwnTeamPaste",              "reader", "skipped",
        "Pokemon Showdown formatted paste from program options. CANONICAL source for own-side state "
        "(species, moves, item, ability for all 6 slots). Loaded once at program start.");

    //  ── WIP / unavailable (declared but not wired) ──
    add("MovesAndMoreReader",        "reader", "n/a",
        "Requires controller navigation to enter 'View Details -> Moves & More'. "
        "Cannot run in passive mode. AutoLadder uses this to load own species/moves/abilities at match start.");
    add("BattleLogReader",           "reader", "skipped",
        "OCRs the bottom-center battle text bar (move/switch/faint/boost/status/weather/terrain). "
        "Fires whenever the bar is visible during in-battle screens; dedupes by raw text so a "
        "single sticky line only updates the tracker once. Feeds BattleStateTracker::update_from_log().");
    add("StatusOverlayReader",       "reader", "wip",
        "No reader exists yet. Status condition icons (PSN/PAR/BRN/SLP/FRZ) on the HUD are not OCR'd.");
    add("BoostsReader",              "reader", "wip",
        "No reader exists yet. Stat-up/down arrows on the HUD are not parsed; boosts come only via BattleLogReader (also WIP).");
    add("WeatherReader",             "reader", "wip", "No reader exists yet. Weather overlay (sun/rain/sand/snow) not parsed.");
    add("TerrainReader",             "reader", "wip", "No reader exists yet. Terrain overlay (electric/grassy/misty/psychic) not parsed.");
    add("TrickRoomDetector",         "detector", "wip", "No detector exists yet. Trick Room state not parsed.");
    add("TailwindDetector",          "detector", "wip", "No detector exists yet. Per-side Tailwind not parsed.");
    add("ScreensDetector",           "detector", "wip", "No detector exists yet. Light Screen / Reflect / Aurora Veil per side not parsed.");
    add("MegaEvolveDetector",        "detector", "skipped", "Reads whether the Mega Evolve toggle pill is showing on Move Select. Fires only on move_select.");
}


void LiveDetectorTrace::declare_wip_entries(){
    //  Re-mark wip/n/a entries each poll so a transient mis-classification
    //  doesn't promote a wip entry to "skipped". (Skipped means "applicable
    //  reader, just not for this screen"; wip means "not implemented at all.")
    for (auto& [name, e] : m_pipeline){
        if (e.status == "wip" || e.status == "n/a"){
            e.last_check_ms = now_ms();
        }
    }
}


void LiveDetectorTrace::mark(const std::string& name, const std::string& status, JsonValue output){
    auto it = m_pipeline.find(name);
    if (it == m_pipeline.end()) return;
    PipelineEntry& e = it->second;
    int64_t t = now_ms();
    e.last_check_ms = t;
    //  Don't overwrite wip/n/a — those are intrinsic to the entry.
    if (e.status == "wip" || e.status == "n/a") return;
    e.status = status;
    if (status == "ok"){
        e.last_fire_ms = t;
        if (output.type() != JsonType::EMPTY){
            e.last_output = std::move(output);
        }
    }
}


void LiveDetectorTrace::mark_skipped(const std::string& name){
    auto it = m_pipeline.find(name);
    if (it == m_pipeline.end()) return;
    PipelineEntry& e = it->second;
    if (e.status == "wip" || e.status == "n/a") return;
    //  Preserve "ok" history but flag that the reader didn't run this poll.
    //  age_pipeline_entries() will downgrade to "stale" once it's been a while.
    if (e.status != "ok"){
        e.status = "skipped";
    }
    e.last_check_ms = now_ms();
}


void LiveDetectorTrace::age_pipeline_entries(int64_t now){
    int64_t stale_window = (uint32_t)STALE_AFTER_MILLISECONDS;
    for (auto& [name, e] : m_pipeline){
        if (e.status == "wip" || e.status == "n/a") continue;
        if (e.status == "ok" && e.last_fire_ms > 0 && (now - e.last_fire_ms) > stale_window){
            e.status = "stale";
        }
    }
}


// ─── Screen classification ──────────────────────────────────────────────────

std::string LiveDetectorTrace::classify_screen(Logger& logger, const ImageViewRGB32& screen){
    //  Try detectors in priority order. First match wins. Each detector
    //  is constructed locally (cheap) and gets marked in pipeline status.
    auto try_det = [&](const std::string& name, auto& det) -> bool {
        bool fired = det.detect(screen);
        mark(name, fired ? "ok" : "skipped");
        return fired;
    };

    //  Order matters: most-specific in-battle screens first, since their
    //  evidence is unambiguous. TeamPreview / MainMenu fall through.
    {
        //  More specific than MoveSelect — target-select happens after a
        //  move is picked in doubles. Check first so we don't misclassify.
        TargetSelectDetector det;
        if (try_det("TargetSelectDetector", det)){
            JsonObject out;
            out["selected_index"] = (int64_t)det.selected_index();
            mark("TargetSelectDetector", "ok", std::move(out));
            return "target_select";
        }
    }
    {
        MoveSelectDetector det;
        if (try_det("MoveSelectDetector", det)) return "move_select";
    }
    {
        ActionMenuDetector det;
        if (try_det("ActionMenuDetector", det)) return "action_menu";
    }
    {
        PreparingForBattleDetector det;
        if (try_det("PreparingForBattleDetector", det)) return "preparing";
    }
    {
        ResultScreenDetector det;
        if (try_det("ResultScreenDetector", det)) return "result_screen";
    }
    {
        PostMatchScreenDetector det;
        if (try_det("PostMatchScreenDetector", det)) return "post_match";
    }
    {
        TeamPreviewDetector det;
        if (try_det("TeamPreviewDetector", det)) return "team_preview";
    }
    {
        TeamSelectDetector det;
        if (try_det("TeamSelectDetector", det)){
            JsonObject out;
            out["selected_tab"] = (int64_t)det.selected_team();
            mark("TeamSelectDetector", "ok", std::move(out));
            return "team_select";
        }
    }
    //  Both View Details tabs share the purple-card backdrop but differ in
    //  which tab label is yellow-green. Order doesn't matter — they
    //  mutually exclude (only one tab is active at a time).
    {
        MovesMoreDetector det;
        if (try_det("MovesMoreDetector", det)) return "moves_and_more";
    }
    {
        TeamStatsTabDetector det;
        if (try_det("TeamStatsTabDetector", det)) return "team_stats";
    }
    {
        MainMenuDetector det;
        if (try_det("MainMenuDetector", det)) return "main_menu";
    }
    return "unknown";
}


// ─── Per-screen reader fan-out ──────────────────────────────────────────────

void LiveDetectorTrace::try_battle_mode(Logger& logger, const ImageViewRGB32& screen){
    BattleModeDetector det;
    BattleMode mode = det.read_mode(logger, screen);
    if (mode != BattleMode::UNKNOWN){
        m_mode = mode;
        m_tracker.set_mode(mode);
        JsonObject out;
        out["mode"] = std::string(battle_mode_str(mode));
        mark("BattleModeDetector", "ok", std::move(out));
    }else{
        mark("BattleModeDetector", "error");
    }
}


void LiveDetectorTrace::run_team_preview_screen(Logger& logger, const ImageViewRGB32& screen){
    try_battle_mode(logger, screen);

    TeamPreviewReader reader(Language::English);
    TeamPreviewResult result = reader.read(logger, screen);

    int own_count = 0, opp_count = 0;
    JsonArray own_arr, opp_arr;
    for (uint8_t i = 0; i < 6; i++){
        const auto& slot = result.own[i];
        JsonObject row;
        row["slot"] = (int64_t)i;
        row["species"] = slot.species;
        row["item"] = slot.item;
        own_arr.push_back(std::move(row));
        if (!slot.species.empty()) own_count++;

        if (!slot.item.empty()){
            m_tracker.set_own_item(i, slot.item);
        }

        const std::string& opp_sp = result.opp_species[i];
        JsonObject orow;
        orow["slot"] = (int64_t)i;
        orow["species"] = opp_sp;
        opp_arr.push_back(std::move(orow));
        if (!opp_sp.empty()){
            m_tracker.set_opp_species_preview(i, opp_sp);
            opp_count++;
        }
    }

    //  Own-side OCR is INTENTIONALLY NOT applied to the tracker here.
    //  Own team state comes from OWN_TEAM_PASTE (Showdown paste) loaded at
    //  program start — that's the canonical source per
    //  feedback_own_team_via_paste.md. We still report what the OCR saw in
    //  the pipeline status so it's visible as a confirmation/diff signal,
    //  but we don't overwrite the paste-loaded tracker fields with possibly
    //  bad OCR. Item-only update from OCR is kept (above) since paste
    //  provides item too but per-match item changes shouldn't be common.

    JsonObject summary;
    summary["own_species_read"] = (int64_t)own_count;
    summary["opp_species_matched"] = (int64_t)opp_count;
    summary["own"] = std::move(own_arr);
    summary["opp"] = std::move(opp_arr);
    mark("TeamPreviewReader", (own_count + opp_count) > 0 ? "ok" : "error", std::move(summary));
}


void LiveDetectorTrace::run_moves_and_more_screen(Logger& logger, const ImageViewRGB32& screen){
    TeamSummaryReader reader(Language::English);
    auto team = reader.read_team(logger, screen);

    //  Build a signature from the species+item+ability concat so we only
    //  fire update_from_team_summary once per distinct read while the
    //  user sits on this screen.
    std::string sig;
    for (const auto& t : team){
        sig += t.species + "|" + t.ability + "|" + t.item + "|"
             + t.moves[0] + "," + t.moves[1] + "," + t.moves[2] + "," + t.moves[3] + ";";
    }
    bool fresh = (sig != m_prev_team_summary_sig);
    m_prev_team_summary_sig = sig;

    if (fresh){
        m_tracker.update_from_team_summary(team);
    }

    JsonObject out;
    JsonArray slot_arr;
    for (uint8_t i = 0; i < 6; i++){
        JsonObject s;
        s["slot"] = (int64_t)i;
        s["species"] = team[i].species;
        s["ability"] = team[i].ability;
        s["item"] = team[i].item;
        JsonArray moves;
        for (uint8_t m = 0; m < 4; m++) moves.push_back(team[i].moves[m]);
        s["moves"] = std::move(moves);
        slot_arr.push_back(std::move(s));
    }
    out["slots"] = std::move(slot_arr);
    out["fresh"] = fresh;
    mark("TeamSummaryReader", "ok", std::move(out));
}


void LiveDetectorTrace::run_team_stats_screen(Logger& logger, const ImageViewRGB32& screen){
    TeamStatsReader reader;
    auto team = reader.read_team(logger, screen);

    std::string sig;
    for (const auto& t : team){
        sig += t.nature_slug + "|";
        for (const auto& s : t.stats){
            sig += std::to_string(s.actual) + "," + std::to_string(s.evs) + ";";
        }
    }
    bool fresh = (sig != m_prev_team_stats_sig);
    m_prev_team_stats_sig = sig;

    if (fresh){
        m_tracker.update_from_team_stats(team);
    }

    JsonObject out;
    JsonArray slot_arr;
    static const char* keys[6] = {"hp","atk","def","spa","spd","spe"};
    for (uint8_t i = 0; i < 6; i++){
        JsonObject s;
        s["slot"] = (int64_t)i;
        s["nature"] = team[i].nature_slug;
        JsonObject stats;
        for (uint8_t k = 0; k < 6; k++){
            JsonObject one;
            one["actual"] = (int64_t)team[i].stats[k].actual;
            one["evs"] = (int64_t)team[i].stats[k].evs;
            one["nature"] = std::string(nature_mod_name(team[i].stats[k].nature));
            stats[keys[k]] = std::move(one);
        }
        s["stats"] = std::move(stats);
        slot_arr.push_back(std::move(s));
    }
    out["slots"] = std::move(slot_arr);
    out["fresh"] = fresh;
    mark("TeamStatsReader", "ok", std::move(out));
}


void LiveDetectorTrace::run_target_select_screen(Logger& logger, const ImageViewRGB32& screen){
    TargetSelectReader reader(Language::English);
    TargetSelectReadout r = reader.read(logger, screen);

    JsonObject out;
    JsonArray opp_t, own_t, opp_e, own_e, own_m;
    for (uint8_t i = 0; i < 2; i++){
        opp_t.push_back(r.opp_targeted[i]);
        own_t.push_back(r.own_targeted[i]);
        opp_e.push_back(r.opp_effectiveness[i]);
        own_e.push_back(r.own_effectiveness[i]);
        own_m.push_back(r.own_moves[i]);
    }
    out["opp_targeted"]      = std::move(opp_t);
    out["own_targeted"]      = std::move(own_t);
    out["opp_effectiveness"] = std::move(opp_e);
    out["own_effectiveness"] = std::move(own_e);
    out["own_moves"]         = std::move(own_m);
    mark("TargetSelectReader", "ok", std::move(out));
}


void LiveDetectorTrace::run_ability_item_reader(Logger& logger, const ImageViewRGB32& screen){
    AbilityItemReader reader;
    AbilityItemReadout r = reader.read(logger, screen);
    if (!r.detected){
        mark_skipped("AbilityItemReader");
        return;
    }
    bool fresh = (r.raw_text != m_prev_ability_item_text);
    m_prev_ability_item_text = r.raw_text;

    JsonObject out;
    out["raw"] = r.raw_text;
    out["pokemon"] = r.pokemon;
    out["name"] = r.name;
    out["kind"] = r.kind;
    out["side"] = r.side;
    out["fresh"] = fresh;
    mark("AbilityItemReader", "ok", std::move(out));

    //  Auto-capture: first occurrence of each (kind, name) per session.
    if (fresh && !r.name.empty()){
        std::string key = r.kind + ":" + r.name;
        JsonObject meta;
        meta["channel"] = std::string("ability_item");
        meta["kind"] = r.kind;
        meta["name"] = r.name;
        if (!r.pokemon.empty()) meta["pokemon"] = r.pokemon;
        if (!r.side.empty())    meta["side"] = r.side;
        meta["raw_text"] = r.raw_text;
        maybe_capture(logger, screen,
            "novel-ability-item", key,
            m_seen_ability_items, std::move(meta));
    }
}


void LiveDetectorTrace::run_battle_log_reader(Logger& logger, const ImageViewRGB32& screen){
    BattleLogReader reader;
    if (!reader.detect_text_bar(screen)){
        mark_skipped("BattleLogReader");
        return;
    }
    BattleLogEvent ev = reader.read_event(logger, screen);
    if (ev.raw_text.empty()){
        mark("BattleLogReader", "error");
        return;
    }

    bool fresh = (ev.raw_text != m_prev_log_text);
    m_prev_log_text = ev.raw_text;

    JsonObject out;
    out["type"] = event_type_to_string(ev.type);
    out["raw"] = ev.raw_text;
    out["is_opponent"] = ev.is_opponent;
    out["fresh"] = fresh;
    if (!ev.pokemon.empty()) out["pokemon"] = ev.pokemon;
    if (!ev.move.empty())    out["move"] = ev.move;
    if (!ev.stat.empty())    out["stat"] = ev.stat;
    if (!ev.item.empty())    out["item"] = ev.item;
    if (!ev.ability.empty()) out["ability"] = ev.ability;
    if (!ev.effect.empty())  out["effect"] = ev.effect;
    if (ev.boost_stages != 0) out["boost_stages"] = (int64_t)ev.boost_stages;

    //  Only feed the tracker once per distinct line, and only when the
    //  parser produced a recognized event type. UNKNOWN/OTHER lines are
    //  surfaced in the dashboard but not applied to state.
    if (fresh
        && ev.type != BattleLogEventType::UNKNOWN
        && ev.type != BattleLogEventType::OTHER)
    {
        m_tracker.update_from_log(ev);

        //  Auto-capture: first occurrence of each event_type per session.
        //  Coarser than per-line so we don't capture every MOVE_USED, but
        //  catches the rare events (ABILITY_CHANGE, TRANSFORM, FIELD_EFFECT,
        //  PRIMAL, etc.) we'd want labeled.
        std::string evname = event_type_to_string(ev.type);
        JsonObject meta;
        meta["channel"] = std::string("battle_log");
        meta["event_type"] = evname;
        meta["raw_text"] = ev.raw_text;
        if (!ev.pokemon.empty()) meta["pokemon"] = ev.pokemon;
        if (!ev.move.empty())    meta["move"] = ev.move;
        maybe_capture(logger, screen,
            "novel-event-type", evname,
            m_seen_log_event_types, std::move(meta));
    }

    mark("BattleLogReader", "ok", std::move(out));
}


void LiveDetectorTrace::run_battle_screen(Logger& logger, const ImageViewRGB32& screen){
    //  BattleHUD reader — opp active species + both side HPs.
    {
        BattleHUDReader reader(Language::English);
        BattleHUDState hud = reader.read_all(logger, screen);
        m_tracker.update_from_hud(hud);

        JsonObject out;
        JsonArray opps;
        for (uint8_t i = 0; i < 2; i++){
            JsonObject o;
            o["slot"] = (int64_t)i;
            o["species"] = hud.opponents[i].species;
            o["hp_pct"] = (double)hud.opponents[i].hp_pct;
            opps.push_back(std::move(o));
        }
        JsonArray owns;
        for (uint8_t i = 0; i < 2; i++){
            JsonObject o;
            o["slot"] = (int64_t)i;
            o["hp_pct"] = (double)hud.own[i].hp_pct;
            owns.push_back(std::move(o));
        }
        out["opponents"] = std::move(opps);
        out["own"] = std::move(owns);
        bool any = !hud.opponents[0].species.empty() || !hud.opponents[1].species.empty()
                || hud.opponents[0].hp_pct > 0 || hud.own[0].hp_pct > 0;
        mark("BattleHUDReader", any ? "ok" : "error", std::move(out));

        //  Auto-capture: first time we see each opp species this session.
        //  Skips non-ASCII / nicknamed reads (those need sprite-match path).
        for (uint8_t i = 0; i < 2; i++){
            const std::string& sp = hud.opponents[i].species;
            if (sp.empty()) continue;
            bool ascii = true;
            for (unsigned char c : sp){ if (c >= 128){ ascii = false; break; } }
            if (!ascii) continue;
            JsonObject meta;
            meta["channel"] = std::string("opp_species");
            meta["species"] = sp;
            meta["slot"] = (int64_t)i;
            maybe_capture(logger, screen,
                "novel-opp-species", sp,
                m_seen_opp_species, std::move(meta));
        }
    }

    //  Pokeball alive-mask — both sides, all 6 slots.
    {
        PokeballAliveDetector det;
        PokeballAliveResult pb = det.read(screen);
        JsonObject out;
        JsonArray own_arr, opp_arr;
        for (uint8_t i = 0; i < 6; i++){
            own_arr.push_back(std::string(pokeball_state_name(pb.own[i])));
            opp_arr.push_back(std::string(pokeball_state_name(pb.opp[i])));
        }
        out["own"] = std::move(own_arr);
        out["opp"] = std::move(opp_arr);
        out["own_alive_count"] = (int64_t)pb.own_alive_count();
        out["opp_alive_count"] = (int64_t)pb.opp_alive_count();
        mark("PokeballAliveDetector", "ok", std::move(out));
    }

    //  Active HUD slot (which own slot is currently selected for move pick).
    {
        ActiveHUDSlotDetector det;
        bool fired = det.detect(screen);
        JsonObject out;
        if (fired){
            out["active_slot"] = (int64_t)det.active_slot();
            mark("ActiveHUDSlotDetector", "ok", std::move(out));
        }else{
            mark("ActiveHUDSlotDetector", "skipped");
        }
    }

    //  Battle log text bar — fires whenever the bar is visible. The reader
    //  internally gates on detect_text_bar() so it's cheap on frames with
    //  no bar showing.
    run_battle_log_reader(logger, screen);

    //  Ability/item reveal overlay — self-gates on its own visual detection.
    run_ability_item_reader(logger, screen);
}


void LiveDetectorTrace::run_move_select_screen(Logger& logger, const ImageViewRGB32& screen){
    //  Battle HUD is also visible on Move Select — run it too.
    run_battle_screen(logger, screen);

    //  4 own active moves.
    MoveNameReader reader(Language::English);
    MoveSelectionRead res = reader.read_all(logger, screen);

    int n = 0;
    for (const auto& m : res.moves) if (!m.empty()) n++;
    if (n > 0){
        std::array<std::string, 4> moves{};
        for (size_t i = 0; i < 4 && i < res.moves.size(); i++){
            moves[i] = res.moves[i];
        }
        uint8_t active_slot = res.active_slot >= 0 ? (uint8_t)res.active_slot : 0;
        m_tracker.update_from_moves(moves, active_slot);
    }

    JsonObject out;
    JsonArray arr;
    for (size_t i = 0; i < res.moves.size(); i++){
        arr.push_back(res.moves[i]);
    }
    out["moves"] = std::move(arr);
    out["active_slot"] = (int64_t)res.active_slot;
    mark("MoveNameReader", n > 0 ? "ok" : "error", std::move(out));

    //  Mega Evolve toggle visibility.
    {
        MegaEvolveDetector mega;
        bool can_mega = mega.detect(screen);
        JsonObject mout;
        mout["can_mega_evolve"] = can_mega;
        mark("MegaEvolveDetector", "ok", std::move(mout));
    }
}


// ─── Event payload ──────────────────────────────────────────────────────────

JsonObject LiveDetectorTrace::build_event(const std::string& screen, int64_t ts_ms, uint64_t seq){
    JsonObject ev;
    ev["seq"] = (int64_t)seq;
    ev["ts_ms"] = ts_ms;
    ev["type"] = std::string("snapshot");
    ev["current_screen"] = screen;
    ev["battle_mode"] = std::string(battle_mode_str(m_mode));
    ev["match_in_progress"] = m_match_in_progress;

    JsonObject pipeline;
    int64_t now = now_ms();
    for (const auto& [name, e] : m_pipeline){
        JsonObject p;
        p["category"] = e.category;
        p["status"] = e.status;
        p["note"] = e.note;
        p["last_fire_ms_ago"] = e.last_fire_ms > 0 ? (int64_t)(now - e.last_fire_ms) : (int64_t)-1;
        p["last_check_ms_ago"] = e.last_check_ms > 0 ? (int64_t)(now - e.last_check_ms) : (int64_t)-1;
        if (e.last_output.type() != JsonType::EMPTY){
            p["last_output"] = e.last_output.clone();
        }
        pipeline[name] = std::move(p);
    }
    ev["pipeline"] = std::move(pipeline);

    ev["engine_view"] = m_tracker.to_predict_json();
    return ev;
}


// ─── Main loop ──────────────────────────────────────────────────────────────

void LiveDetectorTrace::program(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    std::string sink_url = SINK_URL;
    env.console.log("LiveDetectorTrace: starting. Sink = " + sink_url, COLOR_BLUE);

    init_pipeline_registry();
    m_tracker.reset();
    m_prev_screen.clear();
    m_prev_log_text.clear();
    m_prev_ability_item_text.clear();
    m_prev_team_summary_sig.clear();
    m_prev_team_stats_sig.clear();
    m_match_in_progress = false;
    m_seen_log_event_types.clear();
    m_seen_opp_species.clear();
    m_seen_ability_items.clear();
    m_captured_screen_entries.clear();
    m_capture_window_ms.clear();
    uint64_t seq = 0;

    //  Seed own-team from Showdown paste (canonical source per
    //  feedback_own_team_via_paste.md). Visual own-side OCR is fallback only.
    {
        std::string paste = OWN_TEAM_PASTE;
        if (!paste.empty()){
            int loaded = m_tracker.load_team_from_showdown_paste(paste);
            env.console.log(
                "LiveDetectorTrace: loaded " + std::to_string(loaded) +
                "/6 own Pokemon from Showdown paste.",
                loaded > 0 ? COLOR_GREEN : COLOR_YELLOW
            );
            mark("OwnTeamPaste", "ok", JsonValue((int64_t)loaded));
        }else{
            env.console.log(
                "LiveDetectorTrace: no Showdown paste provided; own team will "
                "be empty until visual OCR is wired (currently WIP).",
                COLOR_YELLOW
            );
            mark("OwnTeamPaste", "error");
        }
    }

    while (true){
        VideoSnapshot snapshot = env.console.video().snapshot();
        if (!snapshot){
            context.wait_until(
                std::chrono::system_clock::now() +
                std::chrono::milliseconds((uint32_t)POLL_PERIOD_MILLISECONDS)
            );
            continue;
        }

        declare_wip_entries();

        //  Reset every detector's per-poll status to "skipped" — they'll
        //  override to "ok" when they fire below.
        for (auto& [name, e] : m_pipeline){
            if (e.status == "ok") mark_skipped(name);
        }

        std::string screen = classify_screen(env.console, snapshot);

        //  CommunicatingDetector is an overlay signal — it can fire on top of
        //  any underlying screen, so run it independently of the cascade and
        //  surface it in the pipeline. Doesn't replace the underlying screen
        //  classification; the dashboard treats it as a co-fire bool.
        {
            CommunicatingDetector det;
            bool fired = det.detect(snapshot);
            if (fired){
                JsonObject out;
                out["communicating"] = true;
                mark("CommunicatingDetector", "ok", std::move(out));
            }else{
                mark_skipped("CommunicatingDetector");
            }
        }

        //  Match-state transitions: enter a new match on TeamPreview after
        //  a non-battle screen; mark match over on Result/PostMatch.
        if (screen == "team_preview" && (m_prev_screen.empty()
                || m_prev_screen == "main_menu" || m_prev_screen == "post_match"
                || m_prev_screen == "result_screen")){
            if (m_match_in_progress || m_tracker.opp_seen_count() > 0){
                env.console.log("LiveDetectorTrace: new match — wiping tracker + reloading own paste.", COLOR_BLUE);
            }
            m_tracker.reset();
            m_tracker.set_mode(m_mode);
            m_prev_log_text.clear();
            m_prev_ability_item_text.clear();
    m_prev_team_summary_sig.clear();
    m_prev_team_stats_sig.clear();
            //  Per-match dedup — re-arm screen-entry captures so we get a
            //  fresh target_select / team_select snapshot on each new match.
            //  Other seen sets are session-scoped and survive matches.
            m_captured_screen_entries.clear();
            //  Re-seed own team from paste so it survives the reset.
            std::string paste = OWN_TEAM_PASTE;
            if (!paste.empty()){
                m_tracker.load_team_from_showdown_paste(paste);
            }
            m_match_in_progress = true;
        }
        if (screen == "post_match" || screen == "result_screen"){
            m_match_in_progress = false;
        }

        //  Auto-capture: under-labeled screen entries (transition INTO the
        //  screen, not while we sit on it). Reset per match, so re-entering
        //  target_select on the next turn captures again only if we haven't
        //  in this match.
        if ((screen == "target_select" || screen == "team_select"
                || screen == "moves_and_more" || screen == "team_stats")
            && screen != m_prev_screen)
        {
            JsonObject meta;
            meta["screen"] = screen;
            maybe_capture(env.console, snapshot,
                "screen-entry", screen,
                m_captured_screen_entries, std::move(meta));
        }

        //  Run readers for whatever screen we're on.
        if (screen == "team_preview"){
            run_team_preview_screen(env.console, snapshot);
        }else if (screen == "move_select"){
            run_move_select_screen(env.console, snapshot);
        }else if (screen == "action_menu" || screen == "preparing"){
            run_battle_screen(env.console, snapshot);
        }else if (screen == "target_select"){
            run_target_select_screen(env.console, snapshot);
        }else if (screen == "moves_and_more"){
            run_moves_and_more_screen(env.console, snapshot);
        }else if (screen == "team_stats"){
            run_team_stats_screen(env.console, snapshot);
        }else if (screen == "unknown" && m_match_in_progress){
            //  Mid-animation frames (post-move flashes, switch transitions,
            //  faint sequences) usually classify as "unknown" — but the
            //  battle text bar AND the ability/item reveal overlay are most
            //  often visible exactly during these frames. Both readers
            //  internally gate on their own visual checks, so this is a
            //  cheap no-op when neither overlay is showing.
            run_battle_log_reader(env.console, snapshot);
            run_ability_item_reader(env.console, snapshot);
        }
        //  result_screen / post_match / main_menu / unknown (out of match) —
        //  no readers fire, but pipeline status still reports the screen
        //  detector hit.

        age_pipeline_entries(now_ms());

        JsonObject ev = build_event(screen, now_ms(), seq++);
        post_event(env.console, sink_url, ev.dump());

        m_prev_screen = screen;

        context.wait_until(snapshot.timestamp + std::chrono::milliseconds((uint32_t)POLL_PERIOD_MILLISECONDS));
    }
}


}
}
}
