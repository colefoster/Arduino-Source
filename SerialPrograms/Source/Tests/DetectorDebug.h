/*  Detector Debug
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Run all detectors on a single image with verbose output showing
 *  internal decision values (color stats per region, threshold comparisons).
 *  Used for tuning detectors against failing test images.
 */

#ifndef PokemonAutomation_Tests_DetectorDebug_H
#define PokemonAutomation_Tests_DetectorDebug_H

#include <string>

namespace PokemonAutomation{

//  Run all Champions detectors on `image_path` with verbose debug output.
//  Prints JSON to stdout with per-detector results including:
//  - detected: bool
//  - regions: [{name, box, color_stats, is_solid_result, threshold}]
//  Returns 0 on success.
int run_detector_debug(const std::string& image_path);

}
#endif
