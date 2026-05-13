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
#include <set>

#include <QByteArray>
#include <QEventLoop>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>

#include "Common/Cpp/Json/JsonArray.h"
#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "CommonFramework/Globals.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoFeed.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "NintendoSwitch/Commands/NintendoSwitch_Commands_PushButtons.h"
#include "NintendoSwitch/Controllers/NintendoSwitch_ControllerButtons.h"
#include "NintendoSwitch/Programs/NintendoSwitch_GameEntry.h"
#include "PokemonChampions/Programs/PokemonChampions_InputSuggester.h"

#include "PokemonChampions/Inference/PokemonChampions_AbilityItemReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleInfoDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleInfoReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewCursorReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewLeadsReader.h"
#include "PokemonChampions/Inference/PokemonChampions_ActionMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_ActiveHUDSlotDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleModeDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_CommunicatingDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleModeMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_CasualFormatSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_CasualPreMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MainMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_RankedFormatSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_SearchingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MegaEvolveDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PokeballAliveDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PokemonSwitchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PokemonSwitchReader.h"
#include "PokemonChampions/Inference/PokemonChampions_PostMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreparingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSelectModalDetector.h"
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
    //  Default = grip menu. Switch 2 (and detached-joycon Switch 1) need
    //  this so SP's virtual controller becomes the only paired controller
    //  before any auto-press fires.
    : START_LOCATION(true)
    , FORMAT_TARGET(
        "<b>Queue Format:</b><br>"
        "Which Ranked battle format the auto-press flow should pick on the "
        "format-select screen.",
        {
            {0, "singles", "Singles"},
            {1, "doubles", "Doubles"},
        },
        LockMode::UNLOCK_WHILE_RUNNING,
        0   //  Default = Singles
    )
    , BATTLE_MODE_TARGET(
        "<b>Battle Mode:</b><br>"
        "Which row of the Battle menu to pick. Casual is recommended while "
        "the auto-queuer is being validated.",
        {
            {0, "ranked", "Ranked Battles"},
            {1, "casual", "Casual Battles"},
        },
        LockMode::UNLOCK_WHILE_RUNNING,
        1   //  Default = Casual
    )
    , TEAM_INDEX(
        "<b>Team Index:</b><br>"
        "Which saved team (1..18) to pick on the team_select screen. The "
        "auto-press flow left-homes to Team 1 first (cursor at column 0 "
        "is the only unambiguous anchor in the 5-column carousel), then "
        "steps Right to land on the target.",
        {
            { 0, "team1",  "Team 1"},
            { 1, "team2",  "Team 2"},
            { 2, "team3",  "Team 3"},
            { 3, "team4",  "Team 4"},
            { 4, "team5",  "Team 5"},
            { 5, "team6",  "Team 6"},
            { 6, "team7",  "Team 7"},
            { 7, "team8",  "Team 8"},
            { 8, "team9",  "Team 9"},
            { 9, "team10", "Team 10"},
            {10, "team11", "Team 11"},
            {11, "team12", "Team 12"},
            {12, "team13", "Team 13"},
            {13, "team14", "Team 14"},
            {14, "team15", "Team 15"},
            {15, "team16", "Team 16"},
            {16, "team17", "Team 17"},
            {17, "team18", "Team 18"},
        },
        LockMode::UNLOCK_WHILE_RUNNING,
        0   //  Default = Team 1
    )
    , LEAD_ORDER_SINGLES(
        false,
        "<b>Lead Order (Singles):</b><br>"
        "Comma-separated own-team slot numbers (1..6) for the 3 leads on "
        "the team-preview selecting screen, in pick order. E.g. <code>3,1,5</code> "
        "marks slot 3 as Lead 1, slot 1 as Lead 2, slot 5 as Lead 3. "
        "Leave blank for a random pick (re-rolled each match).",
        LockMode::UNLOCK_WHILE_RUNNING,
        "",
        ""
    )
    , LEAD_ORDER_DOUBLES(
        false,
        "<b>Lead Order (Doubles):</b><br>"
        "Comma-separated own-team slot numbers (1..6) for the 4 leads on "
        "the team-preview selecting screen, in pick order. E.g. <code>4,2,1,6</code> "
        "marks slot 4 as Lead 1, slot 2 as Lead 2, slot 1 as Lead 3, slot 6 as Lead 4. "
        "Leave blank for a random pick (re-rolled each match).",
        LockMode::UNLOCK_WHILE_RUNNING,
        "",
        ""
    )
    , POLL_PERIOD_MILLISECONDS(
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
    , ENABLE_AUTO_PRESS(
        "<b>Enable Auto-Press (DANGEROUS):</b><br>"
        "When ON, the program presses the suggested button for screens on the "
        "menu-nav allowlist (main_menu, battle_mode_menu, ranked_format_select, "
        "pre_match, team_select, team_preview_locked_in/preparing, result_screen, "
        "post_match). IN-BATTLE screens (action_menu, move_select, target_select, "
        "pokemon_switch) and team_preview_selecting are NEVER auto-pressed even "
        "with this on — they remain suggest-only. Per-(screen, button) dedup "
        "with a 10s retry. Default OFF.",
        LockMode::UNLOCK_WHILE_RUNNING,
        false
    )
    , ENABLE_AUTO_COLLECT_BEFORE_QUEUE(
        "<b>Auto-Collect Missions + Mailbox Before Queue:</b><br>"
        "Runs ONCE per program session before the first queue: from main_menu, "
        "navs to Missions, presses X (Claim All), waits ~2.5s for the claim "
        "animation, presses A to accept, B back to main_menu; same for Mailbox; "
        "then resumes the normal queue flow. Requires the bot to start on "
        "main_menu. No-op after the first match completes.",
        LockMode::UNLOCK_WHILE_RUNNING,
        false
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
        "/Users/cole/Dev/mimikyu/devtools/test_images/_inbox",
        "/Users/cole/Dev/mimikyu/devtools/test_images/_inbox"
    )
    , AUTO_CAPTURE_MAX_PER_HOUR(
        "<b>Max Captures / Hour:</b><br>"
        "Sliding hourly cap; older captures fall out of the window automatically. "
        "0 = no cap (not recommended).",
        LockMode::UNLOCK_WHILE_RUNNING,
        60
    )
    , AI_SERVER_URL(
        false,
        "<b>AI Inference Server URL (shadow logging):</b><br>"
        "URL of the Python inference server. Empty = disabled. When set and "
        "reachable, the trace fires one POST /decide per turn and logs the "
        "decoded action to the trace event + video overlay. Heuristic still "
        "drives presses unless the model-driven flags below are on. See "
        "plans/decide_endpoint_contract.md.",
        LockMode::UNLOCK_WHILE_RUNNING,
        "http://localhost:8265",
        "http://localhost:8265"
    )
    , ENABLE_MODEL_MOVE_PICK(
        "<b>Enable Model-Driven Move Pick:</b><br>"
        "When on AND a fresh /decide prediction is available, the trace "
        "uses the model's chosen move slot (overrides the random roll). "
        "Choice-lock still wins over the model (lock is a hard mask). "
        "Falls back to random when the model is unavailable.",
        LockMode::UNLOCK_WHILE_RUNNING,
        false
    )
    , ENABLE_MODEL_SWITCH_PICK(
        "<b>Enable Model-Driven Switch Pick:</b><br>"
        "When on AND the latest /decide prediction is a switch action "
        "(switch_0 / switch_1), the trace navigates to that bench slot. "
        "Falls back to random when the model is unavailable.",
        LockMode::UNLOCK_WHILE_RUNNING,
        false
    )
    , ENABLE_MODEL_TEAM_PICK(
        "<b>Enable Model-Driven Team Pick:</b><br>"
        "When on AND the inference server responds to POST /decide-team "
        "at team_preview, the trace overrides LEAD_ORDER_* with the "
        "model's bring + lead picks. Falls back to LEAD_ORDER_* (or "
        "random) when the model is unavailable. "
        "See plans/decide_team_select_contract.md.",
        LockMode::UNLOCK_WHILE_RUNNING,
        false
    )
{
    PA_ADD_OPTION(START_LOCATION);
    PA_ADD_OPTION(BATTLE_MODE_TARGET);
    PA_ADD_OPTION(FORMAT_TARGET);
    PA_ADD_OPTION(TEAM_INDEX);
    PA_ADD_OPTION(LEAD_ORDER_SINGLES);
    PA_ADD_OPTION(LEAD_ORDER_DOUBLES);
    PA_ADD_OPTION(POLL_PERIOD_MILLISECONDS);
    PA_ADD_OPTION(STALE_AFTER_MILLISECONDS);
    PA_ADD_OPTION(SINK_URL);
    PA_ADD_OPTION(ENABLE_AUTO_PRESS);
    PA_ADD_OPTION(ENABLE_AUTO_COLLECT_BEFORE_QUEUE);
    PA_ADD_OPTION(ENABLE_AUTO_CAPTURE);
    PA_ADD_OPTION(AUTO_CAPTURE_DIR);
    PA_ADD_OPTION(AUTO_CAPTURE_MAX_PER_HOUR);
    PA_ADD_OPTION(AI_SERVER_URL);
    PA_ADD_OPTION(ENABLE_MODEL_MOVE_PICK);
    PA_ADD_OPTION(ENABLE_MODEL_SWITCH_PICK);
    PA_ADD_OPTION(ENABLE_MODEL_TEAM_PICK);
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


//  Coerce a (possibly Tesseract-emitted) byte string into valid UTF-8 by
//  replacing any malformed sequences with '?'. nlohmann::json (and our JSON
//  dumper) throws json.exception.type_error.316 on invalid UTF-8, which has
//  killed the whole trace mid-match when the OCR engine spat out a stray
//  high byte (e.g. 0xC? followed by 'p'). Apply to anything OCR-derived
//  before it enters a JsonValue.
static std::string safe_utf8(const std::string& s){
    std::string out;
    out.reserve(s.size());
    size_t i = 0;
    while (i < s.size()){
        unsigned char c = (unsigned char)s[i];
        size_t need;
        uint32_t min_cp;
        if (c < 0x80){ out += (char)c; i++; continue; }
        else if ((c & 0xE0) == 0xC0){ need = 1; min_cp = 0x80; }
        else if ((c & 0xF0) == 0xE0){ need = 2; min_cp = 0x800; }
        else if ((c & 0xF8) == 0xF0){ need = 3; min_cp = 0x10000; }
        else { out += '?'; i++; continue; }

        if (i + need >= s.size()){ out += '?'; i++; continue; }
        uint32_t cp = c & (0x7F >> need);
        bool ok = true;
        for (size_t k = 1; k <= need; k++){
            unsigned char cc = (unsigned char)s[i + k];
            if ((cc & 0xC0) != 0x80){ ok = false; break; }
            cp = (cp << 6) | (cc & 0x3F);
        }
        if (!ok || cp < min_cp || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)){
            out += '?';
            i++;
        }else{
            out.append(s, i, need + 1);
            i += need + 1;
        }
    }
    return out;
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
    add("BattleModeMenuDetector",    "detector", "skipped", "Detects the Battle mode list (Ranked / Casual / Private / Online Comp / Battle Data).");
    add("RankedFormatSelectDetector","detector", "skipped", "Detects the Ranked format selector (Singles vs Doubles).");
    add("CasualFormatSelectDetector","detector", "skipped", "Detects the Casual battles format selector (Single/Double pills). Reports selected_index 0=Singles, 1=Doubles.");
    add("CasualPreMatchDetector",    "detector", "skipped", "Detects the casual pre-match staging screen. Reports selected_index 0=Team Select, 1=Change Music, 2=Begin Matchmaking, -1=on a footer button.");
    add("PreMatchDetector",          "detector", "skipped", "Detects the pre-match staging screen (selected team + Begin Matchmaking / Change Team).");
    add("SearchingForBattleDetector","detector", "skipped", "Detects the matchmaking 'Searching for opponent' screen.");
    add("TeamPreviewCursorReader",   "reader",   "skipped", "On team_preview_selecting, reports which of the 6 own slots the cursor is on (yellow ▶ arrow). -1 if no confident pick.");
    add("ActiveHUDSlotDetector",     "detector", "skipped", "Reads which own slot has the lime-green active outline (doubles).");
    add("TeamSelectDetector",        "detector", "skipped", "Detects the team-select tab strip (the screen before Team Preview where you pick which 4 to bring); also reports selected_tab.");
    add("TeamSelectModalDetector",   "detector", "skipped", "Detects the 4-option popup (Select / Edit / View details / Cancel) that opens on top of team_select when A is pressed on a team. Reports selected_option (0..3).");
    add("TargetSelectDetector",      "detector", "skipped", "Detects the doubles target-select modal: 4 selector strips visible with exactly one in the selected (yellow/green) state. Reports selected_index 0..3 (opp_a/opp_b/own_a/own_b).");
    add("PokemonSwitchDetector",     "detector", "skipped", "Detects the Pokemon switch menu (reached from action_menu's POKEMON button): 6-mon left column + Moves & More center panel + opp right column. Cursor-independent.");
    add("PokemonSwitchReader",       "reader",   "skipped", "On the Pokemon switch menu, reads species + HP fraction for each own slot and HP% for each opp slot. Fills bench HP that the in-battle HUD only shows for active slots. Selected slot detected via yellow highlight.");
    add("CommunicatingDetector",     "detector", "skipped", "Detects the 'syncing with opponent' transitional overlay; co-fires with whatever screen is underneath.");
    add("MovesMoreDetector",         "detector", "skipped", "Detects the 'View Details — Moves & More' tab. Shows species/ability/item/4 moves per slot.");
    add("TeamStatsTabDetector",      "detector", "skipped", "Detects the 'View Details — Stats' tab. Shows 6 stats × {actual, EVs, nature direction} per slot.");

    //  ── Wired readers ──
    add("BattleModeDetector",        "reader", "skipped", "Reads format label: Singles vs Doubles. Refreshed on TeamPreview / matchmaking screens.");
    add("TeamPreviewReader",         "reader", "skipped",
        "Sprite-matches all 6 opp species (CANONICAL for opp side). "
        "Also OCR's own species/items but those are NOT applied to the "
        "tracker as text — instead, the OCR'd own species are used as a "
        "lookup key against the saved-team library to load the matching team.");
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
    add("BattleInfoDetector",        "detector", "skipped",
        "Detects the mid-battle Battle Info tab. Co-evidence: dark-red \"Active Statuses & Effects\" "
        "header strip + pink/purple species panel bg.");
    add("BattleInfoReader",          "reader", "skipped",
        "Reads the focused mon on the Battle Info tab: species, HP (X/Y or %), 2 types via color "
        "classifier, ability + item (own only), 5 main-stat boost stages from multiplier OCR (×1.5 → +1, "
        "×0.67 → -1 etc.), and the first row of Active Statuses & Effects with turn counter. The selected "
        "slot (own/opp × 0/1) is detected by the yellow-bg pill in the L/R icon bar at top.");
    add("TeamPreviewLeadsReader",    "reader", "skipped",
        "Reads the 4 yellow lead-order tags (1-4) on the locked-in team-preview screen. "
        "Per-slot pipeline: yellow->white + invert + flood-fill outside -> Tesseract SINGLE_CHAR -> "
        "normalize 7|/ confusables to 1. Outputs send-out order; feeds BattleStateTracker::set_own_leads.");
    add("OwnTeamLibrary",            "reader", "skipped",
        "File-backed library of scanned teams at <settings>/PokemonChampionsTeams/. Each scan writes "
        "a JSON keyed on the sorted species slugs joined by '_'. Loaded automatically when the team "
        "preview selecting screen reveals the 6 own species — the matching file is consulted to "
        "populate species/ability/item/moves/nature/EVs.");

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
        if (try_det("MoveSelectDetector", det)){
            m_move_select_cursor = det.cursor_slot();  //  -1 if pre-highlight
            JsonObject out;
            out["cursor"] = (int64_t)m_move_select_cursor;
            out["target"] = (int64_t)m_target_move_slot;
            mark("MoveSelectDetector", "ok", std::move(out));
            return "move_select";
        }
    }
    {
        //  Pokemon switch menu — same broad layout as Moves & More (purple
        //  card bg + lime tab) but reached from the action menu's POKEMON
        //  button. Check before action_menu since it's a more specific match.
        PokemonSwitchDetector det;
        if (try_det("PokemonSwitchDetector", det)) return "pokemon_switch";
    }
    {
        ActionMenuDetector det;
        if (try_det("ActionMenuDetector", det)){
            //  0 = FIGHT, 1 = POKEMON. Drives switch-every-3rd-turn nav.
            m_action_menu_cursor = (int)det.cursored();
            JsonObject out;
            out["cursor"] = (int64_t)m_action_menu_cursor;
            mark("ActionMenuDetector", "ok", std::move(out));
            return "action_menu";
        }
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
        if (try_det("PostMatchScreenDetector", det)){
            //  0=Quit, 1=Edit, 2=Continue. Reuse menu_selected_index so the
            //  suggester can nav with Left/Right.
            m_menu_selected_index = (int)det.cursored();
            JsonObject out;
            out["selected_index"] = (int64_t)m_menu_selected_index;
            mark("PostMatchScreenDetector", "ok", std::move(out));
            return "post_match";
        }
    }
    {
        TeamPreviewDetector det;
        if (try_det("TeamPreviewDetector", det)) return "team_preview";
    }
    //  Modal takes precedence over the carousel — the team_select tabs
    //  are still partially visible behind the popup (and TeamSelectDetector
    //  would still fire), but the active input target is the modal.
    //  Co-evidence: also require the carousel cursor (yellow team-tab
    //  marker) to be visible — the modal's pill yellow is ratio-similar
    //  to several non-team_select UI yellows (notably the main_menu
    //  BATTLE button glow), and without this gate the modal detector
    //  false-fires whenever any of its 60 sample boxes happens to land
    //  on a saturated-yellow pixel elsewhere.
    {
        TeamSelectModalDetector modal_det;
        if (modal_det.detect(screen)){
            TeamSelectDetector carousel_det;
            const bool carousel_visible = carousel_det.detect(screen);
            if (carousel_visible){
                const int opt = (int)modal_det.selected_option();
                JsonObject out;
                out["selected_option"] = (int64_t)opt;
                out["carousel_cursor_col"] = (int64_t)carousel_det.selected_team();
                mark("TeamSelectModalDetector", "ok", std::move(out));
                //  Reuse menu_selected_index for the modal cursor.
                m_menu_selected_index = opt;
                //  Modal counts as still being on team_select for stickiness.
                m_team_select_last_seen_ms = now_ms();
                return "team_select_modal";
            }
            mark("TeamSelectModalDetector", "skipped");  //  modal hit but no carousel — ignore
        }else{
            mark("TeamSelectModalDetector", "skipped");
        }
    }
    {
        TeamSelectDetector det;
        if (try_det("TeamSelectDetector", det)){
            //  selected_team() returns the visible cursor column 0..4 in
            //  the carousel — NOT the absolute team index. Treat it as a
            //  cursor column and track absolute team via m_team_select_known_n.
            const int col = (int)det.selected_team();
            const int prev_known = m_team_select_known_n;
            m_menu_selected_index = col;
            //  Edge anchors: col 0 is reachable only on Team 1, col 4 only
            //  on Team 18. When unknown, latch known_n on either edge.
            if (m_team_select_known_n == 0){
                if (col == 0){
                    m_team_select_known_n = 1;
                    m_team_select_known_n_changed_at_ms = now_ms();
                }else if (col == 4){
                    m_team_select_known_n = 18;
                    m_team_select_known_n_changed_at_ms = now_ms();
                }
            }
            //  Throttled log: only on entry / when state changes, so we
            //  don't spam the SP console at 4 Hz while idle on the screen.
            const bool just_entered = (m_prev_screen != "team_select");
            const bool col_changed = (col != m_team_select_logged_col);
            const bool known_changed = (m_team_select_known_n != prev_known);
            if (just_entered || col_changed || known_changed){
                logger.log(
                    "TeamSelectDetector: cursor_col=" + std::to_string(col)
                    + " known_team_n=" + std::to_string(m_team_select_known_n)
                    + (m_team_select_known_n == 0 ? " (homing)" : ""),
                    COLOR_GREEN
                );
                m_team_select_logged_col = col;
            }
            JsonObject out;
            out["selected_tab"] = (int64_t)col;     //  back-compat field name.
            out["cursor_col"]   = (int64_t)col;
            out["known_team_n"] = (int64_t)m_team_select_known_n;
            mark("TeamSelectDetector", "ok", std::move(out));
            m_team_select_last_seen_ms = now_ms();
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
        BattleInfoDetector det;
        if (try_det("BattleInfoDetector", det)) return "battle_info";
    }
    {
        SearchingForBattleDetector det;
        if (try_det("SearchingForBattleDetector", det)) return "searching_for_battle";
    }
    {
        PreMatchDetector det;
        if (try_det("PreMatchDetector", det)){
            m_menu_selected_index = det.selected_index();
            JsonObject out;
            out["selected_index"] = (int64_t)det.selected_index();
            mark("PreMatchDetector", "ok", std::move(out));
            return "pre_match";
        }
    }
    {
        CasualPreMatchDetector det;
        if (try_det("CasualPreMatchDetector", det)){
            m_menu_selected_index = det.selected_index();
            JsonObject out;
            out["selected_index"] = (int64_t)det.selected_index();
            mark("CasualPreMatchDetector", "ok", std::move(out));
            return "casual_pre_match";
        }
    }
    {
        RankedFormatSelectDetector det;
        if (try_det("RankedFormatSelectDetector", det)){
            m_menu_selected_index = det.selected_index();
            JsonObject out;
            out["selected_index"] = (int64_t)det.selected_index();
            mark("RankedFormatSelectDetector", "ok", std::move(out));
            return "ranked_format_select";
        }
    }
    {
        CasualFormatSelectDetector det;
        if (try_det("CasualFormatSelectDetector", det)){
            m_menu_selected_index = det.selected_index();
            JsonObject out;
            out["selected_index"] = (int64_t)det.selected_index();
            mark("CasualFormatSelectDetector", "ok", std::move(out));
            return "casual_format_select";
        }
    }
    {
        BattleModeMenuDetector det;
        if (try_det("BattleModeMenuDetector", det)){
            m_menu_selected_index = det.selected_index();
            JsonObject out;
            out["selected_index"] = (int64_t)det.selected_index();
            mark("BattleModeMenuDetector", "ok", std::move(out));
            return "battle_mode_menu";
        }
    }
    {
        MainMenuDetector det;
        if (try_det("MainMenuDetector", det)){
            m_menu_selected_index = det.selected_index();
            JsonObject out;
            out["selected_index"] = (int64_t)det.selected_index();
            mark("MainMenuDetector", "ok", std::move(out));
            return "main_menu";
        }
    }
    //  match_intro is a cinematic VS-banner with no detector. Infer it:
    //  if we just came from searching_for_battle (or already in match_intro)
    //  and nothing else fires, we're in the cinematic. Anything classifiable
    //  pulls us out (e.g. team_preview_selecting or preparing).
    if (m_prev_screen == "searching_for_battle" || m_prev_screen == "match_intro"){
        return "match_intro";
    }
    //  Auto-collect sub-screens. Missions and Mailbox screens have no
    //  visual detector, but the state machine knows when we MUST be on
    //  them: collect_step == 1 right after pressing A on Missions from
    //  main_menu means the current frame is missions; step == 2 with no
    //  other classifier match means we're still on missions; same
    //  pattern for mailbox at steps 3 / 4. Sticky until main_menu
    //  classifies (B closed the screen).
    if (m_collect_step == 1 || m_collect_step == 2){
        if (m_prev_screen == "main_menu" || m_prev_screen == "missions_screen"){
            return "missions_screen";
        }
    }
    if (m_collect_step == 3 || m_collect_step == 4){
        if (m_prev_screen == "main_menu" || m_prev_screen == "mailbox_screen"){
            return "mailbox_screen";
        }
    }
    //  Mid-turn battle animation. After the player commits a move /
    //  target / switch, the screen leaves action_menu / move_select /
    //  target_select / pokemon_switch and enters a sequence of
    //  animation frames (attack effect, HP drain, faint cinematic,
    //  battle-log text bar). None of those frames have a dedicated
    //  detector. Infer them from the previous screen + match-in-progress
    //  so the live trace and overlay readers can treat them as a
    //  proper state instead of a noisy "unknown". Sticky until the
    //  next detectable screen fires (action_menu when turn resumes,
    //  result_screen when battle ends, etc.).
    if (m_match_in_progress){
        static const std::set<std::string> animation_entrants = {
            "action_menu", "move_select", "target_select",
            "pokemon_switch", "battle_animation",
        };
        if (animation_entrants.count(m_prev_screen)){
            return "battle_animation";
        }
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

    //  When all 6 own species are visible, look up the matching team in
    //  the saved library and load it. Then reorder so internal indexing
    //  matches screen positions (leads + HUD active slot become direct).
    if (own_count == 6){
        std::array<std::string, 6> screen_species;
        for (uint8_t i = 0; i < 6; i++){
            screen_species[i] = result.own[i].species;
        }
        const std::string team_dir = SETTINGS_PATH() + "PokemonChampionsTeams";
        bool matched = m_tracker.load_team_matching(team_dir, screen_species);
        if (matched){
            logger.log(
                "LiveDetectorTrace: matched saved team in library — own state seeded.",
                COLOR_GREEN);
        }
        m_tracker.reorder_own_team_to_screen(screen_species);
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

    //  Cursor read — which of the 6 boxes is currently highlighted on the
    //  selecting variant. -1 means no slot scored above the floor (often
    //  means cursor drifted to the Done button after 4 picks).
    {
        TeamPreviewCursorReader cursor;
        int slot = cursor.read(logger, screen);
        m_tp_cursor_slot = slot;
        //  Nav-loop guard: reset the nav-since-change counter whenever
        //  the cursor moves to a new slot. If the cursor reads stably
        //  at the same slot after several Down presses, the suggester
        //  falls back to A (assume cursor on Done but reader missed it).
        if (slot >= 0 && slot != m_tp_last_cursor_seen){
            m_tp_last_cursor_seen = slot;
            m_tp_nav_since_change = 0;
            m_tp_nav_error_logged = false;
        }
        JsonObject out;
        out["selected_slot"] = (int64_t)slot;
        mark("TeamPreviewCursorReader", slot >= 0 ? "ok" : "error", std::move(out));
    }

    //  Lead-mark digit read — same OCR pipeline as the locked-in screen,
    //  with the selecting-screen badge boxes. Per-slot digit '1'..'4' or 0.
    //
    //  Stickiness: per-slot Tesseract reads on the tiny yellow badges flicker
    //  (a confirmed mark reads blank for 1 poll out of 5 or so), which made
    //  the suggester ping cursor Up/Down at the boundary between "go mark
    //  slot X" and "advance to Done." We latch the digit per slot — once a
    //  fresh read returns 1-4, hold it. Clear the latch only after
    //  TP_MARKS_BLANK_STREAK consecutive blanks (player un-marked) or on
    //  screen exit.
    {
        constexpr uint8_t TP_MARKS_BLANK_STREAK = 5;
        TeamPreviewLeadsReader marks(TeamPreviewLeadsReader::selecting_screen_boxes());
        TeamPreviewLeadsResult res = marks.read(logger, screen);
        for (uint8_t i = 0; i < 6; i++){
            char d = res.digit_per_slot[i];
            if (d >= '1' && d <= '4'){
                m_tp_marks_per_slot[i] = d;        //  fresh confident read — latch
                m_tp_marks_blank_streak[i] = 0;
            }else{
                if (m_tp_marks_blank_streak[i] < 255){
                    m_tp_marks_blank_streak[i]++;
                }
                if (m_tp_marks_blank_streak[i] >= TP_MARKS_BLANK_STREAK){
                    m_tp_marks_per_slot[i] = 0;     //  sustained blank — release
                }
            }
        }
        int marks_count = 0;
        for (char c : m_tp_marks_per_slot){ if (c >= '1' && c <= '4') marks_count++; }
        //  Lead detection: slot tagged '1' is the first active; in doubles,
        //  slot tagged '2' is the second active. (Marks 3 and 4 are bench
        //  reserves for doubles — those aren't on the field at match start.)
        //  Marks are sticky-latched above, so this won't flicker once seen.
        const bool doubles_mode = (m_tracker.mode() == BattleMode::DOUBLES);
        int lead1 = -1;
        int lead2 = -1;
        for (uint8_t i = 0; i < 6; i++){
            if (m_tp_marks_per_slot[i] == '1') lead1 = (int)i;
            if (m_tp_marks_per_slot[i] == '2') lead2 = (int)i;
        }
        if (lead1 >= 0 && m_known_own_active[0] != lead1){
            logger.log(
                "active tracker: lead0 = slot " + std::to_string(lead1)
                + " (from team_preview mark '1')",
                COLOR_CYAN);
            m_known_own_active[0] = lead1;
        }
        if (doubles_mode && lead2 >= 0 && m_known_own_active[1] != lead2){
            logger.log(
                "active tracker: lead1 = slot " + std::to_string(lead2)
                + " (from team_preview mark '2', doubles)",
                COLOR_CYAN);
            m_known_own_active[1] = lead2;
        }
        //  Push latched leads into the tracker so the snapshot reports
        //  correct own_active_slots from poll 1 of preparing/action_menu
        //  instead of the {0, 1} default that waits for a HUD remap.
        //  Singles passes -1 for slot_b (ignored by setter).
        m_tracker.set_own_actives(
            m_known_own_active[0],
            doubles_mode ? m_known_own_active[1] : -1);
        JsonObject out;
        out["marks_count"] = (int64_t)marks_count;
        JsonArray arr;
        for (uint8_t i = 0; i < 6; i++){
            JsonObject r;
            r["slot"] = (int64_t)i;
            //  Latched value used by the suggester.
            r["digit"] = m_tp_marks_per_slot[i]
                ? std::string(1, m_tp_marks_per_slot[i]) : std::string();
            //  Raw per-poll read for flicker visibility.
            r["digit_raw"] = res.digit_per_slot[i]
                ? std::string(1, res.digit_per_slot[i]) : std::string();
            r["blank_streak"] = (int64_t)m_tp_marks_blank_streak[i];
            r["raw"] = res.raw_ocr[i];
            arr.push_back(std::move(r));
        }
        out["slots"] = std::move(arr);
        mark("TeamPreviewSelectingMarks",
             marks_count > 0 ? "ok" : "skipped", std::move(out));
    }
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
        //  One log line per slot — the canonical "what set is this mon
        //  running" dump. Fires only when the signature changes (i.e.
        //  once per distinct team summary read), so it doesn't spam.
        for (uint8_t i = 0; i < 6; i++){
            const auto& t = team[i];
            //  Skip empty slots (read returned nothing).
            if (t.species.empty()
                && t.ability.empty()
                && t.item.empty()
                && t.moves[0].empty()){
                continue;
            }
            std::string moves_csv;
            for (uint8_t m = 0; m < 4; m++){
                if (m > 0) moves_csv += ", ";
                moves_csv += t.moves[m].empty() ? std::string("-") : t.moves[m];
            }
            logger.log(
                "team set: slot " + std::to_string(i)
                + " " + (t.species.empty() ? std::string("?") : t.species)
                + " @ " + (t.item.empty() ? std::string("-") : t.item)
                + " / " + (t.ability.empty() ? std::string("-") : t.ability)
                + " [" + moves_csv + "]",
                COLOR_GREEN);
        }
        //  Persist the merged team to the multi-team library. File is
        //  named after the sorted species slugs so the same set in any
        //  order maps to the same file (overwrites on re-scan).
        const std::string team_dir = SETTINGS_PATH() + "PokemonChampionsTeams";
        std::string saved_path = m_tracker.save_team_to_library(team_dir);
        if (!saved_path.empty()){
            logger.log("LiveDetectorTrace: team saved to " + saved_path, COLOR_GREEN);
        }
        //  Also pin the scanned team to the current TEAM_INDEX slot. The
        //  species-keyed library file above is the canonical store; this
        //  by-index sidecar lets us seed m_own_team at program start (or
        //  when TEAM_INDEX changes) before team_preview ever fires —
        //  which is what makes the dashboard show the team pre-match.
        const int team_idx = (int)TEAM_INDEX.current_value();
        const std::string idx_path =
            team_dir + "/team_index_" + std::to_string(team_idx) + ".json";
        if (m_tracker.save_team_to_file(idx_path)){
            logger.log("LiveDetectorTrace: team also pinned to " + idx_path, COLOR_GREEN);
        }
    }

    JsonObject out;
    JsonArray slot_arr;
    for (uint8_t i = 0; i < 6; i++){
        JsonObject s;
        s["slot"] = (int64_t)i;
        s["species"] = safe_utf8(team[i].species);
        s["ability"] = safe_utf8(team[i].ability);
        s["item"] = safe_utf8(team[i].item);
        JsonArray moves;
        for (uint8_t m = 0; m < 4; m++) moves.push_back(safe_utf8(team[i].moves[m]));
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
        s["nature"] = safe_utf8(team[i].nature_slug);
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
        opp_e.push_back(safe_utf8(r.opp_effectiveness[i]));
        own_e.push_back(safe_utf8(r.own_effectiveness[i]));
        own_m.push_back(safe_utf8(r.own_moves[i]));
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
    TeamCandidates ai_cand = m_tracker.candidates();
    AbilityItemReadout r = reader.read(logger, screen, &ai_cand);
    if (!r.detected){
        //  The reader's detected flag stays false if (a) no text on
        //  either box, or (b) text present but parse couldn't split
        //  "Pokemon's Item". Case (b) is the one that hides ability
        //  reveals from the dashboard — surface the raw OCR text so
        //  we can see what the reader saw and tune the parser.
        if (!r.raw_text.empty()){
            //  Dedup against prior raw so we don't re-fire on every
            //  poll the same partial OCR is visible (~4-8 polls per
            //  ~1-2s reveal animation at 250ms poll period).
            bool fresh_attempt = (r.raw_text != m_prev_ability_item_text);
            m_prev_ability_item_text = r.raw_text;
            JsonObject err;
            err["raw"] = safe_utf8(r.raw_text);
            err["side"] = safe_utf8(r.side);
            err["note"] = std::string("text present but parse failed");
            mark("AbilityItemReader", "error", std::move(err));
            //  Auto-capture so we can build the parser to handle this
            //  text. One screenshot per distinct raw text per session.
            if (fresh_attempt){
                JsonObject meta;
                meta["channel"] = std::string("ability_item_parse_fail");
                meta["raw_text"] = safe_utf8(r.raw_text);
                if (!r.side.empty()) meta["side"] = safe_utf8(r.side);
                maybe_capture(logger, screen,
                    "ability-item-parse-fail",
                    "parse:" + r.raw_text.substr(0, 40),
                    m_seen_ability_items, std::move(meta));
            }
        }else{
            mark_skipped("AbilityItemReader");
        }
        return;
    }
    bool fresh = (r.raw_text != m_prev_ability_item_text);
    m_prev_ability_item_text = r.raw_text;

    JsonObject out;
    out["raw"] = safe_utf8(r.raw_text);
    out["pokemon"] = safe_utf8(r.pokemon);
    out["name"] = safe_utf8(r.name);
    out["kind"] = safe_utf8(r.kind);
    out["side"] = safe_utf8(r.side);
    out["fresh"] = fresh;

    //  Write into tracker on a fresh reveal — only fills empty fields,
    //  so paste-loaded own ability/item is never clobbered. Opp side is
    //  the high-value path; species-slug match selects the slot.
    bool tracker_applied = false;
    if (fresh && !r.name.empty() && !r.pokemon.empty()){
        tracker_applied = m_tracker.apply_ability_item_reveal(
            r.side, r.pokemon, r.name, r.kind);
    }
    out["tracker_applied"] = tracker_applied;

    mark("AbilityItemReader", "ok", std::move(out));

    //  Auto-capture: first occurrence of each (kind, name) per session.
    if (fresh && !r.name.empty()){
        std::string key = r.kind + ":" + r.name;
        JsonObject meta;
        meta["channel"] = std::string("ability_item");
        meta["kind"] = safe_utf8(r.kind);
        meta["name"] = safe_utf8(r.name);
        if (!r.pokemon.empty()) meta["pokemon"] = safe_utf8(r.pokemon);
        if (!r.side.empty())    meta["side"] = safe_utf8(r.side);
        meta["raw_text"] = safe_utf8(r.raw_text);
        maybe_capture(logger, screen,
            "novel-ability-item", key,
            m_seen_ability_items, std::move(meta));
    }
}


void LiveDetectorTrace::run_locked_in_screen(Logger& logger, const ImageViewRGB32& screen){
    TeamPreviewLeadsReader reader;
    TeamPreviewLeadsResult result = reader.read(logger, screen);

    //  Build a signature so we don't re-fire the tracker every poll.
    std::string sig;
    for (uint8_t s : result.leads){ sig += char('0' + s); sig += '|'; }
    bool fresh = (sig != m_prev_leads_sig);
    m_prev_leads_sig = sig;

    JsonArray digits_arr;
    for (uint8_t i = 0; i < 6; i++){
        char d = result.digit_per_slot[i];
        digits_arr.push_back(JsonValue(d ? std::string(1, d) : std::string()));
    }
    JsonArray leads_arr;
    for (uint8_t s : result.leads){
        leads_arr.push_back(JsonValue(static_cast<int64_t>(s)));
    }

    JsonObject out;
    out["digit_per_slot"] = std::move(digits_arr);
    out["leads"] = std::move(leads_arr);
    out["fresh"] = fresh;
    out["lead_count"] = (int64_t)result.leads.size();

    if (fresh && !result.leads.empty()){
        m_tracker.set_own_leads(result.leads);
    }

    mark("TeamPreviewLeadsReader",
         result.leads.empty() ? "error" : "ok",
         std::move(out));
}


void LiveDetectorTrace::run_pokemon_switch_screen(Logger& logger, const ImageViewRGB32& screen){
    PokemonSwitchReader reader(Language::English);
    TeamCandidates sw_cand = m_tracker.candidates();
    PokemonSwitchResult r = reader.read(logger, screen, &sw_cand);

    JsonObject out;
    out["selected_own_slot"] = (int64_t)r.selected_own_slot;

    JsonArray own_arr;
    std::array<std::pair<int, int>, 6> own_hp{};
    for (uint8_t i = 0; i < 6; i++){
        JsonObject row;
        row["slot"] = (int64_t)i;
        row["species"] = r.own[i].species;
        row["hp_current"] = (int64_t)r.own[i].hp_current;
        row["hp_max"] = (int64_t)r.own[i].hp_max;
        own_arr.push_back(JsonValue(std::move(row)));
        own_hp[i] = {r.own[i].hp_current, r.own[i].hp_max};
    }
    out["own"] = std::move(own_arr);

    JsonArray opp_arr;
    std::array<int, 6> opp_pct{};
    for (uint8_t i = 0; i < 6; i++){
        JsonObject row;
        row["slot"] = (int64_t)i;
        row["hp_pct"] = (int64_t)r.opp[i].hp_pct;
        opp_arr.push_back(JsonValue(std::move(row)));
        opp_pct[i] = r.opp[i].hp_pct;
    }
    out["opp"] = std::move(opp_arr);

    m_tracker.apply_switch_screen_hp(own_hp, opp_pct);

    //  Cache for the suggester: cursor + per-slot alive bitmap. A slot
    //  becomes "alive" on a confirmed positive read (hp_max>0 && hp_current>0).
    //  IMPORTANT: a failed read (hp_max<=0) does NOT downgrade alive back
    //  to false — the cursored slot's HP text is obscured by the yellow
    //  highlight every poll the cursor sits on it, so a strict per-poll
    //  rewrite causes the candidate pool to flip between {cursored slot
    //  excluded} and {others excluded} as the cursor moves, oscillating
    //  Down→Up→Down forever. The bitmap is reset on screen exit
    //  (m_switch_alive = {}) so prior switch-screen state never bleeds in.
    m_switch_cursor = r.selected_own_slot;
    for (uint8_t i = 0; i < 6; i++){
        if (r.own[i].hp_max > 0 && r.own[i].hp_current > 0){
            m_switch_alive[i] = true;
        }
    }
    //  Successful cursor read clears the blind-nudge retry state. Subsequent
    //  cursor losses (e.g., a context modal opens) should be treated as a
    //  fresh blind episode, not a continuation.
    if (r.selected_own_slot >= 0){
        m_switch_blind_attempts = 0;
        m_switch_blind_last_press_ms = 0;
        m_switch_blind_error_logged = false;
    }
    //  Nav-loop guard: reset the nav-since-change counter whenever the
    //  cursor moves to a new slot. If the cursor reads stably at the
    //  same slot after several Up/Down presses, the suggester gives up.
    if (r.selected_own_slot >= 0
        && r.selected_own_slot != m_switch_last_cursor_seen){
        m_switch_last_cursor_seen = r.selected_own_slot;
        m_switch_nav_since_change = 0;
        m_switch_nav_error_logged = false;
    }

    mark("PokemonSwitchReader", "ok", std::move(out));
}


void LiveDetectorTrace::run_battle_info_screen(Logger& logger, const ImageViewRGB32& screen){
    BattleInfoReader reader(Language::English);
    BattleInfoResult r = reader.read(logger, screen);

    //  Signature: focus + species + HP + boosts + status text. Skips redundant
    //  tracker writes while sitting on the screen unchanged.
    std::string sig;
    sig += r.focused.valid ? (r.focused.side + std::to_string(r.focused.slot)) : "?";
    sig += "|" + r.species + "|" + std::to_string(r.hp_current) + "/" +
           std::to_string(r.hp_max) + "|" + std::to_string(r.hp_pct);
    for (int8_t b : r.boosts) sig += "," + std::to_string((int)b);
    sig += "|" + r.status_text;
    bool fresh = (sig != m_prev_battle_info_sig);
    m_prev_battle_info_sig = sig;

    JsonObject out;
    JsonObject focus;
    focus["valid"] = r.focused.valid;
    focus["side"] = r.focused.side;
    focus["slot"] = (int64_t)r.focused.slot;
    out["focused"] = std::move(focus);
    out["species"] = r.species;
    out["hp_current"] = (int64_t)r.hp_current;
    out["hp_max"] = (int64_t)r.hp_max;
    out["hp_pct"] = (int64_t)r.hp_pct;
    {
        JsonArray types;
        for (const auto& t : r.types) types.push_back(JsonValue(t));
        out["types"] = std::move(types);
    }
    out["ability"] = r.ability;
    out["item"] = r.item;
    {
        JsonArray boosts;
        for (int8_t b : r.boosts) boosts.push_back(JsonValue((int64_t)b));
        out["boosts"] = std::move(boosts);
    }
    out["status_text"] = r.status_text;
    out["status_turns_current"] = (int64_t)r.status_turns_current;
    out["status_turns_max"] = (int64_t)r.status_turns_max;
    out["fresh"] = fresh;

    //  Tracker write on fresh reads only.
    if (fresh && r.focused.valid){
        m_tracker.apply_battle_info_focused(
            r.focused.side, r.focused.slot,
            r.species,
            r.hp_current, r.hp_max, r.hp_pct,
            r.types, r.ability, r.item,
            r.boosts,
            r.status_text, r.status_turns_current, r.status_turns_max
        );
    }

    mark("BattleInfoReader", r.focused.valid ? "ok" : "error", std::move(out));
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
    out["raw"] = safe_utf8(ev.raw_text);
    out["is_opponent"] = ev.is_opponent;
    out["fresh"] = fresh;
    if (!ev.pokemon.empty()) out["pokemon"] = safe_utf8(ev.pokemon);
    if (!ev.move.empty())    out["move"] = safe_utf8(ev.move);
    if (!ev.stat.empty())    out["stat"] = safe_utf8(ev.stat);
    if (!ev.item.empty())    out["item"] = safe_utf8(ev.item);
    if (!ev.ability.empty()) out["ability"] = safe_utf8(ev.ability);
    if (!ev.effect.empty())  out["effect"] = safe_utf8(ev.effect);
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
        TeamCandidates hud_cand = m_tracker.candidates();
        BattleHUDState hud = reader.read_all(logger, screen, &hud_cand);
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

    //  4 own active moves. Pass the tracker's team-candidate snapshot so
    //  the reader can prefer one of the 4 known moves over a far-off
    //  global match (e.g. "Heatful" -> "Heat Wave"). Resolve the active
    //  mon's own-team slot via leads + active HUD slot when available;
    //  -1 disables team biasing.
    MoveNameReader reader(Language::English);
    TeamCandidates cand = m_tracker.candidates();
    int active_hud = reader.read_active_slot(logger, screen);
    int own_team_slot = -1;
    if (!cand.own_brought_indices.empty()){
        size_t idx = (active_hud >= 0) ? (size_t)active_hud : 0;
        if (idx < cand.own_brought_indices.size()){
            own_team_slot = cand.own_brought_indices[idx];
        }
    }
    MoveSelectionRead res = reader.read_all(logger, screen, &cand, own_team_slot);

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

    //  Cache OCR'd move names so the move_select roll-site overlay log
    //  can show the actual move ("Down -> Moonblast") instead of just a
    //  slot index.
    for (size_t i = 0; i < 4; i++){
        m_move_select_moves[i] = (i < res.moves.size()) ? res.moves[i] : std::string{};
    }

    JsonObject out;
    JsonArray arr;
    for (size_t i = 0; i < res.moves.size(); i++){
        arr.push_back(res.moves[i]);
    }
    out["moves"] = std::move(arr);
    out["active_slot"] = (int64_t)res.active_slot;
    mark("MoveNameReader", n > 0 ? "ok" : "error", std::move(out));

    //  Mega Evolve toggle visibility. Stash on the trace so the suggester
    //  (which runs after this in the poll loop) can decide to fire R.
    {
        MegaEvolveDetector mega;
        bool can_mega = mega.detect(screen);
        m_can_mega_evolve = can_mega;
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

    //  Live tactical snapshot — the same struct the suggester sees this
    //  poll. Surfaced on the event so the dashboard can render active
    //  slots, alive bitmaps, and field state without re-deriving from
    //  the engine_view payload.
    {
        BattleSnapshot sit = m_tracker.snapshot();
        JsonObject sj;
        JsonArray own_act, opp_act;
        own_act.push_back((int64_t)sit.own_active_slots[0]);
        own_act.push_back((int64_t)sit.own_active_slots[1]);
        opp_act.push_back((int64_t)sit.opp_active_slots[0]);
        opp_act.push_back((int64_t)sit.opp_active_slots[1]);
        sj["own_active_slots"] = std::move(own_act);
        sj["opp_active_slots"] = std::move(opp_act);
        JsonArray own_alive, opp_alive;
        for (uint8_t i = 0; i < 6; i++){
            own_alive.push_back(sit.own_alive[i]);
            opp_alive.push_back(sit.opp_alive[i]);
        }
        sj["own_alive"] = std::move(own_alive);
        sj["opp_alive"] = std::move(opp_alive);
        sj["weather"] = sit.weather;
        sj["terrain"] = sit.terrain;
        sj["trick_room"] = sit.trick_room;
        sj["tailwind_own"] = sit.tailwind_own;
        sj["tailwind_opp"] = sit.tailwind_opp;
        JsonArray scr_own, scr_opp;
        for (bool b : sit.screens_own) scr_own.push_back(b);
        for (bool b : sit.screens_opp) scr_opp.push_back(b);
        sj["screens_own"] = std::move(scr_own);
        sj["screens_opp"] = std::move(scr_opp);
        sj["turn"] = (int64_t)sit.turn;
        sj["mode"] = std::string(battle_mode_str(sit.mode));
        ev["snapshot"] = std::move(sj);
    }

    if (m_last_suggestion){
        JsonObject s;
        s["button"] = m_last_suggestion->button;
        s["label"] = m_last_suggestion->label;
        s["reason"] = m_last_suggestion->reason;
        JsonArray boxes;
        for (const ImageFloatBox& b : m_last_suggestion->highlights){
            JsonObject bj;
            bj["x"] = b.x;
            bj["y"] = b.y;
            bj["width"] = b.width;
            bj["height"] = b.height;
            boxes.push_back(std::move(bj));
        }
        s["highlights"] = std::move(boxes);
        ev["suggested_input"] = std::move(s);
    }

    return ev;
}


// ─── Main loop ──────────────────────────────────────────────────────────────

void LiveDetectorTrace::program(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    std::string sink_url = SINK_URL;
    env.console.log("LiveDetectorTrace: starting. Sink = " + sink_url, COLOR_BLUE);

    //  Pair virtual controller via grip menu if requested. Required when a
    //  physical controller is or was paired with the console — otherwise
    //  auto-press writes are silently dropped.
    if (START_LOCATION.start_in_grip_menu()){
        env.console.log("LiveDetectorTrace: grip-menu pairing dance.", COLOR_BLUE);
        grip_menu_connect_go_home(context);
        //  grip_menu_connect_go_home leaves us at the Switch Home screen.
        //  Press Home again to resume the most-recent app (Pokemon Champions).
        env.console.log("LiveDetectorTrace: resuming game from Home.", COLOR_BLUE);
        resume_game_from_home(env.console, context);
    }

    init_pipeline_registry();
    m_tracker.reset();
    //  Pre-seed m_own_team from the by-index sidecar (written by the team
    //  scan). Without this, the dashboard's engine-view panel is empty
    //  until the first team_preview of a match — even though the team is
    //  sitting on disk. With this, the panel shows the saved team
    //  immediately at program start.
    {
        const std::string team_dir = SETTINGS_PATH() + "PokemonChampionsTeams";
        const int team_idx = (int)TEAM_INDEX.current_value();
        const std::string idx_path =
            team_dir + "/team_index_" + std::to_string(team_idx) + ".json";
        if (m_tracker.load_team_from_file(idx_path)){
            env.console.log(
                "LiveDetectorTrace: pre-seeded own team from " + idx_path,
                COLOR_GREEN);
        }
    }
    m_prev_screen.clear();
    m_prev_log_text.clear();
    m_prev_ability_item_text.clear();
    m_prev_team_summary_sig.clear();
    m_prev_team_stats_sig.clear();
    m_prev_leads_sig.clear();
    m_prev_battle_info_sig.clear();
    m_match_in_progress = false;
    m_random_lead_order_rolled = false;
    //  Auto-collect: arm the sub-flow if the option is on. Becomes 0
    //  (DONE) once the mailbox sequence completes — or if the option
    //  is off, never fires.
    m_collect_step = ENABLE_AUTO_COLLECT_BEFORE_QUEUE ? 1 : 0;
    m_collect_x_fired_at_ms = 0;
    m_collect_a_fired = false;
    m_seen_log_event_types.clear();
    m_seen_opp_species.clear();
    m_seen_ability_items.clear();
    m_captured_screen_entries.clear();
    m_capture_window_ms.clear();
    uint64_t seq = 0;

    //  Live overlay for the currently-suggested button. Re-populated each
    //  poll; cleared automatically when the program ends.
    VideoOverlaySet suggestion_overlay(env.console.overlay());

    //  ── Inference client (M1 shadow) ──
    //  Health-check once at program entry. On failure we run unchanged,
    //  just without the model logs. URL is unlocked-while-running so the
    //  user can re-enable mid-session by editing the option + restarting.
    m_inference_client.reset();
    m_last_decision = DecideResult{};
    m_decision_for_visit = -1;
    m_decide_pending_visit = -1;
    {
        const std::string url = AI_SERVER_URL;
        if (!url.empty()){
            m_inference_client = std::make_unique<InferenceClient>(url);
            if (!m_inference_client->health_check(env.console)){
                env.console.log(
                    "AI server not reachable at " + url + ". "
                    "Shadow logging disabled this session.",
                    COLOR_RED);
                m_inference_client.reset();
            }else{
                env.console.log(
                    "AI server connected at " + url + ". "
                    "Shadow logging enabled — model decisions will be logged each turn.",
                    COLOR_GREEN);
            }
        }
    }

    //  Persistent screen-label overlay — shows the trace's current screen
    //  classification in the top-left of the video. Replaced on every
    //  screen transition; cleared automatically on program exit.
    std::unique_ptr<OverlayTextScope> screen_label;

    //  Own team is no longer seeded at program start. The library at
    //  <settings>/PokemonChampionsTeams/<sorted-slugs>.json is consulted
    //  on every team-preview-selecting screen — when all 6 own species are
    //  visible we look up the matching file and load it. Run a Moves &
    //  More scan in-game to populate the library.

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

        //  Stickiness: if classify dropped to "unknown" but we were on
        //  team_select within the last ~1500ms, hold the classification.
        //  The cursor markers briefly fail to read yellow during nav/A
        //  animations and modal transitions; without this, a single
        //  blip flips the screen to "unknown", scan-step branches gate
        //  out, and the recovery-B watchdog eventually backs us out of
        //  team_select entirely. The window is shorter than the modal-
        //  to-info-screen latency, so genuine exits still fall through
        //  cleanly once the new screen's detector fires.
        if (screen == "unknown" && m_team_select_last_seen_ms > 0
            && now_ms() - m_team_select_last_seen_ms < 1500){
            //  If we were on the modal recently, hold that — otherwise
            //  hold the carousel. Conservative: prefer the modal tag
            //  when in doubt, since the modal layer is the active
            //  input target when both are visible.
            screen = (m_prev_screen == "team_select_modal")
                     ? "team_select_modal" : "team_select";
        }

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

        //  Mid-battle recovery: if the very first poll after program
        //  start lands on an in-battle screen, we missed the
        //  team_preview match-start transition that normally sets
        //  m_match_in_progress + m_mode. Without this, the match-end
        //  transition (post_match / result_screen) wouldn't surface
        //  any cleanup because m_match_in_progress is still false.
        //
        //  One-shot gate — m_prev_screen is empty only on the very
        //  first poll after program() entry (assigned at end of every
        //  poll, line ~2542), so this block can NEVER fire during the
        //  normal flow. Strictly additive: marks match-in-progress and
        //  seeds the mode from FORMAT_TARGET. Own team is already
        //  loaded from team_index_<N>.json at program start; opp team
        //  will fill in as run_battle_screen's HUD reader sees them.
        if (m_prev_screen.empty() && !m_match_in_progress){
            static const std::set<std::string> in_battle = {
                "action_menu", "move_select", "target_select",
                "pokemon_switch", "preparing", "battle_info",
            };
            if (in_battle.count(screen)){
                BattleMode bm = ((int)FORMAT_TARGET.current_value() == 1)
                    ? BattleMode::DOUBLES : BattleMode::SINGLES;
                env.console.log(
                    "LiveDetectorTrace: mid-battle resume on '" + screen
                    + "'. Seeding match-in-progress + mode="
                    + std::string(battle_mode_str(bm))
                    + " from FORMAT_TARGET; opp team fills in as HUD reads.",
                    COLOR_BLUE);
                m_match_in_progress = true;
                m_mode = bm;
                m_tracker.set_mode(bm);
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
            //  Re-seed own team from the by-index sidecar after the
            //  match-start reset. The species-keyed library load that
            //  happens later (when team_preview reads 6 species) will
            //  overwrite this — but having it here keeps the dashboard
            //  showing the team during the gap.
            {
                const std::string team_dir = SETTINGS_PATH() + "PokemonChampionsTeams";
                const int team_idx = (int)TEAM_INDEX.current_value();
                const std::string idx_path =
                    team_dir + "/team_index_" + std::to_string(team_idx) + ".json";
                m_tracker.load_team_from_file(idx_path);
            }
            m_prev_log_text.clear();
            m_prev_ability_item_text.clear();
    m_prev_team_summary_sig.clear();
    m_prev_team_stats_sig.clear();
    m_prev_leads_sig.clear();
    m_prev_battle_info_sig.clear();
            //  Per-match dedup — re-arm screen-entry captures so we get a
            //  fresh target_select / team_select snapshot on each new match.
            //  Other seen sets are session-scoped and survive matches.
            m_captured_screen_entries.clear();
            //  Don't re-seed here — selecting-screen handler matches against
            //  the team library when own species become visible.
            m_match_in_progress = true;
            //  Reset the in-battle action counter so the 2-fight + 1-switch
            //  cycle starts fresh on every match.
            m_battle_action_menu_visits = 0;
            m_move_slot_rolled_for = -1;
            m_switch_rolled_for = -1;
            m_mega_toggled_for_visit = -1;
            //  Active tracker resets at match start. Re-seeded from the
            //  team_preview '1' mark (and '2' in doubles) once selecting
            //  begins.
            m_known_own_active = {-1, -1};
            //  Force re-roll of the random lead order for the next
            //  team-preview-selecting phase, so each match gets a fresh
            //  pick when no explicit LEAD_ORDER is configured.
            m_random_lead_order_rolled = false;
            //  M4: reset the per-match team-decision cache so the next
            //  match fires a fresh /decide-team.
            m_team_decision_fired = false;
            m_last_team_decision = DecideTeamResult{};
        }
        if (screen == "post_match" || screen == "result_screen"){
            m_match_in_progress = false;
            //  Cancel any in-flight scan step (defensive — shouldn't be
            //  active here), but DO NOT reset m_team_scan_complete: the
            //  selected team persists between matches in the same loop, so
            //  one scan covers the whole session. To re-scan (e.g. after
            //  editing a team), restart the program.
            m_team_scan_step = -1;
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
            //  "preparing" is also the locked-in team-preview screen — leads
            //  reader runs alongside the battle pipeline (cheap when leads
            //  are stable: signature dedup skips the tracker write).
            if (screen == "preparing"){
                run_locked_in_screen(env.console, snapshot);
            }
        }else if (screen == "target_select"){
            run_target_select_screen(env.console, snapshot);
        }else if (screen == "moves_and_more"){
            run_moves_and_more_screen(env.console, snapshot);
        }else if (screen == "team_stats"){
            run_team_stats_screen(env.console, snapshot);
        }else if (screen == "battle_info"){
            run_battle_info_screen(env.console, snapshot);
        }else if (screen == "pokemon_switch"){
            run_pokemon_switch_screen(env.console, snapshot);
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

        //  Cross-cutting overlay readers. The ability/item reveal popup
        //  and battle-log text bar can appear on top of *any* in-battle
        //  screen — target_select, pokemon_switch, battle_info — not
        //  just the screens that funnel through run_battle_screen.
        //  Before this catch-all, items revealed during a forced switch
        //  or while the doubles target-pick modal was open went unseen.
        //  Both readers self-gate, so this is a cheap no-op when no
        //  overlay is visible. Skipped on screens that already ran
        //  them above (avoid double-firing per poll).
        if (m_match_in_progress){
            static const std::set<std::string> already_ran_overlays = {
                "move_select", "action_menu", "preparing", "unknown",
            };
            if (!already_ran_overlays.count(screen)){
                run_battle_log_reader(env.console, snapshot);
                run_ability_item_reader(env.console, snapshot);
            }
        }
        //  result_screen / post_match / main_menu / unknown (out of match) —
        //  no readers fire, but pipeline status still reports the screen
        //  detector hit.

        age_pipeline_entries(now_ms());

        //  Compute "what I'd press" for the current screen + state, render
        //  to the SP overlay, and stash for build_event() to emit on the
        //  dashboard.
        LiveContext sctx;
        sctx.tp_cursor_slot = m_tp_cursor_slot;
        sctx.tp_marks_per_slot = m_tp_marks_per_slot;
        sctx.tp_nav_since_change = m_tp_nav_since_change;

        //  ── M4: /decide-team shadow + driver ──
        //  Fire once per match the first time both rosters are visible.
        //  team_preview / team_preview_selecting screens carry the 12
        //  species via TeamPreviewReader's tracker writes. Empty bench
        //  slots (Champions: always 6 own + 6 opp) means the read isn't
        //  ready yet — wait another poll.
        if (m_inference_client
            && !m_team_decision_fired
            && (screen == "team_preview" || screen == "team_preview_selecting")){
            TeamCandidates tc = m_tracker.candidates();
            //  Need all 6 own species and at least 6 opp species (Champions
            //  always reveals 6 at team_preview).
            bool ready = tc.own_species.size() >= 6 && tc.opp_species.size() >= 6;
            for (size_t i = 0; ready && i < 6; i++){
                if (tc.own_species[i].empty() || tc.opp_species[i].empty()){
                    ready = false;
                }
            }
            if (ready){
                JsonObject teams;
                JsonArray own_arr;
                JsonArray opp_arr;
                for (size_t i = 0; i < 6; i++){
                    own_arr.push_back(JsonValue(tc.own_species[i]));
                    opp_arr.push_back(JsonValue(tc.opp_species[i]));
                }
                teams["own_team"] = JsonValue(std::move(own_arr));
                teams["opp_team"] = JsonValue(std::move(opp_arr));
                teams["format"] = JsonValue(((int)FORMAT_TARGET.current_value() == 1)
                    ? std::string("doubles") : std::string("singles"));
                teams["regulation"] = JsonValue(std::string("M-A"));

                DecideTeamResult tr = m_inference_client->decide_team(env.console, teams);
                m_team_decision_fired = true;
                if (tr.success){
                    m_last_team_decision = tr;
                    std::string brought;
                    for (int k = 0; k < 4; k++){
                        if (k > 0) brought += ", ";
                        int idx = tr.bring[k];
                        brought += (idx >= 0 && idx < 6 && !tc.own_species[idx].empty())
                            ? tc.own_species[idx]
                            : ("slot" + std::to_string(idx));
                    }
                    std::string leads;
                    for (int k = 0; k < 2; k++){
                        if (k > 0) leads += ", ";
                        int li = tr.lead[k];
                        int team_idx = (li >= 0 && li < 4) ? (int)tr.bring[li] : -1;
                        leads += (team_idx >= 0 && team_idx < 6
                                  && !tc.own_species[team_idx].empty())
                            ? tc.own_species[team_idx]
                            : ("?" + std::to_string(li));
                    }
                    env.console.log(
                        "model team: bring=[" + brought + "] lead=[" + leads + "]"
                        + (tr.model_version.empty() ? std::string()
                           : (" v=" + tr.model_version + "/" + tr.endpoint_impl)),
                        COLOR_CYAN);
                    env.console.overlay().add_log(
                        "team: " + brought + " | leads: " + leads,
                        COLOR_CYAN);
                }else{
                    env.console.log(
                        "/decide-team failed (server unreachable or parse error)",
                        COLOR_ORANGE);
                }
            }
        }

        //  Parse the configured lead order. Singles uses 3 entries,
        //  doubles uses 4 — pick the right StringOption based on
        //  FORMAT_TARGET (0=Singles, 1=Doubles). Entries outside 0..5
        //  or missing become -1 sentinels.
        //
        //  Blank / fully-invalid config falls back to a random
        //  permutation rolled once per match (gated by
        //  m_random_lead_order_rolled; reset at match-start).
        {
            const bool is_doubles = ((int)FORMAT_TARGET.current_value() == 1);
            sctx.tp_lead_needed = is_doubles ? 4 : 3;
            std::array<int, 4> order = {-1, -1, -1, -1};
            const std::string raw = is_doubles
                ? (std::string)LEAD_ORDER_DOUBLES
                : (std::string)LEAD_ORDER_SINGLES;
            int p = 0;
            int cur = -1;
            int valid = 0;
            //  User-facing input is 1-indexed (slot numbers 1..6 to match
            //  the on-screen card order). Convert to internal 0-indexed
            //  here; everything downstream (team_preview marks, suggester,
            //  active tracker) uses 0..5.
            auto commit = [&](){
                if (p < sctx.tp_lead_needed && cur >= 1 && cur <= 6){
                    order[p] = cur - 1;
                    valid++;
                }
                if (cur >= 0) p++;
                cur = -1;
            };
            for (char c : raw){
                if (c >= '0' && c <= '9'){
                    cur = (cur < 0 ? 0 : cur * 10) + (c - '0');
                }else if (cur >= 0){
                    commit();
                }
            }
            commit();
            //  M4 driver: model overrides LEAD_ORDER_* entirely when on.
            //  bring[] from /decide-team is already in send-out order;
            //  drop into tp_lead_order[0..3]. Singles uses the first 3.
            //  Falls back to LEAD_ORDER_* / random if the call hasn't
            //  succeeded.
            if (ENABLE_MODEL_TEAM_PICK && m_last_team_decision.success){
                for (int k = 0; k < sctx.tp_lead_needed; k++){
                    order[k] = m_last_team_decision.bring[k];
                }
                valid = sctx.tp_lead_needed;   // suppresses the random fallback
            }

            if (valid == 0){
                //  No explicit config — use the random fallback. Roll
                //  once per match (gated by m_random_lead_order_rolled).
                if (!m_random_lead_order_rolled){
                    std::array<int, 6> all = {0, 1, 2, 3, 4, 5};
                    //  Fisher-Yates using wall-clock as seed source.
                    uint64_t s = (uint64_t)now_ms();
                    for (int i = 5; i > 0; i--){
                        s = s * 6364136223846793005ULL + 1442695040888963407ULL;
                        int j = (int)((s >> 33) % (uint64_t)(i + 1));
                        std::swap(all[i], all[j]);
                    }
                    for (int k = 0; k < 4; k++){
                        m_random_lead_order[k] = (k < (int)all.size()) ? all[k] : -1;
                    }
                    m_random_lead_order_rolled = true;
                    //  Log in user-facing 1-indexed form to match the
                    //  Lead Order option's input format.
                    env.console.log(
                        std::string("lead-order: rolled random ")
                        + std::to_string(m_random_lead_order[0] + 1) + ","
                        + std::to_string(m_random_lead_order[1] + 1) + ","
                        + std::to_string(m_random_lead_order[2] + 1) + ","
                        + std::to_string(m_random_lead_order[3] + 1)
                        + " (1-indexed)",
                        COLOR_BLUE);
                }
                for (int k = 0; k < sctx.tp_lead_needed; k++){
                    order[k] = m_random_lead_order[k];
                }
            }
            sctx.tp_lead_order = order;
        }
        sctx.menu_selected_index = m_menu_selected_index;
        sctx.switch_cursor = m_switch_cursor;
        sctx.switch_alive = m_switch_alive;
        sctx.format_target = (int)FORMAT_TARGET.current_value();
        sctx.battle_mode_target = (int)BATTLE_MODE_TARGET.current_value();
        sctx.team_index_target = (int)TEAM_INDEX.current_value();
        //  Re-arm the scan flow if the user changed the target mid-run.
        //  Without this, team_scan_complete remains true from a prior
        //  match and the pre_match suggester goes straight to "Begin
        //  Matchmaking" — queueing the previously-selected team rather
        //  than the new one. Don't fire on the first poll (sentinel = -1).
        if (m_team_index_last_seen >= 0
            && m_team_index_last_seen != sctx.team_index_target){
            env.console.log(
                "TEAM_INDEX changed (" + std::to_string(m_team_index_last_seen)
                + " -> " + std::to_string(sctx.team_index_target)
                + ") — re-arming team scan + clearing known team.",
                COLOR_PURPLE);
            m_team_scan_complete = false;
            m_team_scan_step = -1;
            m_team_select_known_n = 0;
            //  Re-seed own team from the new index's by-index sidecar so
            //  the dashboard reflects what we'll actually play. Falls
            //  through silently if the new team hasn't been scanned yet.
            const std::string team_dir = SETTINGS_PATH() + "PokemonChampionsTeams";
            const std::string idx_path =
                team_dir + "/team_index_" + std::to_string(sctx.team_index_target) + ".json";
            if (m_tracker.load_team_from_file(idx_path)){
                env.console.log(
                    "LiveDetectorTrace: re-seeded own team from " + idx_path,
                    COLOR_GREEN);
            }
        }
        m_team_index_last_seen = sctx.team_index_target;
        sctx.team_select_known_n = m_team_select_known_n;
        sctx.team_select_cursor_col =
            (screen == "team_select") ? m_menu_selected_index : -1;
        sctx.team_select_settle_ok =
            (m_team_select_known_n_changed_at_ms == 0)
            || (now_ms() - m_team_select_known_n_changed_at_ms >= 400);
        sctx.battle_action_menu_visits = m_battle_action_menu_visits;
        sctx.action_menu_cursor = m_action_menu_cursor;
        sctx.move_select_cursor = m_move_select_cursor;
        sctx.target_move_slot = m_target_move_slot;
        sctx.can_mega_evolve = m_can_mega_evolve;
        sctx.mega_toggled_this_turn =
            (m_mega_toggled_for_visit == m_battle_action_menu_visits);
        sctx.switch_target_slot = m_switch_target_slot;
        sctx.switch_blind_attempts = m_switch_blind_attempts;
        sctx.switch_blind_last_press_ms = m_switch_blind_last_press_ms;
        sctx.switch_nav_since_change = m_switch_nav_since_change;
        sctx.switch_nav_total = m_switch_nav_total;
        sctx.collect_step = m_collect_step;
        sctx.collect_x_fired_at_ms = m_collect_x_fired_at_ms;
        sctx.collect_a_fired = m_collect_a_fired;
        sctx.now_ms = (int64_t)now_ms();
        //  Live tactical snapshot — the canonical source for active-slot
        //  indices, alive bitmaps, and field state. Lives on this poll's
        //  stack frame; the LiveContext borrows it for the duration of
        //  suggest_for_screen. Legacy own_active_slots[2] kept in sync
        //  for any consumer that hasn't migrated to the snapshot pointer.
        BattleSnapshot poll_snapshot = m_tracker.snapshot();
        sctx.snapshot = &poll_snapshot;
        sctx.own_active_slots = poll_snapshot.own_active_slots;

        //  Initialize team-scan sub-flow on first sight of team_select with
        //  the carousel landed on the target team. Stays inactive (-1)
        //  afterwards until match-end resets m_team_scan_complete.
        //  Settle gate: known_n is updated optimistically the moment a
        //  Right/Left press fires, but the press takes ~340ms to land on
        //  the Switch — without this gate the next poll racing the press
        //  would open a modal on the wrong team.
        if (screen == "team_select"
            && m_team_select_known_n > 0
            && m_team_select_known_n - 1 == sctx.team_index_target
            && m_team_scan_step < 0
            && !m_team_scan_complete
            && now_ms() - m_team_select_known_n_changed_at_ms >= 400){
            m_team_scan_step = 0;
            env.console.log("LiveDetectorTrace: starting team-scan sub-flow.", COLOR_PURPLE);
        }
        sctx.team_scan_step = m_team_scan_step;
        sctx.team_scan_complete = m_team_scan_complete;
        m_last_suggestion = suggest_for_screen(screen, m_tracker, sctx);
        //  Bounded retry on pokemon_switch with no yellow highlight: after
        //  3 blind Down nudges the suggester gives up (returns nullopt).
        //  Log a single error so the dashboard surfaces "we're stuck on
        //  pokemon_switch with no readable cursor".
        if (screen == "pokemon_switch" && m_switch_cursor < 0
            && m_switch_blind_attempts >= 3
            && !m_switch_blind_error_logged){
            env.console.log(
                "ERROR: pokemon_switch — no yellow highlight after 3 Down "
                "nudges; cursor unreadable. Giving up auto-press until the "
                "screen changes.",
                COLOR_RED);
            m_switch_blind_error_logged = true;
        }
        //  Nav-loop guard: cursor reads but isn't moving despite repeated
        //  Up/Down presses. Likely cause: forced-switch screen layout
        //  mismatch (singles 3-row vs reader's 4-row tuning), so the
        //  cursor's reported slot is stale and never reaches our target.
        if (screen == "pokemon_switch" && m_switch_cursor >= 0
            && m_switch_nav_since_change >= 5
            && !m_switch_nav_error_logged){
            env.console.log(
                "ERROR: pokemon_switch — cursor stuck at slot "
                + std::to_string(m_switch_cursor)
                + " after 5 nav presses. Reader/layout mismatch likely."
                  " Giving up auto-press until cursor moves or screen exits.",
                COLOR_RED);
            m_switch_nav_error_logged = true;
        }
        //  Visibility for the team_select flow: log the chosen suggestion
        //  whenever it changes (or first time we see it on this screen).
        //  Helps debug "auto-press isn't doing anything" — if no suggestion
        //  is chosen the detector probably isn't firing at all.
        if (screen == "team_select"){
            const std::string sug = m_last_suggestion
                ? (m_last_suggestion->button + " — " + m_last_suggestion->reason)
                : std::string("(no suggestion)");
            if (sug != m_team_select_logged_suggestion){
                env.console.log("team_select suggestion: " + sug, COLOR_PURPLE);
                m_team_select_logged_suggestion = sug;
            }
        }else{
            m_team_select_logged_suggestion.clear();
        }
        suggestion_overlay.clear();
        if (m_last_suggestion){
            for (const ImageFloatBox& box : m_last_suggestion->highlights){
                suggestion_overlay.add(m_last_suggestion->color, box, m_last_suggestion->label);
            }
        }

        //  Track screen-change time for the watchdog log.
        if (screen != m_prev_screen){
            m_last_screen_change_ms = now_ms();
            //  Refresh the persistent screen label on the video overlay.
            //  Reset the unique_ptr first so the old OverlayTextScope's
            //  destructor removes the previous text before we add the new.
            screen_label.reset();
            screen_label = std::make_unique<OverlayTextScope>(
                env.console.overlay(),
                COLOR_CYAN,
                std::string("screen: ") + screen,
                0.01, 0.03, 3.0
            );
            env.console.log(
                "screen: " + (m_prev_screen.empty() ? std::string("(none)") : m_prev_screen)
                + " -> " + screen,
                COLOR_BLUE);
            //  Reset press dedup on every transition so the next screen's
            //  first suggestion fires immediately.
            m_last_pressed_screen.clear();
            m_last_pressed_button.clear();
            //  Clear team_preview state on leave (stale cursor / marks
            //  shouldn't leak into the next entry).
            if (m_prev_screen == "team_preview" && screen != "team_preview"){
                m_tp_cursor_slot = -1;
                m_tp_marks_per_slot = {};
                m_tp_marks_blank_streak = {};
                m_tp_last_cursor_seen = -2;
                m_tp_nav_since_change = 0;
                m_tp_nav_error_logged = false;
            }
            if (m_prev_screen == "pokemon_switch" && screen != "pokemon_switch"){
                m_switch_cursor = -1;
                m_switch_alive = {};
                m_switch_blind_attempts = 0;
                m_switch_blind_last_press_ms = 0;
                m_switch_blind_error_logged = false;
                m_switch_last_cursor_seen = -2;
                m_switch_nav_since_change = 0;
                m_switch_nav_total = 0;
                m_switch_nav_error_logged = false;
            }
            //  Auto-collect state-machine transitions. The sub-screens
            //  (missions, mailbox) classify as "unknown" — we don't need
            //  to detect them specifically. The transitions are:
            //
            //    Step 1 (GO_MISSIONS) -> 2 (AT_MISSIONS): we just left
            //      main_menu after pressing A on Missions, so we're
            //      now on the missions screen by construction.
            //    Step 2 -> 3 (GO_MAILBOX): we're back on main_menu (B
            //      closed the missions screen).
            //    Step 3 -> 4 (AT_MAILBOX): same pattern as 1->2.
            //    Step 4 -> 0 (DONE): back on main_menu, all collected.
            if (m_collect_step == 1 && m_prev_screen == "main_menu"
                && screen != "main_menu"){
                m_collect_step = 2;
                m_collect_x_fired_at_ms = 0;
                m_collect_a_fired = false;
                env.console.log(
                    "auto-collect: opened missions; running X/A/B sequence.",
                    COLOR_BLUE);
            }
            else if (m_collect_step == 2 && screen == "main_menu"
                     && m_prev_screen != "main_menu"){
                m_collect_step = 3;
                m_collect_x_fired_at_ms = 0;
                m_collect_a_fired = false;
                env.console.log(
                    "auto-collect: missions done; navigating to mailbox.",
                    COLOR_BLUE);
            }
            else if (m_collect_step == 3 && m_prev_screen == "main_menu"
                     && screen != "main_menu"){
                m_collect_step = 4;
                m_collect_x_fired_at_ms = 0;
                m_collect_a_fired = false;
                env.console.log(
                    "auto-collect: opened mailbox; running X/A/B sequence.",
                    COLOR_BLUE);
            }
            else if (m_collect_step == 4 && screen == "main_menu"
                     && m_prev_screen != "main_menu"){
                m_collect_step = 0;
                env.console.log(
                    "auto-collect: complete. Resuming normal queue flow.",
                    COLOR_GREEN);
            }
            //  In-battle action counter: bump on every fresh entry to
            //  action_menu, so the suggester knows whether it's a fight
            //  turn (visits=1,2,4,5,...) or a switch turn (visits=3,6,9...).
            if (screen == "action_menu" && m_prev_screen != "action_menu"){
                m_battle_action_menu_visits++;
                env.console.log(
                    "in-battle: action_menu visit #"
                    + std::to_string(m_battle_action_menu_visits)
                    + ((m_battle_action_menu_visits > 0
                        && m_battle_action_menu_visits % 3 == 0)
                        ? " (SWITCH turn)" : " (fight turn)"),
                    COLOR_BLUE);
                //  Turn-boundary snapshot for the model's LSTM history
                //  feature. Push after every re-entry past the first —
                //  the first action_menu entry is turn 1's decision
                //  point with no prior turn to record. Subsequent
                //  entries capture whatever state followed the prior
                //  action; the tracker handles the K-window cap.
                if (m_battle_action_menu_visits > 1){
                    m_tracker.push_history_snapshot();
                }
                //  M1 shadow: arm a /decide call for the new turn. The
                //  actual POST happens 1 poll later so HUD reads can
                //  settle before we snapshot to_predict_json().
                if (m_inference_client){
                    m_decide_pending_visit = m_battle_action_menu_visits;
                    m_decide_polls_waited = 0;
                }
            }
            //  Roll a random move slot once per move_select visit. Tied
            //  to m_battle_action_menu_visits so each turn gets one
            //  fresh roll, but a re-entry within the same turn (e.g.
            //  unknown blip + re-detect) sticks with the same target.
            //
            //  Roll defers until the cursor reads — otherwise we'd roll
            //  on the first move_select poll (cursor still -1 from
            //  animation), the suggester would wait, and once the
            //  cursor renders we'd potentially have rolled the same
            //  slot the cursor is already on → instant A on the
            //  default move, looks like "didn't nav at all". Now we
            //  roll *avoiding* the current cursor so a nav press
            //  always happens.
            if (screen == "move_select"
                && m_move_select_cursor >= 0
                && m_move_slot_rolled_for != m_battle_action_menu_visits){
                //  Lock override: if the active mon is Choice-locked /
                //  encored / etc., the tracker carries locked_to_move.
                //  Match it against the OCR'd move pills; if found, force
                //  that slot instead of rolling. Falls through to random
                //  if the lock can't be matched (lock set before moves
                //  read, or stale lock after switch — defensive).
                int locked_slot = -1;
                if (m_known_own_active[0] >= 0){
                    const std::string& locked =
                        m_tracker.own((uint8_t)m_known_own_active[0]).locked_to_move;
                    if (!locked.empty()){
                        for (int s = 0; s < 4; s++){
                            if (m_move_select_moves[s] == locked){
                                locked_slot = s;
                                break;
                            }
                        }
                    }
                }

                //  M2: model-driven move pick. Precedence: Choice-lock >
                //  model > random. The model is only consulted when the
                //  prediction is fresh for THIS visit AND the action is
                //  a move (< 12, not a switch).
                int model_slot = -1;
                if (locked_slot < 0
                    && ENABLE_MODEL_MOVE_PICK
                    && m_inference_client
                    && m_last_decision.success
                    && m_decision_for_visit == m_battle_action_menu_visits
                    && m_last_decision.action_a < 12){
                    model_slot = m_last_decision.action_a / 3;
                }

                const char* pick_source;
                if (locked_slot >= 0){
                    m_target_move_slot = locked_slot;
                    pick_source = "locked";
                }else if (model_slot >= 0){
                    m_target_move_slot = model_slot;
                    pick_source = "model";
                }else{
                    //  Pick one of the 3 slots that isn't the current cursor.
                    int offset = 1 + (int)(now_ms() % 3);  //  1..3
                    m_target_move_slot = (m_move_select_cursor + offset) % 4;
                    pick_source = "random";
                }
                m_move_slot_rolled_for = m_battle_action_menu_visits;
                const std::string& move_name = m_move_select_moves[m_target_move_slot];
                const std::string move_label =
                    move_name.empty() ? ("slot " + std::to_string(m_target_move_slot))
                                      : move_name;
                env.console.log(
                    std::string("in-battle: ")
                    + pick_source + " move slot "
                    + std::to_string(m_target_move_slot)
                    + " (" + move_label
                    + ", cursor=" + std::to_string(m_move_select_cursor)
                    + ") for action_menu visit #"
                    + std::to_string(m_battle_action_menu_visits),
                    COLOR_BLUE);
                env.console.overlay().add_log(
                    std::string(pick_source) + ": " + move_label,
                    COLOR_CYAN);
            }
            //  Roll a switch target once per pokemon_switch attempt. Keyed
            //  off the action_menu visit count so a single attempt sticks
            //  with one target across modal-flicker re-entries, but a
            //  fresh switch on a later turn rerolls.
            //
            //  The target is an ABSOLUTE slot 0-3 picked from {alive AND
            //  not on-field} at this moment. Defer rolling until at least
            //  one candidate is visible — on the first switch-screen poll
            //  the alive bitmap may still be populating (cursored slot's
            //  HP is obscured by the yellow highlight).
            if (screen == "pokemon_switch"
                && m_switch_rolled_for != m_battle_action_menu_visits){
                std::array<int, 4> candidates{};
                int cand_count = 0;
                const auto& active = poll_snapshot.own_active_slots;
                for (int i = 0; i < 4; i++){
                    if (!m_switch_alive[i]) continue;
                    //  Self-tracked active is authoritative — set from
                    //  team_preview lead marks + every confirmed switch-in.
                    //  Both doubles active slots are excluded here.
                    //  BattleHUD snapshot is consulted as a secondary
                    //  check in case the self-tracker is stale.
                    if (m_known_own_active[0] == i || m_known_own_active[1] == i) continue;
                    bool on_field = false;
                    for (int a : active){
                        if (a == i){ on_field = true; break; }
                    }
                    if (on_field) continue;
                    candidates[cand_count++] = i;
                }
                if (cand_count > 0){
                    //  M3 switch: model override. Action 12/13 indexes
                    //  into the own_bench emission order from
                    //  to_predict_json (non-active slots in 0..5 order,
                    //  first 2). Compute the same emission inline; pick
                    //  bench[i] if alive and reachable, else fall back.
                    int model_target = -1;
                    if (ENABLE_MODEL_SWITCH_PICK
                        && m_inference_client
                        && m_last_decision.success
                        && m_decision_for_visit == m_battle_action_menu_visits
                        && m_last_decision.action_a >= 12){
                        uint8_t bench_emission[2] = {255, 255};
                        uint8_t bn = 0;
                        for (uint8_t i = 0; i < 6 && bn < 2; i++){
                            bool is_active = (m_known_own_active[0] == (int)i
                                || m_known_own_active[1] == (int)i);
                            if (is_active) continue;
                            if (m_tracker.own(i).species.empty()) continue;
                            bench_emission[bn++] = i;
                        }
                        uint8_t want = bench_emission[m_last_decision.action_a - 12];
                        if (want != 255){
                            //  Confirm it's in the alive-candidate set.
                            for (int k = 0; k < cand_count; k++){
                                if (candidates[k] == want){
                                    model_target = want;
                                    break;
                                }
                            }
                        }
                    }

                    const char* switch_source;
                    if (model_target >= 0){
                        m_switch_target_slot = model_target;
                        switch_source = "model";
                    }else{
                        //  Use a different mod source than move-slot so the two
                        //  rolls aren't always in lockstep.
                        const int pick = (int)((now_ms() / 7) % cand_count);
                        m_switch_target_slot = candidates[pick];
                        switch_source = "random";
                    }
                    m_switch_rolled_for = m_battle_action_menu_visits;
                    env.console.log(
                        std::string("in-battle: ") + switch_source
                        + " switch target slot "
                        + std::to_string(m_switch_target_slot)
                        + " (from " + std::to_string(cand_count)
                        + " candidates) for action_menu visit #"
                        + std::to_string(m_battle_action_menu_visits),
                        COLOR_BLUE);
                    env.console.overlay().add_log(
                        std::string(switch_source) + " switch: slot "
                        + std::to_string(m_switch_target_slot)
                        + " (" + std::to_string(cand_count) + " cand)",
                        COLOR_CYAN);
                }
            }
            if (screen != "action_menu" && m_prev_screen == "action_menu"){
                m_action_menu_cursor = -1;
            }
            if (screen != "move_select" && m_prev_screen == "move_select"){
                m_move_select_cursor = -1;
                m_can_mega_evolve = false;
                m_move_select_moves = {};
            }
            //  Re-home on every fresh entry to team_select. A manual
            //  interruption mid-flow (or returning to it after a scan
            //  detour) shouldn't keep stale absolute-team state.
            //
            //  Also reset known_n when returning from team_stats /
            //  moves_and_more — pressing B from those screens puts the
            //  cursor on whichever team was previously *confirmed*,
            //  NOT the team we just inspected. Without this reset, our
            //  press-counter-based known_n would still claim we're on
            //  the inspected team.
            //
            //  Also abandon a stalled scan: if scan_step is in the
            //  modal-walk range (1) when we re-enter team_select, the
            //  previous attempt didn't reach moves_and_more / team_stats
            //  and the modal closed on us. Resetting to -1 lets the
            //  scan retrigger from step 0 once known_n re-anchors.
            const bool fresh_entry =
                screen == "team_select" && m_prev_screen != "team_select"
                && m_prev_screen != "team_select_modal";
            const bool returning_from_info =
                screen == "team_select"
                && (m_prev_screen == "moves_and_more"
                    || m_prev_screen == "team_stats");
            if (fresh_entry || returning_from_info){
                m_team_select_known_n = 0;
                m_team_select_known_n_changed_at_ms = 0;
                //  Step layout (post-modal-detector):
                //    0 team_select       1 modal walk -> View
                //    2 moves_and_more    3 team_stats
                //    4 team_select       5 modal walk -> Select (final A)
                //  Re-entering team_select with step in {1, 2, 3} means
                //  we exited info-screen flow without completing it
                //  (modal closed unexpectedly). Reset to retry.
                if (m_team_scan_step == 1){
                    env.console.log(
                        "team-scan: abandoning stalled modal walk (step 1) — "
                        "re-entering team_select from " + m_prev_screen,
                        COLOR_ORANGE);
                    m_team_scan_step = -1;
                }else if (m_team_scan_step == 2 || m_team_scan_step == 3){
                    env.console.log(
                        "team-scan: abandoning stalled info-screen wait (step "
                        + std::to_string(m_team_scan_step)
                        + ") — modal closed without reaching moves_and_more / team_stats",
                        COLOR_ORANGE);
                    m_team_scan_step = -1;
                }
            }
            //  Stale-cursor protection: if we leave a menu screen, clear
            //  the index so the next menu's cursor doesn't inherit it
            //  before its detector fires.
            m_menu_selected_index = -1;
        }

        //  Auto-press (off by default). Allowlist: menu nav + result/post-match.
        //  In-battle screens and team_preview_selecting stay suggest-only.
        if (ENABLE_AUTO_PRESS && m_last_suggestion && !m_last_suggestion->button.empty()){
            static const std::set<std::string> safe_screens = {
                "main_menu", "battle_mode_menu", "ranked_format_select",
                "casual_format_select",
                "pre_match", "casual_pre_match", "team_select",
                "team_select_modal",
                //  Info screens reached during the team-scan sub-flow:
                //  step 2 fires R on moves_and_more, step 3 fires B on
                //  team_stats. Without these, the press dispatcher
                //  silently drops both presses and the scan stalls
                //  forever on the first info screen.
                "moves_and_more", "team_stats",
                "team_preview", "team_preview_locked_in", "preparing",
                "result_screen", "post_match",
                //  In-battle dummy strategy: A on Fight, A on Move 1, A on
                //  default target, switch to first alive bench. Required
                //  for the auto-queuer to actually finish a match.
                "action_menu", "move_select", "target_select", "pokemon_switch",
            };
            //  Modal-step exception: scan steps 1 and 5 walk the modal
            //  cursor (Down/Up + A). The modal screen is now classified
            //  explicitly (team_select_modal, in safe_screens), so this
            //  flag is mostly redundant — but kept for the timing /
            //  dedup-bypass logic below, which needs to know "this press
            //  is part of a deterministic state-machine sequence and
            //  shouldn't be deduped".
            const bool scan_modal_step =
                m_last_suggestion
                && (m_team_scan_step == 1 || m_team_scan_step == 5);
            //  Auto-collect bypass: the missions and mailbox screens
            //  classify as "unknown", which isn't in safe_screens. When
            //  the collect sub-flow is at AT_MISSIONS / AT_MAILBOX
            //  (steps 2 / 4), allow presses through regardless.
            const bool auto_collect_step =
                (m_collect_step == 2 || m_collect_step == 4)
                && screen != "main_menu";
            if (safe_screens.count(screen) || scan_modal_step || auto_collect_step){
                //  Dedup logic: prevent burst-pressing the same action
                //  button (A/B/X/Y/Plus) through a slow screen transition.
                //  Nav buttons (Up/Down/Left/Right) are EXEMPT — when the
                //  suggester emits Down repeatedly to walk a cursor, each
                //  press should fire immediately; the cursor's new position
                //  is the natural state-change signal.
                const std::string& b = m_last_suggestion->button;
                bool is_nav = (b == "Up" || b == "Down" || b == "Left" || b == "Right");
                bool same = (screen == m_last_pressed_screen
                             && b == m_last_pressed_button);
                int64_t since_press_ms = now_ms() - m_last_press_ms;
                //  Two windows:
                //    Nav (Up/Down/Left/Right): 350ms — long enough to absorb
                //      the cursor-read lag after one press (poll period
                //      ≈250ms), short enough to permit multi-step nav
                //      (e.g. Down, Down, Down on team_preview_selecting).
                //    Action (A/B/X/Y/Plus/L/R): 1500ms — absorbs typical
                //      screen transitions while still permitting needed
                //      double-A patterns on the next poll.
                int64_t window_ms = is_nav ? 350 : 1500;
                //  Scan-modal walk emits the SAME button (Down or A)
                //  until the modal cursor reaches the target option, so
                //  short-window dedup blocks would stall the walk —
                //  but bypassing dedup entirely fires a new press every
                //  poll (250ms) while the previous press takes ~990ms
                //  to land on Switch, queueing 3-4 Downs per intended
                //  step and lapping the cursor around the 4-option
                //  modal. Use a window matched to actual press duration
                //  (240ms pre-delay + 150ms hold + 600ms release ≈
                //  1000ms) so consecutive scan-modal presses fire at
                //  press-cycle cadence, one tap per cursor advance.
                if (scan_modal_step) window_ms = 1000;
                bool retry_window = same && since_press_ms < window_ms;
                if (retry_window){
                    //  Visibility into when dedup is the reason a press
                    //  didn't fire — surfaces "stuck on Edit" type bugs.
                    static int64_t last_skip_log = 0;
                    if (now_ms() - last_skip_log > 1000){
                        env.console.log(
                            "auto-press dedup SKIP: " + b + " on " + screen
                            + " (last fired " + std::to_string(since_press_ms)
                            + "ms ago, window " + std::to_string(window_ms) + "ms)",
                            COLOR_ORANGE);
                        last_skip_log = now_ms();
                    }
                }
                if (!retry_window){
                    Button btn = BUTTON_NONE;
                    DpadPosition dpad = DPAD_NONE;
                    if      (b == "A")     btn = BUTTON_A;
                    else if (b == "B")     btn = BUTTON_B;
                    else if (b == "X")     btn = BUTTON_X;
                    else if (b == "Y")     btn = BUTTON_Y;
                    else if (b == "L")     btn = BUTTON_L;
                    else if (b == "R")     btn = BUTTON_R;
                    else if (b == "Plus")  btn = BUTTON_PLUS;
                    else if (b == "Up")    dpad = DPAD_UP;
                    else if (b == "Down")  dpad = DPAD_DOWN;
                    else if (b == "Left")  dpad = DPAD_LEFT;
                    else if (b == "Right") dpad = DPAD_RIGHT;
                    if (btn != BUTTON_NONE || dpad != DPAD_NONE){
                        env.console.log(
                            "LiveDetectorTrace: AUTO-PRESS " + b
                            + " on " + screen + " — " + m_last_suggestion->reason,
                            COLOR_PURPLE);
                        //  m_last_suggestion->label already starts with the
                        //  button name (e.g. "A — Done", "Down — to slot 2").
                        //  Don't prepend `b` here or it reads "A — A — Done".
                        env.console.overlay().add_log(
                            m_last_suggestion->label,
                            COLOR_PURPLE);
                        //  Conservative timing for the team-scan modal:
                        //  back-to-back Downs at the default 80/160ms can
                        //  saturate the Switch's input queue and the
                        //  second tap silently drops. 150ms hold + 600ms
                        //  release puts ~750ms between physical presses
                        //  — well past the input-merge window. (100/400
                        //  was tried first; Switch still dropped one.)
                        const auto hold_ms = scan_modal_step ? 150ms : 80ms;
                        const auto cool_ms = scan_modal_step ? 600ms : 160ms;
                        if (btn != BUTTON_NONE){
                            pbf_press_button(context, btn, hold_ms, cool_ms);
                        }else{
                            pbf_press_dpad(context, dpad, hold_ms, cool_ms);
                        }
                        m_last_pressed_screen = screen;
                        m_last_pressed_button = b;
                        m_last_press_ms = now_ms();

                        //  Auto-collect press tracking. When the sub-
                        //  flow is in AT_MISSIONS / AT_MAILBOX (step 2
                        //  or 4) and we're NOT on main_menu, X kicks
                        //  off the claim animation and A is the accept
                        //  press that follows. We track which has
                        //  fired so the suggester can sequence
                        //  X → wait → A → B without re-firing. No
                        //  missions/mailbox screen detector needed —
                        //  "not on main_menu while step ∈ {2,4}" is
                        //  enough signal.
                        if ((m_collect_step == 2 || m_collect_step == 4)
                            && screen != "main_menu"){
                            if (b == "X" && m_collect_x_fired_at_ms == 0){
                                m_collect_x_fired_at_ms = now_ms();
                            }else if (b == "A" && m_collect_x_fired_at_ms != 0
                                      && !m_collect_a_fired){
                                m_collect_a_fired = true;
                            }
                        }

                        //  Mark mega-toggle as fired for this turn so the
                        //  next move_select poll suggests A on the move
                        //  rather than re-pressing R (which would un-mega).
                        //  Keyed on action_menu visit count so a fresh
                        //  turn re-arms the toggle automatically.
                        if (screen == "move_select" && b == "R"
                            && m_last_suggestion
                            && m_last_suggestion->reason.rfind("mega:", 0) == 0){
                            m_mega_toggled_for_visit = m_battle_action_menu_visits;
                        }

                        //  Track blind-nudge attempts on pokemon_switch when
                        //  the suggester emitted Down because no yellow
                        //  highlight could be read. Bounded at 3.
                        if (screen == "pokemon_switch" && b == "Down"
                            && m_switch_cursor < 0){
                            m_switch_blind_attempts++;
                            m_switch_blind_last_press_ms = now_ms();
                        }
                        //  Nav-loop counter: every Up/Down fired on
                        //  pokemon_switch with the cursor known. Reset
                        //  on cursor-change (run_pokemon_switch_screen)
                        //  or screen-exit. Suggester gives up at 5.
                        if (screen == "pokemon_switch"
                            && (b == "Up" || b == "Down")
                            && m_switch_cursor >= 0){
                            m_switch_nav_since_change++;
                            m_switch_nav_total++;
                        }
                        //  Active tracker update: A on pokemon_switch confirms
                        //  the switch-in. Whichever slot the cursor was on at
                        //  press time becomes the new active. (First A press
                        //  opens the context modal — cursor is still on the
                        //  same slot at that moment. Subsequent A's confirm
                        //  the modal but the cursor reads as -1 then, so we
                        //  only credit the press that had a known cursor.)
                        if (screen == "pokemon_switch" && b == "A"
                            && m_switch_cursor >= 0 && m_switch_cursor < 6){
                            //  Identify which active entry to replace. The
                            //  fainted slot (no longer in m_switch_alive)
                            //  is the one being filled. If neither entry's
                            //  slot is fainted, this is a voluntary switch
                            //  (rare) — skip the update; we don't know
                            //  which slot the player is putting the new
                            //  mon into.
                            int replace_idx = -1;
                            for (int idx = 0; idx < 2; idx++){
                                int s = m_known_own_active[idx];
                                if (s < 0) continue;
                                if (s < 6 && !m_switch_alive[s]){
                                    replace_idx = idx;
                                    break;
                                }
                            }
                            //  Empty entry (e.g. singles slot[1] = -1) is
                            //  also a valid target.
                            if (replace_idx < 0){
                                for (int idx = 0; idx < 2; idx++){
                                    if (m_known_own_active[idx] < 0){
                                        replace_idx = idx;
                                        break;
                                    }
                                }
                            }
                            if (replace_idx >= 0
                                && m_known_own_active[replace_idx] != m_switch_cursor){
                                env.console.log(
                                    "active tracker: switched to slot "
                                    + std::to_string(m_switch_cursor)
                                    + " (was " + std::to_string(m_known_own_active[replace_idx])
                                    + " at active[" + std::to_string(replace_idx) + "])",
                                    COLOR_CYAN);
                                m_known_own_active[replace_idx] = m_switch_cursor;
                            }
                        }
                        //  Same guard on team_preview_selecting: Done
                        //  button's cursor strip occasionally fails to
                        //  score, so the suggester emits Down forever
                        //  once marks are placed. Bounded at 6 in the
                        //  suggester — past that it falls back to A.
                        if (screen == "team_preview"
                            && (b == "Up" || b == "Down")){
                            m_tp_nav_since_change++;
                        }

                        //  Carousel-aware team_select: each fired Left/Right
                        //  shifts the known team by one, wrapping at the
                        //  ends (Right at 18 -> 1, Left at 1 -> 18). We only
                        //  advance once known_n is anchored — homing presses
                        //  with known_n == 0 are no-ops here; the col-0/col-4
                        //  latch in classify_screen sets known_n the moment
                        //  the cursor lands at an edge.
                        if (screen == "team_select" && m_team_select_known_n > 0){
                            if (b == "Right"){
                                m_team_select_known_n =
                                    (m_team_select_known_n == 18)
                                        ? 1
                                        : m_team_select_known_n + 1;
                                m_team_select_known_n_changed_at_ms = now_ms();
                            }else if (b == "Left"){
                                m_team_select_known_n =
                                    (m_team_select_known_n == 1)
                                        ? 18
                                        : m_team_select_known_n - 1;
                                m_team_select_known_n_changed_at_ms = now_ms();
                            }
                        }

                        //  Team-scan state machine. Steps 0-5 (was 0-7,
                        //  collapsed since modal nav is now cursor-aware
                        //  rather than blind Down counting):
                        //    0  team_select        A    open modal
                        //    1  team_select_modal  walk to View, then A
                        //    2  moves_and_more     R    tab to Stats
                        //    3  team_stats         B    back out
                        //    4  team_select        A    open modal again
                        //    5  team_select_modal  walk to Select, then A
                        //
                        //  Within steps 1 and 5 the modal is walked with
                        //  Down/Up presses BEFORE the final A — we only
                        //  advance the step counter when an A actually
                        //  fires while inside the modal walk, since
                        //  that's the press that exits the step. Down/Up
                        //  presses inside the modal walk leave step
                        //  unchanged. All other steps advance on any
                        //  scan-tagged press.
                        const bool is_scan_press =
                            m_team_scan_step >= 0
                            && m_last_suggestion
                            && m_last_suggestion->reason.rfind("scan step ", 0) == 0;
                        //  Steps 1 and 5 walk the modal cursor; step 4
                        //  re-navigates the carousel (Right/Left ×N + A)
                        //  because B from team_stats puts the cursor
                        //  back on the previously-confirmed team, not
                        //  the one we just inspected. All three are
                        //  multi-press steps that complete on A.
                        const bool is_modal_walk_step =
                            (m_team_scan_step == 1
                             || m_team_scan_step == 4
                             || m_team_scan_step == 5);
                        const bool advance =
                            is_scan_press
                            && (!is_modal_walk_step || b == "A");
                        if (advance){
                            if (m_team_scan_step == 5){
                                m_team_scan_complete = true;
                                m_team_scan_step = -1;
                                env.console.log(
                                    "LiveDetectorTrace: team-scan sub-flow complete.",
                                    COLOR_PURPLE);
                            }else{
                                m_team_scan_step++;
                                //  Step 3's B press advances us to step 4.
                                //  B from team_stats lands the cursor on
                                //  the *previously-confirmed* team, not
                                //  the team we just inspected, so the
                                //  carousel anchor (m_team_select_known_n)
                                //  is stale. Reset here — at the
                                //  deterministic step transition, before
                                //  any post-B screen classification can
                                //  race the carousel-entry reset path
                                //  (which runs only on direct
                                //  team_stats -> team_select transitions
                                //  and misses the common "team_stats ->
                                //  unknown -> team_select" path).
                                if (m_team_scan_step == 4){
                                    m_team_select_known_n = 0;
                                    m_team_select_known_n_changed_at_ms = 0;
                                    env.console.log(
                                        "team-scan: cleared known_team_n "
                                        "for re-nav after B from team_stats.",
                                        COLOR_PURPLE);
                                }
                            }
                        }
                    }
                }
            }
        }

        //  Recovery: when classify_screen returns "unknown" for an extended
        //  period and auto-press is on, press B every 5s up to 4 times to
        //  back out of any unexpected modal/sub-menu/dialog. 10s grace
        //  period absorbs animation transitions before kicking in. Resets
        //  the moment a known screen reclassifies.
        if (screen == "unknown" && ENABLE_AUTO_PRESS){
            if (m_unknown_since_ms == 0){
                m_unknown_since_ms = now_ms();
            }
            //  One-shot diagnostic the first time we sit on 'unknown' for
            //  >2s after entering from a screen that should lead into
            //  team_select. Surfaces what the live capture is actually
            //  reading at the 5 cursor boxes so we can re-tune thresholds
            //  / geometry without needing a fresh stored screenshot.
            if (!m_team_select_unknown_dumped
                && (m_prev_screen == "casual_pre_match"
                    || m_prev_screen == "pre_match"
                    || m_prev_screen == "team_select")
                && now_ms() - m_unknown_since_ms > 2000){
                TeamSelectDetector det;
                env.console.log(
                    "team_select diag (stuck unknown after " + m_prev_screen + "): "
                    + det.debug_dump(snapshot),
                    COLOR_ORANGE);
                m_team_select_unknown_dumped = true;
            }
            int64_t elapsed = now_ms() - m_unknown_since_ms;
            const int64_t GRACE_MS = 10000;
            const int64_t INTERVAL_MS = 5000;
            const int MAX_BS = 4;
            if (elapsed >= GRACE_MS && m_recovery_b_count < MAX_BS){
                bool ready = (m_recovery_b_count == 0)
                          || (now_ms() - m_recovery_last_b_ms >= INTERVAL_MS);
                if (ready){
                    m_recovery_b_count++;
                    m_recovery_last_b_ms = now_ms();
                    env.console.log(
                        "LiveDetectorTrace: stuck on 'unknown' — recovery B "
                        + std::to_string(m_recovery_b_count) + "/"
                        + std::to_string(MAX_BS),
                        COLOR_ORANGE);
                    pbf_press_button(context, BUTTON_B, 80ms, 160ms);
                }
            }
        }else{
            m_unknown_since_ms = 0;
            m_recovery_b_count = 0;
            m_team_select_unknown_dumped = false;
        }

        //  Watchdog: log if we've been on the same screen for >60s.
        if (m_last_screen_change_ms > 0 && now_ms() - m_last_screen_change_ms > 60000){
            //  Throttle: only log once per 60s window.
            static int64_t last_warn_ms = 0;
            if (now_ms() - last_warn_ms > 60000){
                env.console.log(
                    "LiveDetectorTrace: stuck on '" + screen + "' for >60s.",
                    COLOR_ORANGE);
                last_warn_ms = now_ms();
            }
        }

        //  ── M1 shadow: fire /decide once per turn, +1 poll delay ──
        //  The visit-increment block above set m_decide_pending_visit
        //  to the new turn number. We wait at least 1 poll past that
        //  so HUD readers can populate, then POST. Synchronous call;
        //  latency adds to this poll's wall-clock. Async refactor in M2.
        if (m_inference_client
            && m_decide_pending_visit > 0
            && m_decide_pending_visit > m_decision_for_visit){
            if (m_decide_polls_waited < 1){
                m_decide_polls_waited++;
            }else{
                JsonObject state = m_tracker.to_predict_json();
                DecideResult r = m_inference_client->decide(env.console, state);
                if (r.success){
                    m_last_decision = r;
                    m_decision_for_visit = m_decide_pending_visit;

                    //  Build a human-readable log line. Pull the OCR'd
                    //  move names from the cached move_select reads (if
                    //  any) and the bench species from the tracker.
                    const bool is_singles = (m_mode != BattleMode::DOUBLES);
                    std::array<std::string, 2> bench_sp{};
                    {
                        uint8_t bench_n = 0;
                        const auto own_active = m_tracker.own_active_slot_indices();
                        for (uint8_t i = 0; i < 6 && bench_n < 2; i++){
                            bool is_active = (i == own_active[0])
                                || (!is_singles && i == own_active[1]);
                            if (is_active) continue;
                            const auto& mon = m_tracker.own(i);
                            if (mon.species.empty()) continue;
                            bench_sp[bench_n++] = mon.species;
                        }
                    }
                    std::string sa = decode_action_human(
                        r.action_a, m_move_select_moves, bench_sp, is_singles);
                    std::string sb = is_singles ? std::string()
                        : decode_action_human(
                            r.action_b, m_move_select_moves, bench_sp, false);

                    int pct_a = static_cast<int>(r.probs_a[r.action_a] * 100);
                    std::string overlay = "model: " + sa
                        + " (p=" + std::to_string(pct_a) + "%)";
                    std::string logline = "model decision visit#"
                        + std::to_string(m_decision_for_visit)
                        + ": A=" + sa + " (p=" + std::to_string(pct_a) + "%)";
                    if (!is_singles){
                        int pct_b = static_cast<int>(r.probs_b[r.action_b] * 100);
                        logline += " B=" + sb + " (p=" + std::to_string(pct_b) + "%)";
                        overlay += " | " + sb;
                    }
                    if (r.win_pct >= 0.0f){
                        int wp = static_cast<int>(r.win_pct * 100);
                        logline += " win=" + std::to_string(wp) + "%";
                    }
                    if (!r.model_version.empty()){
                        logline += " v=" + r.model_version;
                        if (!r.endpoint_impl.empty()) logline += "/" + r.endpoint_impl;
                    }
                    env.console.log(logline, COLOR_CYAN);
                    env.console.overlay().add_log(overlay, COLOR_CYAN);

                    //  M5.1: opp prediction overlay. When /decide carries
                    //  the perspective-swapped pass, surface the model's
                    //  guess at the opp's action so we can sanity-check.
                    //  Decoded against opp's side — the opp's target=0
                    //  (their "opp_a") is our own_a from our POV; we
                    //  mirror the label for the human watching.
                    if (r.has_opp){
                        //  Opp's bench species — for switch decoding —
                        //  best-effort from the tracker's opp_team.
                        std::array<std::string, 2> opp_bench_sp{};
                        {
                            uint8_t bn = 0;
                            const auto opp_active = m_tracker.opp_active_slot_indices();
                            for (uint8_t i = 0; i < m_tracker.opp_seen_count() && bn < 2; i++){
                                bool is_active = (i == opp_active[0])
                                    || (!is_singles && i == opp_active[1]);
                                if (is_active) continue;
                                const auto& mon = m_tracker.opp(i);
                                if (mon.species.empty()) continue;
                                opp_bench_sp[bn++] = mon.species;
                            }
                        }
                        //  Opp's move slugs aren't OCR'd live (we only
                        //  read our own move pills); pass empty array so
                        //  the decoder falls back to "moveN".
                        std::array<std::string, 4> empty_moves{};
                        std::string opp_sa = decode_action_human(
                            r.opp_action_a, empty_moves, opp_bench_sp, is_singles);
                        int opct_a = static_cast<int>(r.opp_probs_a[r.opp_action_a] * 100);
                        std::string opp_line = "opp predicts visit#"
                            + std::to_string(m_decision_for_visit)
                            + ": A=" + opp_sa + " (p=" + std::to_string(opct_a) + "%)";
                        std::string opp_overlay = "opp: " + opp_sa
                            + " (p=" + std::to_string(opct_a) + "%)";
                        if (!is_singles){
                            std::string opp_sb = decode_action_human(
                                r.opp_action_b, empty_moves, opp_bench_sp, false);
                            int opct_b = static_cast<int>(r.opp_probs_b[r.opp_action_b] * 100);
                            opp_line += " B=" + opp_sb + " (p="
                                + std::to_string(opct_b) + "%)";
                            opp_overlay += " | " + opp_sb;
                        }
                        env.console.log(opp_line, COLOR_PURPLE);
                        env.console.overlay().add_log(opp_overlay, COLOR_PURPLE);
                    }
                }else{
                    env.console.log(
                        "model decision visit#"
                        + std::to_string(m_decide_pending_visit)
                        + ": /decide failed (server unreachable or parse error)",
                        COLOR_ORANGE);
                    //  Mark this visit as "tried" so we don't retry every
                    //  poll for the rest of the turn.
                    m_decision_for_visit = m_decide_pending_visit;
                }
                m_decide_pending_visit = -1;
            }
        }

        JsonObject ev = build_event(screen, now_ms(), seq++);
        post_event(env.console, sink_url, ev.dump());

        m_prev_screen = screen;

        context.wait_until(snapshot.timestamp + std::chrono::milliseconds((uint32_t)POLL_PERIOD_MILLISECONDS));
    }
}


}
}
}
