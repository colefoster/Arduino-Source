/*  Pokemon Champions Battle Log Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  The bottom text bar during battle animations spans roughly:
 *    x: 300-1620 / 1920 = 0.156 - 0.844
 *    y: 920-975  / 1080 = 0.852 - 0.903
 *
 *  Text is white with a thin black outline, on a semi-transparent dark
 *  overlay. We use WHITE_TEXT_FILTERS for OCR.
 *
 */

#include <cctype>
#include <regex>
#include <utility>
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_BattleLogPatterns.h"
#include "PokemonChampions_BattleLogReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


BattleLogReader::BattleLogReader()
    //  Bottom-center text bar region.
    //  x: 200-1600 / 1920, y: 801-850 / 1080
    : m_text_bar(0.1532, 0.741, 0.704, 0.046)
{}

void BattleLogReader::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_text_bar);
}

bool BattleLogReader::detect_text_bar(const ImageViewRGB32& screen) const{
    //  Check if the text bar region has sufficient contrast/content.
    //  When no text bar is shown, this region is the game field (dark, noisy).
    //  When the text bar is shown, there's a dark semi-transparent overlay
    //  with bright white text — we detect this via the brightness spread.
    ImageStats stats = image_stats(extract_box_reference(screen, m_text_bar));
    //  Text bar present → high stddev (bright text on dark bg).
    //  No text bar → lower stddev (game field).
    return stats.stddev.sum() > 80;
}

std::string BattleLogReader::read_raw(
    Logger& logger, const ImageViewRGB32& screen
) const{
    ImageViewRGB32 cropped = extract_box_reference(screen, m_text_bar);
    std::string text = OCR::ocr_read(Language::English, cropped, OCR::PageSegMode::SINGLE_LINE);
    //  Strip trailing whitespace/newlines.
    while (!text.empty() && (text.back() == '\n' || text.back() == '\r' || text.back() == ' ')){
        text.pop_back();
    }
    if (!text.empty()){
        logger.log("BattleLogReader: \"" + text + "\"");
    }
    return text;
}

BattleLogEvent BattleLogReader::read_event(
    Logger& logger, const ImageViewRGB32& screen
) const{
    if (!detect_text_bar(screen)){
        return BattleLogEvent{};
    }
    std::string text = read_raw(logger, screen);
    if (text.empty()){
        return BattleLogEvent{};
    }
    return parse(text);
}


// ─── Helpers ─────────────────────────────────────────────────────────

//  Strip leading OCR noise (non-alpha characters) from a pokemon name.
//  e.g. "~ Rotom" -> "Rotom",  "# _Rotom" -> "Rotom"
static std::string clean_pokemon_name(const std::string& raw){
    size_t start = 0;
    while (start < raw.size() && !std::isalpha(static_cast<unsigned char>(raw[start]))){
        start++;
    }
    return raw.substr(start);
}


// ─── Pattern-driven parsing ──────────────────────────────────────────
//
//  The pattern table is generated from Pokemon Showdown's
//  data/text/default.ts (see tools/generate_battle_log_patterns.py and
//  PokemonChampions_BattleLogPatterns_Generated.cpp). We walk the table
//  top-to-bottom; first match wins. The table is sorted so longer literal
//  templates come before shorter, more permissive ones.

static std::string strip_opposing_prefix(const std::string& s, bool& is_opponent){
    static const std::string prefix = "the opposing ";
    is_opponent = false;
    if (s.size() < prefix.size()) return s;
    std::string head = s.substr(0, prefix.size());
    for (char& c : head) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (head == prefix){
        is_opponent = true;
        return s.substr(prefix.size());
    }
    return s;
}

