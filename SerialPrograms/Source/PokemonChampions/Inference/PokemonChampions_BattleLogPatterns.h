/*  Pokemon Champions Battle Log Patterns
 *
 *  Pattern table for BattleLogReader::parse(). The patterns themselves are
 *  generated from Pokemon Showdown's data/text/default.ts via
 *  tools/generate_battle_log_patterns.py — see PokemonChampions_BattleLogPatterns_Generated.cpp.
 *
 *  Each pattern is a regex with [PLACEHOLDER]-style capture groups already
 *  replaced. At parse time we walk the table top-to-bottom and the first
 *  match wins. PS templates with more literal text are listed first so they
 *  beat shorter, more permissive patterns.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_BattleLogPatterns_H
#define PokemonAutomation_PokemonChampions_BattleLogPatterns_H

#include <regex>
#include <string>
#include <vector>
#include "PokemonChampions_BattleLogReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Which BattleLogEvent field to fill from a given regex capture group.
enum class BattleLogSlot{
    NONE,
    POKEMON,    //  Pokemon name; "the opposing X" prefix sets is_opponent.
    STAT,       //  Stat name for STAT_CHANGE; status name for STATUS_INFLICTED.
    MOVE,       //  Move name.
    ITEM,       //  Item name.
    ABILITY,    //  Ability name.
    EFFECT,     //  Generic effect / type / number — stored in `effect`.
};


struct BattleLogPattern{
    //  Compiled regex matching the whole (trimmed) OCR string.
    std::regex regex;

    //  Event type produced on match.
    BattleLogEventType event_type;

    //  Static boost magnitude (signed) for STAT_CHANGE patterns. 0 otherwise.
    int boost_stages;

    //  Static value to assign to BattleLogEvent::stat when this pattern matches
    //  (used to attach the burn/par/etc. status name to STATUS_INFLICTED).
    //  Empty string means "use the captured group instead".
    std::string static_stat;

    //  Capture-group → field-slot mapping. slots[i] tells us where regex
    //  group i+1 should be stored. Length == regex group count.
    std::vector<BattleLogSlot> slots;

    //  Original PS template (uncompiled). For debugging / overlay only.
    std::string template_text;

    //  PS dotted path (e.g. "default.move", "brn.start"). For debugging.
    std::string ps_path;
};


//  Returns the global pattern table. Compiled once on first call.
const std::vector<BattleLogPattern>& battle_log_patterns();


}
}
}
#endif
