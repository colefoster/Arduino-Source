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

//  ── Void (development / debug) ─────────────────────────────────────

//  Runs all OCR readers and prints results. No pass/fail — for dev iteration.
int test_pokemonChampions_OCRDump(const ImageViewRGB32& image);


}

#endif
