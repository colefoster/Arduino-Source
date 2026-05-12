/*  Pokemon Champions Battle State Tracker
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include <algorithm>
#include <cstdlib>
#include <map>
#include <mutex>
#include <unordered_map>
#include "Common/Cpp/Json/JsonArray.h"
#include "Common/Cpp/Json/JsonObject.h"
#include "Common/Cpp/Json/JsonValue.h"
#include "CommonFramework/Globals.h"
#include "CommonFramework/Logging/Logger.h"
#include "PokemonChampions_BattleStateTracker.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamStatsReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


// ─── TrackedPokemon ──────────────────────────────────────────────

void TrackedPokemon::reset_volatile(){
    boosts.fill(0);
    //  Choice / encore / multi-turn lock state resets on switch-out — the
    //  real game clears it the moment the mon leaves the field. We reset
    //  on switch-in (the next time the mon is volatile-reset) which is the
    //  natural sync point in update_from_log.
    locked_to_move.clear();
    //  Volatile statuses (substitute, taunt, encore, confusion, etc.)
    //  evaporate the moment the mon leaves the field — except for the
    //  ones that DON'T (e.g. ingrain, yawn-source). Cleared en masse here;
    //  any persistent-across-switch volatile would need a carve-out.
    volatile_statuses.clear();
    substitute_hp_frac = 0.0f;
    sleep_turns_remaining = 0;
    toxic_counter = 0;
}

void TrackedPokemon::add_move(const std::string& move){
    if (move.empty()) return;
    if (std::find(known_moves.begin(), known_moves.end(), move) == known_moves.end()){
        if (known_moves.size() < 4){
            known_moves.push_back(move);
        }
    }
}


// ─── Opponent set prior ─────────────────────────────────────────
//
//  Per-species "most likely set" defaults drawn from Smogon chaos stats
//  for the current regulation (data/usage_stats/...). Used to backfill
//  empty item / ability / moves on the opponent side so the model never
//  sees blank slugs (which map to UNK at training time and degrade
//  calibration). Loaded lazily on first lookup; cached process-wide.
//
//  Schema (see scripts/build_usage_stats.py + data/usage_stats/SCHEMA.md):
//    { "format": "...", "source": "...",
//      "priors": { "<species_slug>": {
//          "item": "<item_slug>", "ability": "<ability_slug>",
//          "moves": ["<move>", "<move>", "<move>", "<move>"]
//      }}}

struct OppSetPrior{
    std::string item;
    std::string ability;
    std::array<std::string, 4> moves = {};
};

static const std::map<std::string, OppSetPrior>& load_opp_set_priors(){
    static std::map<std::string, OppSetPrior> table;
    static std::once_flag flag;
    std::call_once(flag, [](){
        const std::string path = RESOURCE_PATH() + "PokemonChampions/OpponentSetPrior.json";
        JsonValue root;
        try{
            root = load_json_file(path);
        }catch (...){
            //  No prior file shipped — leave table empty; lookups will
            //  return defaults and the opp-emission path will fall through
            //  to its existing empty-string behavior.
            return;
        }
        const JsonObject* obj = root.to_object();
        if (obj == nullptr) return;
        const JsonObject* priors = obj->get_object("priors");
        if (priors == nullptr) return;
        for (const auto& kv : *priors){
            const JsonObject* mon = kv.second.to_object();
            if (mon == nullptr) continue;
            OppSetPrior p;
            if (auto* s = mon->get_string("item")) p.item = *s;
            if (auto* s = mon->get_string("ability")) p.ability = *s;
            if (const JsonArray* moves = mon->get_array("moves")){
                for (size_t k = 0; k < moves->size() && k < 4; k++){
                    if (auto* mv = (*moves)[k].to_string()) p.moves[k] = *mv;
                }
            }
            table.emplace(kv.first, std::move(p));
        }
    });
    return table;
}

//  Return prior defaults for a species slug, or an all-empty struct.
static OppSetPrior opp_set_prior_for(const std::string& species_slug){
    if (species_slug.empty()) return {};
    const auto& table = load_opp_set_priors();
    auto it = table.find(species_slug);
    if (it == table.end()) return {};
    return it->second;
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

    m_own_leads.clear();

    m_history.clear();
}


void BattleStateTracker::push_history_snapshot(){
    BattleHistoryEntry entry;

    bool doubles = (m_mode == BattleMode::DOUBLES);

    auto fill_pair = [&](
        const std::array<TrackedPokemon, 6>& team,
        const std::array<uint8_t, 2>& active,
        uint8_t base_idx
    ){
        uint8_t positions = doubles ? 2 : 1;
        for (uint8_t i = 0; i < positions; i++){
            uint8_t slot = active[i];
            if (slot >= 6) continue;
            const TrackedPokemon& mon = team[slot];
            if (mon.species.empty()) continue;
            entry.active_species[base_idx + i] = mon.species;
            entry.active_hp[base_idx + i] = mon.alive ? mon.hp : 0.0f;
        }
    };

    fill_pair(m_own_team, m_own_active, 0);   //  slots 0,1 = own_a, own_b
    fill_pair(m_opp_team, m_opp_active, 2);   //  slots 2,3 = opp_a, opp_b

    //  Field-state snapshot at push time. The LSTM packer diffs these
    //  across consecutive entries (and last-vs-current request) to set
    //  the `field_changed` flag.
    entry.weather = m_weather;
    entry.terrain = m_terrain;
    entry.trick_room = m_trick_room;

    //  action_types / action_moves: we don't reliably know what each
    //  participant chose last turn from the C++ pipeline, so leave them
    //  as the "noop" / empty defaults. action_moves and move_order get
    //  populated mid-turn by update_from_log's MOVE_USED case (writing
    //  to m_history.back()). The model treats noop as a valid history
    //  entry; the state trajectory carries most of the signal.

    m_history.push_back(std::move(entry));
    while ((int)m_history.size() > BATTLE_HISTORY_K){
        m_history.pop_front();
    }

    //  Reset the per-turn MOVE_USED order counter — the next turn's
    //  moves write into this fresh history entry's move_order[].
    m_turn_move_count = 0;
}

void BattleStateTracker::set_mode(BattleMode mode){
    m_mode = mode;
}

void BattleStateTracker::set_own_actives(int slot_a, int slot_b){
    if (slot_a >= 0 && slot_a < 6) m_own_active[0] = (uint8_t)slot_a;
    if (slot_b >= 0 && slot_b < 6) m_own_active[1] = (uint8_t)slot_b;
}

// ─── Showdown paste parser ────────────────────────────────────────

//  Convert a display name to a slug: "Sucker Punch" -> "sucker-punch"
static std::string to_slug(const std::string& name){
    std::string slug;
    for (char c : name){
        if (c == ' ') slug += '-';
        else if (c == '\'') {}  //  skip apostrophes
        else slug += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return slug;
}

static std::string trim(const std::string& s){
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}


int BattleStateTracker::load_team_from_showdown_paste(const std::string& paste){
    //  Parse Showdown paste format:
    //    Species @ Item        (or: Nickname (Species) @ Item)
    //    Ability: AbilityName
    //    EVs: ...
    //    Nature Nature
    //    - Move 1
    //    - Move 2
    //    - Move 3
    //    - Move 4
    //    (blank line separates Pokemon)

    std::array<ConfiguredPokemon, 6> team;
    int count = 0;

    //  Split into lines.
    std::vector<std::string> lines;
    std::string current_line;
    for (char c : paste){
        if (c == '\n'){
            lines.push_back(current_line);
            current_line.clear();
        }else{
            current_line += c;
        }
    }
    if (!current_line.empty()) lines.push_back(current_line);

    ConfiguredPokemon* current = nullptr;
    int move_idx = 0;

    for (const auto& raw_line : lines){
        std::string line = trim(raw_line);

        //  Blank line = end of current Pokemon.
        if (line.empty()){
            if (current != nullptr){
                current = nullptr;
            }
            continue;
        }

        //  Start a new Pokemon (first non-blank line after a gap).
        if (current == nullptr){
            if (count >= 6) break;
            current = &team[count];
            move_idx = 0;
            count++;

            //  Parse "Species @ Item" or "Nickname (Species) @ Item"
            std::string left, item;
            size_t at_pos = line.find('@');
            if (at_pos != std::string::npos){
                left = trim(line.substr(0, at_pos));
                item = trim(line.substr(at_pos + 1));
                current->item = to_slug(item);
            }else{
                left = trim(line);
            }

            //  Handle nickname: "Nickname (Species)" or just "Species"
            size_t paren_open = left.find('(');
            size_t paren_close = left.find(')');
            if (paren_open != std::string::npos && paren_close != std::string::npos){
                current->species = to_slug(trim(left.substr(paren_open + 1, paren_close - paren_open - 1)));
            }else{
                //  Strip gender suffix: "Kingambit (M)" or "Kingambit (F)"
                if (left.size() > 4 && left[left.size()-1] == ')' &&
                    (left[left.size()-2] == 'M' || left[left.size()-2] == 'F') &&
                    left[left.size()-3] == '(')
                {
                    left = trim(left.substr(0, left.size() - 4));
                }
                current->species = to_slug(left);
            }
            continue;
        }

        //  Ability line.
        if (line.size() > 9 && line.substr(0, 8) == "Ability:"){
            current->ability = to_slug(trim(line.substr(8)));
            continue;
        }

        //  Move line.
        if (line.size() > 2 && line[0] == '-' && line[1] == ' '){
            if (move_idx < 4){
                current->moves[move_idx] = to_slug(trim(line.substr(2)));
                move_idx++;
            }
            continue;
        }

        //  Skip EVs, IVs, Nature, Level lines — not needed for the model.
    }

    //  Finalize.
    set_own_team(team);
    return count;
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


void BattleStateTracker::set_own_item(uint8_t slot, const std::string& item){
    if (slot >= 6) return;
    m_own_team[slot].item = item;
}


void BattleStateTracker::set_opp_species_preview(uint8_t slot, const std::string& species){
    if (slot >= 6) return;
    if (species.empty()) return;
    std::string lower = species;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    m_opp_team[slot].species = lower;
    m_opp_team[slot].alive = true;
    //  Bump m_opp_seen so preview-seeded entries surface in to_predict_json's
    //  bench loop. find_or_add_opponent matches by species, so HUD reads will
    //  reuse these slots instead of duplicating.
    if (slot >= m_opp_seen) m_opp_seen = slot + 1;
}


void BattleStateTracker::apply_switch_screen_hp(
    const std::array<std::pair<int, int>, 6>& own_hp,
    const std::array<int, 6>& opp_hp_pct
){
    for (uint8_t i = 0; i < 6; i++){
        const auto& hp = own_hp[i];
        if (hp.first >= 0 && hp.second > 0){
            m_own_team[i].hp = static_cast<float>(hp.first) / hp.second;
        }
    }
    for (uint8_t i = 0; i < 6; i++){
        if (opp_hp_pct[i] >= 0 && opp_hp_pct[i] <= 100 && i < m_opp_seen){
            m_opp_team[i].hp = opp_hp_pct[i] / 100.0f;
        }
    }
}


void BattleStateTracker::apply_battle_info_focused(
    const std::string& side, uint8_t slot,
    const std::string& species,
    int hp_current, int hp_max, int hp_pct,
    const std::array<std::string, 2>& types,
    const std::string& ability, const std::string& item,
    const std::array<int8_t, 5>& boosts,
    const std::string& status_text,
    int status_turns_current, int status_turns_max
){
    (void)types;  //  Tracker doesn't currently store types; reserved for future.
    if (slot >= 2) return;
    bool is_own = (side == "own");
    auto& team = is_own ? m_own_team : m_opp_team;
    auto& active = is_own ? m_own_active : m_opp_active;
    TrackedPokemon& mon = team[active[slot]];

    if (!species.empty()) mon.species = species;
    if (hp_current >= 0 && hp_max > 0){
        mon.hp = static_cast<float>(hp_current) / hp_max;
    }else if (hp_pct >= 0){
        mon.hp = hp_pct / 100.0f;
    }
    if (!ability.empty()) mon.ability = ability;
    if (!item.empty()) mon.item = item;

    //  Boosts: 5 main stats. Battle Info shows the canonical post-application
    //  stage, which is strictly more authoritative than log-derived values.
    for (size_t i = 0; i < 5; i++){
        mon.boosts[i] = boosts[i];
    }

    //  Field effects from status_text. Match canonical names; for tailwind
    //  + screens we don't have a side context in the text so we apply to
    //  the focused side. Trick Room is global.
    std::string lower = status_text;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    if (lower.find("trick room") != std::string::npos){
        m_trick_room = true;
    }
    if (lower.find("tailwind") != std::string::npos){
        if (is_own) m_tailwind_own = true;
        else        m_tailwind_opp = true;
    }
    //  Screen names → m_screens_*[3]: light_screen, reflect, aurora_veil.
    if (lower.find("light screen") != std::string::npos){
        if (is_own) m_screens_own[0] = true; else m_screens_opp[0] = true;
    }
    if (lower.find("reflect") != std::string::npos){
        if (is_own) m_screens_own[1] = true; else m_screens_opp[1] = true;
    }
    if (lower.find("aurora veil") != std::string::npos){
        if (is_own) m_screens_own[2] = true; else m_screens_opp[2] = true;
    }
    //  Weather + terrain — already log-fed, but re-confirm here as belt-and-suspenders.
    if (lower.find("harsh sunlight") != std::string::npos || lower.find("sunny") != std::string::npos){
        m_weather = "SunnyDay";
    }else if (lower.find("rain") != std::string::npos){
        m_weather = "RainDance";
    }else if (lower.find("sandstorm") != std::string::npos){
        m_weather = "Sandstorm";
    }else if (lower.find("snow") != std::string::npos || lower.find("hail") != std::string::npos){
        m_weather = "Snow";
    }
    if (lower.find("electric terrain") != std::string::npos) m_terrain = "Electric";
    else if (lower.find("grassy terrain") != std::string::npos) m_terrain = "Grassy";
    else if (lower.find("psychic terrain") != std::string::npos) m_terrain = "Psychic";
    else if (lower.find("misty terrain") != std::string::npos)   m_terrain = "Misty";

    (void)status_turns_current;
    (void)status_turns_max;
    //  TODO: surface remaining turns once the JSON schema has slots for them.
}


// ─── Persistent team store ──────────────────────────────────────────

bool BattleStateTracker::save_team_to_file(const std::string& path) const{
    JsonArray arr;
    for (uint8_t i = 0; i < 6; i++){
        const TrackedPokemon& m = m_own_team[i];
        JsonObject mon;
        mon["species"] = JsonValue(m.species);
        mon["ability"] = JsonValue(m.ability);
        mon["item"] = JsonValue(m.item);
        mon["nature"] = JsonValue(m.nature);

        JsonArray moves;
        for (const auto& mv : m.known_moves) moves.push_back(JsonValue(mv));
        mon["moves"] = JsonValue(std::move(moves));

        JsonArray evs;
        for (int e : m.evs) evs.push_back(JsonValue((int64_t)e));
        mon["evs"] = JsonValue(std::move(evs));

        arr.push_back(JsonValue(std::move(mon)));
    }
    JsonObject root;
    root["own_team"] = JsonValue(std::move(arr));
    try {
        JsonValue(std::move(root)).dump(path);
        return true;
    } catch (...) {
        return false;
    }
}


bool BattleStateTracker::load_team_from_file(const std::string& path){
    JsonValue root;
    try {
        root = load_json_file(path);
    } catch (...) {
        return false;
    }
    const JsonObject* obj = root.to_object();
    if (obj == nullptr) return false;
    const JsonArray* arr = obj->get_array("own_team");
    if (arr == nullptr) return false;
    for (uint8_t i = 0; i < 6 && i < arr->size(); i++){
        const JsonObject* mon = (*arr)[i].to_object();
        if (mon == nullptr) continue;
        TrackedPokemon& dst = m_own_team[i];
        if (auto* s = mon->get_string("species")) dst.species = *s;
        if (auto* s = mon->get_string("ability")) dst.ability = *s;
        if (auto* s = mon->get_string("item"))    dst.item = *s;
        if (auto* s = mon->get_string("nature"))  dst.nature = *s;

        if (const JsonArray* moves = mon->get_array("moves")){
            dst.known_moves.clear();
            for (size_t k = 0; k < moves->size() && k < 4; k++){
                if (auto* mv = (*moves)[k].to_string()) dst.known_moves.push_back(*mv);
            }
        }
        if (const JsonArray* evs = mon->get_array("evs")){
            for (size_t k = 0; k < evs->size() && k < 6; k++){
                int64_t v = 0;
                if ((*evs)[k].read_integer(v)) dst.evs[k] = (int)v;
            }
        }
    }
    return true;
}


//  Build the canonical filename for a team: sorted species slugs joined by
//  underscore, with ".json" appended. Same set of 6 in any order maps to
//  the same file. Empty slots are skipped.
static std::string team_filename(const std::array<std::string, 6>& species){
    std::vector<std::string> slugs;
    for (const auto& s : species){ if (!s.empty()) slugs.push_back(s); }
    std::sort(slugs.begin(), slugs.end());
    std::string out;
    for (size_t i = 0; i < slugs.size(); i++){
        if (i > 0) out += "_";
        out += slugs[i];
    }
    out += ".json";
    return out;
}

//  Cross-platform-ish mkdir-p. POSIX-only here since SerialPrograms targets
//  macOS / Linux / Windows-with-MSYS — Qt has QDir::mkpath but pulling that
//  in for one call is overkill.
#include <sys/stat.h>
static void ensure_dir(const std::string& path){
    if (path.empty()) return;
    mkdir(path.c_str(), 0755);
}


std::string BattleStateTracker::save_team_to_library(const std::string& dir) const{
    std::array<std::string, 6> species;
    for (uint8_t i = 0; i < 6; i++){
        if (m_own_team[i].species.empty()) return "";  // partial team — skip
        species[i] = m_own_team[i].species;
    }
    ensure_dir(dir);
    std::string path = dir;
    if (!path.empty() && path.back() != '/' && path.back() != '\\') path += '/';
    path += team_filename(species);
    if (save_team_to_file(path)) return path;
    return "";
}


bool BattleStateTracker::load_team_matching(
    const std::string& dir,
    const std::array<std::string, 6>& species
){
    //  All 6 species must be present (sorted-set lookup is meaningless
    //  with gaps). Caller should only invoke this when the selecting
    //  screen has full coverage.
    for (const auto& s : species){
        if (s.empty()) return false;
    }
    std::string path = dir;
    if (!path.empty() && path.back() != '/' && path.back() != '\\') path += '/';
    path += team_filename(species);
    return load_team_from_file(path);
}


void BattleStateTracker::reorder_own_team_to_screen(
    const std::array<std::string, 6>& screen_species
){
    //  For each screen position i, find which m_own_team[k] (k >= i) has
    //  the matching species and swap to position i. Empty inputs keep
    //  whatever's at that position. Stable for already-aligned teams.
    for (uint8_t i = 0; i < 6; i++){
        if (screen_species[i].empty()) continue;
        if (m_own_team[i].species == screen_species[i]) continue;
        for (uint8_t k = i + 1; k < 6; k++){
            if (m_own_team[k].species == screen_species[i]){
                std::swap(m_own_team[i], m_own_team[k]);
                break;
            }
        }
    }
}


void BattleStateTracker::set_own_leads(const std::vector<uint8_t>& leads){
    m_own_leads.clear();
    for (uint8_t s : leads){
        if (s < 6) m_own_leads.push_back(s);
    }
}


static int levenshtein_capped_(const std::string& a, const std::string& b, int cap){
    const int n = (int)a.size();
    const int m = (int)b.size();
    if (std::abs(n - m) > cap) return cap + 1;
    std::vector<int> prev(m + 1), cur(m + 1);
    for (int j = 0; j <= m; j++) prev[j] = j;
    for (int i = 1; i <= n; i++){
        cur[0] = i;
        int row_min = cur[0];
        for (int j = 1; j <= m; j++){
            int cost = (a[i - 1] == b[j - 1]) ? 0 : 1;
            cur[j] = std::min({prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost});
            if (cur[j] < row_min) row_min = cur[j];
        }
        if (row_min > cap) return cap + 1;
        std::swap(prev, cur);
    }
    return prev[m];
}

std::string team_bias_snap(
    const std::string& global_token,
    const std::vector<std::string>& candidates,
    int max_edit_distance
){
    if (global_token.empty() || candidates.empty()) return global_token;
    for (const auto& c : candidates){
        if (c == global_token) return global_token;
    }
    int best_d = max_edit_distance + 1;
    std::string best;
    for (const auto& c : candidates){
        int d = levenshtein_capped_(global_token, c, max_edit_distance);
        if (d < best_d){ best_d = d; best = c; }
    }
    return best.empty() ? global_token : best;
}


BattleSnapshot BattleStateTracker::snapshot() const{
    BattleSnapshot s;
    s.own_active_slots[0] = (int)m_own_active[0];
    s.own_active_slots[1] = (m_mode == BattleMode::DOUBLES) ? (int)m_own_active[1] : -1;
    s.opp_active_slots[0] = (int)m_opp_active[0];
    s.opp_active_slots[1] = (m_mode == BattleMode::DOUBLES) ? (int)m_opp_active[1] : -1;
    for (uint8_t i = 0; i < 6; i++){
        s.own_alive[i] = m_own_team[i].alive && m_own_team[i].hp > 0.0f;
    }
    for (uint8_t i = 0; i < m_opp_seen && i < 6; i++){
        s.opp_alive[i] = m_opp_team[i].alive && m_opp_team[i].hp > 0.0f;
    }
    s.weather = m_weather;
    s.terrain = m_terrain;
    s.trick_room = m_trick_room;
    s.tailwind_own = m_tailwind_own;
    s.tailwind_opp = m_tailwind_opp;
    s.screens_own = m_screens_own;
    s.screens_opp = m_screens_opp;
    s.turn = m_turn;
    s.mode = m_mode;
    return s;
}


TeamCandidates BattleStateTracker::candidates() const{
    TeamCandidates c;
    auto push_unique = [](std::vector<std::string>& v, const std::string& s){
        if (s.empty()) return;
        for (const auto& e : v) if (e == s) return;
        v.push_back(s);
    };
    for (uint8_t i = 0; i < 6; i++){
        push_unique(c.own_species,     m_own_team[i].species);
        push_unique(c.abilities_seen,  m_own_team[i].ability);
        push_unique(c.items_seen,      m_own_team[i].item);
        c.moves_for_own_slot[i] = m_own_team[i].known_moves;
    }
    for (uint8_t i = 0; i < m_opp_seen && i < 6; i++){
        push_unique(c.opp_species,     m_opp_team[i].species);
        push_unique(c.abilities_seen,  m_opp_team[i].ability);
        push_unique(c.items_seen,      m_opp_team[i].item);
    }
    c.own_brought_indices = m_own_leads;
    return c;
}


bool BattleStateTracker::apply_ability_item_reveal(
    const std::string& side,
    const std::string& pokemon_slug,
    const std::string& name_slug,
    const std::string& kind
){
    if (pokemon_slug.empty() || name_slug.empty()) return false;
    if (kind != "ability" && kind != "item") return false;

    auto try_apply = [&](TrackedPokemon& mon) -> bool {
        if (mon.species != pokemon_slug) return false;
        std::string& field = (kind == "ability") ? mon.ability : mon.item;
        if (field.empty()){
            field = name_slug;
        }
        //  Either way (already-known or just-set), reveal pins this to a
        //  fully-confident state — the popup is the ground truth.
        if (kind == "ability"){
            mon.ability_confidence = 1.0f;
        }else{
            mon.item_confidence = 1.0f;
        }
        return true;
    };

    //  Opp first (higher signal — own team is usually paste-loaded).
    //  `side` would let us prefer one half but us/them mapping varies by
    //  match; species match is the authoritative key.
    (void)side;
    for (auto& mon : m_opp_team){
        if (try_apply(mon)) return true;
    }
    for (auto& mon : m_own_team){
        if (try_apply(mon)) return true;
    }
    return false;
}


// ─── Move-name volatile inference ────────────────────────────────
//
//  For moves whose effect is a 1:1 deterministic volatile on a known
//  target, infer the volatile the moment MOVE_USED fires — skipping the
//  follow-up text entirely. Cheaper and more reliable than OCRing the
//  second message, and covers volatiles whose text we haven't built a
//  pattern for yet.
//
//  target_kind: SELF = applied to the mover, OPP = applied to the
//  opposite-side first active. ALLY is rare (Helping Hand, Rage Powder
//  in doubles) and not handled here.
//
//  Only includes moves where the effect cannot reasonably "fail" (or
//  where a stray false positive on a fail is harmless — the volatile
//  is cleared on the mon's next switch-out via reset_volatile). Moves
//  with miss/accuracy windows that could no-op the volatile are NOT
//  inferred here; their pattern-text match in BattleLogReader covers
//  the success case authoritatively.
enum class VolatileTarget { SELF, OPP };
struct MoveVolatileSpec {
    const char* volatile_name;
    VolatileTarget target;
};

static const MoveVolatileSpec* lookup_move_volatile(const std::string& move_slug){
    static const std::unordered_map<std::string, MoveVolatileSpec> table = {
        // ── Self-applied, deterministic — no accuracy check, no fail mode ──
        {"substitute",      {"SUBSTITUTE",   VolatileTarget::SELF}},
        {"protect",         {"PROTECT",      VolatileTarget::SELF}},
        {"detect",          {"PROTECT",      VolatileTarget::SELF}},
        {"endure",          {"ENDURE",       VolatileTarget::SELF}},
        {"kings-shield",    {"KINGSSHIELD",  VolatileTarget::SELF}},
        {"spiky-shield",    {"SPIKYSHIELD",  VolatileTarget::SELF}},
        {"baneful-bunker",  {"BANEFULBUNKER",VolatileTarget::SELF}},
        {"burning-bulwark", {"BURNINGBULWARK", VolatileTarget::SELF}},
        {"silk-trap",       {"SILKTRAP",     VolatileTarget::SELF}},
        {"max-guard",       {"MAXGUARD",     VolatileTarget::SELF}},
        {"focus-energy",    {"FOCUSENERGY",  VolatileTarget::SELF}},
        {"laser-focus",     {"LASERFOCUS",   VolatileTarget::SELF}},
        {"magnet-rise",     {"MAGNETRISE",   VolatileTarget::SELF}},
        {"ingrain",         {"INGRAIN",      VolatileTarget::SELF}},
        {"aqua-ring",       {"AQUARING",     VolatileTarget::SELF}},
        {"autotomize",      {"AUTOTOMIZE",   VolatileTarget::SELF}},
        {"charge",          {"CHARGE",       VolatileTarget::SELF}},
        {"defense-curl",    {"DEFENSECURL",  VolatileTarget::SELF}},
        {"destiny-bond",    {"DESTINYBOND",  VolatileTarget::SELF}},
        {"geomancy",        {"GEOMANCY",     VolatileTarget::SELF}},
        {"grudge",          {"GRUDGE",       VolatileTarget::SELF}},
        {"imprison",        {"IMPRISON",     VolatileTarget::SELF}},
        {"magic-coat",      {"MAGICCOAT",    VolatileTarget::SELF}},
        {"minimize",        {"MINIMIZE",     VolatileTarget::SELF}},
        {"no-retreat",      {"NORETREAT",    VolatileTarget::SELF}},
        {"power-shift",     {"POWERSHIFT",   VolatileTarget::SELF}},
        {"power-trick",     {"POWERTRICK",   VolatileTarget::SELF}},
        {"rage",            {"RAGE",         VolatileTarget::SELF}},
        {"rage-powder",     {"RAGEPOWDER",   VolatileTarget::SELF}},
        {"roost",           {"ROOST",        VolatileTarget::SELF}},
        {"snatch",          {"SNATCH",       VolatileTarget::SELF}},
        {"spotlight",       {"SPOTLIGHT",    VolatileTarget::SELF}},
        {"stockpile",       {"STOCKPILE",    VolatileTarget::SELF}},
        {"follow-me",       {"FOLLOWME",     VolatileTarget::SELF}},
        {"helping-hand",    {"HELPINGHAND",  VolatileTarget::SELF}},
        {"conversion",      {"TYPECHANGE",   VolatileTarget::SELF}},
        {"conversion-2",    {"TYPECHANGE",   VolatileTarget::SELF}},

        // ── Charging-turn (multi-turn moves) — the volatile is the prep
        //    state. Cleared on the resolve turn or on switch-out. Inferring
        //    on MOVE_USED is correct for the prep turn; the resolve turn
        //    fires MOVE_USED again and we'll re-set it (idempotent). The
        //    volatile gets cleared via reset_volatile on switch-out.
        {"bide",            {"BIDE",         VolatileTarget::SELF}},
        {"bounce",          {"BOUNCE",       VolatileTarget::SELF}},
        {"dig",             {"DIG",          VolatileTarget::SELF}},
        {"dive",            {"DIVE",         VolatileTarget::SELF}},
        {"fly",             {"FLY",          VolatileTarget::SELF}},
        {"phantom-force",   {"PHANTOMFORCE", VolatileTarget::SELF}},
        {"razor-wind",      {"RAZORWIND",    VolatileTarget::SELF}},
        {"shadow-force",    {"SHADOWFORCE",  VolatileTarget::SELF}},
        {"sky-attack",      {"SKYATTACK",    VolatileTarget::SELF}},
        {"sky-drop",        {"SKYDROP",      VolatileTarget::SELF}},
        {"solar-beam",      {"SOLARBEAM",    VolatileTarget::SELF}},
        {"solar-blade",     {"SOLARBLADE",   VolatileTarget::SELF}},
        {"skull-bash",      {"SKULLBASH",    VolatileTarget::SELF}},
        {"meteor-beam",     {"METEORBEAM",   VolatileTarget::SELF}},
        {"freeze-shock",    {"FREEZESHOCK",  VolatileTarget::SELF}},
        {"ice-burn",        {"ICEBURN",      VolatileTarget::SELF}},
        {"electro-shot",    {"ELECTROSHOT",  VolatileTarget::SELF}},
        {"sparkling-aria",  {"SPARKLINGARIA",VolatileTarget::SELF}},
        {"uproar",          {"UPROAR",       VolatileTarget::SELF}},
    };
    auto it = table.find(move_slug);
    if (it == table.end()) return nullptr;
    return &it->second;
}


// ─── Updates ─────────────────────────────────────────────────────

void BattleStateTracker::update_from_hud(const BattleHUDState& hud){
    //  HUD always exposes both slots; slot 0 is empty for singles. The
    //  tracker keeps its own slot-0-first internal indexing, so we
    //  remap: in singles, read HUD slot 1 (the lone visible mon) but
    //  write to tracker slot 0.
    uint8_t slots = (m_mode == BattleMode::DOUBLES) ? 2 : 1;

    for (uint8_t i = 0; i < slots; i++){
        uint8_t hud_slot = (m_mode == BattleMode::DOUBLES) ? i : 1;
        const auto& opp = hud.opponents[hud_slot];
        if (!opp.species.empty()){
            uint8_t idx = find_or_add_opponent(opp.species);
            m_opp_active[i] = idx;
            if (opp.hp_pct >= 0){
                m_opp_team[idx].hp = opp.hp_pct / 100.0f;
            }
        }

        const auto& own = hud.own[hud_slot];
        //  Remap m_own_active[i] to whichever team slot has the species
        //  currently shown on the HUD. Without this, m_own_active stays
        //  pinned to the initial leads {0,1} and the suggester treats the
        //  on-field mon as a valid switch target. Only remap when we have
        //  a non-empty species AND a matching team slot — otherwise keep
        //  the prior mapping so a missed-species poll doesn't clobber.
        if (!own.species.empty()){
            for (uint8_t j = 0; j < 6; j++){
                if (!m_own_team[j].species.empty() && m_own_team[j].species == own.species){
                    m_own_active[i] = j;
                    break;
                }
            }
        }
        if (own.hp_current >= 0 && own.hp_max > 0){
            m_own_team[m_own_active[i]].hp = static_cast<float>(own.hp_current) / own.hp_max;
        }
    }

    //  Per-move PP for the slot-0 own active mon (move-select HUD only shows
    //  the active mon's moves; in doubles the slot-1 active gets its PP read
    //  the next time we re-enter move_select for it).
    auto& own_active_mon = m_own_team[m_own_active[0]];
    for (uint8_t m = 0; m < 4; m++){
        if (hud.move_pp[m].current >= 0 && hud.move_pp[m].max > 0){
            own_active_mon.move_pp[m].current = hud.move_pp[m].current;
            own_active_mon.move_pp[m].max = hud.move_pp[m].max;
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

//  Resolve which active position (0 or 1) on the given side an event refers
//  to. BattleLogEvent does not (currently) carry an explicit position field,
//  so we match `pokemon_display` (raw display name from the OCR'd log line,
//  e.g. "Volcarona" or "The opposing Volcarona") against the species slug of
//  the on-field mons. Returns -1 if no match.
//
//  TODO: if BattleLogReader is later extended to emit event.position, prefer
//  that signal and use this species-match only as the fallback (logging an
//  orange line when the fallback fires, so we can see real wild cases).
//
//  Ambiguity case: in doubles two active mons may share a species root
//  (Urshifu-Single-Strike + Urshifu-Rapid-Strike). When both actives match
//  the display name we return position 0 and log a COLOR_ORANGE warning so
//  the bad attribution is visible. Real disambiguation would need the
//  position field from the reader.
//
//  In SINGLES only position 0 is valid; we still attempt position 0 (and
//  ignore an erroneous position 1 in active[]) by capping `positions`.
static int resolve_active_position(
    const std::string& pokemon_display,
    const std::array<TrackedPokemon, 6>& team,
    const std::array<uint8_t, 2>& active,
    BattleMode mode
){
    if (pokemon_display.empty()) return -1;
    std::string lower = pokemon_display;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    uint8_t positions = (mode == BattleMode::DOUBLES) ? 2 : 1;
    int first_hit = -1;
    int hit_count = 0;
    for (uint8_t i = 0; i < positions; i++){
        uint8_t slot = active[i];
        if (slot >= 6) continue;
        const std::string& sp = team[slot].species;
        if (sp.empty()) continue;
        if (lower.find(sp) != std::string::npos ||
            sp.find(lower) != std::string::npos)
        {
            if (first_hit < 0) first_hit = (int)i;
            hit_count++;
        }
    }
    if (hit_count > 1){
        global_logger_tagged().log(
            "resolve_active_position: ambiguous species match for '" +
            pokemon_display + "' (both actives matched) — defaulting to pos " +
            std::to_string(first_hit),
            COLOR_ORANGE
        );
    }
    return first_hit;
}

void BattleStateTracker::update_from_log(const BattleLogEvent& event){
    switch (event.type){
    case BattleLogEventType::MOVE_USED:{
        //  Per-side last-move ledger — encoder reads last_move_p1/p2 as
        //  vocab IDs, we keep them as slugs and resolve at request time.
        const std::string slug = to_slug(event.move);
        if (event.is_opponent){
            m_last_move_opp = slug;
        }else{
            m_last_move_own = slug;
        }

        //  Per-mon last-move. Per-side is just a derivation of "whichever
        //  active mon moved most recently"; the per-mon value is the
        //  ground truth for encore / instruct / mimic predicates and for
        //  attributing the side-level value to the right slot. Match by
        //  species against active mons on the moving side; persists
        //  across switch-out so re-entry doesn't lose the history.
        {
            std::string lower_pokemon = event.pokemon;
            std::transform(lower_pokemon.begin(), lower_pokemon.end(),
                           lower_pokemon.begin(), ::tolower);
            auto& team = event.is_opponent ? m_opp_team : m_own_team;
            auto& active = event.is_opponent ? m_opp_active : m_own_active;
            uint8_t positions = (m_mode == BattleMode::DOUBLES) ? 2 : 1;
            for (uint8_t i = 0; i < positions; i++){
                auto& mon = team[active[i]];
                if (mon.species.empty()) continue;
                if (lower_pokemon.find(mon.species) != std::string::npos
                    || mon.species.find(lower_pokemon) != std::string::npos){
                    mon.last_move = slug;
                    break;
                }
            }
        }

        //  Move-name volatile inference. Catches the "one move = one
        //  volatile" cases (Substitute, Protect, Roost, Magnet Rise,
        //  multi-turn prep states, etc.) without needing a follow-up
        //  text pattern. The volatile_statuses vector dedupes on push.
        const MoveVolatileSpec* spec = lookup_move_volatile(slug);
        if (spec != nullptr){
            //  Side resolution:
            //    SELF + opp move → opp active[0]
            //    SELF + own move → own active[0]
            //    OPP  + opp move → own active[0]
            //    OPP  + own move → opp active[0]
            bool target_is_opp_side = event.is_opponent;
            if (spec->target == VolatileTarget::OPP){
                target_is_opp_side = !target_is_opp_side;
            }
            auto& team = target_is_opp_side ? m_opp_team : m_own_team;
            auto& active = target_is_opp_side ? m_opp_active : m_own_active;
            auto& mon = team[active[0]];
            std::string name = spec->volatile_name;
            bool present = std::find(
                mon.volatile_statuses.begin(),
                mon.volatile_statuses.end(), name)
                != mon.volatile_statuses.end();
            if (!present){
                mon.volatile_statuses.push_back(name);
            }
            if (name == "SUBSTITUTE"){
                mon.substitute_hp_frac = 1.0f;
            }
        }

        //  Per-turn history: record this move on the most recent history
        //  entry under the right [own_a, own_b, opp_a, opp_b] slot. The
        //  history snapshot is pushed by the trace on each action_menu
        //  re-entry; if we have no entry yet (move fired before our first
        //  snapshot) we simply drop the attribution.
        if (!m_history.empty() && !slug.empty()){
            const auto& team = event.is_opponent ? m_opp_team : m_own_team;
            const auto& active = event.is_opponent ? m_opp_active : m_own_active;
            int pos = resolve_active_position(event.pokemon, team, active, m_mode);
            if (pos >= 0){
                int idx = (event.is_opponent ? 2 : 0) + pos;
                if (idx >= 0 && idx < 4){
                    m_history.back().action_moves[idx] = slug;
                    m_history.back().action_types[idx] = "move";
                    //  Stamp the slot's rank in this turn's MOVE_USED
                    //  sequence — but only the *first* MOVE_USED for the
                    //  slot. Multi-hit moves and status events re-fire
                    //  MOVE_USED, and we don't want those to bump the
                    //  rank away from "went first/second/...".
                    if (m_history.back().move_order[idx] < 0){
                        m_history.back().move_order[idx] = m_turn_move_count++;
                    }
                }
            }
        }

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
                        std::string move_slug = to_slug(event.move);
                        mon.add_move(move_slug);
                        //  Confidence bump: the move is now positively
                        //  revealed in-battle (vs team-paste prior).
                        for (size_t k = 0; k < mon.known_moves.size() && k < 4; k++){
                            if (mon.known_moves[k] == move_slug){
                                mon.move_confidences[k] = 1.0f;
                                break;
                            }
                        }
                        break;
                    }
                }
            }
        }else{
            //  Proactive Choice-lock: when an own mon holding a Choice item
            //  uses a move, the next turn locks them into that move. Set
            //  locked_to_move now so the next move_select roll picks that
            //  slot directly instead of trial-and-erroring through the
            //  in-game rejection toast.
            //
            //  Matched by species (event.pokemon is the visible name, not a
            //  slot index). Walk both active positions to handle doubles.
            std::string lower_pokemon = event.pokemon;
            std::transform(lower_pokemon.begin(), lower_pokemon.end(),
                           lower_pokemon.begin(), ::tolower);
            uint8_t positions = (m_mode == BattleMode::DOUBLES) ? 2 : 1;
            for (uint8_t i = 0; i < positions; i++){
                auto& mon = m_own_team[m_own_active[i]];
                if (mon.species.empty()) continue;
                bool species_match =
                    lower_pokemon.find(mon.species) != std::string::npos
                    || mon.species.find(lower_pokemon) != std::string::npos;
                if (!species_match) continue;
                //  Choice items: choice-band / choice-specs / choice-scarf.
                //  Item slugs are stored lowercase-with-dashes.
                bool is_choice_item =
                    mon.item == "choice-scarf"
                    || mon.item == "choice-band"
                    || mon.item == "choice-specs";
                if (is_choice_item){
                    mon.locked_to_move = to_slug(event.move);
                }
                break;
            }
        }
        break;
    }

    case BattleLogEventType::MOVE_LOCKED:{
        //  Reactive lock — the user tried an illegal move and got the
        //  rejection toast. The text names the legal move, so we set the
        //  active own mon's locked_to_move directly. Always own-side
        //  (the opponent's lock state is hidden in normal play).
        //
        //  In doubles we don't know which of the two active mons owns the
        //  rejection — it fires while a specific move_select is on screen,
        //  but BattleLogEvent doesn't carry the active position. The
        //  ActiveHUDSlotDetector / MoveNameReader::read_active_slot would
        //  be the right cross-reference, but the simple "first active that
        //  holds a Choice item" heuristic is correct for ~all real lock
        //  cases (a Choice mon can be locked; a non-Choice mon can't).
        uint8_t positions = (m_mode == BattleMode::DOUBLES) ? 2 : 1;
        std::string locked = to_slug(event.move);
        for (uint8_t i = 0; i < positions; i++){
            auto& mon = m_own_team[m_own_active[i]];
            bool is_choice_item =
                mon.item == "choice-scarf"
                || mon.item == "choice-band"
                || mon.item == "choice-specs";
            //  If we don't yet know the item (item OCR pending), still
            //  apply on position 0 — singles always, doubles is a guess.
            //  The lock will be overwritten on the next MOVE_USED if wrong.
            if (is_choice_item || (i == 0 && mon.item.empty())){
                mon.locked_to_move = locked;
                break;
            }
        }
        break;
    }

    case BattleLogEventType::STAT_CHANGE:{
        //  Find the Pokemon and apply boost.
        //  event.stat may be "Atk", "Sp. Atk", "Speed", or comma-separated.
        //  event.boost_stages = +1, -1, +2, etc.
        //  For now, handle single-stat changes.
        //
        //  Server schema accepts atk/def/spa/spd/spe/accuracy/evasion (7-D)
        //  but the C++ side stores 6-D (no accuracy) — PS does emit accuracy
        //  changes but they're rare and not in the encoder's boost slot
        //  ordering anyway, so we drop them.
        int idx = stat_name_to_index(event.stat);
        if (idx >= 0){
            auto& team = event.is_opponent ? m_opp_team : m_own_team;
            auto& active = event.is_opponent ? m_opp_active : m_own_active;
            //  Resolve the affected active position via species match; in
            //  doubles this is the only way to disambiguate. Falls back to
            //  position 0 (the historical behavior) when the species lookup
            //  doesn't land.
            int pos = resolve_active_position(event.pokemon, team, active, m_mode);
            if (pos < 0) pos = 0;
            uint8_t slot = active[pos];
            if (slot < 6){
                team[slot].boosts[idx] = static_cast<int8_t>(std::clamp(
                    static_cast<int>(team[slot].boosts[idx]) + event.boost_stages, -6, 6
                ));
            }
        }
        break;
    }

    case BattleLogEventType::STAT_CHANGE_OTHER:{
        //  STAT_CHANGE_OTHER aggregates every non-numeric stat mutation in
        //  PS's default.ts. Route by raw_text keyword.
        //
        //  Wired:
        //    clearAllBoost            "All stat changes were eliminated!"   (Haze)
        //    clearBoost               "[POKEMON]'s stat changes were removed!"
        //    invertBoost              "[POKEMON]'s stat changes were inverted!"
        //    clearBoostFromZEffect    "[POKEMON] returned its decreased stats to normal …"
        //    swapBoost                "[POKEMON] switched stat changes with its target!"
        //
        //  TODOs (rarely seen in Champions, deferred):
        //    swapDefensiveBoost  — Power Swap-style cross-mon variant
        //    swapOffensiveBoost  — same family
        //    copyBoost           — Psych Up
        const std::string& raw = event.raw_text;

        //  clearAllBoost — Haze. Both sides, both active positions.
        if (raw.find("All stat changes were eliminated") != std::string::npos){
            for (auto& mon : m_own_team) mon.boosts.fill(0);
            for (auto& mon : m_opp_team) mon.boosts.fill(0);
            break;
        }

        auto& team = event.is_opponent ? m_opp_team : m_own_team;
        auto& active = event.is_opponent ? m_opp_active : m_own_active;
        int pos = resolve_active_position(event.pokemon, team, active, m_mode);
        if (pos < 0) pos = 0;
        uint8_t slot = active[pos];
        if (slot >= 6) break;

        //  clearBoost — clear all boosts on one mon.
        if (raw.find("stat changes were removed") != std::string::npos){
            team[slot].boosts.fill(0);
            break;
        }

        //  invertBoost — negate every boost stage on one mon.
        if (raw.find("stat changes were inverted") != std::string::npos){
            for (auto& b : team[slot].boosts){
                b = static_cast<int8_t>(std::clamp(-static_cast<int>(b), -6, 6));
            }
            break;
        }

        //  clearBoostFromZEffect — zero only the negative entries; leave
        //  positives intact. "returned its decreased stats to normal".
        if (raw.find("returned its decreased stats to normal") != std::string::npos){
            for (auto& b : team[slot].boosts){
                if (b < 0) b = 0;
            }
            break;
        }

        //  swapBoost — swap boost arrays between actor and target. The log
        //  line names only the actor; we assume the target is the opposing
        //  active in the same lane position (matches typical doubles use of
        //  Power Trick / Heart Swap etc. on a same-lane target). Singles
        //  always pos 0 ↔ pos 0.
        //  TODO: BattleLogEvent doesn't carry the target — if a future
        //  reader pass adds it, prefer that.
        if (raw.find("switched stat changes with its target") != std::string::npos){
            auto& other_team = event.is_opponent ? m_own_team : m_opp_team;
            auto& other_active = event.is_opponent ? m_own_active : m_opp_active;
            uint8_t other_slot = other_active[pos];
            if (other_slot < 6){
                std::swap(team[slot].boosts, other_team[other_slot].boosts);
            }
            break;
        }

        break;
    }

    case BattleLogEventType::STATUS_INFLICTED:{
        //  event.stat contains the human status name ("burned", "paralyzed",
        //  "badly poisoned", etc.) — populated by the generator from PS's
        //  static_stat field. Map to canonical server slugs.
        //  Check "badly poison" before "poison" — substring order matters.
        std::string status;
        if      (event.stat.find("burn") != std::string::npos)        status = "brn";
        else if (event.stat.find("paralyz") != std::string::npos)     status = "par";
        else if (event.stat.find("badly poison") != std::string::npos) status = "tox";
        else if (event.stat.find("poison") != std::string::npos)      status = "psn";
        else if (event.stat.find("sleep") != std::string::npos)       status = "slp";
        else if (event.stat.find("asleep") != std::string::npos)      status = "slp";
        else if (event.stat.find("froz") != std::string::npos)        status = "frz";

        if (!status.empty()){
            auto& team = event.is_opponent ? m_opp_team : m_own_team;
            auto& active = event.is_opponent ? m_opp_active : m_own_active;
            int pos = resolve_active_position(event.pokemon, team, active, m_mode);
            if (pos < 0) pos = 0;
            uint8_t slot = active[pos];
            if (slot < 6){
                auto& mon = team[slot];
                mon.status = status;
                //  Seed duration counters from the inflict event so the
                //  encoder always sees a defensible value, not 0.
                if (status == "slp"){
                    //  Game range is 1-3 turns; without knowing the roll we
                    //  default to 3 (worst case for the player). Wake-up
                    //  will fire STATUS_HEALED which clears status.
                    mon.sleep_turns_remaining = 3;
                }else if (status == "tox"){
                    mon.toxic_counter = 1;
                }
            }
        }
        break;
    }

    case BattleLogEventType::STATUS_HEALED:{
        //  Clear status when the mon is cured (woke up, thawed, paralysis
        //  healed, etc.). The reader's static_stat field carries the
        //  matched status name; we don't need to dispatch on it since the
        //  game only ever has one primary status at a time, so any
        //  STATUS_HEALED on the named mon clears whichever status it had.
        //  FAINTED clears alive but leaves status untouched; that's fine —
        //  to_predict_json gates on alive, so a stale status string on a
        //  dead mon never reaches the encoder.
        auto& team = event.is_opponent ? m_opp_team : m_own_team;
        auto& active = event.is_opponent ? m_opp_active : m_own_active;
        int pos = resolve_active_position(event.pokemon, team, active, m_mode);
        if (pos < 0) pos = 0;
        uint8_t slot = active[pos];
        if (slot < 6){
            auto& mon = team[slot];
            mon.status.clear();
            mon.sleep_turns_remaining = 0;
            mon.toxic_counter = 0;
        }
        break;
    }

    case BattleLogEventType::MEGA_EVOLVE:{
        //  "Charizard has Mega Evolved into Mega Charizard X!" — set is_mega
        //  on whichever active mon (own or opp) matches the species. Belt-
        //  and-suspenders against the C++ R-toggle that sends the input.
        std::string lower = event.pokemon;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        auto& team = event.is_opponent ? m_opp_team : m_own_team;
        auto& active = event.is_opponent ? m_opp_active : m_own_active;
        for (uint8_t i = 0; i < 2; i++){
            auto& mon = team[active[i]];
            if (!mon.species.empty() &&
                (lower.find(mon.species) != std::string::npos ||
                 mon.species.find(lower) != std::string::npos))
            {
                mon.is_mega = true;
                break;
            }
        }
        break;
    }

    case BattleLogEventType::SWITCH_IN:{
        //  Slot tracking on switch comes from the HUD species reader, not
        //  from this log line — BattleLogEvent has no `position` field, and
        //  unconditionally writing m_opp_active[0] would clobber the
        //  right-side slot in doubles. We still ensure the species is in the
        //  roster so it appears in the bench until HUD assigns it a slot.
        if (event.is_opponent && !event.pokemon.empty()){
            std::string species = event.pokemon;
            std::transform(species.begin(), species.end(), species.begin(), ::tolower);
            uint8_t idx = find_or_add_opponent(species);
            m_opp_team[idx].reset_volatile();
        }else if (!event.is_opponent && !event.pokemon.empty()){
            //  Own switch. Walk all 6 team slots looking for the new
            //  active species, then update m_own_active so subsequent
            //  reads / suggestions know who's actually on field. The HUD
            //  reader will confirm it within ~250ms but the log line
            //  fires on the same poll the swap announces, so we get a
            //  faster signal here. We don't know which active position
            //  (0 vs 1 in doubles) the switch went into — pick the slot
            //  whose current m_own_active mon is no longer alive (faint
            //  switch), else the slot whose species doesn't match an
            //  active any more, else default to 0.
            std::string lower = event.pokemon;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
            int new_team_slot = -1;
            for (uint8_t j = 0; j < 6; j++){
                const auto& mon = m_own_team[j];
                if (!mon.species.empty() &&
                    (lower.find(mon.species) != std::string::npos ||
                     mon.species.find(lower) != std::string::npos))
                {
                    new_team_slot = j;
                    break;
                }
            }
            if (new_team_slot >= 0){
                //  Singles only ever has one active position. Iterating
                //  both in singles would let m_own_active[1] (still at
                //  its init value of 1) match a fainted mon and steer
                //  the write to the wrong slot.
                const uint8_t positions = (m_mode == BattleMode::DOUBLES) ? 2 : 1;
                int target_pos = -1;
                for (uint8_t i = 0; i < positions; i++){
                    if (!m_own_team[m_own_active[i]].alive){ target_pos = i; break; }
                }
                if (target_pos < 0){
                    //  No fainted active — voluntary switch. In doubles
                    //  pick the position whose mon doesn't match the new
                    //  species; singles always lands on position 0.
                    for (uint8_t i = 0; i < positions; i++){
                        if (m_own_active[i] != new_team_slot){ target_pos = i; break; }
                    }
                    if (target_pos < 0) target_pos = 0;
                }
                m_own_active[target_pos] = (uint8_t)new_team_slot;
                m_own_team[new_team_slot].reset_volatile();
            }
        }
        break;
    }

    case BattleLogEventType::VOLATILE_START:{
        //  Add canonical volatile name to the active mon's list (no dup).
        //  Substitute also sets substitute_hp_frac = 1.0 — the active mon
        //  just dropped 25% HP to spawn the sub at full sub-HP.
        auto& team = event.is_opponent ? m_opp_team : m_own_team;
        auto& active = event.is_opponent ? m_opp_active : m_own_active;
        auto& mon = team[active[0]];
        const std::string& name = event.effect;
        if (!name.empty()){
            bool present = std::find(
                mon.volatile_statuses.begin(),
                mon.volatile_statuses.end(), name)
                != mon.volatile_statuses.end();
            if (!present){
                mon.volatile_statuses.push_back(name);
            }
            if (name == "SUBSTITUTE"){
                mon.substitute_hp_frac = 1.0f;
            }
        }
        break;
    }

    case BattleLogEventType::VOLATILE_END:{
        auto& team = event.is_opponent ? m_opp_team : m_own_team;
        auto& active = event.is_opponent ? m_opp_active : m_own_active;
        auto& mon = team[active[0]];
        const std::string& name = event.effect;
        if (!name.empty()){
            auto it = std::find(
                mon.volatile_statuses.begin(),
                mon.volatile_statuses.end(), name);
            if (it != mon.volatile_statuses.end()){
                mon.volatile_statuses.erase(it);
            }
            if (name == "SUBSTITUTE"){
                mon.substitute_hp_frac = 0.0f;
            }
        }
        break;
    }

    case BattleLogEventType::HAZARD_SET:{
        //  event.is_opponent identifies whose team the hazard sits on (the
        //  affected side, not the user who set it). "all" via Defog text
        //  is treated as clear-all on the named side.
        Hazards& h = event.is_opponent ? m_hazards_opp : m_hazards_own;
        const std::string& kind = event.effect;
        if      (kind == "stealth_rock") h.stealth_rock = true;
        else if (kind == "spikes")       h.spikes_layers = std::min<uint8_t>(3, h.spikes_layers + 1);
        else if (kind == "toxic_spikes") h.toxic_spikes_layers = std::min<uint8_t>(2, h.toxic_spikes_layers + 1);
        else if (kind == "sticky_web")   h.sticky_web = true;
        break;
    }

    case BattleLogEventType::HAZARD_CLEAR:{
        //  Rapid Spin / Defog / Mortal Spin / Tidy Up — clear all hazards
        //  on the named side. event.is_opponent identifies the cleared side.
        Hazards& h = event.is_opponent ? m_hazards_opp : m_hazards_own;
        h = Hazards{};
        break;
    }

    case BattleLogEventType::SIDE_START:{
        const std::string& kind = event.effect;
        if (event.is_opponent){
            if      (kind == "tailwind"){     m_tailwind_opp = true;  m_timers_opp.tailwind = 4; }
            else if (kind == "light_screen"){ m_screens_opp[0] = true; m_timers_opp.light_screen = 5; }
            else if (kind == "reflect"){      m_screens_opp[1] = true; m_timers_opp.reflect = 5; }
            else if (kind == "aurora_veil"){  m_screens_opp[2] = true; m_timers_opp.aurora_veil = 5; }
            else if (kind == "safeguard"){    m_hazards_opp.safeguard = true; }
            else if (kind == "mist"){         m_hazards_opp.mist = true; }
            else if (kind == "lucky_chant"){  m_hazards_opp.lucky_chant = true; }
        }else{
            if      (kind == "tailwind"){     m_tailwind_own = true;  m_timers_own.tailwind = 4; }
            else if (kind == "light_screen"){ m_screens_own[0] = true; m_timers_own.light_screen = 5; }
            else if (kind == "reflect"){      m_screens_own[1] = true; m_timers_own.reflect = 5; }
            else if (kind == "aurora_veil"){  m_screens_own[2] = true; m_timers_own.aurora_veil = 5; }
            else if (kind == "safeguard"){    m_hazards_own.safeguard = true; }
            else if (kind == "mist"){         m_hazards_own.mist = true; }
            else if (kind == "lucky_chant"){  m_hazards_own.lucky_chant = true; }
        }
        break;
    }

    case BattleLogEventType::SIDE_END:{
        const std::string& kind = event.effect;
        if (event.is_opponent){
            if      (kind == "tailwind"){     m_tailwind_opp = false; m_timers_opp.tailwind = 0; }
            else if (kind == "light_screen"){ m_screens_opp[0] = false; m_timers_opp.light_screen = 0; }
            else if (kind == "reflect"){      m_screens_opp[1] = false; m_timers_opp.reflect = 0; }
            else if (kind == "aurora_veil"){  m_screens_opp[2] = false; m_timers_opp.aurora_veil = 0; }
            else if (kind == "safeguard"){    m_hazards_opp.safeguard = false; }
            else if (kind == "mist"){         m_hazards_opp.mist = false; }
            else if (kind == "lucky_chant"){  m_hazards_opp.lucky_chant = false; }
        }else{
            if      (kind == "tailwind"){     m_tailwind_own = false; m_timers_own.tailwind = 0; }
            else if (kind == "light_screen"){ m_screens_own[0] = false; m_timers_own.light_screen = 0; }
            else if (kind == "reflect"){      m_screens_own[1] = false; m_timers_own.reflect = 0; }
            else if (kind == "aurora_veil"){  m_screens_own[2] = false; m_timers_own.aurora_veil = 0; }
            else if (kind == "safeguard"){    m_hazards_own.safeguard = false; }
            else if (kind == "mist"){         m_hazards_own.mist = false; }
            else if (kind == "lucky_chant"){  m_hazards_own.lucky_chant = false; }
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
            //  Lock state dies with the mon — next replacement is fresh.
            team[active[i]].locked_to_move.clear();
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

    //  Decrement side-condition timers. Bool flags stay live as long as
    //  the counter is non-zero; the SIDE_END event will clean them up
    //  authoritatively when the log says so, but this decrement keeps
    //  the timer field meaningful when log events are missed.
    auto tick = [](SideTimers& t, bool& tw, std::array<bool, 3>& sc){
        if (t.tailwind > 0)     { t.tailwind--;     if (t.tailwind == 0) tw = false; }
        if (t.light_screen > 0) { t.light_screen--; if (t.light_screen == 0) sc[0] = false; }
        if (t.reflect > 0)      { t.reflect--;      if (t.reflect == 0) sc[1] = false; }
        if (t.aurora_veil > 0)  { t.aurora_veil--;  if (t.aurora_veil == 0) sc[2] = false; }
    };
    tick(m_timers_own, m_tailwind_own, m_screens_own);
    tick(m_timers_opp, m_tailwind_opp, m_screens_opp);

    //  Status duration counters on the active mons. Sleep ticks down each
    //  turn; toxic counter goes up (1 → 2 → 3 → …). Real game uses random
    //  1-3 turns for sleep; we initialize at 3 and the actual wake-up is
    //  signaled by STATUS_HEALED.
    auto tick_status = [](TrackedPokemon& mon){
        if (mon.sleep_turns_remaining > 0) mon.sleep_turns_remaining--;
        if (mon.status == "tox" && mon.toxic_counter < 15){
            mon.toxic_counter++;
        }
    };
    uint8_t positions = (m_mode == BattleMode::DOUBLES) ? 2 : 1;
    for (uint8_t i = 0; i < positions; i++){
        tick_status(m_own_team[m_own_active[i]]);
        tick_status(m_opp_team[m_opp_active[i]]);
    }
}


// ─── Opponent tracking ───────────────────────────────────────────

uint8_t BattleStateTracker::find_or_add_opponent(const std::string& species){
    //  Normalize to lowercase.
    std::string lower = species;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    //  1) Match by species (preview-seeded or already-seen).
    for (uint8_t i = 0; i < m_opp_seen; i++){
        if (m_opp_team[i].species == lower){
            return i;
        }
    }
    //  2) Fill an empty-species slot inside m_opp_seen (preview gap from OCR miss).
    for (uint8_t i = 0; i < m_opp_seen; i++){
        if (m_opp_team[i].species.empty()){
            m_opp_team[i].species = lower;
            m_opp_team[i].alive = true;
            return i;
        }
    }
    //  3) Append.
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

static JsonObject pokemon_to_json(const TrackedPokemon& p, int slot = -1, bool is_opponent = false){
    JsonObject obj;
    if (slot >= 0) obj["slot"] = JsonValue(static_cast<int64_t>(slot));
    obj["species"] = JsonValue(p.species);
    obj["hp"] = JsonValue(static_cast<double>(p.hp));
    obj["status"] = JsonValue(p.status);

    //  Opponent set prior: when a known opp species hasn't yet revealed
    //  its item / ability / moves, backfill from the Smogon-chaos prior
    //  for this format. The model was trained on progressive revelation
    //  but a *completely* empty slug maps to UNK at the tokenizer; the
    //  prior gives us a sensible default that's still distinguishable
    //  from a revealed value via the confidence channels (which stay
    //  at 0.0 — already the case for unrevealed fields).
    OppSetPrior prior;
    if (is_opponent && !p.species.empty()){
        prior = opp_set_prior_for(p.species);
    }
    const std::string item_out = (is_opponent && p.item.empty()) ? prior.item : p.item;
    const std::string ability_out = (is_opponent && p.ability.empty()) ? prior.ability : p.ability;
    obj["item"] = JsonValue(item_out);
    obj["ability"] = JsonValue(ability_out);
    obj["is_mega"] = JsonValue(p.is_mega);
    obj["alive"] = JsonValue(p.alive);

    JsonArray moves;
    if (is_opponent && p.known_moves.empty()){
        for (const auto& m : prior.moves){
            if (!m.empty()) moves.push_back(JsonValue(m));
        }
    }else{
        for (const auto& m : p.known_moves){
            moves.push_back(JsonValue(m));
        }
    }
    obj["moves"] = JsonValue(std::move(moves));

    //  Stat boosts. Internal layout is 6-D (atk/def/spa/spd/spe/evasion);
    //  the encoder expects 7-D (atk/def/spa/spd/spe/accuracy/evasion). Slot
    //  an explicit 0 at the accuracy index so consumers can index the
    //  array uniformly. JSON shape:
    //    [atk, def, spa, spd, spe, accuracy=0, evasion]
    JsonArray boosts;
    for (size_t i = 0; i < 5; i++){
        boosts.push_back(JsonValue(static_cast<int64_t>(p.boosts[i])));
    }
    boosts.push_back(JsonValue(static_cast<int64_t>(0)));         //  accuracy
    boosts.push_back(JsonValue(static_cast<int64_t>(p.boosts[5])));  //  evasion
    obj["boosts"] = JsonValue(std::move(boosts));

    //  Per-move PP, aligned to known_moves order. Each entry is [current, max]
    //  or null when unread (-1 sentinel from BattleHUDState).
    JsonArray move_pp;
    for (const auto& pp : p.move_pp){
        if (pp.current >= 0 && pp.max > 0){
            JsonArray pair;
            pair.push_back(JsonValue(static_cast<int64_t>(pp.current)));
            pair.push_back(JsonValue(static_cast<int64_t>(pp.max)));
            move_pp.push_back(JsonValue(std::move(pair)));
        }else{
            move_pp.push_back(JsonValue());  //  null
        }
    }
    obj["move_pp"] = JsonValue(std::move(move_pp));

    //  Volatile-status names, encoder-canonical uppercase form. Empty list
    //  is the "no volatile" sentinel and what every empty slot defaults to.
    JsonArray volatiles;
    for (const auto& v : p.volatile_statuses){
        volatiles.push_back(JsonValue(v));
    }
    obj["volatile_statuses"] = JsonValue(std::move(volatiles));
    obj["substitute_hp_frac"] = JsonValue(static_cast<double>(p.substitute_hp_frac));

    //  Reveal confidences in [0, 1]. 1.0 = positively revealed in-battle;
    //  0.0 = pre-match prior / no signal. Per-move confidence array is
    //  aligned to known_moves order, padded with 0s.
    obj["item_confidence"] = JsonValue(static_cast<double>(p.item_confidence));
    obj["ability_confidence"] = JsonValue(static_cast<double>(p.ability_confidence));
    JsonArray move_confs;
    for (size_t i = 0; i < 4; i++){
        move_confs.push_back(JsonValue(static_cast<double>(p.move_confidences[i])));
    }
    obj["move_confidences"] = JsonValue(std::move(move_confs));

    //  Status duration counters. Encoder reads these as ints; 0 = no
    //  counter for that status (or unknown).
    obj["sleep_turns_remaining"] = JsonValue(static_cast<int64_t>(p.sleep_turns_remaining));
    obj["toxic_counter"] = JsonValue(static_cast<int64_t>(p.toxic_counter));

    //  Locked-into-move slug ("" if no lock). Exposed so the inference
    //  server can hard-mask move slots that don't match.
    obj["locked_to_move"] = JsonValue(p.locked_to_move);

    //  Most recent move this mon used. Empty before its first MOVE_USED.
    //  Per-mon ground truth; field-level last_move_own/opp on the field
    //  block are the derived "whoever moved most recently per side".
    obj["last_move"] = JsonValue(p.last_move);

    //  Configuration prior: nature + EVs. Empty / zero is "not yet scanned".
    obj["nature"] = JsonValue(p.nature);
    JsonArray evs;
    for (int v : p.evs){
        evs.push_back(JsonValue(static_cast<int64_t>(v)));
    }
    obj["evs"] = JsonValue(std::move(evs));

    return obj;
}

JsonObject BattleStateTracker::to_predict_json() const{
    JsonObject root;

    //  Own active. In DOUBLES we always emit 2 entries even when the HUD
    //  hasn't yet confirmed a slot; an unconfirmed slot renders as a
    //  placeholder so the front-end can show "[0]" / "[1]" reliably.
    JsonArray own_active;
    uint8_t slots = (m_mode == BattleMode::DOUBLES) ? 2 : 1;
    for (uint8_t i = 0; i < slots; i++){
        uint8_t slot_idx = m_own_active[i];
        const TrackedPokemon& mon = m_own_team[slot_idx];
        if (!mon.species.empty()){
            own_active.push_back(JsonValue(pokemon_to_json(mon, slot_idx)));
        }else{
            TrackedPokemon placeholder;
            placeholder.species = "(unknown)";
            own_active.push_back(JsonValue(pokemon_to_json(placeholder, slot_idx)));
        }
    }
    root["own_active"] = JsonValue(std::move(own_active));

    //  Own bench. Includes fainted slots so lead pills can resolve to species
    //  names even after a KO. Filtering on alive made the dashboard show
    //  bare slot indices for KO'd leads.
    JsonArray own_bench;
    for (uint8_t i = 0; i < 6; i++){
        bool is_active = false;
        for (uint8_t a = 0; a < slots; a++){
            if (m_own_active[a] == i) is_active = true;
        }
        if (!is_active && !m_own_team[i].species.empty()){
            own_bench.push_back(JsonValue(pokemon_to_json(m_own_team[i], i)));
        }
    }
    root["own_bench"] = JsonValue(std::move(own_bench));

    //  Opponent active. Always emit `slots` entries in DOUBLES; placeholder
    //  when the HUD hasn't confirmed slot N yet (or species is still empty).
    JsonArray opp_active;
    for (uint8_t i = 0; i < slots; i++){
        uint8_t slot_idx = m_opp_active[i];
        bool has_real = slot_idx < m_opp_seen && !m_opp_team[slot_idx].species.empty();
        if (has_real){
            opp_active.push_back(JsonValue(pokemon_to_json(m_opp_team[slot_idx], slot_idx, /*is_opponent=*/true)));
        }else{
            TrackedPokemon placeholder;
            placeholder.species = "(unknown)";
            opp_active.push_back(JsonValue(pokemon_to_json(placeholder, slot_idx, /*is_opponent=*/true)));
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
            opp_bench.push_back(JsonValue(pokemon_to_json(m_opp_team[i], i, /*is_opponent=*/true)));
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

    //  Side-condition remaining-turn counters. Parallel arrays to the
    //  bools above. 0 = inactive. Encoder doesn't read these today but
    //  the v2/search pipeline can — emitting now means no schema break
    //  later. Order matches m_screens_*: [light_screen, reflect, aurora_veil].
    JsonObject timers_own, timers_opp;
    timers_own["tailwind"] = JsonValue(static_cast<int64_t>(m_timers_own.tailwind));
    timers_own["light_screen"] = JsonValue(static_cast<int64_t>(m_timers_own.light_screen));
    timers_own["reflect"] = JsonValue(static_cast<int64_t>(m_timers_own.reflect));
    timers_own["aurora_veil"] = JsonValue(static_cast<int64_t>(m_timers_own.aurora_veil));
    timers_opp["tailwind"] = JsonValue(static_cast<int64_t>(m_timers_opp.tailwind));
    timers_opp["light_screen"] = JsonValue(static_cast<int64_t>(m_timers_opp.light_screen));
    timers_opp["reflect"] = JsonValue(static_cast<int64_t>(m_timers_opp.reflect));
    timers_opp["aurora_veil"] = JsonValue(static_cast<int64_t>(m_timers_opp.aurora_veil));
    field["side_timers_own"] = JsonValue(std::move(timers_own));
    field["side_timers_opp"] = JsonValue(std::move(timers_opp));

    //  Entry hazards + protection. Mirrors encoder.py::_build_hazards:
    //  stealth_rock, spikes (0..3), toxic_spikes (0..2), sticky_web,
    //  safeguard, mist, lucky_chant. Emitted as a nested object per
    //  side rather than a flat 14-vec so the field is self-describing.
    auto hazards_obj = [](const Hazards& h){
        JsonObject o;
        o["stealth_rock"] = JsonValue(h.stealth_rock);
        o["spikes"] = JsonValue(static_cast<int64_t>(h.spikes_layers));
        o["toxic_spikes"] = JsonValue(static_cast<int64_t>(h.toxic_spikes_layers));
        o["sticky_web"] = JsonValue(h.sticky_web);
        o["safeguard"] = JsonValue(h.safeguard);
        o["mist"] = JsonValue(h.mist);
        o["lucky_chant"] = JsonValue(h.lucky_chant);
        return o;
    };
    field["hazards_own"] = JsonValue(hazards_obj(m_hazards_own));
    field["hazards_opp"] = JsonValue(hazards_obj(m_hazards_opp));

    //  Last move used by each side (slug). Empty before any move resolved.
    //  Encoder reads last_move_p1 / last_move_p2; the inference server
    //  maps own↔p1 / opp↔p2 (or vice versa) at request time.
    field["last_move_own"] = JsonValue(m_last_move_own);
    field["last_move_opp"] = JsonValue(m_last_move_opp);

    root["field"] = JsonValue(std::move(field));

    //  Lead lineup chosen on the locked-in team-preview screen.
    //  own_leads = own-team slot indices in send-out order (leads[0] first).
    JsonArray own_leads;
    for (uint8_t s : m_own_leads){
        own_leads.push_back(JsonValue(static_cast<int64_t>(s)));
    }
    root["own_leads"] = JsonValue(std::move(own_leads));

    //  Legal-action mask per active slot. 14 entries each, layout:
    //    [m0→oppA, m0→oppB, m0→ally,
    //     m1→oppA, m1→oppB, m1→ally,
    //     m2→oppA, m2→oppB, m2→ally,
    //     m3→oppA, m3→oppB, m3→ally,
    //     switch→bench0, switch→bench1]
    //  bench0/bench1 follow own_bench emission order: slot indices 0..5
    //  skipping active, taking first 2. Server applies as a hard mask
    //  before argmax (see inference/server.py:254 + model_player.py:147).
    //
    //  Choice-lock handled via mon.locked_to_move (set by MOVE_LOCKED text
    //  parse + proactive MOVE_USED when item is a Choice item). Still TODO:
    //  encore / disable / multi-turn-lock / taunt — would slot into the
    //  same locked_to_move field once their detection patterns are added.
    bool doubles = (m_mode == BattleMode::DOUBLES);

    auto build_legal_mask = [&](uint8_t active_idx){
        JsonArray mask;
        const TrackedPokemon& mon = m_own_team[active_idx];

        //  Target validity from alive bits + mode.
        bool opp_a_alive = m_opp_team[m_opp_active[0]].alive;
        bool opp_b_alive = doubles && m_opp_team[m_opp_active[1]].alive;
        uint8_t ally_idx = (active_idx == m_own_active[0])
            ? m_own_active[1] : m_own_active[0];
        bool ally_alive = doubles
            && ally_idx != active_idx
            && m_own_team[ally_idx].alive;
        bool target_ok[3] = {opp_a_alive, opp_b_alive, ally_alive};

        //  Choice / encore / multi-turn lock: if locked_to_move is set, only
        //  the matching known_moves slot is usable. Find that slot once.
        //  If we have a lock but can't match it to any of the 4 known_moves
        //  yet (move OCR hasn't populated, or the lock text said a move
        //  this mon doesn't own — shouldn't happen), fall back to "no lock"
        //  rather than zeroing every move row.
        int locked_slot = -1;
        if (!mon.locked_to_move.empty()){
            for (uint8_t m = 0; m < mon.known_moves.size() && m < 4; m++){
                if (mon.known_moves[m] == mon.locked_to_move){
                    locked_slot = (int)m;
                    break;
                }
            }
        }

        //  Move slots: PP > 0, or unread (-1) → assume legal. Locked rows
        //  are zeroed for every slot except locked_slot.
        for (uint8_t m = 0; m < 4; m++){
            bool pp_ok = (mon.move_pp[m].current > 0 || mon.move_pp[m].current < 0);
            bool lock_ok = (locked_slot < 0) || ((int)m == locked_slot);
            for (uint8_t t = 0; t < 3; t++){
                mask.push_back(JsonValue(pp_ok && lock_ok && target_ok[t]));
            }
        }

        //  Switch slots: walk slot indices in own_bench emission order,
        //  take first two non-active non-empty. Mark legal only if alive.
        bool bench_alive[2] = {false, false};
        int bench_n = 0;
        for (uint8_t i = 0; i < 6 && bench_n < 2; i++){
            bool is_active = (i == m_own_active[0])
                || (doubles && i == m_own_active[1]);
            if (is_active) continue;
            if (m_own_team[i].species.empty()) continue;
            bench_alive[bench_n] = m_own_team[i].alive;
            bench_n++;
        }
        mask.push_back(JsonValue(bench_alive[0]));
        mask.push_back(JsonValue(bench_alive[1]));

        return mask;
    };

    root["legal_actions_a"] = JsonValue(build_legal_mask(m_own_active[0]));
    if (doubles){
        root["legal_actions_b"] = JsonValue(build_legal_mask(m_own_active[1]));
    }

    //  Per-turn rolling history for the LSTM history feature. Shape
    //  matches src/vgc_model/data/encoder.py::_summarize_turn: a list
    //  of entries, each with four 4-vectors keyed [own_a, own_b,
    //  opp_a, opp_b]. Newest-last; never longer than BATTLE_HISTORY_K.
    //  Pushed once per turn transition (action_menu re-entry) by the
    //  live trace; cleared on match start.
    JsonArray history;
    for (const auto& entry : m_history){
        JsonObject e;

        JsonArray species;
        for (const auto& s : entry.active_species){
            species.push_back(JsonValue(s));
        }
        e["active_species"] = JsonValue(std::move(species));

        JsonArray hp;
        for (float v : entry.active_hp){
            hp.push_back(JsonValue((double)v));
        }
        e["active_hp"] = JsonValue(std::move(hp));

        JsonArray types;
        for (const auto& t : entry.action_types){
            types.push_back(JsonValue(t));
        }
        e["action_types"] = JsonValue(std::move(types));

        JsonArray moves;
        for (const auto& m : entry.action_moves){
            moves.push_back(JsonValue(m));
        }
        e["action_moves"] = JsonValue(std::move(moves));

        e["weather"] = JsonValue(entry.weather);
        e["terrain"] = JsonValue(entry.terrain);
        e["trick_room"] = JsonValue(entry.trick_room);

        JsonArray order;
        for (int v : entry.move_order){
            order.push_back(JsonValue((int64_t)v));
        }
        e["move_order"] = JsonValue(std::move(order));

        history.push_back(JsonValue(std::move(e)));
    }
    root["history"] = JsonValue(std::move(history));

    return root;
}

