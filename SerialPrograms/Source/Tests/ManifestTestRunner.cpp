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

static int test_manifest_SpeciesReader(const ImageViewRGB32& image, const json& entry){
    // The manifest stores under BattleHUDReader with opponent_species field.
    // For singles, it's a string. Build words = ["prefix", "species"]
    std::string species = entry.at("opponent_species").get<std::string>();
    std::vector<std::string> words = {"manifest", species};
    return test_pokemonChampions_SpeciesReader(image, words);
}

static int test_manifest_SpeciesReader_Doubles(const ImageViewRGB32& image, const json& entry){
    // Doubles stores per-slot. Entry has "slot" and "opponent_species".
    int slot = entry.at("slot").get<int>();
    std::string species = entry.at("opponent_species").get<std::string>();
    std::string slot_str = "s" + std::to_string(slot);
    std::vector<std::string> words = {"manifest", slot_str, species};
    return test_pokemonChampions_SpeciesReader_Doubles(image, words);
}

static int test_manifest_OpponentHPReader(const ImageViewRGB32& image, const json& entry){
    int hp = entry.at("opponent_hp_pct").get<int>();
    return test_pokemonChampions_OpponentHPReader(image, hp);
}

static int test_manifest_OpponentHPReader_Doubles(const ImageViewRGB32& image, const json& entry){
    int slot = entry.at("slot").get<int>();
    int hp = entry.at("opponent_hp_pct").get<int>();
    std::string slot_str = "s" + std::to_string(slot);
    std::string hp_str = std::to_string(hp);
    std::vector<std::string> words = {"manifest", slot_str, hp_str};
    return test_pokemonChampions_OpponentHPReader_Doubles(image, words);
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

    // ── BattleHUDReader sub-field tests ─────────────────────────────
    //  The manifest has entries like:
    //    "BattleHUDReader": { "opponent_species": "gengar", "opponent_hp_pct": 100 }
    //  But the C++ tests are separate functions per field. We handle them here.

    // Singles SpeciesReader
    {
        TestStats& stats = all_stats["SpeciesReader"];
        stats.name = "SpeciesReader";

        for (const std::string& screen : {"move_select_singles", "action_menu_singles"}){
            std::string full_dir = test_images_dir + "/" + screen;
            std::string manifest_path = full_dir + "/manifest.json";
            json manifest;
            try{ manifest = load_json_file(manifest_path); }catch(...){ continue; }

            for (const auto& [fname, labels] : manifest.items()){
                if (!labels.contains("BattleHUDReader")) continue;
                const auto& hud = labels["BattleHUDReader"];
                if (!hud.contains("opponent_species") || !hud["opponent_species"].is_string()) continue;

                std::string file_path = full_dir + "/" + fname;
                cout << "  " << screen << "/" << fname << " (SpeciesReader)" << endl;

                int ret = 0;
                try{
                    ImageRGB32 image(file_path);
                    std::vector<std::string> words = {"manifest", hud["opponent_species"].get<std::string>()};
                    ret = test_pokemonChampions_SpeciesReader(image, words);
                }catch(const std::exception& e){
                    cerr << "  Exception: " << e.what() << endl;
                    ret = 1;
                }
                if (ret > 0){ stats.failed++; stats.failures.push_back(screen + "/" + fname); if (!regression) return 1; }
                else if (ret == 0){ stats.passed++; }
                else{ stats.skipped++; }
            }
        }
    }

    // Doubles SpeciesReader
    {
        TestStats& stats = all_stats["SpeciesReader_Doubles"];
        stats.name = "SpeciesReader_Doubles";

        for (const std::string& screen : {"move_select_doubles", "action_menu_doubles"}){
            std::string full_dir = test_images_dir + "/" + screen;
            std::string manifest_path = full_dir + "/manifest.json";
            json manifest;
            try{ manifest = load_json_file(manifest_path); }catch(...){ continue; }

            for (const auto& [fname, labels] : manifest.items()){
                if (!labels.contains("SpeciesReader_Doubles")) continue;
                const auto& sr = labels["SpeciesReader_Doubles"];

                std::string file_path = full_dir + "/" + fname;
                cout << "  " << screen << "/" << fname << " (SpeciesReader_Doubles)" << endl;

                int ret = 0;
                try{
                    ImageRGB32 image(file_path);
                    std::string slot_str = "s" + std::to_string(sr["slot"].get<int>());
                    std::vector<std::string> words = {"manifest", slot_str, sr["opponent_species"].get<std::string>()};
                    ret = test_pokemonChampions_SpeciesReader_Doubles(image, words);
                }catch(const std::exception& e){
                    cerr << "  Exception: " << e.what() << endl;
                    ret = 1;
                }
                if (ret > 0){ stats.failed++; stats.failures.push_back(screen + "/" + fname); if (!regression) return 1; }
                else if (ret == 0){ stats.passed++; }
                else{ stats.skipped++; }
            }
        }
    }

    // Singles OwnSpeciesReader
    {
        TestStats& stats = all_stats["OwnSpeciesReader"];
        stats.name = "OwnSpeciesReader";

        for (const std::string& screen : {"move_select_singles", "action_menu_singles"}){
            std::string full_dir = test_images_dir + "/" + screen;
            std::string manifest_path = full_dir + "/manifest.json";
            json manifest;
            try{ manifest = load_json_file(manifest_path); }catch(...){ continue; }

            for (const auto& [fname, labels] : manifest.items()){
                if (!labels.contains("BattleHUDReader")) continue;
                const auto& hud = labels["BattleHUDReader"];
                if (!hud.contains("own_species")) continue;

                //  own_species can be array (per-slot) or scalar string.
                std::string expected;
                if (hud["own_species"].is_array()){
                    if (hud["own_species"].empty()) continue;
                    const auto& v = hud["own_species"][0];
                    if (!v.is_string() || v.get<std::string>().empty()) continue;
                    expected = v.get<std::string>();
                }else if (hud["own_species"].is_string()){
                    expected = hud["own_species"].get<std::string>();
                    if (expected.empty()) continue;
                }else{
                    continue;
                }

                std::string file_path = full_dir + "/" + fname;
                cout << "  " << screen << "/" << fname << " (OwnSpeciesReader)" << endl;

                int ret = 0;
                try{
                    ImageRGB32 image(file_path);
                    std::vector<std::string> words = {"manifest", expected};
                    ret = test_pokemonChampions_OwnSpeciesReader(image, words);
                }catch(const std::exception& e){
                    cerr << "  Exception: " << e.what() << endl;
                    ret = 1;
                }
                if (ret > 0){ stats.failed++; stats.failures.push_back(screen + "/" + fname); if (!regression) return 1; }
                else if (ret == 0){ stats.passed++; }
                else{ stats.skipped++; }
            }
        }
    }

    // Doubles OwnSpeciesReader (per-slot from own_species array)
    {
        TestStats& stats = all_stats["OwnSpeciesReader_Doubles"];
        stats.name = "OwnSpeciesReader_Doubles";

        for (const std::string& screen : {"move_select_doubles", "action_menu_doubles"}){
            std::string full_dir = test_images_dir + "/" + screen;
            std::string manifest_path = full_dir + "/manifest.json";
            json manifest;
            try{ manifest = load_json_file(manifest_path); }catch(...){ continue; }

            for (const auto& [fname, labels] : manifest.items()){
                if (!labels.contains("BattleHUDReader")) continue;
                const auto& hud = labels["BattleHUDReader"];
                if (!hud.contains("own_species") || !hud["own_species"].is_array()) continue;

                std::string file_path = full_dir + "/" + fname;
                for (size_t slot = 0; slot < hud["own_species"].size() && slot < 2; slot++){
                    const auto& v = hud["own_species"][slot];
                    if (!v.is_string()) continue;
                    std::string expected = v.get<std::string>();
                    if (expected.empty()) continue;

                    cout << "  " << screen << "/" << fname << " s" << slot << " (OwnSpeciesReader_Doubles)" << endl;

                    int ret = 0;
                    try{
                        ImageRGB32 image(file_path);
                        std::string slot_str = "s" + std::to_string(slot);
                        std::vector<std::string> words = {"manifest", slot_str, expected};
                        ret = test_pokemonChampions_OwnSpeciesReader_Doubles(image, words);
                    }catch(const std::exception& e){
                        cerr << "  Exception: " << e.what() << endl;
                        ret = 1;
                    }
                    if (ret > 0){ stats.failed++; stats.failures.push_back(screen + "/" + fname + " s" + std::to_string(slot)); if (!regression) return 1; }
                    else if (ret == 0){ stats.passed++; }
                    else{ stats.skipped++; }
                }
            }
        }
    }

    // Singles OpponentHPReader
    {
        TestStats& stats = all_stats["OpponentHPReader"];
        stats.name = "OpponentHPReader";

        for (const std::string& screen : {"move_select_singles", "action_menu_singles"}){
            std::string full_dir = test_images_dir + "/" + screen;
            std::string manifest_path = full_dir + "/manifest.json";
            json manifest;
            try{ manifest = load_json_file(manifest_path); }catch(...){ continue; }

            for (const auto& [fname, labels] : manifest.items()){
                if (!labels.contains("BattleHUDReader")) continue;
                const auto& hud = labels["BattleHUDReader"];
                if (!hud.contains("opponent_hp_pct") || !hud["opponent_hp_pct"].is_number_integer()) continue;

                std::string file_path = full_dir + "/" + fname;
                cout << "  " << screen << "/" << fname << " (OpponentHPReader)" << endl;

                int ret = 0;
                try{
                    ImageRGB32 image(file_path);
                    ret = test_pokemonChampions_OpponentHPReader(image, hud["opponent_hp_pct"].get<int>());
                }catch(const std::exception& e){
                    cerr << "  Exception: " << e.what() << endl;
                    ret = 1;
                }
                if (ret > 0){ stats.failed++; stats.failures.push_back(screen + "/" + fname); if (!regression) return 1; }
                else if (ret == 0){ stats.passed++; }
                else{ stats.skipped++; }
            }
        }
    }

    // Doubles OpponentHPReader
    {
        TestStats& stats = all_stats["OpponentHPReader_Doubles"];
        stats.name = "OpponentHPReader_Doubles";

        for (const std::string& screen : {"move_select_doubles", "action_menu_doubles"}){
            std::string full_dir = test_images_dir + "/" + screen;
            std::string manifest_path = full_dir + "/manifest.json";
            json manifest;
            try{ manifest = load_json_file(manifest_path); }catch(...){ continue; }

            for (const auto& [fname, labels] : manifest.items()){
                if (!labels.contains("OpponentHPReader_Doubles")) continue;
                const auto& hp = labels["OpponentHPReader_Doubles"];

                std::string file_path = full_dir + "/" + fname;
                cout << "  " << screen << "/" << fname << " (OpponentHPReader_Doubles)" << endl;

                int ret = 0;
                try{
                    ImageRGB32 image(file_path);
                    std::string slot_str = "s" + std::to_string(hp["slot"].get<int>());
                    std::string hp_str = std::to_string(hp["opponent_hp_pct"].get<int>());
                    std::vector<std::string> words = {"manifest", slot_str, hp_str};
                    ret = test_pokemonChampions_OpponentHPReader_Doubles(image, words);
                }catch(const std::exception& e){
                    cerr << "  Exception: " << e.what() << endl;
                    ret = 1;
                }
                if (ret > 0){ stats.failed++; stats.failures.push_back(screen + "/" + fname); if (!regression) return 1; }
                else if (ret == 0){ stats.passed++; }
                else{ stats.skipped++; }
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