BattleLogEvent BattleLogReader::parse(const std::string& text){
    BattleLogEvent event;
    event.raw_text = text;

    //  Trim leading/trailing whitespace and a single wrapping pair of
    //  parentheses (PS uses "  (...)" for background-message styling; OCR
    //  may or may not capture the parens).
    std::string trimmed = text;
    size_t start = trimmed.find_first_not_of(" \t\r\n");
    size_t end = trimmed.find_last_not_of(" \t\r\n");
    if (start == std::string::npos){
        event.type = BattleLogEventType::UNKNOWN;
        return event;
    }
    trimmed = trimmed.substr(start, end - start + 1);
    if (trimmed.size() >= 2 && trimmed.front() == '(' && trimmed.back() == ')'){
        trimmed = trimmed.substr(1, trimmed.size() - 2);
    }

    std::smatch m;
    for (const BattleLogPattern& p : battle_log_patterns()){
        //  regex_search (not regex_match) so trailing OCR garbage (" - . s",
        //  "S S", etc.) doesn't break the match. The patterns are sorted by
        //  literal length so more specific templates beat shorter ones.
        if (!std::regex_search(trimmed, m, p.regex)) continue;
        event.type = p.event_type;
        event.boost_stages = p.boost_stages;
        if (!p.static_stat.empty()){
            event.stat = p.static_stat;
        }
        for (size_t i = 0; i < p.slots.size() && (i + 1) < m.size(); i++){
            const std::string captured = m[i + 1].str();
            switch (p.slots[i]){
            case BattleLogSlot::POKEMON: {
                bool opp = false;
                event.pokemon = clean_pokemon_name(strip_opposing_prefix(captured, opp));
                if (opp) event.is_opponent = true;
                break;
            }
            case BattleLogSlot::STAT:
                if (p.static_stat.empty()) event.stat = captured;
                break;
            case BattleLogSlot::MOVE:    event.move = captured;    break;
            case BattleLogSlot::ITEM:    event.item = captured;    break;
            case BattleLogSlot::ABILITY: event.ability = captured; break;
            case BattleLogSlot::EFFECT:  event.effect = captured;  break;
            case BattleLogSlot::NONE:    break;
            }
        }
        return event;
    }

    //  No pattern matched.
    event.type = BattleLogEventType::OTHER;
    return event;
}


// ─── Enum <-> name conversions ───────────────────────────────────────

std::string event_type_to_string(BattleLogEventType type){
    switch (type){
    case BattleLogEventType::UNKNOWN:            return "UNKNOWN";
    case BattleLogEventType::MOVE_USED:          return "MOVE_USED";
    case BattleLogEventType::SWITCH_IN:          return "SWITCH_IN";
    case BattleLogEventType::SWITCH_OUT:         return "SWITCH_OUT";
    case BattleLogEventType::DRAG:               return "DRAG";
    case BattleLogEventType::FAINTED:            return "FAINTED";
    case BattleLogEventType::CANT:               return "CANT";
    case BattleLogEventType::FAILED:             return "FAILED";
    case BattleLogEventType::STAT_CHANGE:        return "STAT_CHANGE";
    case BattleLogEventType::STAT_CHANGE_AT_CAP: return "STAT_CHANGE_AT_CAP";
    case BattleLogEventType::STAT_CHANGE_OTHER:  return "STAT_CHANGE_OTHER";
    case BattleLogEventType::DAMAGE:             return "DAMAGE";
    case BattleLogEventType::HEAL:               return "HEAL";
    case BattleLogEventType::CRIT:               return "CRIT";
    case BattleLogEventType::SUPER_EFFECTIVE:    return "SUPER_EFFECTIVE";
    case BattleLogEventType::NOT_EFFECTIVE:      return "NOT_EFFECTIVE";
    case BattleLogEventType::IMMUNE:             return "IMMUNE";
    case BattleLogEventType::MISS:               return "MISS";
    case BattleLogEventType::HIT_COUNT:          return "HIT_COUNT";
    case BattleLogEventType::OHKO:               return "OHKO";
    case BattleLogEventType::STATUS_INFLICTED:   return "STATUS_INFLICTED";
    case BattleLogEventType::STATUS_HEALED:      return "STATUS_HEALED";
    case BattleLogEventType::STATUS_DAMAGE:      return "STATUS_DAMAGE";
    case BattleLogEventType::CONFUSION:          return "CONFUSION";
    case BattleLogEventType::WEATHER:            return "WEATHER";
    case BattleLogEventType::TERRAIN:            return "TERRAIN";
    case BattleLogEventType::TRICK_ROOM:         return "TRICK_ROOM";
    case BattleLogEventType::FIELD_EFFECT:       return "FIELD_EFFECT";
    case BattleLogEventType::MEGA_EVOLVE:        return "MEGA_EVOLVE";
    case BattleLogEventType::PRIMAL:             return "PRIMAL";
    case BattleLogEventType::TYPE_CHANGE:        return "TYPE_CHANGE";
    case BattleLogEventType::TRANSFORM:          return "TRANSFORM";
    case BattleLogEventType::ITEM_ACTIVATED:     return "ITEM_ACTIVATED";
    case BattleLogEventType::ITEM_TRANSFER:      return "ITEM_TRANSFER";
    case BattleLogEventType::ABILITY_CHANGE:     return "ABILITY_CHANGE";
    case BattleLogEventType::EFFECT_START:       return "EFFECT_START";
    case BattleLogEventType::EFFECT_END:         return "EFFECT_END";
    case BattleLogEventType::EFFECT_ACTIVATE:    return "EFFECT_ACTIVATE";
    case BattleLogEventType::BATTLE_START:       return "BATTLE_START";
    case BattleLogEventType::BATTLE_END:         return "BATTLE_END";
    case BattleLogEventType::TURN_MARKER:        return "TURN_MARKER";
    case BattleLogEventType::OTHER:              return "OTHER";
    }
    return "UNKNOWN";
}

