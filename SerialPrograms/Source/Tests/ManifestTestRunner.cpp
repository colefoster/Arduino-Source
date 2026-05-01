/*  Manifest-based Test Runner
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Screen-based test runner for PokemonChampions detectors and readers.
 *  Uses test_registry.json + per-screen manifest.json instead of
 *  filename-encoded labels.
 */

#include "ManifestTestRunner.h"
#include "PokemonChampions_Tests.h"
#include "TestUtils.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/Logging/Logger.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleHUDReader.h"

#include <nlohmann/json.hpp>

#include <QDir>
#include <QDirIterator>

#include <iostream>
#include <fstream>
#include <iomanip>
#include <map>
#include <set>
#include <vector>
#include <functional>

using json = nlohmann::json;
using std::cout;
using std::cerr;
using std::endl;

namespace PokemonAutomation{

// PokemonChampions test functions are in PokemonAutomation namespace already
// (no sub-namespace needed — the test functions are declared in PokemonChampions_Tests.h)


// ═══════════════════════════════════════════════════════════════════════
//  Detector test functions — take image + expected bool
// ═══════════════════════════════════════════════════════════════════════

using BoolDetectorFn = std::function<int(const ImageViewRGB32&, bool)>;

static const std::map<std::string, BoolDetectorFn> DETECTOR_FUNCTIONS = {
    {"TeamSelectDetector",          test_pokemonChampions_TeamSelectDetector},
    {"TeamPreviewDetector",         test_pokemonChampions_TeamPreviewDetector},
    {"PreparingForBattleDetector",  test_pokemonChampions_PreparingForBattleDetector},
    {"ActionMenuDetector",          test_pokemonChampions_ActionMenuDetector},
    {"MoveSelectDetector",          test_pokemonChampions_MoveSelectDetector},
    {"ResultScreenDetector",        test_pokemonChampions_ResultScreenDetector},
    {"PostMatchScreenDetector",     test_pokemonChampions_PostMatchScreenDetector},
    {"MainMenuDetector",            test_pokemonChampions_MainMenuDetector},
    {"MovesMoreDetector",           test_pokemonChampions_MovesMoreDetector},
    {"MegaEvolveDetector",          test_pokemonChampions_MegaEvolveDetector},
};


// ═══════════════════════════════════════════════════════════════════════
//  Reader test functions — take image + JSON manifest entry
//  Return 0 on success, >0 on failure, <0 to skip.
// ═══════════════════════════════════════════════════════════════════════

using ReaderTestFn = std::function<int(const ImageViewRGB32&, const json&)>;


static int test_manifest_MoveNameReader(const ImageViewRGB32& image, const json& entry){
    auto moves_json = entry.at("moves");
    std::vector<std::string> words;
    // Build words array compatible with the existing test function:
    // prefix word + 4 move slugs
    words.push_back("manifest");
    for (const auto& m : moves_json){
        words.push_back(m.is_null() ? "NONE" : m.get<std::string>());
    }
    return test_pokemonChampions_MoveNameReader(image, words);
}

static int test_manifest_MoveSelectCursorSlot(const ImageViewRGB32& image, const json& entry){
    int slot = entry.at("slot").get<int>();
    return test_pokemonChampions_MoveSelectCursorSlot(image, slot);
}

static int test_manifest_ActiveHUDSlot(const ImageViewRGB32& image, const json& entry){
    int slot = entry.at("slot").get<int>();
    return test_pokemonChampions_ActiveHUDSlot(image, slot);
}

static int test_manifest_BattleLogReader(const ImageViewRGB32& image, const json& entry){
    std::string event_type = entry.at("event_type").get<std::string>();
    // Split by _ and pass as words
    std::vector<std::string> words;
    std::string token;
    for (char c : event_type){
        if (c == '_'){
            if (!token.empty()) words.push_back(token);
            token.clear();
        }else{
            token += c;
        }
    }
    if (!token.empty()) words.push_back(token);
    return test_pokemonChampions_BattleLogReader(image, words);
}

static int test_manifest_TeamSelectReader(const ImageViewRGB32& image, const json& entry){
    auto species_json = entry.at("species");
    std::vector<std::string> words;
    words.push_back("manifest");
    for (const auto& s : species_json){
        words.push_back(s.is_null() ? "NONE" : s.get<std::string>());
    }
    return test_pokemonChampions_TeamSelectReader(image, words);
}

static int test_manifest_TeamSummaryReader(const ImageViewRGB32& image, const json& entry){
    auto species_json = entry.at("species");
    std::vector<std::string> words;
    words.push_back("manifest");
    for (const auto& s : species_json){
        words.push_back(s.is_null() ? "NONE" : s.get<std::string>());
    }
    return test_pokemonChampions_TeamSummaryReader(image, words);
}

static int test_manifest_TeamPreviewReader(const ImageViewRGB32& image, const json& entry){
    auto opp_json = entry.at("opponent_species");
    std::vector<std::string> words;
    words.push_back("manifest");
    for (const auto& s : opp_json){
        words.push_back(s.is_null() ? "NONE" : s.get<std::string>());
    }
    return test_pokemonChampions_TeamPreviewReader(image, words);
}


// Map manifest reader names to test functions.
// Note: some manifest readers (like BattleHUDReader) contain multiple sub-fields
// that map to different C++ test functions. We handle this with specialized adapters.
static const std::map<std::string, ReaderTestFn> READER_FUNCTIONS = {
    {"MoveNameReader",       test_manifest_MoveNameReader},
    {"MoveSelectCursorSlot", test_manifest_MoveSelectCursorSlot},
    {"ActiveHUDSlot",        test_manifest_ActiveHUDSlot},
    {"BattleLogReader",      test_manifest_BattleLogReader},
    {"TeamSelectReader",     test_manifest_TeamSelectReader},
    {"TeamSummaryReader",    test_manifest_TeamSummaryReader},
    {"TeamPreviewReader",    test_manifest_TeamPreviewReader},
};

// BattleHUDReader sub-field adapters: the manifest stores fields under
// "BattleHUDReader" but we test them via separate C++ functions.
// These are registered specially below in the test loop.


// ═══════════════════════════════════════════════════════════════════════
//  Stats tracking
// ═══════════════════════════════════════════════════════════════════════

struct TestStats{
    std::string name;
    size_t passed  = 0;
    size_t failed  = 0;
    size_t skipped = 0;
    std::vector<std::string> failures;  // file paths

