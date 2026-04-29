/*  Command Line Tool Main
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Command-line executable for Pokemon Automation utilities.
 *
 *  Usage:
 *    SerialProgramsCommandLine --test <path>     Run tests on a directory or file
 *    SerialProgramsCommandLine <port_name>       Test controller on a serial port
 *
 *  Test path can be:
 *    CommandLineTests/                                          (run all tests)
 *    CommandLineTests/PokemonChampions/                         (run all Champions tests)
 *    CommandLineTests/PokemonChampions/OCRDump/                 (run one test category)
 *    CommandLineTests/PokemonChampions/OCRDump/frame.png        (run on a single file)
 */

#include <iostream>
#include <string>
#include <cstring>
#include <QCoreApplication>
#include "Common/Cpp/Color.h"
#include "CommonFramework/Logging/Logger.h"
#include "Tests/CommandLineTests.h"
#include "Tests/ManifestTestRunner.h"

//  OCR suggest mode — reader includes
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/Language.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveNameReader.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleLogReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSelectReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSummaryReader.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewReader.h"
#include "Integrations/PybindSwitchController.h"
#include "NintendoSwitch/Controllers/NintendoSwitch_ControllerButtons.h"

using namespace PokemonAutomation;
using namespace PokemonAutomation::NintendoSwitch;

static void print_usage(const char* argv0){
    std::cerr << "Usage:" << std::endl;
    std::cerr << "  " << argv0 << " --test <path>            Run tests (fail-fast) on a directory or file" << std::endl;
    std::cerr << "  " << argv0 << " --regression <path>      Run all tests and print accuracy report" << std::endl;
    std::cerr << "  " << argv0 << " --manifest-test <dir>    Run manifest-based tests (fail-fast) on test_images/ dir" << std::endl;
    std::cerr << "  " << argv0 << " --manifest-regression <dir>  Run manifest-based regression report" << std::endl;
    std::cerr << "  " << argv0 << " --ocr-suggest <reader> <image>  Run one reader on one image, output JSON" << std::endl;
    std::cerr << "  " << argv0 << " <port_name>              Test controller on a serial port" << std::endl;
}

static int run_controller_test(Logger& logger, const std::string& port_name){
    logger.log("================================================================================");
    logger.log("Testing PybindSwitchProController...");

    try{
        logger.log("Creating PybindSwitchProController with port: " + port_name);

        PybindSwitchProController controller(port_name);
        controller.wait_for_ready(5000);

        if (controller.is_ready()){
            logger.log("Controller is ready!", COLOR_GREEN);
            logger.log("Status: " + controller.current_status());

            logger.log("Mashing A button for 3 seconds...");

            for (int i = 0; i < 30; i++){
                controller.push_button(0, 50, 50, static_cast<uint32_t>(BUTTON_A));
            }

            logger.log("Waiting for all requests to complete...");
            controller.wait_for_all_requests();

            logger.log("A button mashing completed!", COLOR_GREEN);
        }else{
            logger.log("Controller is not ready!", COLOR_RED);
            logger.log("Status: " + controller.current_status());
        }

    }catch (const std::exception& e){
        logger.log("Error during controller test: " + std::string(e.what()), COLOR_RED);
    }

    return 0;
}

