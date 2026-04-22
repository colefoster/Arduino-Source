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
int test_pokemonChampions_ActionMenuDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_ResultScreenDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_PreparingForBattleDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_PostMatchScreenDetector(const ImageViewRGB32& image, bool target);
int test_pokemonChampions_MainMenuDetector(const ImageViewRGB32& image, bool target);

//  ── OCR Readers (words from filename) ──────────────────────────────

//  Filename: <prefix>_<move0>_<move1>_<move2>_<move3>.png
//  Each move is a slug (e.g. "fake-out"). Use "NONE" for unreadable slots.
int test_pokemonChampions_MoveNameReader(const ImageViewRGB32& image, const std::vector<std::string>& words);

//  Filename: <prefix>_<species-slug>.png
int test_pokemonChampions_SpeciesReader(const ImageViewRGB32& image, const std::vector<std::string>& words);

//  Filename: <prefix>_<hp-pct>.png  (e.g. frame_75.png for 75%)
int test_pokemonChampions_OpponentHPReader(const ImageViewRGB32& image, int target);

//  Filename: <prefix>_<event-type>.png  (e.g. frame_MOVE_USED.png)
int test_pokemonChampions_BattleLogReader(const ImageViewRGB32& image, const std::vector<std::string>& words);

//  Filename: <prefix>_<cursor-slot>.png  (e.g. frame_2.png for slot 2)
int test_pokemonChampions_MoveSelectCursorSlot(const ImageViewRGB32& image, int target);

//  ── Void (development / debug) ─────────────────────────────────────

//  Runs all OCR readers and prints results. No pass/fail — for dev iteration.
int test_pokemonChampions_OCRDump(const ImageViewRGB32& image);


}

#endif
