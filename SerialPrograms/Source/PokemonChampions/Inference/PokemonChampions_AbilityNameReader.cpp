/*  Pokemon Champions Ability Name Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_AbilityNameReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


AbilityNameOCR& AbilityNameOCR::instance(){
    static AbilityNameOCR reader;
    return reader;
}

AbilityNameOCR::AbilityNameOCR()
    : SmallDictionaryMatcher("PokemonChampions/PokemonAbilitiesOCR.json")
{}

OCR::StringMatchResult AbilityNameOCR::read_substring(
    Logger& logger,
    Language language,
    const ImageViewRGB32& image,
    const std::vector<OCR::TextColorRange>& text_color_ranges,
    double min_text_ratio, double max_text_ratio
) const{
    return match_substring_from_image_multifiltered(
        &logger, language, image, text_color_ranges,
        MAX_LOG10P, MAX_LOG10P_SPREAD, min_text_ratio, max_text_ratio
    );
}


}
}
}
