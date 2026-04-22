/*  PokemonChampions Tests
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Test functions for Pokemon Champions screen detectors and OCR readers.
 *  These run the exact same C++ inference code used in production against
 *  static screenshot images loaded from disk.
 *
 */


#include "PokemonChampions_Tests.h"
#include "TestUtils.h"
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"

//  Screen detectors
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_ActionMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreparingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PostMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MainMenuDetector.h"

//  OCR readers
#include "PokemonChampions/Inference/PokemonChampions_BattleModeDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"

#include <iostream>
using std::cout;
using std::cerr;
using std::endl;

namespace PokemonAutomation{

using namespace NintendoSwitch::PokemonChampions;


// ─── Screen Detectors ───────────────────────────────────────────────

int test_pokemonChampions_MoveSelectDetector(const ImageViewRGB32& image, bool target){
    MoveSelectDetector detector;
    bool result = detector.detect(image);
    TEST_RESULT_EQUAL(result, target);
    return 0;
}

int test_pokemonChampions_ActionMenuDetector(const ImageViewRGB32& image, bool target){
    ActionMenuDetector detector;
    bool result = detector.detect(image);
    TEST_RESULT_EQUAL(result, target);
    return 0;
}

int test_pokemonChampions_ResultScreenDetector(const ImageViewRGB32& image, bool target){
    ResultScreenDetector detector;
    bool result = detector.detect(image);
    TEST_RESULT_EQUAL(result, target);
    return 0;
}

int test_pokemonChampions_PreparingForBattleDetector(const ImageViewRGB32& image, bool target){
    PreparingForBattleDetector detector;
    bool result = detector.detect(image);
    TEST_RESULT_EQUAL(result, target);
    return 0;
}

int test_pokemonChampions_PostMatchScreenDetector(const ImageViewRGB32& image, bool target){
    PostMatchScreenDetector detector;
    bool result = detector.detect(image);
    TEST_RESULT_EQUAL(result, target);
    return 0;
}

int test_pokemonChampions_MainMenuDetector(const ImageViewRGB32& image, bool target){
    MainMenuDetector detector;
    bool result = detector.detect(image);
    TEST_RESULT_EQUAL(result, target);
    return 0;
}


// ─── MoveNameReader ─────────────────────────────────────────────────
//
//  Filename convention: <prefix>_<move0>_<move1>_<move2>_<move3>.png
//  Each move is a slug like "fake-out". Use "NONE" for unreadable slots.
//  Hyphens in slugs survive parse_words() because '_' is the delimiter.

int test_pokemonChampions_MoveNameReader(const ImageViewRGB32& image, const std::vector<std::string>& words){
    if (words.size() < 4){
        cerr << "Error: MoveNameReader test needs 4 move slugs in filename "
             << "(got " << words.size() << " words total)." << endl;
        return 1;
    }

    //  Last 4 words are the expected move slugs.
    std::array<std::string, 4> expected;
    for (size_t i = 0; i < 4; i++){
        const std::string& slug = words[words.size() - 4 + i];
        expected[i] = (slug == "NONE") ? "" : slug;
    }

    auto& logger = global_logger_command_line();
    MoveNameReader reader(Language::English);
    auto result = reader.read_all_moves(logger, image);

    for (size_t i = 0; i < 4; i++){
        if (result[i] != expected[i]){
            cerr << "Error: MoveNameReader slot " << i
                 << " got \"" << result[i]
                 << "\" but expected \"" << expected[i] << "\"." << endl;
            return 1;
        }
    }

    cout << "MoveNameReader: all 4 slots matched." << endl;
    return 0;
}


// ─── SpeciesReader ──────────────────────────────────────────────────
//
//  Filename convention: <prefix>_<species-slug>.png
//  Last word is the expected species slug (e.g. "mienshao").

int test_pokemonChampions_SpeciesReader(const ImageViewRGB32& image, const std::vector<std::string>& words){
    if (words.empty()){
        cerr << "Error: SpeciesReader test needs a species slug in filename." << endl;
        return 1;
    }

    const std::string& expected = words.back();

    auto& logger = global_logger_command_line();
    BattleHUDReader reader(Language::English);
    std::string result = reader.read_opponent_species(logger, image, 0);

    TEST_RESULT_EQUAL(result, expected);
    return 0;
}


// ─── Opponent HP Reader ─────────────────────────────────────────────
//
//  Filename convention: <prefix>_<hp-pct>.png  (e.g. frame_75.png)

int test_pokemonChampions_OpponentHPReader(const ImageViewRGB32& image, int target){
    auto& logger = global_logger_command_line();
    BattleHUDReader reader(Language::English);
    int result = reader.read_opponent_hp_pct(logger, image, 0);

    TEST_RESULT_EQUAL(result, target);
    return 0;
}


// ─── BattleLogReader ────────────────────────────────────────────────
//
//  Filename convention: <prefix>_<EVENT_TYPE>.png
//  Last word is the expected BattleLogEventType name.
//  Example: frame_MOVE_USED.png  (note: parse_words splits on '_',
//  so multi-word types like MOVE_USED arrive as ["MOVE", "USED"]).
//
//  We join the last N words with '_' and match against enum names.

static BattleLogEventType event_type_from_string(const std::string& name){
    if (name == "MOVE_USED")          return BattleLogEventType::MOVE_USED;
    if (name == "STAT_CHANGE")        return BattleLogEventType::STAT_CHANGE;
    if (name == "STATUS_INFLICTED")   return BattleLogEventType::STATUS_INFLICTED;
    if (name == "SWITCH_IN")          return BattleLogEventType::SWITCH_IN;
    if (name == "WEATHER")            return BattleLogEventType::WEATHER;
    if (name == "TERRAIN")            return BattleLogEventType::TERRAIN;
    if (name == "TRICK_ROOM")         return BattleLogEventType::TRICK_ROOM;
    if (name == "SUPER_EFFECTIVE")    return BattleLogEventType::SUPER_EFFECTIVE;
    if (name == "NOT_EFFECTIVE")      return BattleLogEventType::NOT_EFFECTIVE;
    if (name == "FAINTED")            return BattleLogEventType::FAINTED;
    if (name == "ITEM_ACTIVATED")     return BattleLogEventType::ITEM_ACTIVATED;
    if (name == "OTHER")              return BattleLogEventType::OTHER;
    return BattleLogEventType::UNKNOWN;
}

static std::string event_type_to_string(BattleLogEventType type){
    switch (type){
    case BattleLogEventType::UNKNOWN:          return "UNKNOWN";
    case BattleLogEventType::MOVE_USED:        return "MOVE_USED";
    case BattleLogEventType::STAT_CHANGE:      return "STAT_CHANGE";
    case BattleLogEventType::STATUS_INFLICTED: return "STATUS_INFLICTED";
    case BattleLogEventType::SWITCH_IN:        return "SWITCH_IN";
    case BattleLogEventType::WEATHER:          return "WEATHER";
    case BattleLogEventType::TERRAIN:          return "TERRAIN";
    case BattleLogEventType::TRICK_ROOM:       return "TRICK_ROOM";
    case BattleLogEventType::SUPER_EFFECTIVE:  return "SUPER_EFFECTIVE";
    case BattleLogEventType::NOT_EFFECTIVE:    return "NOT_EFFECTIVE";
    case BattleLogEventType::FAINTED:          return "FAINTED";
    case BattleLogEventType::ITEM_ACTIVATED:   return "ITEM_ACTIVATED";
    case BattleLogEventType::OTHER:            return "OTHER";
    }
    return "UNKNOWN";
}

int test_pokemonChampions_BattleLogReader(const ImageViewRGB32& image, const std::vector<std::string>& words){
    if (words.empty()){
        cerr << "Error: BattleLogReader test needs an event type in filename." << endl;
        return 1;
    }

    //  Reconstruct the event type name by joining trailing uppercase words with '_'.
    //  e.g. words = ["frame", "MOVE", "USED"] -> "MOVE_USED"
    std::string type_name;
    for (size_t i = 0; i < words.size(); i++){
        const std::string& w = words[i];
        //  Skip leading lowercase prefix words.
        bool is_upper = !w.empty() && (w[0] >= 'A' && w[0] <= 'Z');
        if (type_name.empty() && !is_upper) continue;
        if (!type_name.empty()) type_name += "_";
        type_name += w;
    }

    BattleLogEventType expected = event_type_from_string(type_name);
    if (expected == BattleLogEventType::UNKNOWN && type_name != "UNKNOWN"){
        cerr << "Error: unrecognized event type '" << type_name << "' in filename." << endl;
        return 1;
    }

    auto& logger = global_logger_command_line();
    BattleLogReader reader;
    BattleLogEvent event = reader.read_event(logger, image);

    cout << "BattleLogReader: raw=\"" << event.raw_text
         << "\"  type=" << event_type_to_string(event.type) << endl;

    if (event.type != expected){
        cerr << "Error: BattleLogReader got " << event_type_to_string(event.type)
             << " but expected " << event_type_to_string(expected) << "." << endl;
        return 1;
    }
    return 0;
}


// ─── MoveSelectCursorSlot ───────────────────────────────────────────
//
//  Filename convention: <prefix>_<slot>.png  (e.g. frame_2.png)
//  Tests that cursor_slot() returns the expected slot index.

int test_pokemonChampions_MoveSelectCursorSlot(const ImageViewRGB32& image, int target){
    MoveSelectDetector detector;
    bool detected = detector.detect(image);
    if (!detected){
        cerr << "Error: MoveSelectDetector did not detect move select screen." << endl;
        return 1;
    }

    int result = detector.cursor_slot();
    TEST_RESULT_EQUAL(result, target);
    return 0;
}


// ─── OCR Dump (void/dev) ────────────────────────────────────────────
//
//  Runs all readers on the image and prints results. Always returns 0.
//  Useful for quick iteration when tuning crop boxes or filters.

int test_pokemonChampions_OCRDump(const ImageViewRGB32& image){
    auto& logger = global_logger_command_line();

    //  Move names
    {
        MoveNameReader reader(Language::English);
        auto moves = reader.read_all_moves(logger, image);
        cout << "=== Move Names ===" << endl;
        for (size_t i = 0; i < 4; i++){
            cout << "  slot " << i << ": \"" << moves[i] << "\"" << endl;
        }
    }

    //  HUD (singles)
    {
        BattleHUDReader reader(Language::English, BattleMode::SINGLES);
        cout << "=== Battle HUD (Singles) ===" << endl;

        std::string species = reader.read_opponent_species(logger, image, 0);
        cout << "  opponent species: \"" << species << "\"" << endl;

        int hp_pct = reader.read_opponent_hp_pct(logger, image, 0);
        cout << "  opponent HP%: " << hp_pct << endl;

        auto own_hp = reader.read_own_hp(logger, image, 0);
        cout << "  own HP: " << own_hp.first << "/" << own_hp.second << endl;

        for (uint8_t i = 0; i < 4; i++){
            auto pp = reader.read_move_pp(logger, image, i);
            cout << "  PP slot " << (int)i << ": " << pp.first << "/" << pp.second << endl;
        }
    }

    //  HUD (doubles)
    {
        BattleHUDReader reader(Language::English, BattleMode::DOUBLES);
        cout << "=== Battle HUD (Doubles) ===" << endl;

        for (uint8_t slot = 0; slot < 2; slot++){
            std::string species = reader.read_opponent_species(logger, image, slot);
            cout << "  opp " << (int)slot << " species: \"" << species << "\"" << endl;

            int hp_pct = reader.read_opponent_hp_pct(logger, image, slot);
            cout << "  opp " << (int)slot << " HP%: " << hp_pct << endl;
        }

        for (uint8_t slot = 0; slot < 2; slot++){
            auto own_hp = reader.read_own_hp(logger, image, slot);
            cout << "  own " << (int)slot << " HP: " << own_hp.first << "/" << own_hp.second << endl;
        }
    }

    //  Battle log
    {
        BattleLogReader reader;
        cout << "=== Battle Log ===" << endl;
        cout << "  text bar visible: " << reader.detect_text_bar(image) << endl;
        if (reader.detect_text_bar(image)){
            BattleLogEvent event = reader.read_event(logger, image);
            cout << "  raw: \"" << event.raw_text << "\"" << endl;
            cout << "  type: " << event_type_to_string(event.type) << endl;
            if (!event.pokemon.empty()) cout << "  pokemon: \"" << event.pokemon << "\"" << endl;
            if (!event.move.empty())    cout << "  move: \"" << event.move << "\"" << endl;
            if (!event.stat.empty())    cout << "  stat: \"" << event.stat << "\"" << endl;
            if (event.boost_stages != 0) cout << "  boost: " << event.boost_stages << endl;
        }
    }

    return 0;
}


}
