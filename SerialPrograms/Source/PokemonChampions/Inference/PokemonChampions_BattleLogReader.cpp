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

    //  Champions-specific patterns. The generated table is rebuilt from PS
    //  default.ts (see tools/generate_battle_log_patterns.py) so anything
    //  Champions adds on top of PS lives here. Checked before the table walk
    //  so a Champions message can't be mis-matched by a generic PS pattern.
    //
    //  Most volatile / hazard / side-condition texts live in PS moves.ts and
    //  abilities.ts (not default.ts), so the generated table doesn't cover
    //  them. The text strings used below are the canonical PS-protocol
    //  messages, which are the same strings the Champions client displays
    //  (we've confirmed this for the Choice-lock case and assume parity
    //  elsewhere — auto-capture will surface any divergence).
    {
        //  Choice-item lock rejection. Captures the item ("Choice Scarf" /
        //  "Choice Band" / "Choice Specs") and the only legal move name.
        //    "The Choice Scarf only allows the use of Wave Crash!"
        static const std::regex choice_lock(
            R"___(The\s+(Choice\s+(?:Scarf|Band|Specs))\s+only\s+allows\s+the\s+use\s+of\s+(.+?)!?\s*$)___",
            std::regex::icase);
        std::smatch lm;
        if (std::regex_search(trimmed, lm, choice_lock)){
            event.type = BattleLogEventType::MOVE_LOCKED;
            event.item = lm[1].str();
            event.move = lm[2].str();
            return event;
        }
    }

    //  Helper: one row in the Champions overlay. (regex, event_type,
    //  canonical-effect-name, slot mapping). slot[0] is the [POKEMON]
    //  capture position if any; -1 if the pattern has no pokemon group.
    //  Effect name goes into event.effect.
    struct ChampionsOverlay {
        std::regex re;
        BattleLogEventType type;
        const char* effect;     //  canonical name
        int pokemon_group;      //  1-based; 0 = no pokemon capture
    };

    static const std::vector<ChampionsOverlay>& champions_overlays = [](){
        static std::vector<ChampionsOverlay> v;
        auto add = [&](const char* pat, BattleLogEventType t,
                       const char* eff, int pg){
            v.push_back({std::regex(pat, std::regex::icase), t, eff, pg});
        };

        // ── Volatile statuses ─────────────────────────────────────────
        // Names are upper-case canonical, matching VOLATILE_STATUSES in
        // src/vgc_model/data/volatile_statuses.py.
        add(R"___((.+?)\s+put\s+in\s+a\s+substitute!?$)___",
            BattleLogEventType::VOLATILE_START, "SUBSTITUTE", 1);
        add(R"___((.+?)(?:'s)?\s+substitute\s+faded!?$)___",
            BattleLogEventType::VOLATILE_END,   "SUBSTITUTE", 1);
        add(R"___((.+?)\s+fell\s+for\s+the\s+taunt!?$)___",
            BattleLogEventType::VOLATILE_START, "TAUNT", 1);
        add(R"___((.+?)(?:'s)?\s+taunt\s+wore\s+off!?$)___",
            BattleLogEventType::VOLATILE_END,   "TAUNT", 1);
        add(R"___((.+?)\s+received\s+an\s+encore!?$)___",
            BattleLogEventType::VOLATILE_START, "ENCORE", 1);
        add(R"___((.+?)(?:'s)?\s+encore\s+ended!?$)___",
            BattleLogEventType::VOLATILE_END,   "ENCORE", 1);
        add(R"___((.+?)(?:'s)?\s+(?:.+?)\s+was\s+disabled!?$)___",
            BattleLogEventType::VOLATILE_START, "DISABLE", 1);
        add(R"___((.+?)(?:'s)?\s+move\s+is\s+no\s+longer\s+disabled!?$)___",
            BattleLogEventType::VOLATILE_END,   "DISABLE", 1);
        add(R"___((.+?)\s+was\s+seeded!?$)___",
            BattleLogEventType::VOLATILE_START, "LEECHSEED", 1);
        add(R"___((.+?)\s+protected\s+itself!?$)___",
            BattleLogEventType::VOLATILE_START, "PROTECT", 1);
        add(R"___((.+?)\s+is\s+getting\s+pumped!?$)___",
            BattleLogEventType::VOLATILE_START, "FOCUSENERGY", 1);
        add(R"___((.+?)\s+planted\s+its\s+roots!?$)___",
            BattleLogEventType::VOLATILE_START, "INGRAIN", 1);
        add(R"___((.+?)\s+levitated\s+with\s+electromagnetism!?$)___",
            BattleLogEventType::VOLATILE_START, "MAGNETRISE", 1);
        add(R"___((.+?)\s+was\s+prevented\s+from\s+healing!?$)___",
            BattleLogEventType::VOLATILE_START, "HEALBLOCK", 1);
        add(R"___((.+?)\s+can't\s+use\s+(?:.+?)\s+via\s+sound!?$)___",
            BattleLogEventType::VOLATILE_START, "THROATCHOP", 1);
        add(R"___((.+?)\s+fell\s+in\s+love!?$)___",
            BattleLogEventType::VOLATILE_START, "ATTRACT", 1);
        // Perish Song — count is encoded in the text. Use four entries so
        // each maps cleanly to the canonical perish bit.
        add(R"___((.+?)(?:'s)?\s+perish\s+count\s+fell\s+to\s+3!?$)___",
            BattleLogEventType::VOLATILE_START, "PERISH3", 1);
        add(R"___((.+?)(?:'s)?\s+perish\s+count\s+fell\s+to\s+2!?$)___",
            BattleLogEventType::VOLATILE_START, "PERISH2", 1);
        add(R"___((.+?)(?:'s)?\s+perish\s+count\s+fell\s+to\s+1!?$)___",
            BattleLogEventType::VOLATILE_START, "PERISH1", 1);
        add(R"___((.+?)(?:'s)?\s+perish\s+count\s+fell\s+to\s+0!?$)___",
            BattleLogEventType::VOLATILE_START, "PERISH4", 1);  //  faint marker

        // ── Hazards (entry / removal) ─────────────────────────────────
        // Text uses "the opposing X's team" or "X's team" — we route the
        // affected side via the POKEMON capture's "the opposing" prefix.
        add(R"___(Pointed\s+stones\s+float\s+in\s+the\s+air\s+around\s+(.+?)(?:'s)?\s+team!?$)___",
            BattleLogEventType::HAZARD_SET,   "stealth_rock", 1);
        add(R"___(Spikes\s+were\s+scattered\s+all\s+around\s+(.+?)(?:'s)?\s+(?:feet|team)!?$)___",
            BattleLogEventType::HAZARD_SET,   "spikes", 1);
        add(R"___(Poison\s+spikes\s+were\s+scattered\s+all\s+around\s+(.+?)(?:'s)?\s+(?:feet|team)!?$)___",
            BattleLogEventType::HAZARD_SET,   "toxic_spikes", 1);
        add(R"___(A\s+sticky\s+web\s+has\s+been\s+laid\s+out\s+beneath\s+(.+?)(?:'s)?\s+feet!?$)___",
            BattleLogEventType::HAZARD_SET,   "sticky_web", 1);
        // Rapid Spin / Defog / Mortal Spin / etc. — generic clear text.
        add(R"___((.+?)\s+blew\s+away\s+(?:the\s+)?(?:stealth\s+rock|spikes|toxic\s+spikes|sticky\s+web|hazards)!?$)___",
            BattleLogEventType::HAZARD_CLEAR, "all", 1);

        // ── Side conditions ───────────────────────────────────────────
        add(R"___(The\s+tailwind\s+blew\s+from\s+behind\s+(.+?)(?:'s)?\s+team!?$)___",
            BattleLogEventType::SIDE_START,   "tailwind", 1);
        add(R"___((.+?)(?:'s)?\s+tailwind\s+petered\s+out!?$)___",
            BattleLogEventType::SIDE_END,     "tailwind", 1);
        add(R"___(Light\s+Screen\s+made\s+(.+?)(?:'s)?\s+team\s+stronger\s+against\s+special\s+moves!?$)___",
            BattleLogEventType::SIDE_START,   "light_screen", 1);
        add(R"___((.+?)(?:'s)?\s+Light\s+Screen\s+wore\s+off!?$)___",
            BattleLogEventType::SIDE_END,     "light_screen", 1);
        add(R"___(Reflect\s+made\s+(.+?)(?:'s)?\s+team\s+stronger\s+against\s+physical\s+moves!?$)___",
            BattleLogEventType::SIDE_START,   "reflect", 1);
        add(R"___((.+?)(?:'s)?\s+Reflect\s+wore\s+off!?$)___",
            BattleLogEventType::SIDE_END,     "reflect", 1);
        add(R"___(Aurora\s+Veil\s+made\s+(.+?)(?:'s)?\s+team\s+stronger\s+against\s+(?:both\s+physical\s+and\s+special|all)\s+moves!?$)___",
            BattleLogEventType::SIDE_START,   "aurora_veil", 1);
        add(R"___((.+?)(?:'s)?\s+Aurora\s+Veil\s+wore\s+off!?$)___",
            BattleLogEventType::SIDE_END,     "aurora_veil", 1);
        add(R"___((.+?)(?:'s)?\s+team\s+became\s+cloaked\s+by\s+a\s+mystical\s+veil!?$)___",
            BattleLogEventType::SIDE_START,   "safeguard", 1);
        add(R"___((.+?)(?:'s)?\s+team\s+is\s+no\s+longer\s+protected\s+by\s+Safeguard!?$)___",
            BattleLogEventType::SIDE_END,     "safeguard", 1);
        add(R"___((.+?)(?:'s)?\s+team\s+became\s+shrouded\s+in\s+mist!?$)___",
            BattleLogEventType::SIDE_START,   "mist", 1);
        add(R"___((.+?)(?:'s)?\s+team\s+is\s+no\s+longer\s+protected\s+by\s+Mist!?$)___",
            BattleLogEventType::SIDE_END,     "mist", 1);
        add(R"___(The\s+Lucky\s+Chant\s+shielded\s+(.+?)(?:'s)?\s+team\s+from\s+critical\s+hits!?$)___",
            BattleLogEventType::SIDE_START,   "lucky_chant", 1);
        add(R"___((.+?)(?:'s)?\s+team's\s+Lucky\s+Chant\s+wore\s+off!?$)___",
            BattleLogEventType::SIDE_END,     "lucky_chant", 1);

        return v;
    }();

    for (const auto& ov : champions_overlays){
        std::smatch om;
        if (!std::regex_search(trimmed, om, ov.re)) continue;
        event.type = ov.type;
        event.effect = ov.effect;
        if (ov.pokemon_group > 0 && (size_t)ov.pokemon_group < om.size()){
            bool opp = false;
            event.pokemon = clean_pokemon_name(
                strip_opposing_prefix(om[ov.pokemon_group].str(), opp));
            if (opp) event.is_opponent = true;
        }
        return event;
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
    case BattleLogEventType::MOVE_LOCKED:        return "MOVE_LOCKED";
    case BattleLogEventType::VOLATILE_START:     return "VOLATILE_START";
    case BattleLogEventType::VOLATILE_END:       return "VOLATILE_END";
    case BattleLogEventType::HAZARD_SET:         return "HAZARD_SET";
    case BattleLogEventType::HAZARD_CLEAR:       return "HAZARD_CLEAR";
    case BattleLogEventType::SIDE_START:         return "SIDE_START";
    case BattleLogEventType::SIDE_END:           return "SIDE_END";
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
        {"MOVE_LOCKED",        BattleLogEventType::MOVE_LOCKED},
        {"VOLATILE_START",     BattleLogEventType::VOLATILE_START},
        {"VOLATILE_END",       BattleLogEventType::VOLATILE_END},
        {"HAZARD_SET",         BattleLogEventType::HAZARD_SET},
        {"HAZARD_CLEAR",       BattleLogEventType::HAZARD_CLEAR},
        {"SIDE_START",         BattleLogEventType::SIDE_START},
        {"SIDE_END",           BattleLogEventType::SIDE_END},
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
