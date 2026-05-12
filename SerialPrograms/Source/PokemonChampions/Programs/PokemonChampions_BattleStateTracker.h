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
#include <deque>
#include <string>
#include <vector>
#include "Common/Cpp/Json/JsonObject.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleModeDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Forward decls — defined in TeamSummaryReader.h / TeamStatsReader.h.
//  We can't include those here because TeamSummaryReader.h pulls in this
//  header (for ConfiguredPokemon).
struct TeamSummaryInfo;
struct TeamStatsInfo;


struct TrackedPokemon{
    std::string species;        //  slug, e.g. "kingambit"
    float hp = 1.0f;            //  normalized 0.0-1.0
    std::string status;         //  "brn", "par", "psn", "slp", "frz", "tox", or ""
    std::vector<std::string> known_moves;  //  up to 4 move slugs
    std::string item;           //  slug, e.g. "bright-powder"
    std::string ability;        //  slug, e.g. "defiant"
    std::string nature;         //  "Adamant", "Timid", etc. Empty until scanned.
    //  EVs in HP/Atk/Def/SpA/SpD/Spe order. Zeros until scanned. These are
    //  the small numbers next to each stat on the Stats tab.
    std::array<int, 6> evs = {};
    //  Stat-stage boosts in atk/def/spa/spd/spe/evasion order. Range -6..+6.
    //  Encoder consumes a 7-D vector (atk/def/spa/spd/spe/accuracy/evasion);
    //  the JSON emitter inserts a 0 at the accuracy slot rather than carry
    //  an extra always-zero field through the rest of the C++ pipeline.
    std::array<int8_t, 6> boosts = {};

    //  Per-move PP, updated from the move-select HUD reader. Aligned with
    //  known_moves order. -1 = unread; populated only for the active mon
    //  while move_select is on screen. Persists between polls.
    struct MovePP{ int current = -1; int max = -1; };
    std::array<MovePP, 4> move_pp = {};

    bool is_mega = false;
    bool alive = true;

    //  Move slug this mon is currently locked into (Choice item, encore,
    //  multi-turn move, etc.). Empty means "no known lock — any move is
    //  legal". Set by BattleLogReader's MOVE_LOCKED rejection text and
    //  pre-emptively by MOVE_USED when the mon is holding a Choice item.
    //  Cleared on switch-in (via reset_volatile) and on faint.
    std::string locked_to_move;

    //  Volatile-status names, canonical uppercase per
    //  src/vgc_model/data/volatile_statuses.py (e.g. "CONFUSION", "TAUNT",
    //  "ENCORE", "LEECHSEED", "SUBSTITUTE", "PROTECT"). Stored as a slug
    //  list rather than a fixed-width bitmask so the C++ side stays
    //  agnostic to the Python encoder's index numbering — the inference
    //  server bit-encodes at request time. Cleared on switch-in.
    std::vector<std::string> volatile_statuses;

    //  Substitute remaining HP fraction (0.0..1.0), 0 if no Substitute.
    float substitute_hp_frac = 0.0f;

    //  Per-field confidence (0.0..1.0). 1.0 = positively revealed in this
    //  match (HUD reveal, used a move, etc.); 0.0 = pre-match prior /
    //  team-paste only. The model was trained with progressive revelation
    //  so these need to reflect "have we actually seen it in play yet."
    //  Bumped by readers and log events; never decremented.
    float item_confidence = 0.0f;
    float ability_confidence = 0.0f;
    std::array<float, 4> move_confidences = {};

    //  Status condition turn counters. -1 / 0 = unknown or not applicable.
    //  sleep_turns_remaining: real Showdown semantics, decremented per turn
    //  the mon is asleep (resets on wake/switch). toxic_counter: the
    //  multiplier index for badly-poisoned damage tick (1 on first turn).
    int sleep_turns_remaining = 0;
    int toxic_counter = 0;

    void reset_volatile();      //  Clear boosts + volatiles + lock state.
    void add_move(const std::string& move);  //  Add to known_moves if not present.
};


