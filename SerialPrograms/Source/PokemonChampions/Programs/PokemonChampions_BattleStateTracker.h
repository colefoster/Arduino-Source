/*  Pokemon Champions Battle State Tracker
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Accumulates game state across turns within a single match.
 *  Fed by OCR readers (BattleHUDReader, MoveNameReader, BattleLogReader)
 *  and produces JSON payloads for the inference server.
 *
 *  Lifecycle:
 *    1. reset() at match start
 *    2. set_own_team() from user-configured team options
 *    3. update_from_hud() / update_from_moves() / update_from_log() each turn
 *    4. to_predict_json() when the AI needs to decide
 *    5. Discarded at match end
 *
 */

#ifndef PokemonAutomation_PokemonChampions_BattleStateTracker_H
#define PokemonAutomation_PokemonChampions_BattleStateTracker_H

#include <array>
#include <string>
#include <vector>
#include "Common/Cpp/Json/JsonObject.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleModeDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


struct TrackedPokemon{
    std::string species;        //  slug, e.g. "kingambit"
    float hp = 1.0f;            //  normalized 0.0-1.0
    std::string status;         //  "brn", "par", "psn", "slp", "frz", "tox", or ""
    std::vector<std::string> known_moves;  //  up to 4 move slugs
    std::string item;           //  slug, e.g. "bright-powder"
    std::string ability;        //  slug, e.g. "defiant"
    std::array<int8_t, 6> boosts = {};  //  atk, def, spa, spd, spe, evasion
    bool is_mega = false;
    bool alive = true;

    void reset_volatile();      //  Clear boosts (on switch-out).
    void add_move(const std::string& move);  //  Add to known_moves if not present.
};


//  User-configured Pokemon for the own team.
struct ConfiguredPokemon{
    std::string species;
    std::array<std::string, 4> moves;
    std::string item;
    std::string ability;
};


class BattleStateTracker{
public:
    BattleStateTracker();

    void reset();
    void set_mode(BattleMode mode);
    void set_own_team(const std::array<ConfiguredPokemon, 6>& team);

    //  Parse a Showdown paste format team string and populate own team.
    //  Returns the number of Pokemon successfully parsed (0-6).
    int load_team_from_showdown_paste(const std::string& paste);

    //  ── Per-frame updates ───────────────────────────────────────

    //  Update from the HUD reader (opponent species + HP, own HP).
    void update_from_hud(const BattleHUDState& hud);

    //  Update from the move name reader (own active mon's moves).
    //  Only call for the currently active slot.
    void update_from_moves(const std::array<std::string, 4>& move_slugs, uint8_t active_slot = 0);

    //  Update from a parsed battle log event.
    void update_from_log(const BattleLogEvent& event);

    //  Advance the turn counter.
    void advance_turn();

    //  ── JSON output ─────────────────────────────────────────────

    //  Build the JSON payload matching the inference server's PredictRequest format.
    JsonObject to_predict_json() const;

    //  Build the JSON payload for team selection.
    JsonObject to_team_select_json(const std::vector<std::string>& opp_species) const;

    //  ── Accessors ───────────────────────────────────────────────

    BattleMode mode() const{ return m_mode; }
    uint8_t turn() const{ return m_turn; }
    const TrackedPokemon& own(uint8_t slot) const{ return m_own_team[slot]; }
    const TrackedPokemon& opp(uint8_t slot) const{ return m_opp_team[slot]; }
    uint8_t opp_seen_count() const{ return m_opp_seen; }

    //  Fill an item slug on an already-configured own Pokemon (e.g. from
    //  the Team Preview screen after Moves & More loaded species/moves).
    void set_own_item(uint8_t slot, const std::string& item);

    //  Pre-populate an opponent slot with a known species (from the Team
    //  Preview screen's sprite-matcher). Seeds m_opp_team[slot].species
    //  without marking it as "seen in battle".
    void set_opp_species_preview(uint8_t slot, const std::string& species);

private:
    //  Find or create an opponent slot for a species. Returns index 0-5.
    uint8_t find_or_add_opponent(const std::string& species);

    //  Map a stat name string to boost array index.
    static int stat_name_to_index(const std::string& stat);

    BattleMode m_mode = BattleMode::UNKNOWN;
    uint8_t m_turn = 0;

    //  Own team: 6 mons, indices into this array.
    std::array<TrackedPokemon, 6> m_own_team;
    std::array<uint8_t, 2> m_own_active = {0, 1};  //  active slot indices

    //  Opponent team: up to 6 discovered mons.
    std::array<TrackedPokemon, 6> m_opp_team;
    std::array<uint8_t, 2> m_opp_active = {0, 1};
    uint8_t m_opp_seen = 0;

    //  Field state.
    std::string m_weather;
    std::string m_terrain;
    bool m_trick_room = false;
    bool m_tailwind_own = false;
    bool m_tailwind_opp = false;
    std::array<bool, 3> m_screens_own = {};   //  light_screen, reflect, aurora_veil
    std::array<bool, 3> m_screens_opp = {};
};


}
}
}
#endif