BattleLogEventType event_type_from_string(const std::string& name){
    //  Brute-force linear scan; called from tests + dashboard, not hot path.
    static const std::pair<const char*, BattleLogEventType> table[] = {
        {"UNKNOWN",            BattleLogEventType::UNKNOWN},
        {"MOVE_USED",          BattleLogEventType::MOVE_USED},
        {"SWITCH_IN",          BattleLogEventType::SWITCH_IN},
        {"SWITCH_OUT",         BattleLogEventType::SWITCH_OUT},
        {"DRAG",               BattleLogEventType::DRAG},
        {"FAINTED",            BattleLogEventType::FAINTED},
        {"CANT",               BattleLogEventType::CANT},
        {"FAILED",             BattleLogEventType::FAILED},
        {"STAT_CHANGE",        BattleLogEventType::STAT_CHANGE},
        {"STAT_CHANGE_AT_CAP", BattleLogEventType::STAT_CHANGE_AT_CAP},
        {"STAT_CHANGE_OTHER",  BattleLogEventType::STAT_CHANGE_OTHER},
        {"DAMAGE",             BattleLogEventType::DAMAGE},
        {"HEAL",               BattleLogEventType::HEAL},
        {"CRIT",               BattleLogEventType::CRIT},
        {"SUPER_EFFECTIVE",    BattleLogEventType::SUPER_EFFECTIVE},
        {"NOT_EFFECTIVE",      BattleLogEventType::NOT_EFFECTIVE},
        {"IMMUNE",             BattleLogEventType::IMMUNE},
        {"MISS",               BattleLogEventType::MISS},
        {"HIT_COUNT",          BattleLogEventType::HIT_COUNT},
        {"OHKO",               BattleLogEventType::OHKO},
        {"STATUS_INFLICTED",   BattleLogEventType::STATUS_INFLICTED},
        {"STATUS_HEALED",      BattleLogEventType::STATUS_HEALED},
        {"STATUS_DAMAGE",      BattleLogEventType::STATUS_DAMAGE},
        {"CONFUSION",          BattleLogEventType::CONFUSION},
        {"WEATHER",            BattleLogEventType::WEATHER},
        {"TERRAIN",            BattleLogEventType::TERRAIN},
        {"TRICK_ROOM",         BattleLogEventType::TRICK_ROOM},
        {"FIELD_EFFECT",       BattleLogEventType::FIELD_EFFECT},
        {"MEGA_EVOLVE",        BattleLogEventType::MEGA_EVOLVE},
        {"PRIMAL",             BattleLogEventType::PRIMAL},
        {"TYPE_CHANGE",        BattleLogEventType::TYPE_CHANGE},
        {"TRANSFORM",          BattleLogEventType::TRANSFORM},
        {"ITEM_ACTIVATED",     BattleLogEventType::ITEM_ACTIVATED},
        {"ITEM_TRANSFER",      BattleLogEventType::ITEM_TRANSFER},
        {"ABILITY_CHANGE",     BattleLogEventType::ABILITY_CHANGE},
        {"EFFECT_START",       BattleLogEventType::EFFECT_START},
        {"EFFECT_END",         BattleLogEventType::EFFECT_END},
        {"EFFECT_ACTIVATE",    BattleLogEventType::EFFECT_ACTIVATE},
        {"BATTLE_START",       BattleLogEventType::BATTLE_START},
        {"BATTLE_END",         BattleLogEventType::BATTLE_END},
        {"TURN_MARKER",        BattleLogEventType::TURN_MARKER},
        {"OTHER",              BattleLogEventType::OTHER},
    };
    for (const auto& [s, t] : table){
        if (name == s) return t;
    }
    return BattleLogEventType::UNKNOWN;
}


}
}
}
