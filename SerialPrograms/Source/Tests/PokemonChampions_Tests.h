/*  PokemonChampions Tests
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Command-line test functions for Pokemon Champions detectors and OCR readers.
 *  These exercise the real C++ OCR pipeline (Tesseract + SmallDictionaryMatcher)
 *  against static screenshot images.
 *
 */


#ifndef PokemonAutomation_Tests_PokemonChampions_Tests_H
#define PokemonAutomation_Tests_PokemonChampions_Tests_H

#include <array>
#include <vector>
#include <string>

namespace PokemonAutomation{

class ImageViewRGB32;


//  ── Screen Detectors (bool) ────────────────────────────────────────

int test_pokemonChampions_MoveSelectDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_MegaEvolveDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_ActionMenuDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_ResultScreenDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_PreparingForBattleDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_PostMatchScreenDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_MainMenuDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_PreMatchDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_SearchingForBattleDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_RankedFormatSelectDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_BattleModeMenuDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_PokemonSwitchDetector(const ImageViewRGB32& image, bool target);

//  ── OCR Readers (words from filename) ──────────────────────────────

//  Filename: <prefix>_<move0>_<move1>_<move2>_<move3>.png
//  Each move is a slug (e.g. "fake-out"). Use "NONE" for unreadable slots.
int test_pokemonChampions_MoveNameReader(const ImageViewRGB32& image, const std::vector<std::string>& words);

//  BattleHUDReader fields (opponent_species, opponent_hp_pct, own_species,
//  own_hp_current, own_hp_max) are exercised directly by the manifest
//  runner against the unified BattleHUDReader class — no per-field test
//  wrappers needed.

//  Filename: <prefix>_<event-type>.png  (e.g. frame_MOVE_USED.png)
int test_pokemonChampions_BattleLogReader(const ImageViewRGB32& image, const std::vector<std::string>& words);

//  Filename: <prefix>_<cursor-slot>.png  (e.g. frame_2.png for slot 2)
int test_pokemonChampions_MoveSelectCursorSlot(const ImageViewRGB32& image, int target);

//  Doubles: which own HUD pill is highlighted (0 = left, 1 = right).
//  Target -1 means "expect no active outline" (singles or transition state).
int test_pokemonChampions_ActiveHUDSlot(const ImageViewRGB32& image, int target);

//  ── Team Scanner ──────────────────────────────────────────────────

//  Filename: standard bool-target convention.
int test_pokemonChampions_TeamSelectDetector(const ImageViewRGB32& image, bool target);

//  Doubles target-select modal. Standard bool-target convention.
int test_pokemonChampions_TargetSelectDetector(const ImageViewRGB32& image, bool target);

//  Filename: <prefix>_<species0>_<species1>_..._<species5>.png (6 species slugs)
int test_pokemonChampions_TeamSelectReader(const ImageViewRGB32& image, const std::vector<std::string>& words);

//  Filename: <prefix>_<species0>_<species1>_..._<species5>.png
//  Reads all 6 cards from the "Moves & More" grid; verifies species only.
int test_pokemonChampions_TeamSummaryReader(const ImageViewRGB32& image, const std::vector<std::string>& words);

//  Filename: standard bool-target convention.
int test_pokemonChampions_MovesMoreDetector(const ImageViewRGB32& image, bool target);

//  Filename: standard bool-target convention.
int test_pokemonChampions_TeamPreviewDetector(const ImageViewRGB32& image, bool target);

//  Filename: <prefix>_<opp0>_<opp1>_..._<opp5>.png (opponent species slugs, NONE for skips)
int test_pokemonChampions_TeamPreviewReader(const ImageViewRGB32& image, const std::vector<std::string>& words);

//  ResultReader exposes ResultScreenDetector::won() as a manifest-validatable
//  field. `target_won` is the expected bool from the manifest.
int test_pokemonChampions_ResultReader(const ImageViewRGB32& image, bool target_won);

//  AbilityItemReader expected fields from the manifest (kind/name/pokemon).
int test_pokemonChampions_AbilityItemReader(
    const ImageViewRGB32& image,
    const std::string& target_kind,
    const std::string& target_name,
    const std::string& target_pokemon
);

//  TargetSelectReader: own_moves[2], opp_targeted[2], own_targeted[2],
//  opp_effectiveness[2], own_effectiveness[2]. Each "" expected slot is
//  treated as "skip" (don't validate this slot).
int test_pokemonChampions_TargetSelectReader(
    const ImageViewRGB32& image,
    const std::array<std::string, 2>& target_own_moves,
    const std::array<int,         2>& target_opp_targeted,  //  -1 skip, 0 false, 1 true
    const std::array<int,         2>& target_own_targeted,
    const std::array<std::string, 2>& target_opp_effectiveness,
    const std::array<std::string, 2>& target_own_effectiveness
);

//  ── Void (development / debug) ─────────────────────────────────────

//  Runs all OCR readers and prints results. No pass/fail — for dev iteration.
int test_pokemonChampions_OCRDump(const ImageViewRGB32& image);


}

#endif
