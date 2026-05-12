/*  Pokemon Champions Inference Client
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  HTTP client that calls the Python inference server to get AI battle
 *  decisions. Uses Qt Network (QNetworkAccessManager) with a blocking
 *  event loop — same pattern as the Discord webhook integration.
 *
 *  The client is called once per turn (~10ms round-trip on localhost).
 *  If the server is unreachable or times out, success=false and the
 *  caller should fall back to a simple strategy.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_InferenceClient_H
#define PokemonAutomation_PokemonChampions_InferenceClient_H

#include <array>
#include <string>
#include "Common/Cpp/Json/JsonObject.h"
#include "CommonFramework/Logging/Logger.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


constexpr int NUM_ACTIONS = 14;  //  4 moves * 3 targets + 2 switches


struct ActionPrediction{
    uint8_t action_a = 0;           //  Best action for slot A (0-13)
    uint8_t action_b = 0;           //  Best action for slot B (0-13)
    std::array<float, NUM_ACTIONS> probs_a = {};
    std::array<float, NUM_ACTIONS> probs_b = {};
    bool success = false;           //  False if server unreachable or error.
};


struct TeamSelection{
    std::array<uint8_t, 4> bring = {};  //  Indices 0-5 of which mons to bring
    std::array<uint8_t, 2> lead = {};   //  Indices into the bring array
    bool success = false;
};


class InferenceClient{
public:
    InferenceClient(
        const std::string& server_url = "http://localhost:8265",
        int timeout_ms = 3000
    );

    //  Check if the inference server is running and model is loaded.
    bool health_check(Logger& logger);

    //  Send game state, get back action predictions for both active slots.
    ActionPrediction predict(Logger& logger, const JsonObject& game_state);

    //  Send both teams' species, get back team + lead selection.
    TeamSelection team_select(Logger& logger, const JsonObject& teams);

    void set_url(const std::string& url){ m_url = url; }
    void set_timeout(int ms){ m_timeout_ms = ms; }

private:
    //  Blocking HTTP POST. Returns response body, or empty string on failure.
    std::string post_json(Logger& logger, const std::string& path, const std::string& json_body);

    std::string m_url;
    int m_timeout_ms;
};


//  Decode action index to human-readable description.
std::string action_name(uint8_t action_idx);


}
}
}
#endif
