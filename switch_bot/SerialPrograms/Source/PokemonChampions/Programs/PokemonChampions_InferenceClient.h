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


//  Response from POST /decide. See plans/decide_endpoint_contract.md.
//  Extends ActionPrediction with win_pct + meta block + opp action
//  distributions (when the server provides them).
struct DecideResult{
    bool success = false;
    uint8_t action_a = 0;
    uint8_t action_b = 0;
    std::array<float, NUM_ACTIONS> probs_a = {};
    std::array<float, NUM_ACTIONS> probs_b = {};
    //  Opponent's predicted actions (optional — populated only when the
    //  server runs a perspective-swapped pass and surfaces them).
    bool has_opp = false;
    uint8_t opp_action_a = 0;
    uint8_t opp_action_b = 0;
    std::array<float, NUM_ACTIONS> opp_probs_a = {};
    std::array<float, NUM_ACTIONS> opp_probs_b = {};
    //  Win probability estimate (optional; -1 sentinel = absent).
    float win_pct = -1.0f;
    //  Meta block. All optional / informational; logged for debugging.
    std::string model_version;
    std::string endpoint_impl;
    float latency_ms = 0.0f;
    int n_rollouts = 0;
};


struct TeamSelection{
    std::array<uint8_t, 4> bring = {};  //  Indices 0-5 of which mons to bring
    std::array<uint8_t, 2> lead = {};   //  Indices into the bring array
    bool success = false;
};


//  Response from POST /decide-team. See plans/decide_team_select_contract.md.
//  Extends TeamSelection with score arrays + meta block.
struct DecideTeamResult{
    bool success = false;
    std::array<uint8_t, 4> bring = {};
    std::array<uint8_t, 2> lead = {};
    std::array<float, 6> bring_scores = {};
    std::array<float, 4> lead_scores = {};
    std::string model_version;
    std::string endpoint_impl;
    float latency_ms = 0.0f;
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

    //  POST /decide — the stable trace-facing decision endpoint. See
    //  plans/decide_endpoint_contract.md. Returns the predicted action
    //  pair plus optional win_pct / opp distributions / meta block.
    //  Synchronous for M1; will be refactored to async when M2 driver
    //  mode needs sub-poll-time decisions.
    DecideResult decide(Logger& logger, const JsonObject& game_state);

    //  Send both teams' species, get back team + lead selection.
    TeamSelection team_select(Logger& logger, const JsonObject& teams);

    //  POST /decide-team — the stable trace-facing team/lead endpoint.
    //  See plans/decide_team_select_contract.md. Synchronous; called
    //  once per match at team_preview_selecting.
    DecideTeamResult decide_team(Logger& logger, const JsonObject& teams);

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

//  Richer decode for shadow-mode logging. Resolves move slot to the
//  OCR'd move name (when available) and switch slot to the bench mon's
//  species (when available). Falls back to action_name() when slugs
//  aren't populated.
//    moves         — 4 slugs from MoveNameReader (or empty if unread).
//    bench_species — first 2 own-bench species in emission order
//                    (matches what /decide.switch_0/1 refer to).
//    is_singles    — drop the "→target" suffix for moves; target is implicit.
std::string decode_action_human(
    uint8_t action_idx,
    const std::array<std::string, 4>& moves,
    const std::array<std::string, 2>& bench_species,
    bool is_singles);


}
}
}
#endif
