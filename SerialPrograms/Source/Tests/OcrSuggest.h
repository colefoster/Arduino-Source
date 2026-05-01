/*  OCR Suggest
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Run a single reader on a single image and output JSON to stdout.
 *  Used by the --ocr-suggest CLI mode for the web labeler.
 */

#ifndef PokemonAutomation_Tests_OcrSuggest_H
#define PokemonAutomation_Tests_OcrSuggest_H

#include <string>

namespace PokemonAutomation{

//  Run `reader_name` on `image_path`, print JSON to stdout.
//  Optional `mode` ("singles"/"doubles") tweaks BattleHUDReader: when
//  "singles" the slot-1 boxes are skipped and slot 0 uses the singles
//  coords. Empty mode defaults to doubles for backward compat.
//  Returns 0 on success, 1 on error.
int run_ocr_suggest(const std::string& reader_name, const std::string& image_path,
                    const std::string& mode = "");

}
#endif
