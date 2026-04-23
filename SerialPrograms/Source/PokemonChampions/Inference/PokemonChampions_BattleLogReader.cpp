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

#include <regex>
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_BattleLogReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


BattleLogReader::BattleLogReader()
    //  Bottom-center text bar region.
    //  x: 200-1600 / 1920, y: 801-850 / 1080
    : m_text_bar(0.104, 0.741, 0.729, 0.046)
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


// ─── Regex-based parsing ─────────────────────────────────────────────

BattleLogEvent BattleLogReader::parse(const std::string& text){
    BattleLogEvent event;
    event.raw_text = text;

    std::smatch m;

    //  "The opposing X used Y!"  or  "X used Y!"
    {
        std::regex re(R"((?:The opposing )?(.+?) used (.+?)!?)");
        if (std::regex_search(text, m, re)){
            event.type = BattleLogEventType::MOVE_USED;
            event.pokemon = clean_pokemon_name(m[1].str());
            event.move = m[2].str();
            event.is_opponent = (text.find("The opposing") != std::string::npos);
            return event;
        }
    }

    //  "[Trainer] sent out X!"
    {
        std::regex re(R"((.+?) sent out (.+?)!?)");
        if (std::regex_search(text, m, re)){
            event.type = BattleLogEventType::SWITCH_IN;
            event.pokemon = clean_pokemon_name(m[2].str());
            //  If the trainer name is not ours, it's opponent.
            //  We can't easily know our own trainer name here, so we mark
            //  this as opponent if it doesn't contain "'s" (which would
            //  indicate a Pokemon-level message, not a send-out).
            event.is_opponent = true;  //  Caller should refine based on context.
            return event;
        }
    }

    //  "X's Atk rose!" / "X's Sp. Atk sharply rose!" / "X's Speed harshly fell!"
    //  Also: "The opposing X's Atk rose!"
    {
        std::regex re(R"((?:The opposing )?(.+?)'s (.+?) (rose|fell|sharply rose|sharply fell|harshly fell|drastically rose)!?)");
        if (std::regex_search(text, m, re)){
            event.type = BattleLogEventType::STAT_CHANGE;
            event.pokemon = clean_pokemon_name(m[1].str());
            event.stat = m[2].str();
            event.is_opponent = (text.find("The opposing") != std::string::npos);

            std::string direction = m[3].str();
            if (direction == "rose")              event.boost_stages = 1;
            else if (direction == "sharply rose")  event.boost_stages = 2;
            else if (direction == "drastically rose") event.boost_stages = 3;
            else if (direction == "fell")          event.boost_stages = -1;
            else if (direction == "sharply fell")  event.boost_stages = -2;
            else if (direction == "harshly fell")  event.boost_stages = -3;
            return event;
        }
    }

    //  Multi-stat changes: "The opposing Volcarona's Sp. Atk, Sp. Def, and Speed rose!"
    {
        std::regex re(R"((?:The opposing )?(.+?)'s (.+?) (rose|fell)!?)");
        if (std::regex_search(text, m, re)){
            event.type = BattleLogEventType::STAT_CHANGE;
            event.pokemon = clean_pokemon_name(m[1].str());
            event.stat = m[2].str();  //  "Sp. Atk, Sp. Def, and Speed"
            event.is_opponent = (text.find("The opposing") != std::string::npos);
            event.boost_stages = (m[3].str() == "rose") ? 1 : -1;
            return event;
        }
    }

    //  "X was burned/paralyzed/poisoned/frozen!"
    //  "X fell asleep!" / "X was put to sleep!"
    {
        std::regex re(R"((?:The opposing )?(.+?) was (burned|paralyzed|poisoned|badly poisoned|frozen|put to sleep)!?)");
        if (std::regex_search(text, m, re)){
            event.type = BattleLogEventType::STATUS_INFLICTED;
            event.pokemon = clean_pokemon_name(m[1].str());
            event.stat = m[2].str();  //  reuse stat field for status name
            event.is_opponent = (text.find("The opposing") != std::string::npos);
            return event;
        }
    }

    //  "X fainted!"
    {
        std::regex re(R"((?:The opposing )?(.+?) fainted!?)");
        if (std::regex_search(text, m, re)){
            event.type = BattleLogEventType::FAINTED;
            event.pokemon = clean_pokemon_name(m[1].str());
            event.is_opponent = (text.find("The opposing") != std::string::npos);
            return event;
        }
    }

    //  "It's super effective!"
    if (text.find("super effective") != std::string::npos){
        event.type = BattleLogEventType::SUPER_EFFECTIVE;
        return event;
    }

    //  "It's not very effective..."
    if (text.find("not very effective") != std::string::npos){
        event.type = BattleLogEventType::NOT_EFFECTIVE;
        return event;
    }

    //  Weather
    if (text.find("started to rain") != std::string::npos ||
        text.find("sunlight turned harsh") != std::string::npos ||
        text.find("sandstorm kicked up") != std::string::npos ||
        text.find("started to snow") != std::string::npos ||
        text.find("rain stopped") != std::string::npos ||
        text.find("sunlight faded") != std::string::npos ||
        text.find("sandstorm subsided") != std::string::npos ||
        text.find("weather disappeared") != std::string::npos ||
        text.find("effects of the weather") != std::string::npos)
    {
        event.type = BattleLogEventType::WEATHER;
        return event;
    }

    //  Terrain
    if (text.find("Terrain") != std::string::npos){
        event.type = BattleLogEventType::TERRAIN;
        return event;
    }

    //  Trick Room
    if (text.find("twisted the dimensions") != std::string::npos ||
        text.find("twisted dimensions") != std::string::npos)
    {
        event.type = BattleLogEventType::TRICK_ROOM;
        return event;
    }

    //  Catch-all: we got text but couldn't parse it.
    event.type = BattleLogEventType::OTHER;
    return event;
}


}
}
}