void BattleStateTracker::update_from_team_summary(
    const std::array<TeamSummaryInfo, 6>& infos
){
    //  Merge — only overwrite a tracker field when the input has a
    //  non-empty value. Lets a partial Moves & More read add to whatever
    //  was already known without clobbering.
    for (uint8_t i = 0; i < 6; i++){
        const TeamSummaryInfo& src = infos[i];
        TrackedPokemon& dst = m_own_team[i];
        if (!src.species.empty()) dst.species = src.species;
        if (!src.ability.empty()) dst.ability = src.ability;
        if (!src.item.empty())    dst.item = src.item;
        for (uint8_t m = 0; m < 4; m++){
            if (!src.moves[m].empty()) dst.add_move(src.moves[m]);
        }
    }
}


void BattleStateTracker::update_from_team_stats(
    const std::array<TeamStatsInfo, 6>& infos
){
    for (uint8_t i = 0; i < 6; i++){
        const TeamStatsInfo& src = infos[i];
        TrackedPokemon& dst = m_own_team[i];
        if (!src.nature_slug.empty()){
            dst.nature = src.nature_slug;
        }
        //  Per-stat EVs. Only overwrite when the input has a non-zero EV
        //  read; OCR sometimes misses single-digit zeros and we don't
        //  want to clobber a known good value with noise.
        bool any_nonzero = false;
        for (uint8_t s = 0; s < 6; s++){
            if (src.stats[s].evs > 0) any_nonzero = true;
        }
        if (any_nonzero){
            for (uint8_t s = 0; s < 6; s++){
                dst.evs[s] = src.stats[s].evs;
            }
        }
    }
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