//  Snapshot of the slugs the tracker currently believes are in play.
//  Cheap to build (vector copies of strings) and consumed by readers as
//  a *bias* — narrow OCR matching to these slugs first, fall through to
//  the global dictionary on a miss. Never used as a hard filter.
//
//  - own_species: up to 6 slugs from the registered team. Empty until
//    Team Scan / paste populates the tracker.
//  - opp_species: slugs the opp has shown so far (Team Preview sprite
//    matcher seeds early; HUD reads fill the rest).
//  - own_brought_indices: 0-4 indices into own_species, in send-out
//    order (mirrors set_own_leads). Empty before locked-in screen.
//  - moves_for_own_slot[i]: the 4 known moves for own_team[i] (from
//    Moves & More scan or accumulated from prior turns). Used by
//    MoveNameReader to constrain its dictionary.
//  - abilities_seen / items_seen: union of tracker-known own + opp
//    ability/item slugs. Used by AbilityItemReader.
struct TeamCandidates{
    std::vector<std::string> own_species;
    std::vector<std::string> opp_species;
    std::vector<uint8_t> own_brought_indices;
    std::array<std::vector<std::string>, 6> moves_for_own_slot;
    std::vector<std::string> abilities_seen;
    std::vector<std::string> items_seen;
};


//  If `global_token` isn't already a member of `candidates` and a member
//  is within Levenshtein-`max_edit_distance` of it, return that member.
//  Otherwise return `global_token` unchanged. `candidates` empty or
//  `global_token` empty short-circuits to returning the original token.
//  Used by readers to snap a global-OCR result to a known team slug.
std::string team_bias_snap(
    const std::string& global_token,
    const std::vector<std::string>& candidates,
    int max_edit_distance = 2);


//  Live tactical state of the current match — companion to TeamCandidates.
//  Where TeamCandidates is the slug snapshot consumed by OCR readers as
//  bias, BattleSnapshot is the per-poll game state consumed by suggesters
//  and (later) the action model. Both are flat structs built from the
//  tracker per poll; readers / suggesters take const refs so they don't
//  couple to tracker layout. Rebuild per poll, do not cache. -1 / empty /
//  false are the sentinel values for "unknown".
struct BattleSnapshot{
    //  Indices into m_own_team / m_opp_team for whoever's currently on
    //  field. Singles: only [0] meaningful; [1] = -1.
    std::array<int, 2> own_active_slots = {-1, -1};
    std::array<int, 2> opp_active_slots = {-1, -1};

    //  Aliveness across the full team (own) / discovered roster (opp).
    //  An "alive" mon has hp_max > 0 and hp > 0. Indices line up with
    //  m_own_team / m_opp_team.
    std::array<bool, 6> own_alive = {};
    std::array<bool, 6> opp_alive = {};

    //  Field state.
    std::string weather;            //  "RainDance" / "SunnyDay" / "Sandstorm" / "Snow" / ""
    std::string terrain;            //  "Electric" / "Grassy" / "Psychic" / "Misty" / ""
    bool trick_room = false;
    bool tailwind_own = false;
    bool tailwind_opp = false;
    std::array<bool, 3> screens_own = {};   //  light_screen, reflect, aurora_veil
    std::array<bool, 3> screens_opp = {};

    //  Match-level: turn counter and battle mode.
    uint8_t turn = 0;
    BattleMode mode = BattleMode::UNKNOWN;
};


//  Per-turn history entry — mirrors `_summarize_turn` in
//  src/vgc_model/data/encoder.py. Slot order is
//  [own_a, own_b, opp_a, opp_b].
//
//  Captured slug-level so the inference server can vocab-lookup with the
//  same Vocabs the model was trained against. action_type is "move",
//  "switch", or "noop"; action_move is a move slug or empty (paired with
//  "move"). All-empty / hp=0 / "noop" is a valid (and common) entry —
//  the C++ side often lacks reliable per-turn action attribution; the
//  trajectory of active species + HP alone carries most of the signal.
struct BattleHistoryEntry{
    std::array<std::string, 4> active_species = {};   //  slug, empty = none
    std::array<float, 4> active_hp = {0.0f, 0.0f, 0.0f, 0.0f};
    std::array<std::string, 4> action_types = {"noop","noop","noop","noop"};
    std::array<std::string, 4> action_moves = {};     //  slug, empty when type != move
};


