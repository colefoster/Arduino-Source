/*  Pokemon Champions Battle State Tracker
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include <algorithm>
#include "Common/Cpp/Json/JsonArray.h"
#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "PokemonChampions_BattleStateTracker.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


// ─── TrackedPokemon ──────────────────────────────────────────────

void TrackedPokemon::reset_volatile(){
    boosts.fill(0);
}

void TrackedPokemon::add_move(const std::string& move){
    if (move.empty()) return;
    if (std::find(known_moves.begin(), known_moves.end(), move) == known_moves.end()){
        if (known_moves.size() < 4){
            known_moves.push_back(move);
        }
    }
}


// ─── BattleStateTracker ──────────────────────────────────────────

BattleStateTracker::BattleStateTracker(){
    reset();
}

void BattleStateTracker::reset(){
    m_mode = BattleMode::UNKNOWN;
    m_turn = 0;
    m_own_active = {0, 1};
    m_opp_active = {0, 1};
    m_opp_seen = 0;
    m_weather.clear();
    m_terrain.clear();
    m_trick_room = false;
    m_tailwind_own = false;
    m_tailwind_opp = false;
    m_screens_own.fill(false);
    m_screens_opp.fill(false);

    for (auto& p : m_own_team){ p = TrackedPokemon{}; }
    for (auto& p : m_opp_team){ p = TrackedPokemon{}; }
}

void BattleStateTracker::set_mode(BattleMode mode){
    m_mode = mode;
}

void BattleStateTracker::set_own_team(const std::array<ConfiguredPokemon, 6>& team){
    for (size_t i = 0; i < 6; i++){
        m_own_team[i].species = team[i].species;
        m_own_team[i].item = team[i].item;
        m_own_team[i].ability = team[i].ability;
        m_own_team[i].known_moves.clear();
        for (const auto& move : team[i].moves){
            if (!move.empty()){
                m_own_team[i].known_moves.push_back(move);
            }
        }
    }
}


// ─── Updates ─────────────────────────────────────────────────────

void BattleStateTracker::update_from_hud(const BattleHUDState& hud){
    uint8_t slots = hud.slot_count();

    for (uint8_t i = 0; i < slots; i++){
        //  Opponent: species + HP%.
        const auto& opp = hud.opponents[i];
        if (!opp.species.empty()){
            uint8_t idx = find_or_add_opponent(opp.species);
            m_opp_active[i] = idx;
            if (opp.hp_pct >= 0){
                m_opp_team[idx].hp = opp.hp_pct / 100.0f;
            }
        }

        //  Own: HP current/max → normalized.
        const auto& own = hud.own[i];
        if (own.hp_current >= 0 && own.hp_max > 0){
            m_own_team[m_own_active[i]].hp = static_cast<float>(own.hp_current) / own.hp_max;
        }
    }
}

void BattleStateTracker::update_from_moves(
    const std::array<std::string, 4>& move_slugs, uint8_t active_slot
){
    if (active_slot >= 2) return;
    TrackedPokemon& mon = m_own_team[m_own_active[active_slot]];
    for (const auto& slug : move_slugs){
        mon.add_move(slug);
    }
}

void BattleStateTracker::update_from_log(const BattleLogEvent& event){
    switch (event.type){
    case BattleLogEventType::MOVE_USED:{
        //  Track opponent moves.
        if (event.is_opponent){
            for (uint8_t i = 0; i < 2; i++){
                auto& mon = m_opp_team[m_opp_active[i]];
                //  Match by checking if the pokemon name contains the species.
                //  The log says "Volcarona" and we track "volcarona".
                if (!mon.species.empty()){
                    //  Rough match: convert both to lowercase for comparison.
                    std::string lower_pokemon = event.pokemon;
                    std::transform(lower_pokemon.begin(), lower_pokemon.end(),
                                   lower_pokemon.begin(), ::tolower);
                    if (lower_pokemon.find(mon.species) != std::string::npos ||
                        mon.species.find(lower_pokemon) != std::string::npos)
                    {
                        //  Convert move name to slug format.
                        std::string slug = event.move;
                        std::transform(slug.begin(), slug.end(), slug.begin(), ::tolower);
                        for (char& c : slug){
                            if (c == ' ') c = '-';
                        }
                        mon.add_move(slug);
                        break;
                    }
                }
            }
        }
        break;
    }

    case BattleLogEventType::STAT_CHANGE:{
        //  Find the Pokemon and apply boost.
        //  event.stat may be "Atk", "Sp. Atk", "Speed", or comma-separated.
        //  event.boost_stages = +1, -1, +2, etc.
        //  For now, handle single-stat changes.
        int idx = stat_name_to_index(event.stat);
        if (idx >= 0){
            auto& team = event.is_opponent ? m_opp_team : m_own_team;
            auto& active = event.is_opponent ? m_opp_active : m_own_active;
            //  Apply to first active slot (simplified).
            team[active[0]].boosts[idx] = static_cast<int8_t>(std::clamp(
                static_cast<int>(team[active[0]].boosts[idx]) + event.boost_stages, -6, 6
            ));
        }
        break;
    }

    case BattleLogEventType::STATUS_INFLICTED:{
        //  event.stat contains the status name ("burned", "paralyzed", etc.)
        std::string status;
        if (event.stat.find("burn") != std::string::npos) status = "brn";
        else if (event.stat.find("paralyz") != std::string::npos) status = "par";
        else if (event.stat.find("poison") != std::string::npos) status = "psn";
        else if (event.stat.find("sleep") != std::string::npos) status = "slp";
        else if (event.stat.find("froz") != std::string::npos) status = "frz";
        else if (event.stat.find("badly poison") != std::string::npos) status = "tox";

        if (!status.empty()){
            auto& team = event.is_opponent ? m_opp_team : m_own_team;
            auto& active = event.is_opponent ? m_opp_active : m_own_active;
            team[active[0]].status = status;
        }
        break;
    }

    case BattleLogEventType::SWITCH_IN:{
        //  Opponent sent out a new Pokemon.
        if (event.is_opponent){
            std::string species = event.pokemon;
            std::transform(species.begin(), species.end(), species.begin(), ::tolower);
            uint8_t idx = find_or_add_opponent(species);
            //  Put in first active slot (simplified — should track which slot).
            m_opp_team[idx].reset_volatile();
            m_opp_active[0] = idx;
        }
        break;
    }

    case BattleLogEventType::FAINTED:{
        auto& team = event.is_opponent ? m_opp_team : m_own_team;
        auto& active = event.is_opponent ? m_opp_active : m_own_active;
        //  Mark first matching active slot as fainted.
        for (uint8_t i = 0; i < 2; i++){
            team[active[i]].alive = false;
            team[active[i]].hp = 0.0f;
            break;  //  Mark first active for simplicity.
        }
        break;
    }

    case BattleLogEventType::WEATHER:{
        std::string raw = event.raw_text;
        std::transform(raw.begin(), raw.end(), raw.begin(), ::tolower);
        if (raw.find("rain") != std::string::npos) m_weather = "RainDance";
        else if (raw.find("sun") != std::string::npos || raw.find("harsh") != std::string::npos) m_weather = "SunnyDay";
        else if (raw.find("sand") != std::string::npos) m_weather = "Sandstorm";
        else if (raw.find("snow") != std::string::npos || raw.find("hail") != std::string::npos) m_weather = "Snow";
        else if (raw.find("stopped") != std::string::npos || raw.find("subsided") != std::string::npos || raw.find("faded") != std::string::npos){
            m_weather.clear();
        }
        break;
    }

    case BattleLogEventType::TERRAIN:{
        std::string raw = event.raw_text;
        std::transform(raw.begin(), raw.end(), raw.begin(), ::tolower);
        if (raw.find("electric") != std::string::npos) m_terrain = "Electric";
        else if (raw.find("grassy") != std::string::npos) m_terrain = "Grassy";
        else if (raw.find("psychic") != std::string::npos) m_terrain = "Psychic";
        else if (raw.find("misty") != std::string::npos) m_terrain = "Misty";
        else m_terrain.clear();
        break;
    }

    case BattleLogEventType::TRICK_ROOM:{
        m_trick_room = !m_trick_room;  //  Toggle.
        break;
    }

    default:
        break;
    }
}

void BattleStateTracker::advance_turn(){
    m_turn++;
}


// ─── Opponent tracking ───────────────────────────────────────────

uint8_t BattleStateTracker::find_or_add_opponent(const std::string& species){
    //  Normalize to lowercase.
    std::string lower = species;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    //  Check if already tracked.
    for (uint8_t i = 0; i < m_opp_seen; i++){
        if (m_opp_team[i].species == lower){
            return i;
        }
    }
    //  Add new.
    if (m_opp_seen < 6){
        m_opp_team[m_opp_seen].species = lower;
        m_opp_team[m_opp_seen].alive = true;
        return m_opp_seen++;
    }
    return 0;  //  Overflow — shouldn't happen.
}

int BattleStateTracker::stat_name_to_index(const std::string& stat){
    std::string lower = stat;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    if (lower.find("atk") != std::string::npos && lower.find("sp") == std::string::npos) return 0;
    if (lower.find("def") != std::string::npos && lower.find("sp") == std::string::npos) return 1;
    if (lower.find("sp. atk") != std::string::npos || lower.find("spa") != std::string::npos) return 2;
    if (lower.find("sp. def") != std::string::npos || lower.find("spd") != std::string::npos) return 3;
    if (lower.find("spe") != std::string::npos || lower.find("speed") != std::string::npos) return 4;
    if (lower.find("eva") != std::string::npos || lower.find("evasion") != std::string::npos) return 5;
    return -1;
}


// ─── JSON output ─────────────────────────────────────────────────

static JsonObject pokemon_to_json(const TrackedPokemon& p){
    JsonObject obj;
    obj["species"] = JsonValue(p.species);
    obj["hp"] = JsonValue(static_cast<double>(p.hp));
    obj["status"] = JsonValue(p.status);
    obj["item"] = JsonValue(p.item);
    obj["ability"] = JsonValue(p.ability);
    obj["is_mega"] = JsonValue(p.is_mega);
    obj["alive"] = JsonValue(p.alive);

    JsonArray moves;
    for (const auto& m : p.known_moves){
        moves.push_back(JsonValue(m));
    }
    obj["moves"] = JsonValue(std::move(moves));

    JsonArray boosts;
    for (int8_t b : p.boosts){
        boosts.push_back(JsonValue(static_cast<int64_t>(b)));
    }
    obj["boosts"] = JsonValue(std::move(boosts));

    return obj;
}

JsonObject BattleStateTracker::to_predict_json() const{
    JsonObject root;

    //  Own active.
    JsonArray own_active;
    uint8_t slots = (m_mode == BattleMode::DOUBLES) ? 2 : 1;
    for (uint8_t i = 0; i < slots; i++){
        own_active.push_back(JsonValue(pokemon_to_json(m_own_team[m_own_active[i]])));
    }
    root["own_active"] = JsonValue(std::move(own_active));

    //  Own bench.
    JsonArray own_bench;
    for (uint8_t i = 0; i < 6; i++){
        bool is_active = false;
        for (uint8_t a = 0; a < slots; a++){
            if (m_own_active[a] == i) is_active = true;
        }
        if (!is_active && m_own_team[i].alive && !m_own_team[i].species.empty()){
            own_bench.push_back(JsonValue(pokemon_to_json(m_own_team[i])));
        }
    }
    root["own_bench"] = JsonValue(std::move(own_bench));

    //  Opponent active.
    JsonArray opp_active;
    for (uint8_t i = 0; i < slots; i++){
        if (m_opp_active[i] < m_opp_seen){
            opp_active.push_back(JsonValue(pokemon_to_json(m_opp_team[m_opp_active[i]])));
        }
    }
    root["opp_active"] = JsonValue(std::move(opp_active));

    //  Opponent bench.
    JsonArray opp_bench;
    for (uint8_t i = 0; i < m_opp_seen; i++){
        bool is_active = false;
        for (uint8_t a = 0; a < slots; a++){
            if (m_opp_active[a] == i) is_active = true;
        }
        if (!is_active && m_opp_team[i].alive){
            opp_bench.push_back(JsonValue(pokemon_to_json(m_opp_team[i])));
        }
    }
    root["opp_bench"] = JsonValue(std::move(opp_bench));

    //  Field state.
    JsonObject field;
    field["weather"] = JsonValue(m_weather);
    field["terrain"] = JsonValue(m_terrain);
    field["trick_room"] = JsonValue(m_trick_room);
    field["tailwind_own"] = JsonValue(m_tailwind_own);
    field["tailwind_opp"] = JsonValue(m_tailwind_opp);
    field["turn"] = JsonValue(static_cast<int64_t>(m_turn));

    JsonArray screens_own;
    for (bool s : m_screens_own) screens_own.push_back(JsonValue(s));
    field["screens_own"] = JsonValue(std::move(screens_own));

    JsonArray screens_opp;
    for (bool s : m_screens_opp) screens_opp.push_back(JsonValue(s));
    field["screens_opp"] = JsonValue(std::move(screens_opp));

    root["field"] = JsonValue(std::move(field));

    return root;
}

JsonObject BattleStateTracker::to_team_select_json(
    const std::vector<std::string>& opp_species
) const{
    JsonObject root;

    JsonArray own_team;
    for (const auto& p : m_own_team){
        own_team.push_back(JsonValue(p.species));
    }
    root["own_team"] = JsonValue(std::move(own_team));

    JsonArray opp_team;
    for (const auto& s : opp_species){
        opp_team.push_back(JsonValue(s));
    }
    //  Pad to 6.
    while (opp_team.size() < 6){
        opp_team.push_back(JsonValue(""));
    }
    root["opp_team"] = JsonValue(std::move(opp_team));

    return root;
}


}
}
}
