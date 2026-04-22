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
#include "Common/Cpp/Color.h"
#include "CommonFramework/Logging/Logger.h"
#include "Tests/CommandLineTests.h"
#include "Integrations/PybindSwitchController.h"
#include "NintendoSwitch/Controllers/NintendoSwitch_ControllerButtons.h"

using namespace PokemonAutomation;
using namespace PokemonAutomation::NintendoSwitch;

static void print_usage(const char* argv0){
    std::cerr << "Usage:" << std::endl;
    std::cerr << "  " << argv0 << " --test <path>     Run tests on a directory or file" << std::endl;
    std::cerr << "  " << argv0 << " <port_name>       Test controller on a serial port" << std::endl;
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
    Logger& logger = global_logger_command_line();

    logger.log("================================================================================");
    logger.log("Pokemon Automation - Command Line Tool");

    if (argc < 2){
        print_usage(argv[0]);
        return 1;
    }

    //  --test mode: run the test framework on a given path.
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

    //  Legacy mode: controller test.
    const std::string port_name = argv[1];
    int ret = run_controller_test(logger, port_name);

    logger.log("================================================================================");
    logger.log("Program completed.");
    return ret;
}