//  Look-back window for the LSTM history feature. Must match
//  ``HISTORY_K`` in ``src/vgc_model/data/encoder.py``. If the encoder's
//  K changes, bump this and rebuild.
constexpr int BATTLE_HISTORY_K = 8;


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
    //  Seed which own-team slots are on the field. Called by the trace
    //  once team-preview marks identify the leads ('1' / '2'), so the
    //  snapshot's active indices are correct from poll 1 of the battle
    //  instead of waiting for a HUD remap. Pass -1 for slot_b in singles.
    //  Out-of-range / -1 values are ignored.
    void set_own_actives(int slot_a, int slot_b);
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

    //  Update own team from a Moves & More tab scan (species + ability +
    //  item + 4 moves). Empty fields in the input are skipped — partial
    //  reads don't clobber prior good data. Safe to call repeatedly.
    void update_from_team_summary(const std::array<TeamSummaryInfo, 6>& infos);

    //  Update own team from a Stats tab scan (nature slug + 6 EVs).
    //  Empty nature / all-zero EVs are skipped. Safe to call repeatedly.
    void update_from_team_stats(const std::array<TeamStatsInfo, 6>& infos);

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

    //  Apply an ability/item overlay reveal. `side` is "left"/"right" from
    //  the reader (screen position, not own/opp). Matches `pokemon_slug`
    //  against opp_team first, then own_team; writes the slug only if the
    //  target field is currently empty. Returns true if a slot matched.
    bool apply_ability_item_reveal(
        const std::string& side,
        const std::string& pokemon_slug,
        const std::string& name_slug,
        const std::string& kind);

    //  ── Persistent team store ───────────────────────────────────
    //
    //  Save / load the full m_own_team[6] (species, ability, item, moves,
    //  nature, EVs) to/from a JSON file. Used to make team scans survive
    //  program restarts.
    bool save_team_to_file(const std::string& path) const;
    bool load_team_from_file(const std::string& path);

    //  Multi-team library — saves each scanned team to a separate file in
    //  `dir`, named after the sorted species slugs joined by `_`. Same set
    //  of 6 species in any order maps to the same file (overwrites on
    //  re-scan, so a team's data stays current).
    //
    //  save_team_to_library: writes the current m_own_team[6]. No-op if any
    //   species slot is empty. Returns the file path written.
    //  load_team_matching: given the 6 species seen on the team-preview
    //   selecting screen (any order), looks up the matching file in `dir`
    //   and populates m_own_team. Returns true if a match was found.
    std::string save_team_to_library(const std::string& dir) const;
    bool load_team_matching(
        const std::string& dir,
        const std::array<std::string, 6>& species);

    //  Reorder m_own_team so that index i holds the mon whose species
    //  matches `screen_species[i]`. Empty entries in screen_species are
    //  left in place. Used after the selecting-stage Team Preview reads
    //  the on-screen own species — aligns internal indexing with screen
    //  positions so leads / active slot indices map directly.
    void reorder_own_team_to_screen(const std::array<std::string, 6>& screen_species);

    //  Apply a Pokemon Switch screen read. `own_hp[i]` = pair of (current,
    //  max); -1 sentinels for unread. `opp_hp_pct[i]` = 0-100 or -1.
    //  Updates HP for every slot whose value is real, leaving others
    //  alone. The switch screen is the only place where bench HP is
    //  visible at once, so this fills the gap left by HUDReader (which
    //  only reads the active 1-2 slots).
    void apply_switch_screen_hp(
        const std::array<std::pair<int, int>, 6>& own_hp,
        const std::array<int, 6>& opp_hp_pct);

    //  Apply a Battle Info tab read for one focused mon. side="own"|"opp",
    //  slot=0|1. Empty/sentinel inputs are skipped, so partial reads merge
    //  with prior state instead of clobbering it. Status text is parsed
    //  for known field effects (Trick Room, Tailwind, Light Screen, ...)
    //  with turn counters.
    void apply_battle_info_focused(
        const std::string& side, uint8_t slot,
        const std::string& species,
        int hp_current, int hp_max, int hp_pct,
        const std::array<std::string, 2>& types,
        const std::string& ability, const std::string& item,
        const std::array<int8_t, 5>& boosts,
        const std::string& status_text,
        int status_turns_current, int status_turns_max);

    //  Set the chosen lead lineup for a match (read from the locked-in
    //  team-preview screen). `leads` is up to 4 own-team slot indices in
    //  send-out order (leads[0] = first out). Slots not in `leads` are
    //  the bench. Pass an empty array to clear.
    void set_own_leads(const std::vector<uint8_t>& leads);

    //  Accessor for serialization / dashboard.
    const std::vector<uint8_t>& own_leads() const { return m_own_leads; }

    //  Bias snapshot for downstream readers. See TeamCandidates docs.
    //  Cheap; rebuild per-poll rather than caching.
    TeamCandidates candidates() const;

    //  Indices into m_own_team / m_opp_team for the mons currently on
    //  field. Singles: only [0] is meaningful (slot 0 holds the lone
    //  active). Doubles: both [0] (left) and [1] (right) are valid.
    //  Returns the raw m_own_active / m_opp_active arrays — callers
    //  should treat the second slot as -1 / unused in singles mode.
    std::array<uint8_t, 2> own_active_slot_indices() const { return m_own_active; }
    std::array<uint8_t, 2> opp_active_slot_indices() const { return m_opp_active; }

    //  Live tactical snapshot. See BattleSnapshot docs. Cheap; rebuild
    //  per-poll rather than caching.
    BattleSnapshot snapshot() const;

    //  ── Per-turn history ───────────────────────────────────────
    //
    //  Capture a BattleHistoryEntry of the current on-field state and
    //  push it onto the rolling per-match history buffer. Buffer is
    //  capped at BATTLE_HISTORY_K entries (oldest dropped). Cleared on
    //  reset(). Should be called once per turn transition (when the
    //  trace re-enters action_menu).
    void push_history_snapshot();

    //  Direct access to the rolling per-match history. Newest-last.
    const std::deque<BattleHistoryEntry>& history() const { return m_history; }

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

    //  Per-side entry-hazard + protection state. Mirrors the 7-element
    //  per-side vector in src/vgc_model/data/encoder.py::_build_hazards:
    //  stealth_rock, spikes_layers (0..3), toxic_spikes_layers (0..2),
    //  sticky_web, safeguard, mist, lucky_chant.
    struct Hazards{
        bool stealth_rock = false;
        uint8_t spikes_layers = 0;        //  0..3
        uint8_t toxic_spikes_layers = 0;  //  0..2
        bool sticky_web = false;
        bool safeguard = false;
        bool mist = false;
        bool lucky_chant = false;
    };
    Hazards m_hazards_own;
    Hazards m_hazards_opp;

    //  Side-condition remaining-turn counters. 0 = inactive. tailwind_*,
    //  light_screen_*, reflect_*, aurora_veil_* parallel the bools above;
    //  the bool says "is it up", the counter says "for how many more turns".
    //  Most cleanly populated from MOVE_USED + dedicated end events, but
    //  defaults to the encoder's expected 0 when unread.
    struct SideTimers{
        uint8_t tailwind = 0;
        uint8_t light_screen = 0;
        uint8_t reflect = 0;
        uint8_t aurora_veil = 0;
    };
    SideTimers m_timers_own;
    SideTimers m_timers_opp;

    //  Last move used by each side, slug form. Empty before any move
    //  resolves. Encoder reads `last_move_p1 / p2`; we translate at JSON
    //  emit time via the own↔p1/p2 convention.
    std::string m_last_move_own;
    std::string m_last_move_opp;

    //  Chosen lead lineup (up to 4 own-team slot indices, in send-out
    //  order). Empty before the locked-in screen has been read.
    std::vector<uint8_t> m_own_leads;

    //  Per-match rolling history of prior turns. See push_history_snapshot.
    std::deque<BattleHistoryEntry> m_history;
};


}
}
}
#endif
