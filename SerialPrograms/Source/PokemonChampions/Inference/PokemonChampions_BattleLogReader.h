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


enum class BattleLogEventType{
    UNKNOWN,
    MOVE_USED,          //  "The opposing X used Y!"  or  "X used Y!"
    STAT_CHANGE,        //  "X's Atk rose!" / "X's Speed harshly fell!"
    STATUS_INFLICTED,   //  "X was burned/paralyzed/poisoned/frozen/put to sleep!"
    SWITCH_IN,          //  "[Trainer] sent out X!"
    WEATHER,            //  "It started to rain!" / "The sandstorm subsided!"
    TERRAIN,            //  "Electric Terrain was set!"
    TRICK_ROOM,         //  "X twisted the dimensions!" / "The twisted dimensions..."
    SUPER_EFFECTIVE,    //  "It's super effective!"
    NOT_EFFECTIVE,      //  "It's not very effective..."
    FAINTED,            //  "X fainted!"
    ITEM_ACTIVATED,     //  "X's Focus Sash" / etc.
    OTHER,              //  Recognized text but no specific parse
};


struct BattleLogEvent{
    BattleLogEventType type = BattleLogEventType::UNKNOWN;

    //  True if the event is about the opponent's Pokemon.
    bool is_opponent = false;

    //  Pokemon name / species (when applicable).
    std::string pokemon;

    //  Move name (for MOVE_USED events).
    std::string move;

    //  Stat name (for STAT_CHANGE events): "Atk", "Sp. Atk", "Speed", etc.
    std::string stat;

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