int main(int argc, char* argv[]){
    //  QCoreApplication is needed so that QCoreApplication::applicationDirPath()
    //  works — which RESOURCE_PATH() depends on to find OCR dictionaries.
    QCoreApplication qt_app(argc, argv);

    Logger& logger = global_logger_command_line();

    logger.log("================================================================================");
    logger.log("Pokemon Automation - Command Line Tool");

    if (argc < 2){
        print_usage(argv[0]);
        return 1;
    }

    //  --test mode: run the test framework on a given path (fail-fast).
    if (std::strcmp(argv[1], "--test") == 0){
        if (argc < 3){
            std::cerr << "Error: --test requires a path argument." << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        const std::string test_path = argv[2];
        logger.log("Running tests on: " + test_path);
        int ret = run_command_line_tests(test_path);
        logger.log("================================================================================");
        if (ret == 0){
            logger.log("All tests passed.", COLOR_GREEN);
        }else{
            logger.log("Tests failed.", COLOR_RED);
        }
        return ret;
    }

    //  --regression mode: run all tests, report accuracy per reader.
    if (std::strcmp(argv[1], "--regression") == 0){
        if (argc < 3){
            std::cerr << "Error: --regression requires a path argument." << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        const std::string test_path = argv[2];
        logger.log("Running regression report on: " + test_path);
        int ret = run_regression_report(test_path);
        logger.log("================================================================================");
        if (ret == 0){
            logger.log("All tests passed.", COLOR_GREEN);
        }else{
            logger.log("Some tests failed — see report above.", COLOR_RED);
        }
        return ret;
    }

    //  --manifest-test mode: screen-based tests from test_images/ (fail-fast).
    if (std::strcmp(argv[1], "--manifest-test") == 0){
        if (argc < 3){
            std::cerr << "Error: --manifest-test requires a test_images/ directory." << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        const std::string dir = argv[2];
        logger.log("Running manifest tests on: " + dir);
        int ret = run_manifest_tests(dir, "test");
        logger.log("================================================================================");
        if (ret == 0){
            logger.log("All tests passed.", COLOR_GREEN);
        }else{
            logger.log("Tests failed.", COLOR_RED);
        }
        return ret;
    }

    //  --manifest-regression mode: screen-based regression report.
    if (std::strcmp(argv[1], "--manifest-regression") == 0){
        if (argc < 3){
            std::cerr << "Error: --manifest-regression requires a test_images/ directory." << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        const std::string dir = argv[2];
        logger.log("Running manifest regression on: " + dir);
        int ret = run_manifest_tests(dir, "regression");
        logger.log("================================================================================");
        if (ret == 0){
            logger.log("All tests passed.", COLOR_GREEN);
        }else{
            logger.log("Some tests failed — see report above.", COLOR_RED);
        }
        return ret;
    }

    //  --ocr-suggest mode: run one reader on one image, output JSON.
    if (std::strcmp(argv[1], "--ocr-suggest") == 0){
        if (argc < 4){
            std::cerr << "Error: --ocr-suggest requires <reader> and <image> arguments." << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        const std::string reader_name = argv[2];
        const std::string image_path = argv[3];
        logger.log("OCR suggest: reader=" + reader_name + " image=" + image_path);

        try{
            ImageRGB32 image(image_path);
            auto& log = global_logger_command_line();

            //  Run the appropriate reader and output JSON to stdout.
            //  Each reader outputs its fields as a JSON object.
            if (reader_name == "MoveNameReader"){
                NintendoSwitch::PokemonChampions::MoveNameReader reader(Language::English);
                auto moves = reader.read_all_moves(log, image);
                std::cout << "{\"moves\":[";
                for (size_t i = 0; i < 4; i++){
                    if (i > 0) std::cout << ",";
                    std::cout << "\"" << moves[i] << "\"";
                }
                std::cout << "]}" << std::endl;
            }
            else if (reader_name == "MoveSelectCursorSlot"){
                NintendoSwitch::PokemonChampions::MoveSelectDetector det;
                det.detect(image);
                std::cout << "{\"slot\":" << det.cursor_slot() << "}" << std::endl;
            }
            else if (reader_name == "BattleHUDReader" || reader_name == "SpeciesReader"){
                NintendoSwitch::PokemonChampions::BattleHUDReader reader(Language::English);
                std::string species = reader.read_opponent_species(log, image, 0);
                int hp = reader.read_opponent_hp_pct(log, image, 0);
                std::cout << "{\"opponent_species\":\"" << species << "\",\"opponent_hp_pct\":" << hp << "}" << std::endl;
            }
            else if (reader_name == "BattleLogReader"){
                NintendoSwitch::PokemonChampions::BattleLogReader reader;
                auto event = reader.read_event(log, image);
                std::cout << "{\"event_type\":\"" << event.raw_text << "\"}" << std::endl;
            }
            else if (reader_name == "TeamSelectReader"){
                NintendoSwitch::PokemonChampions::TeamSelectReader reader(Language::English);
                auto slots = reader.read_all_slots(log, image);
                std::cout << "{\"species\":[";
                for (size_t i = 0; i < 6; i++){
                    if (i > 0) std::cout << ",";
                    std::cout << "\"" << slots[i].species << "\"";
                }
                std::cout << "]}" << std::endl;
            }
            else if (reader_name == "TeamSummaryReader"){
                NintendoSwitch::PokemonChampions::TeamSummaryReader reader(Language::English);
                auto team = reader.read_team(log, image);
                std::cout << "{\"species\":[";
                for (size_t i = 0; i < 6; i++){
                    if (i > 0) std::cout << ",";
                    std::cout << "\"" << team[i].species << "\"";
                }
                std::cout << "]}" << std::endl;
            }
            else if (reader_name == "TeamPreviewReader"){
                NintendoSwitch::PokemonChampions::TeamPreviewReader reader(Language::English);
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

    //  Legacy mode: controller test.
    const std::string port_name = argv[1];
    int ret = run_controller_test(logger, port_name);

    logger.log("================================================================================");
    logger.log("Program completed.");
    return ret;
}
