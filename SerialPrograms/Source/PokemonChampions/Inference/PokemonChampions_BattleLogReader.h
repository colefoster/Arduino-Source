/*  Pokemon Champions Battle Log Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  OCR the bottom-center text bar that appears during battle animations.
 *  This bar shows messages like:
 *    "The opposing Volcarona used Fiery Dance!"
 *    "The opposing Volcarona's Sp. Atk, Sp. Def, and Speed rose!"
 *    "Victor Bell's Victreebelite was burned!"
 *    "RH sent out Kingambit!"
 *    "It started to rain!"
 *
 *  The reader extracts raw text via OCR and then parses it with regex
 *  patterns to produce structured BattleLogEvents.
 *
 *  Coordinates measured from ref_frames/1/frame_00100.jpg (1920x1080).
 *  The text bar spans roughly x: 300-1620, y: 930-970 (white text with
 *  black outline on a semi-transparent dark bar).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_BattleLogReader_H
#define PokemonAutomation_PokemonChampions_BattleLogReader_H

#include <string>
#include <vector>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Event taxonomy. Mirrors Pokemon Showdown's data/text/default.ts so each
//  PS log template maps to exactly one of these values; see
//  tools/generate_battle_log_patterns.py for the mapping.
enum class BattleLogEventType{
    UNKNOWN,
    //  Match flow
    MOVE_USED,          //  "[POKEMON] used [MOVE]!"
    SWITCH_IN,          //  "[TRAINER] sent out [POKEMON]!" / "Go! [POKEMON]!"
    SWITCH_OUT,         //  "[TRAINER] withdrew [POKEMON]!" / "[POKEMON], come back!"
    DRAG,               //  "[POKEMON] was dragged out!"
    FAINTED,            //  "[POKEMON] fainted!"
    CANT,               //  Move blocked: paralyzed/asleep/frozen/flinch/recharge/struggle
    FAILED,             //  "But it failed!" / "It had no effect!"
    //  Stat changes
    STAT_CHANGE,        //  "[POKEMON]'s [STAT] rose/fell!" — boost_stages signed
    STAT_CHANGE_AT_CAP, //  "[POKEMON]'s [STAT] won't go any higher/lower!"
    STAT_CHANGE_OTHER,  //  swap/copy/clear/invert boost effects
    //  Damage / heal
    DAMAGE,             //  Generic damage notice ("[POKEMON] was hurt by …")
    HEAL,               //  HP restored
    CRIT,               //  "A critical hit!"
    SUPER_EFFECTIVE,    //  "It's super effective!" + "extremely effective" (Tera)
    NOT_EFFECTIVE,      //  "It's not very effective..." + "mostly ineffective"
    IMMUNE,             //  "It doesn't affect [POKEMON]…"
    MISS,               //  "[POKEMON] avoided the attack!"
    HIT_COUNT,          //  "Hit [N] times!"
    OHKO,               //  "It's a one-hit KO!"
    //  Statuses
    STATUS_INFLICTED,   //  brn/par/psn/tox/frz/slp.start + Yawn ("grew drowsy")
    STATUS_HEALED,      //  brn/par/psn/frz/slp.end
    STATUS_DAMAGE,      //  burn / poison damage tick
    CONFUSION,          //  start / end / activate
    //  Field state
    WEATHER,            //  weather start/end/upkeep/damage/block
    TERRAIN,            //  terrain start/end/block/heal
    TRICK_ROOM,         //  twisted dimensions
    FIELD_EFFECT,       //  gravity / magic room / wonder room / sport
    //  Form changes / reactions
    MEGA_EVOLVE,        //  "[POKEMON] has Mega Evolved into Mega [SPECIES]!"
    PRIMAL,             //  "Primal Reversion!"
    TYPE_CHANGE,        //  "[POKEMON]'s type changed to [TYPE]!"
    TRANSFORM,          //  "[POKEMON] transformed!"
    //  Items / abilities
    ITEM_ACTIVATED,     //  ate item / used gem / item buff / etc.
    ITEM_TRANSFER,      //  Trick / Switcheroo / Thief / Pickpocket
    ABILITY_CHANGE,     //  "acquired [ABILITY]!"
    //  Generic effect plumbing (rarely surfaced unless the OCR captures parens)
    EFFECT_START,       //  "([EFFECT] started on [POKEMON]!)"
    EFFECT_END,         //  "[POKEMON] was freed from [EFFECT]!"
    EFFECT_ACTIVATE,    //  "([EFFECT] activated!)"
    //  Match boundary / chrome
    BATTLE_START,
    BATTLE_END,
    TURN_MARKER,        //  "== Turn N =="
    OTHER,              //  Recognized text but no specific parse
};


//  Enum <-> name conversions (used by tests, OcrSuggest, dashboard).
std::string event_type_to_string(BattleLogEventType type);
BattleLogEventType event_type_from_string(const std::string& name);


struct BattleLogEvent{
    BattleLogEventType type = BattleLogEventType::UNKNOWN;

    //  True if the event is about the opponent's Pokemon.
    bool is_opponent = false;

    //  Pokemon name / species (when applicable).
    std::string pokemon;

    //  Move name (for MOVE_USED events).
    std::string move;

    //  Stat name (for STAT_CHANGE events): "Atk", "Sp. Atk", "Speed", etc.
    //  Also reused for STATUS_INFLICTED status name (legacy quirk).
    std::string stat;

    //  Item name (for ITEM_ACTIVATED / ITEM_TRANSFER / damage-from-item events).
    std::string item;

    //  Ability name (for ABILITY_CHANGE).
    std::string ability;

    //  Effect / type / move name as captured by the matched pattern. Specific
    //  fields take precedence; this catches the rest.
    std::string effect;

    //  Boost direction: +1 = rose, +2 = sharply rose, -1 = fell, etc.
    int boost_stages = 0;

    //  Raw OCR text.
    std::string raw_text;
};


class BattleLogReader{
public:
    BattleLogReader();

    void make_overlays(VideoOverlaySet& items) const;

    //  Detect whether the text bar is currently visible.
    bool detect_text_bar(const ImageViewRGB32& screen) const;

    //  OCR the text bar and return the raw string.
    std::string read_raw(Logger& logger, const ImageViewRGB32& screen) const;

    //  OCR + parse into a structured event.
    BattleLogEvent read_event(Logger& logger, const ImageViewRGB32& screen) const;

    //  Parse a raw text string into a structured event (no OCR, just regex).
    static BattleLogEvent parse(const std::string& text);

private:
    ImageFloatBox m_text_bar;
};


}
}
}
#endif