    size_t total()    const{ return passed + failed; }
    double accuracy() const{ return total() == 0 ? 0.0 : 100.0 * passed / total(); }
};


// ═══════════════════════════════════════════════════════════════════════
//  Helpers
// ═══════════════════════════════════════════════════════════════════════

static json load_json_file(const std::string& path){
    std::ifstream f(path);
    if (!f.is_open()){
        throw std::runtime_error("Cannot open: " + path);
    }
    return json::parse(f);
}

static std::vector<std::string> list_png_files(const std::string& dir_path){
    std::vector<std::string> files;
    QDirIterator iter(QString::fromStdString(dir_path),
                      QStringList() << "*.png" << "*.PNG",
                      QDir::Files);
    while (iter.hasNext()){
        files.push_back(iter.next().toStdString());
    }
    std::sort(files.begin(), files.end());
    return files;
}

static std::string filename_from_path(const std::string& path){
    size_t pos = path.find_last_of("/\\");
    return (pos == std::string::npos) ? path : path.substr(pos + 1);
}


// ═══════════════════════════════════════════════════════════════════════
//  Main runner
// ═══════════════════════════════════════════════════════════════════════

static void print_regression_table(const std::map<std::string, TestStats>& all_stats){
    cout << endl;
    cout << "╔═══════════════════════════════════════════════════════════════╗" << endl;
    cout << "║                    REGRESSION REPORT                        ║" << endl;
    cout << "╠══════════════════════════════════╦════════╦═════════╦════════╣" << endl;
    cout << "║ Test                             ║ Passed ║  Total  ║  Acc.  ║" << endl;
    cout << "╠══════════════════════════════════╬════════╬═════════╬════════╣" << endl;

    size_t grand_passed = 0, grand_total = 0;
    std::vector<const TestStats*> with_failures;

    for (const auto& [key, stats] : all_stats){
        grand_passed += stats.passed;
        grand_total  += stats.total();

        std::string display = stats.name;
        if (display.size() > 32) display = display.substr(0, 32);

        cout << "║ " << std::left << std::setw(32) << display << " ║ "
             << std::right << std::setw(3) << stats.passed << "/" << std::left << std::setw(3) << stats.total()
             << " ║ " << std::right << std::setw(7) << stats.total()
             << " ║ " << std::right << std::setw(5) << std::fixed << std::setprecision(1)
             << stats.accuracy() << "%" << " ║" << endl;

        if (!stats.failures.empty()){
            with_failures.push_back(&stats);
        }
    }

    double grand_acc = grand_total == 0 ? 0.0 : 100.0 * grand_passed / grand_total;
    cout << "╠══════════════════════════════════╬════════╬═════════╬════════╣" << endl;
    cout << "║ " << std::left << std::setw(32) << "OVERALL" << " ║ "
         << std::right << std::setw(3) << grand_passed << "/" << std::left << std::setw(3) << grand_total
         << " ║ " << std::right << std::setw(7) << grand_total
         << " ║ " << std::right << std::setw(5) << std::fixed << std::setprecision(1)
         << grand_acc << "%" << " ║" << endl;
    cout << "╚══════════════════════════════════╩════════╩═════════╩════════╝" << endl;

    if (!with_failures.empty()){
        cout << endl;
        cout << "─── Failures ───────────────────────────────────────────────────" << endl;
        for (const TestStats* stats : with_failures){
            for (const std::string& f : stats->failures){
                cout << "  FAIL  " << stats->name << "  ←  " << f << endl;
            }
        }
        cout << "────────────────────────────────────────────────────────────────" << endl;
    }
}


int run_manifest_tests(const std::string& test_images_dir, const std::string& mode){
    const bool regression = (mode == "regression");

    //  Load registry
    const std::string registry_path = test_images_dir + "/test_registry.json";
    json registry;
    try{
        registry = load_json_file(registry_path);
    }catch (const std::exception& e){
        cerr << "Error loading registry: " << e.what() << endl;
        return 1;
    }

    const auto all_screen_dirs = registry["all_screen_dirs"].get<std::vector<std::string>>();
    const auto overlay_dirs = registry["overlay_dirs"].get<std::vector<std::string>>();

    //  Combine all dirs for negative testing
    std::vector<std::string> all_dirs = all_screen_dirs;
    all_dirs.insert(all_dirs.end(), overlay_dirs.begin(), overlay_dirs.end());

    std::map<std::string, TestStats> all_stats;

    // ── Detector tests ──────────────────────────────────────────────

    for (const auto& [det_name, det_screens_json] : registry["detectors"].items()){
        auto positive_screens = det_screens_json.get<std::set<std::string>>();

        auto fn_it = DETECTOR_FUNCTIONS.find(det_name);
        if (fn_it == DETECTOR_FUNCTIONS.end()){
            cerr << "Warning: no test function for detector " << det_name << ", skipping." << endl;
            continue;
        }
        const auto& test_fn = fn_it->second;

        TestStats& stats = all_stats[det_name];
        stats.name = det_name;

        cout << "===========================================" << endl;
        cout << "Testing detector: " << det_name << endl;

        for (const auto& screen_dir : all_dirs){
            bool expected = (positive_screens.count(screen_dir) > 0);
            std::string full_dir = test_images_dir + "/" + screen_dir;

            auto files = list_png_files(full_dir);
            for (const auto& file_path : files){
                std::string fname = filename_from_path(file_path);
                cout << "  " << screen_dir << "/" << fname
                     << " (expect=" << (expected ? "true" : "false") << ")" << endl;

                int ret = 0;
                try{
                    ImageRGB32 image(file_path);
                    ret = test_fn(image, expected);
                }catch (const std::exception& e){
                    cerr << "  Exception: " << e.what() << endl;
                    ret = 1;
                }

                if (ret > 0){
                    stats.failed++;
                    stats.failures.push_back(screen_dir + "/" + fname);
                    if (!regression) return 1;
                }else if (ret == 0){
                    stats.passed++;
                }else{
                    stats.skipped++;
                }
            }
        }
    }

    // ── Reader tests ────────────────────────────────────────────────

    for (const auto& [reader_name, reader_info] : registry["readers"].items()){
        auto fn_it = READER_FUNCTIONS.find(reader_name);
        if (fn_it == READER_FUNCTIONS.end()){
            //  Check if it's BattleHUDReader — handled specially
            if (reader_name != "BattleHUDReader" && reader_name != "ResultReader"){
                cerr << "Warning: no test function for reader " << reader_name << ", skipping." << endl;
            }
            continue;
        }
        const auto& test_fn = fn_it->second;

        TestStats& stats = all_stats[reader_name];
        stats.name = reader_name;

        for (const auto& [screen_dir, _fields] : reader_info["screens"].items()){
            std::string full_dir = test_images_dir + "/" + screen_dir;
            std::string manifest_path = full_dir + "/manifest.json";

            json manifest;
            try{
                manifest = load_json_file(manifest_path);
            }catch (...){
                continue;  // No manifest = no reader tests for this screen
            }

            cout << "===========================================" << endl;
            cout << "Testing reader: " << reader_name << " on " << screen_dir << endl;

            for (const auto& [img_fname, img_labels] : manifest.items()){
                if (!img_labels.contains(reader_name)){
                    continue;  // This image doesn't have labels for this reader
                }

                const json& reader_entry = img_labels[reader_name];
                std::string file_path = full_dir + "/" + img_fname;

                cout << "  " << screen_dir << "/" << img_fname << endl;

                int ret = 0;
                try{
                    ImageRGB32 image(file_path);
                    ret = test_fn(image, reader_entry);
                }catch (const std::exception& e){
                    cerr << "  Exception: " << e.what() << endl;
                    ret = 1;
                }

                if (ret > 0){
                    stats.failed++;
                    stats.failures.push_back(screen_dir + "/" + img_fname);
                    if (!regression) return 1;
                }else if (ret == 0){
                    stats.passed++;
                }else{
                    stats.skipped++;
                }
            }
        }
    }

    // ── BattleHUDReader (unified, mode-aware) ────────────────────────
    //  Manifest format (per image):
    //    "BattleHUDReader": {
    //      "opponent_species": [str, str],
    //      "opponent_hp_pct":  [int, int],
    //      "own_species":      [str, str],
    //      "own_hp_current":   [int, int],
    //      "own_hp_max":       [int, int],
    //    }
    //  Mode is inferred per image: any populated slot 1 → DOUBLES.
    //  Stats are bucketed per field (ignoring singles/doubles split).
    {
        using namespace NintendoSwitch::PokemonChampions;

        auto& logger = global_logger_command_line();

        const std::string opp_species_key = "BattleHUDReader.opponent_species";
        const std::string opp_hp_key      = "BattleHUDReader.opponent_hp_pct";
        const std::string own_species_key = "BattleHUDReader.own_species";
        const std::string own_hp_cur_key  = "BattleHUDReader.own_hp_current";
        const std::string own_hp_max_key  = "BattleHUDReader.own_hp_max";

        for (const std::string& key : {opp_species_key, opp_hp_key, own_species_key, own_hp_cur_key, own_hp_max_key}){
            all_stats[key].name = key;
        }

        auto str_slot = [](const json& arr, size_t slot, std::string& out) -> bool {
            if (!arr.is_array() || arr.size() <= slot) return false;
            const auto& v = arr[slot];
            if (!v.is_string()) return false;
            out = v.get<std::string>();
            return !out.empty();
        };
        auto int_slot = [](const json& arr, size_t slot, int& out) -> bool {
            if (!arr.is_array() || arr.size() <= slot) return false;
            const auto& v = arr[slot];
            if (!v.is_number_integer()) return false;
            int n = v.get<int>();
            if (n < 0) return false;
            out = n;
            return true;
        };

        auto record = [&](const std::string& key, int ret, const std::string& trace){
            TestStats& s = all_stats[key];
            if (ret > 0){ s.failed++; s.failures.push_back(trace); }
            else if (ret == 0){ s.passed++; }
            else{ s.skipped++; }
        };

        for (const std::string& screen : {"move_select", "action_menu"}){
            std::string full_dir = test_images_dir + "/" + screen;
            std::string manifest_path = full_dir + "/manifest.json";
            json manifest;
            try{ manifest = load_json_file(manifest_path); }catch(...){ continue; }

            cout << "===========================================" << endl;
            cout << "Testing reader: BattleHUDReader on " << screen << endl;

            for (const auto& [fname, labels] : manifest.items()){
                if (!labels.contains("BattleHUDReader")) continue;
                const auto& hud = labels["BattleHUDReader"];

                //  Mode is explicit in the manifest ("singles" or "doubles").
                //  Fall back to inferring from any populated slot 1.
                bool doubles = false;
                if (hud.contains("mode") && hud["mode"].is_string()){
                    doubles = (hud["mode"].get<std::string>() == "doubles");
                }else{
                    for (const std::string& f : {"opponent_species", "own_species"}){
                        if (hud.contains(f) && hud[f].is_array() && hud[f].size() > 1
                            && hud[f][1].is_string() && !hud[f][1].get<std::string>().empty()){
                            doubles = true; break;
                        }
                    }
                    if (!doubles){
                        for (const std::string& f : {"opponent_hp_pct", "own_hp_current", "own_hp_max"}){
                            if (hud.contains(f) && hud[f].is_array() && hud[f].size() > 1
                                && hud[f][1].is_number_integer() && hud[f][1].get<int>() >= 0){
                                doubles = true; break;
                            }
                        }
                    }
                }

                std::string file_path = full_dir + "/" + fname;
                ImageRGB32 image;
                try{ image = ImageRGB32(file_path); }catch (const std::exception& e){
                    cerr << "  Exception loading " << file_path << ": " << e.what() << endl;
                    continue;
                }

                BattleHUDReader reader(
                    Language::English,
                    doubles ? BattleMode::DOUBLES : BattleMode::SINGLES
                );
                uint8_t slot_count = doubles ? 2 : 1;

                cout << "  " << screen << "/" << fname
                     << " (" << (doubles ? "doubles" : "singles") << ")" << endl;

                for (uint8_t slot = 0; slot < slot_count; slot++){
                    std::string trace = screen + "/" + fname + " s" + std::to_string(slot);

                    std::string sp_expected;
                    if (hud.contains("opponent_species") && str_slot(hud["opponent_species"], slot, sp_expected)){
                        std::string got = reader.read_opponent_species(logger, image, slot);
                        record(opp_species_key, got == sp_expected ? 0 : 1, trace);
                    }

                    int hp_expected = -1;
                    if (hud.contains("opponent_hp_pct") && int_slot(hud["opponent_hp_pct"], slot, hp_expected)){
                        int got = reader.read_opponent_hp_pct(logger, image, slot);
                        record(opp_hp_key, got == hp_expected ? 0 : 1, trace);
                    }

                    std::string own_sp_expected;
                    if (hud.contains("own_species") && str_slot(hud["own_species"], slot, own_sp_expected)){
                        std::string got = reader.read_own_species(logger, image, slot);
                        record(own_species_key, got == own_sp_expected ? 0 : 1, trace);
                    }

                    int own_cur_expected = -1, own_max_expected = -1;
                    bool have_cur = hud.contains("own_hp_current") && int_slot(hud["own_hp_current"], slot, own_cur_expected);
                    bool have_max = hud.contains("own_hp_max")     && int_slot(hud["own_hp_max"],     slot, own_max_expected);
                    if (have_cur || have_max){
                        auto got = reader.read_own_hp(logger, image, slot);
                        if (have_cur) record(own_hp_cur_key, got.first  == own_cur_expected ? 0 : 1, trace);
                        if (have_max) record(own_hp_max_key, got.second == own_max_expected ? 0 : 1, trace);
                    }

                    if (!regression){
                        for (const std::string& key : {opp_species_key, opp_hp_key, own_species_key, own_hp_cur_key, own_hp_max_key}){
                            if (all_stats[key].failed > 0) return 1;
                        }
                    }
                }
            }
        }
    }


    // ── Summary ─────────────────────────────────────────────────────

    if (regression){
        print_regression_table(all_stats);
    }

    //  Count overall
    size_t total_passed = 0, total_failed = 0;
    for (const auto& [key, stats] : all_stats){
        total_passed += stats.passed;
        total_failed += stats.failed;
    }

    if (!regression){
        cout << "===========================================" << endl;
        cout << total_passed << " test" << (total_passed != 1 ? "s" : "") << " passed" << endl;
    }

    return total_failed > 0 ? 1 : 0;
}


}
