/*  OCR Suggest
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Run a single reader on a single image and output JSON to stdout.
 */

#include "OcrSuggest.h"
#include "TestUtils.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/Language.h"
#include "CommonFramework/Logging/Logger.h"

#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSelectReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewReader.h"

#include <iostream>
#include <string>

namespace PokemonAutomation{

using namespace NintendoSwitch::PokemonChampions;


int run_ocr_suggest(const std::string& reader_name, const std::string& image_path){
    try{
        ImageRGB32 image(image_path);
        auto& log = global_logger_command_line();

        if (reader_name == "MoveNameReader"){
            MoveNameReader reader(Language::English);
            auto moves = reader.read_all_moves(log, image);
            std::cout << "{\"moves\":[";
            for (size_t i = 0; i < 4; i++){
                if (i > 0) std::cout << ",";
                std::cout << "\"" << moves[i] << "\"";
            }
            std::cout << "]}" << std::endl;
        }
        else if (reader_name == "MoveSelectCursorSlot"){
            MoveSelectDetector det;
            det.detect(image);
            std::cout << "{\"slot\":" << det.cursor_slot() << "}" << std::endl;
        }
        else if (reader_name == "BattleHUDReader" || reader_name == "SpeciesReader"){
            BattleHUDReader reader(Language::English);
            std::string species = reader.read_opponent_species(log, image, 0);
            int hp = reader.read_opponent_hp_pct(log, image, 0);
            std::cout << "{\"opponent_species\":\"" << species << "\",\"opponent_hp_pct\":" << hp << "}" << std::endl;
        }
        else if (reader_name == "BattleLogReader"){
            BattleLogReader reader;
            auto event = reader.read_event(log, image);
            std::cout << "{\"event_type\":\"" << event.raw_text << "\"}" << std::endl;
        }
        else if (reader_name == "TeamSelectReader"){
            TeamSelectReader reader(Language::English);
            auto slots = reader.read_all_slots(log, image);
            std::cout << "{\"species\":[";
            for (size_t i = 0; i < 6; i++){
                if (i > 0) std::cout << ",";
                std::cout << "\"" << slots[i].species << "\"";
            }
            std::cout << "]}" << std::endl;
        }
        else if (reader_name == "TeamSummaryReader"){
            TeamSummaryReader reader(Language::English);
            auto team = reader.read_team(log, image);
            std::cout << "{\"species\":[";
            for (size_t i = 0; i < 6; i++){
                if (i > 0) std::cout << ",";
                std::cout << "\"" << team[i].species << "\"";
            }
            std::cout << "]}" << std::endl;
        }
        else if (reader_name == "TeamPreviewReader"){
            TeamPreviewReader reader(Language::English);
            auto result = reader.read(log, image);
            std::cout << "{\"own_species\":[";
            for (size_t i = 0; i < 6; i++){
                if (i > 0) std::cout << ",";
                std::cout << "\"" << result.own[i].species << "\"";
            }
            std::cout << "],\"opponent_species\":[";
            for (size_t i = 0; i < 6; i++){
                if (i > 0) std::cout << ",";
                std::cout << "\"" << result.opp_species[i] << "\"";
            }
            std::cout << "]}" << std::endl;
        }
        else{
            std::cerr << "Unknown reader: " << reader_name << std::endl;
            return 1;
        }
    }catch (const std::exception& e){
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}


}
