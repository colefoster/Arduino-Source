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

#include "PokemonChampions/Inference/PokemonChampions_ActiveHUDSlotDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSelectReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewReader.h"
#include "PokemonChampions/Inference/PokemonChampions_PokeballAliveDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_AbilityItemReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TargetSelectReader.h"

#include <array>
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
        else if (reader_name == "ActiveHUDSlot"){
            ActiveHUDSlotDetector det;
            det.detect(image);
            std::cout << "{\"slot\":" << det.active_slot() << "}" << std::endl;
        }
        else if (reader_name == "BattleHUDReader"){
            //  Unified two-slot layout. Singles only has slot 1 populated;
            //  callers/labels treat slot-0 noise as "absent."
            BattleHUDReader reader(Language::English);
            std::string opp0 = reader.read_opponent_species(log, image, 0);
            std::string opp1 = reader.read_opponent_species(log, image, 1);
            std::string own_sp0 = reader.read_own_species(log, image, 0);
            std::string own_sp1 = reader.read_own_species(log, image, 1);
            int hp0 = reader.read_opponent_hp_pct(log, image, 0);
            int hp1 = reader.read_opponent_hp_pct(log, image, 1);
            auto own0 = reader.read_own_hp_with_raw(log, image, 0);
            auto own1 = reader.read_own_hp_with_raw(log, image, 1);
            //  PP boxes only render on the move-select screen; on other
            //  screens these reads return {-1,-1} and are ignored downstream.
            //  Max PP is dropped from the schema — it's static (move data
            //  has it). Current PP is best-effort; -1 means "not available".
            std::array<std::pair<int,int>, 4> pp;
            for (size_t i = 0; i < 4; i++) pp[i] = reader.read_move_pp(log, image, (uint8_t)i);
            std::cout << "{"
                << "\"opponent_species\":[\"" << opp0 << "\",\"" << opp1 << "\"],"
                << "\"opponent_hp_pct\":[" << hp0 << "," << hp1 << "],"
                << "\"own_hp_current\":[" << own0.cur << "," << own1.cur << "],"
                << "\"own_hp_max\":[" << own0.max << "," << own1.max << "],"
                << "\"own_hp_current_raw\":[" << own0.cur_raw << "," << own1.cur_raw << "],"
                << "\"own_hp_max_raw\":[" << own0.max_raw << "," << own1.max_raw << "],"
                << "\"own_species\":[\"" << own_sp0 << "\",\"" << own_sp1 << "\"],"
                << "\"move_pp_current\":["
                    << pp[0].first << "," << pp[1].first << ","
                    << pp[2].first << "," << pp[3].first << "]"
                << "}" << std::endl;
        }
        else if (reader_name == "BattleLogReader"){
            BattleLogReader reader;
            auto event = reader.read_event(log, image);
            //  raw_text is emitted under event_type_raw so the dashboard's
            //  "(raw: X)" annotation surfaces the OCR string alongside the
            //  classified event_type.
            std::string raw = event.raw_text;
            for (size_t i = 0; i < raw.size(); i++){
                if (raw[i] == '"' || raw[i] == '\\') raw[i] = ' ';
                else if (raw[i] == '\n' || raw[i] == '\r' || raw[i] == '\t') raw[i] = ' ';
            }
            std::cout << "{\"event_type\":\"" << event_type_to_string(event.type) << "\","
                      << "\"event_type_raw\":\"" << raw << "\"}" << std::endl;
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
        else if (reader_name == "PokeballAliveDetector"){
            PokeballAliveDetector det;
            PokeballAliveResult r = det.read(image);
            std::cout << "{\"own\":[";
            for (size_t i = 0; i < 6; i++){
                if (i > 0) std::cout << ",";
                std::cout << "\"" << pokeball_state_name(r.own[i]) << "\"";
            }
            std::cout << "],\"opp\":[";
            for (size_t i = 0; i < 6; i++){
                if (i > 0) std::cout << ",";
                std::cout << "\"" << pokeball_state_name(r.opp[i]) << "\"";
            }
            std::cout << "],\"own_alive\":" << (int)r.own_alive_count()
                      << ",\"opp_alive\":" << (int)r.opp_alive_count()
                      << "}" << std::endl;
        }
        else if (reader_name == "AbilityItemReader"){
            auto& log = global_logger_command_line();
            AbilityItemReader reader;
            AbilityItemReadout r = reader.read(log, image);
            //  Escape any quote chars in raw_text for safe JSON.
            std::string raw_escaped;
            for (char c : r.raw_text){
                if (c == '"') raw_escaped += "\\\"";
                else if (c == '\\') raw_escaped += "\\\\";
                else if (c == '\n') raw_escaped += " ";
                else raw_escaped += c;
            }
            std::cout << "{\"detected\":" << (r.detected ? "true" : "false")
                      << ",\"side\":\"" << r.side << "\""
                      << ",\"kind\":\"" << r.kind << "\""
                      << ",\"name\":\"" << r.name << "\""
                      << ",\"pokemon\":\"" << r.pokemon << "\""
                      << ",\"raw_text\":\"" << raw_escaped << "\""
                      << "}" << std::endl;
        }
        else if (reader_name == "TargetSelectReader"){
            auto& log = global_logger_command_line();
            TargetSelectReader reader(Language::English);
            TargetSelectReadout r = reader.read(log, image);
            auto bool_str = [](bool v){ return v ? "true" : "false"; };
            std::cout << "{"
                << "\"own_moves\":[\"" << r.own_moves[0] << "\",\"" << r.own_moves[1] << "\"],"
                << "\"opp_targeted\":[" << bool_str(r.opp_targeted[0]) << "," << bool_str(r.opp_targeted[1]) << "],"
                << "\"own_targeted\":[" << bool_str(r.own_targeted[0]) << "," << bool_str(r.own_targeted[1]) << "],"
                << "\"opp_effectiveness\":[\"" << r.opp_effectiveness[0] << "\",\"" << r.opp_effectiveness[1] << "\"],"
                << "\"own_effectiveness\":[\"" << r.own_effectiveness[0] << "\",\"" << r.own_effectiveness[1] << "\"]"
                << "}" << std::endl;
        }
        else if (reader_name == "ResultReader"){
            //  Wrapper around ResultScreenDetector — exposes the won bool as
            //  a reader entry. detect() must succeed for the won field to be
            //  meaningful; if not on a result screen, both fields are false.
            ResultScreenDetector det;
            bool detected = det.detect(image);
            std::cout << "{\"won\":" << (detected && det.won() ? "true" : "false")
                      << ",\"detected\":" << (detected ? "true" : "false")
                      << "}" << std::endl;
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
