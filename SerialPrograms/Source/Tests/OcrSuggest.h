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
//  Returns 0 on success, 1 on error.
int run_ocr_suggest(const std::string& reader_name, const std::string& image_path);

}
#endif
