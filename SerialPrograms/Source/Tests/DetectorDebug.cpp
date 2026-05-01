/*  Detector Debug
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Verbose detector analysis for tuning.
 */

#include "DetectorDebug.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/Logging/Logger.h"

#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_ActionMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreparingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PostMatchDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MainMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamPreviewDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_TeamSummaryReader.h"  // contains MovesMoreDetector
#include "PokemonChampions/Inference/PokemonChampions_MegaEvolveDetector.h"

#include <iostream>
#include <sstream>
#include <iomanip>

namespace PokemonAutomation{

using namespace NintendoSwitch::PokemonChampions;


//  Helper: extract a crop box and compute color stats, output as JSON fragment.
static std::string region_stats_json(
    const ImageViewRGB32& screen,
    const std::string& name,
    double x, double y, double w, double h
){
    ImageFloatBox box(x, y, w, h);
    ImageViewRGB32 crop = extract_box_reference(screen, box);
    ImageStats stats = image_stats(crop);

    std::ostringstream ss;
    ss << std::fixed << std::setprecision(4);
    ss << "{\"name\":\"" << name << "\""
       << ",\"box\":[" << x << "," << y << "," << w << "," << h << "]"
       << ",\"avg\":[" << stats.average.r << "," << stats.average.g << "," << stats.average.b << "]"
       << ",\"stddev\":" << stats.stddev.sum()
       << ",\"count\":" << stats.count
       << "}";
    return ss.str();
}


int run_detector_debug(const std::string& image_path){
    try{
        ImageRGB32 image(image_path);

        std::cout << "{\"image\":\"" << image_path << "\""
                  << ",\"width\":" << image.width()
                  << ",\"height\":" << image.height()
                  << ",\"detectors\":[";

        bool first = true;

        //  Helper macro to add a detector result
        #define ADD_DETECTOR(NAME, CLASS) \
        { \
            if (!first) std::cout << ","; \
            first = false; \
            CLASS detector; \
            bool result = detector.detect(image); \
            std::cout << "{\"name\":\"" << NAME << "\",\"detected\":" << (result ? "true" : "false") << "}"; \
        }

        ADD_DETECTOR("MoveSelectDetector", MoveSelectDetector)
        ADD_DETECTOR("ActionMenuDetector", ActionMenuDetector)
        ADD_DETECTOR("ResultScreenDetector", ResultScreenDetector)
        ADD_DETECTOR("PreparingForBattleDetector", PreparingForBattleDetector)
        ADD_DETECTOR("PostMatchScreenDetector", PostMatchScreenDetector)
        ADD_DETECTOR("MainMenuDetector", MainMenuDetector)
        ADD_DETECTOR("TeamSelectDetector", TeamSelectDetector)
        ADD_DETECTOR("TeamPreviewDetector", TeamPreviewDetector)
        ADD_DETECTOR("MovesMoreDetector", MovesMoreDetector)
        ADD_DETECTOR("MegaEvolveDetector", MegaEvolveDetector)

        #undef ADD_DETECTOR

        std::cout << "]";

        //  Also output color stats for key regions used by detectors.
        //  This lets the dashboard show what the detector "sees" for tuning.
        std::cout << ",\"regions\":[";

        bool first_region = true;
        auto add_region = [&](const std::string& json){
            if (!first_region) std::cout << ",";
            first_region = false;
            std::cout << json;
        };

        //  MoveSelectDetector regions (4 pill left edges)
        add_region(region_stats_json(image, "move_pill_0", 0.7292, 0.5116, 0.0101, 0.0139));
        add_region(region_stats_json(image, "move_pill_1", 0.7292, 0.6338, 0.0101, 0.0139));
        add_region(region_stats_json(image, "move_pill_2", 0.7292, 0.7542, 0.0101, 0.0139));
        add_region(region_stats_json(image, "move_pill_3", 0.7292, 0.8746, 0.0101, 0.0139));

        //  ActionMenuDetector regions (FIGHT and POKEMON glow)
        add_region(region_stats_json(image, "fight_glow", 0.9219, 0.5787, 0.0182, 0.0213));
        add_region(region_stats_json(image, "pokemon_glow", 0.8932, 0.7907, 0.0182, 0.0213));

        //  TeamPreviewDetector region (title text)
        add_region(region_stats_json(image, "preview_title", 0.3604, 0.2037, 0.1375, 0.0389));

        //  PostMatchScreenDetector — quit/edit/continue button areas
        add_region(region_stats_json(image, "quit_btn", 0.0521, 0.8926, 0.2083, 0.0556));
        add_region(region_stats_json(image, "edit_btn", 0.3333, 0.8926, 0.2083, 0.0556));
        add_region(region_stats_json(image, "continue_btn", 0.6458, 0.8926, 0.2604, 0.0556));

        std::cout << "]}" << std::endl;

    }catch (const std::exception& e){
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
    return 0;
}


}
