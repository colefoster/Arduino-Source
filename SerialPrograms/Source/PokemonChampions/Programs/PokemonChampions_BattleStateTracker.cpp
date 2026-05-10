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
#include "PokemonChampions/Inference/PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamStatsReader.h"

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

    m_own_leads.clear();
}

void BattleStateTracker::set_mode(BattleMode mode){
    m_mode = mode;
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
            //  Own switch — clear boosts on whichever active slot matches.
            std::string lower = event.pokemon;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
            for (uint8_t i = 0; i < 2; i++){
                auto& mon = m_own_team[m_own_active[i]];
                if (!mon.species.empty() &&
                    (lower.find(mon.species) != std::string::npos ||
                     mon.species.find(lower) != std::string::npos))
                {
                    mon.reset_volatile();
                    break;
                }
            }
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

static JsonObject pokemon_to_json(const TrackedPokemon& p, int slot = -1){
    JsonObject obj;
    if (slot >= 0) obj["slot"] = JsonValue(static_cast<int64_t>(slot));
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
    obj["boosts"] = JsonValue(std::move(boosts));

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
            opp_active.push_back(JsonValue(pokemon_to_json(m_opp_team[slot_idx], slot_idx)));
        }else{
            TrackedPokemon placeholder;
            placeholder.species = "(unknown)";
            opp_active.push_back(JsonValue(pokemon_to_json(placeholder, slot_idx)));
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
            opp_bench.push_back(JsonValue(pokemon_to_json(m_opp_team[i], i)));
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
    //  TODO: choice-lock / encore / disable / multi-turn-lock / taunt —
    //  TrackedPokemon doesn't carry those fields yet. PP + alive coverage
    //  alone removes the most common illegal-action class (depleted PP,
    //  fainted target, fainted bench) and is what we have signals for.
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

        //  Move slots: PP > 0, or unread (-1) → assume legal.
        for (uint8_t m = 0; m < 4; m++){
            bool pp_ok = (mon.move_pp[m].current > 0 || mon.move_pp[m].current < 0);
            for (uint8_t t = 0; t < 3; t++){
                mask.push_back(JsonValue(pp_ok && target_ok[t]));
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
