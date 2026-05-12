/*  Manifest-based Test Runner
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Runs detector/reader tests using the screen-based test_images/ structure.
 *  Reads test_registry.json for detector/reader→screen mappings and
 *  manifest.json per screen directory for expected reader outputs.
 *
 *  Detectors:  Positive tests on registered screens, negative on all others.
 *  Readers:    Compare output against manifest.json entries.
 */


#ifndef PokemonAutomation_Tests_ManifestTestRunner_H
#define PokemonAutomation_Tests_ManifestTestRunner_H

#include <string>

namespace PokemonAutomation{


//  Run all manifest-based tests from a test_images/ directory.
//  Returns 0 if all pass, 1 if any fail.
//  Mode: "test" (fail-fast) or "regression" (run all, print summary).
int run_manifest_tests(const std::string& test_images_dir, const std::string& mode);


}
#endif
