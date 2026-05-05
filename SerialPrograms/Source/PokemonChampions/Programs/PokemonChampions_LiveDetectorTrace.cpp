/*  Pokemon Champions Live Detector Trace
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include <chrono>

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

#include "PokemonChampions/Inference/PokemonChampions_ActionMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_ActiveHUDSlotDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleModeDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MainMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PokeballAliveDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PostMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreparingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewReader.h"

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
{
    PA_ADD_OPTION(POLL_PERIOD_MILLISECONDS);
    PA_ADD_OPTION(STALE_AFTER_MILLISECONDS);
    PA_ADD_OPTION(SINK_URL);
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

    //  ── Wired readers ──
    add("BattleModeDetector",        "reader", "skipped", "Reads format label: Singles vs Doubles. Refreshed on TeamPreview / matchmaking screens.");
    add("TeamPreviewReader",         "reader", "skipped", "OCR's all 6 own species + items, sprite-matches all 6 opp species. Fires on TeamPreview screen.");
    add("BattleHUDReader",           "reader", "skipped", "Reads opp active species (text), opp + own active HPs. Fires on action_menu / move_select / preparing screens.");
    add("MoveNameReader",            "reader", "skipped", "Reads the 4 move-name pills on Move Select. Fires only on move_select.");
    add("PokeballAliveDetector",     "reader", "skipped", "Reads alive/fainted/empty for all 6 slots per side from the HUD pokeball strip. Fires whenever the HUD is visible.");

    //  ── WIP / unavailable (declared but not wired) ──
    add("MovesAndMoreReader",        "reader", "n/a",
        "Requires controller navigation to enter 'View Details -> Moves & More'. "
        "Cannot run in passive mode. AutoLadder uses this to load own species/moves/abilities at match start.");
    add("BattleLogReader",           "reader", "wip",
        "Battle log overlay parser exists in code but is not yet wired into LiveDetectorTrace. "
        "Would feed update_from_log() with switch / faint / boost / status / weather events.");
    add("AbilityRevealReader",       "reader", "wip",
        "No reader exists yet. Opp ability reveals (intimidate, drought, prankster trigger) are visible "
        "via 'Garchomp's Sand Veil!' style text bubbles; needs a bubble-text OCR.");
    add("ItemRevealReader",          "reader", "wip",
        "No reader exists yet. Opp item reveals (eat berry, switching items) come through battle log text.");
    add("StatusOverlayReader",       "reader", "wip",
        "No reader exists yet. Status condition icons (PSN/PAR/BRN/SLP/FRZ) on the HUD are not OCR'd.");
    add("BoostsReader",              "reader", "wip",
        "No reader exists yet. Stat-up/down arrows on the HUD are not parsed; boosts come only via BattleLogReader (also WIP).");
    add("WeatherReader",             "reader", "wip", "No reader exists yet. Weather overlay (sun/rain/sand/snow) not parsed.");
    add("TerrainReader",             "reader", "wip", "No reader exists yet. Terrain overlay (electric/grassy/misty/psychic) not parsed.");
    add("TrickRoomDetector",         "detector", "wip", "No detector exists yet. Trick Room state not parsed.");
    add("TailwindDetector",          "detector", "wip", "No detector exists yet. Per-side Tailwind not parsed.");
    add("ScreensDetector",           "detector", "wip", "No detector exists yet. Light Screen / Reflect / Aurora Veil per side not parsed.");
    add("MegaEvolveDetector",        "detector", "wip", "Detector exists in tree but not yet wired into LiveDetectorTrace pipeline.");
    add("CommunicatingDetector",     "detector", "wip", "Detector exists but not yet wired (would mark 'syncing with opponent' transitional screens).");
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

    //  Own species: state tracker doesn't have a public set_own_species
    //  method without ConfiguredPokemon, so we synthesize a partial team
    //  from the OCR for what we have. Items get filled per-slot above;
    //  species we put through set_own_team only if at least one row has
    //  a species, leaving moves/abilities empty (they'll register as WIP
    //  fields in the engine view).
    if (own_count > 0){
        std::array<ConfiguredPokemon, 6> team;
        for (uint8_t i = 0; i < 6; i++){
            team[i].species = result.own[i].species;
            team[i].item = result.own[i].item;
            //  moves[] and ability stay empty — those would come from
            //  Moves & More (unavailable in passive mode).
        }
        m_tracker.set_own_team(team);
    }

    JsonObject summary;
    summary["own_species_read"] = (int64_t)own_count;
    summary["opp_species_matched"] = (int64_t)opp_count;
    summary["own"] = std::move(own_arr);
    summary["opp"] = std::move(opp_arr);
    mark("TeamPreviewReader", (own_count + opp_count) > 0 ? "ok" : "error", std::move(summary));
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
    m_match_in_progress = false;
    uint64_t seq = 0;

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

        //  Match-state transitions: enter a new match on TeamPreview after
        //  a non-battle screen; mark match over on Result/PostMatch.
        if (screen == "team_preview" && (m_prev_screen.empty()
                || m_prev_screen == "main_menu" || m_prev_screen == "post_match"
                || m_prev_screen == "result_screen")){
            if (m_match_in_progress || m_tracker.opp_seen_count() > 0){
                env.console.log("LiveDetectorTrace: new match — wiping tracker.", COLOR_BLUE);
            }
            m_tracker.reset();
            m_tracker.set_mode(m_mode);
            m_match_in_progress = true;
        }
        if (screen == "post_match" || screen == "result_screen"){
            m_match_in_progress = false;
        }

        //  Run readers for whatever screen we're on.
        if (screen == "team_preview"){
            run_team_preview_screen(env.console, snapshot);
        }else if (screen == "move_select"){
            run_move_select_screen(env.console, snapshot);
        }else if (screen == "action_menu" || screen == "preparing"){
            run_battle_screen(env.console, snapshot);
        }
        //  result_screen / post_match / main_menu / unknown — no readers
        //  fire, but pipeline status still reports the screen detector hit.

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
