/*  Pokemon Champions Inference Client
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Uses Qt Network for HTTP. Pattern from DiscordWebhook.cpp:
 *  QNetworkAccessManager + QEventLoop blocking.
 *
 */

#include <QEventLoop>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>

#include "Common/Cpp/Json/JsonArray.h"
#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonTools.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "PokemonChampions_InferenceClient.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


InferenceClient::InferenceClient(const std::string& server_url, int timeout_ms)
    : m_url(server_url)
    , m_timeout_ms(timeout_ms)
{}


// ─── HTTP transport ──────────────────────────────────────────────

std::string InferenceClient::post_json(
    Logger& logger, const std::string& path, const std::string& json_body
){
    QUrl url(QString::fromStdString(m_url + path));
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    request.setTransferTimeout(m_timeout_ms);

    QNetworkAccessManager manager;
    QEventLoop loop;
    QObject::connect(&manager, &QNetworkAccessManager::finished, &loop, &QEventLoop::quit);

    std::unique_ptr<QNetworkReply> reply(
        manager.post(request, QByteArray::fromStdString(json_body))
    );
    loop.exec();

    if (reply->error() != QNetworkReply::NoError){
        logger.log(
            "InferenceClient: HTTP error: " + reply->errorString().toStdString(),
            COLOR_RED
        );
        return "";
    }

    return reply->readAll().toStdString();
}


// ─── Health check ────────────────────────────────────────────────

bool InferenceClient::health_check(Logger& logger){
    QUrl url(QString::fromStdString(m_url + "/health"));
    QNetworkRequest request(url);
    request.setTransferTimeout(m_timeout_ms);

    QNetworkAccessManager manager;
    QEventLoop loop;
    QObject::connect(&manager, &QNetworkAccessManager::finished, &loop, &QEventLoop::quit);

    std::unique_ptr<QNetworkReply> reply(manager.get(request));
    loop.exec();

    if (reply->error() != QNetworkReply::NoError){
        logger.log("InferenceClient: server unreachable at " + m_url, COLOR_RED);
        return false;
    }

    std::string body = reply->readAll().toStdString();
    try{
        JsonValue json = parse_json(body);
        const JsonObject& obj = json.to_object_throw();
        std::string status = obj.get_string_throw("status");
        if (status == "ok"){
            logger.log("InferenceClient: server healthy at " + m_url, COLOR_GREEN);
            return true;
        }
        logger.log("InferenceClient: server status = " + status, COLOR_RED);
    }catch (const std::exception& e){
        logger.log("InferenceClient: failed to parse health response: " + std::string(e.what()), COLOR_RED);
    }
    return false;
}


// ─── Predict ─────────────────────────────────────────────────────

ActionPrediction InferenceClient::predict(Logger& logger, const JsonObject& game_state){
    ActionPrediction result;

    std::string response = post_json(logger, "/predict", game_state.dump());
    if (response.empty()){
        return result;
    }

    try{
        JsonValue json = parse_json(response);
        const JsonObject& root = json.to_object_throw();

        //  Parse slot_a.
        const JsonObject& slot_a = root.get_object_throw("slot_a");
        result.action_a = static_cast<uint8_t>(slot_a.get_integer_throw("action"));
        const JsonArray& probs_a = slot_a.get_array_throw("probs");
        for (size_t i = 0; i < NUM_ACTIONS && i < probs_a.size(); i++){
            result.probs_a[i] = static_cast<float>(probs_a[i].to_double_throw());
        }

        //  Parse slot_b.
        const JsonObject& slot_b = root.get_object_throw("slot_b");
        result.action_b = static_cast<uint8_t>(slot_b.get_integer_throw("action"));
        const JsonArray& probs_b = slot_b.get_array_throw("probs");
        for (size_t i = 0; i < NUM_ACTIONS && i < probs_b.size(); i++){
            result.probs_b[i] = static_cast<float>(probs_b[i].to_double_throw());
        }

        result.success = true;

        logger.log(
            "InferenceClient: predict -> slot_a=" + action_name(result.action_a) +
            " (" + std::to_string(static_cast<int>(result.probs_a[result.action_a] * 100)) + "%)" +
            "  slot_b=" + action_name(result.action_b) +
            " (" + std::to_string(static_cast<int>(result.probs_b[result.action_b] * 100)) + "%)",
            COLOR_BLUE
        );

    }catch (const std::exception& e){
        logger.log("InferenceClient: failed to parse predict response: " + std::string(e.what()), COLOR_RED);
    }

    return result;
}


// ─── Team select ─────────────────────────────────────────────────

TeamSelection InferenceClient::team_select(Logger& logger, const JsonObject& teams){
    TeamSelection result;

    std::string response = post_json(logger, "/team-select", teams.dump());
    if (response.empty()){
        return result;
    }

    try{
        JsonValue json = parse_json(response);
        const JsonObject& root = json.to_object_throw();

        const JsonArray& bring = root.get_array_throw("bring");
        for (size_t i = 0; i < 4 && i < bring.size(); i++){
            result.bring[i] = static_cast<uint8_t>(bring[i].to_integer_throw());
        }

        const JsonArray& lead = root.get_array_throw("lead");
        for (size_t i = 0; i < 2 && i < lead.size(); i++){
            result.lead[i] = static_cast<uint8_t>(lead[i].to_integer_throw());
        }

        result.success = true;

        logger.log(
            "InferenceClient: team_select -> bring=[" +
            std::to_string(result.bring[0]) + "," + std::to_string(result.bring[1]) + "," +
            std::to_string(result.bring[2]) + "," + std::to_string(result.bring[3]) + "]" +
            "  lead=[" + std::to_string(result.lead[0]) + "," + std::to_string(result.lead[1]) + "]",
            COLOR_BLUE
        );

    }catch (const std::exception& e){
        logger.log("InferenceClient: failed to parse team-select response: " + std::string(e.what()), COLOR_RED);
    }

    return result;
}


// ─── Action names ────────────────────────────────────────────────

std::string action_name(uint8_t action_idx){
    static const char* NAMES[NUM_ACTIONS] = {
        "move0→opp_a", "move0→opp_b", "move0→ally",
        "move1→opp_a", "move1→opp_b", "move1→ally",
        "move2→opp_a", "move2→opp_b", "move2→ally",
        "move3→opp_a", "move3→opp_b", "move3→ally",
        "switch→bench0", "switch→bench1",
    };
    if (action_idx < NUM_ACTIONS){
        return NAMES[action_idx];
    }
    return "unknown_action_" + std::to_string(action_idx);
}


}
}
}
