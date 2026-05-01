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
#include "Tests/OcrSuggest.h"
#include "Tests/DetectorDebug.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"
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

    //  --detector-debug mode: run all detectors on one image with verbose output.
    if (std::strcmp(argv[1], "--detector-debug") == 0){
        if (argc < 3){
            std::cerr << "Error: --detector-debug requires an image path." << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        return run_detector_debug(argv[2]);
    }

    //  --ocr-suggest mode: run one reader on one image, output JSON.
    if (std::strcmp(argv[1], "--ocr-suggest") == 0){
        if (argc < 4){
            std::cerr << "Error: --ocr-suggest requires <reader> and <image> arguments." << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        return run_ocr_suggest(argv[2], argv[3]);
    }

    //  --ocr-crop mode: run number-tuned OCR on an arbitrary box of one image.
    //  Used by the Inspector tab's "Test OCR" button to iterate on box coords.
    //  Args: <image> <x> <y> <w> <h>  (floats, normalized to image size)
    if (std::strcmp(argv[1], "--ocr-crop") == 0){
        if (argc < 7){
            std::cerr << "Error: --ocr-crop requires <image> <x> <y> <w> <h>." << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        try{
            ImageRGB32 image(argv[2]);
            double x = std::stod(argv[3]);
            double y = std::stod(argv[4]);
            double w = std::stod(argv[5]);
            double h = std::stod(argv[6]);
            ImageFloatBox box(x, y, w, h);
            ImageViewRGB32 cropped = extract_box_reference(image, box);
            std::string raw = NintendoSwitch::PokemonChampions::raw_ocr_numbers(cropped);
            auto frac = NintendoSwitch::PokemonChampions::parse_fraction(raw);
            //  Escape the few JSON-hostile chars in raw OCR output.
            std::string esc;
            for (char c : raw){
                if (c == '"' || c == '\\') { esc += '\\'; esc += c; }
                else if (c == '\n' || c == '\r' || c == '\t') esc += ' ';
                else esc += c;
            }
            std::cout << "{\"raw\":\"" << esc << "\","
                      << "\"current\":" << frac.first << ","
                      << "\"max\":" << frac.second << "}" << std::endl;
            return 0;
        }catch (const std::exception& e){
            std::cerr << "Error: " << e.what() << std::endl;
            return 1;
        }
    }

    //  Legacy mode: controller test.
    const std::string port_name = argv[1];
    int ret = run_controller_test(logger, port_name);

    logger.log("================================================================================");
    logger.log("Program completed.");
    return ret;
}
