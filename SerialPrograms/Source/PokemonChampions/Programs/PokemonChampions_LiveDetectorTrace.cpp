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

#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoFeed.h"

#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Programs/PokemonChampions_LiveDetectorTrace.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


LiveDetectorTrace_Descriptor::LiveDetectorTrace_Descriptor()
    : SingleSwitchProgramDescriptor(
        "PokemonChampions:LiveDetectorTrace",
        "Pokemon Champions", "Live Detector Trace",
        "Programs/PokemonChampions/LiveDetectorTrace.html",
        "Passive watcher: runs the detector/reader pipeline against the live "
        "capture and POSTs engine-view state changes to mac_dev_runner. "
        "Cole plays manually with a real controller; this program does not "
        "send any inputs.",
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
    , SINK_URL(
        false,
        "<b>Sink URL:</b><br>POST target for state-change events.",
        LockMode::UNLOCK_WHILE_RUNNING,
        "http://127.0.0.1:9876/live-trace/event",
        "http://127.0.0.1:9876/live-trace/event"
    )
{
    PA_ADD_OPTION(POLL_PERIOD_MILLISECONDS);
    PA_ADD_OPTION(SINK_URL);
}


//  Fire-and-forget POST. Returns true on HTTP 2xx, false otherwise.
//  Blocking, but tiny payloads at 4 Hz on loopback — round-trip is sub-ms.
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


void LiveDetectorTrace::program(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    std::string sink_url = SINK_URL;
    env.console.log("LiveDetectorTrace: starting. Sink = " + sink_url, COLOR_BLUE);

    BattleHUDReader hud_reader(Language::English);

    std::string prev_engine_view_dump;
    uint64_t event_seq = 0;

    while (true){
        VideoSnapshot snapshot = env.console.video().snapshot();
        if (!snapshot){
            context.wait_until(
                std::chrono::system_clock::now() +
                std::chrono::milliseconds((uint32_t)POLL_PERIOD_MILLISECONDS)
            );
            continue;
        }

        //  Phase 1 tracer-bullet: always run the BattleHUD reader. Off-screen
        //  reads return junk; the engine-view diff filters most of it. Screen
        //  classification gating comes in Phase 2.
        BattleHUDState hud = hud_reader.read_all(env.console, snapshot);
        m_state_tracker.update_from_hud(hud);

        JsonObject engine_view = m_state_tracker.to_predict_json();
        std::string current_dump = engine_view.dump();

        if (current_dump != prev_engine_view_dump){
            prev_engine_view_dump = current_dump;

            JsonObject event;
            event["seq"] = (int64_t)event_seq++;
            event["ts_ms"] = (int64_t)std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()
            ).count();
            event["type"] = "engine_view";
            event["engine_view"] = std::move(engine_view);

            post_event(env.console, sink_url, event.dump());
        }

        context.wait_until(snapshot.timestamp + std::chrono::milliseconds((uint32_t)POLL_PERIOD_MILLISECONDS));
    }
}


}
}
}
