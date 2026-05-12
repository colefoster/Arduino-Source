/*  Pokemon Champions Item Name Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  OCR reader for held-item names using a SmallDictionaryMatcher loaded
 *  from the Champions item vocabulary (~106 items including Mega Stones).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_ItemNameReader_H
#define PokemonAutomation_PokemonChampions_ItemNameReader_H

#include <string>
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_SmallDictionaryMatcher.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Singleton dictionary matcher for Champions item names.
class ItemNameOCR : public OCR::SmallDictionaryMatcher{
    static constexpr double MAX_LOG10P = -1.40;
    static constexpr double MAX_LOG10P_SPREAD = 0.50;

public:
    static ItemNameOCR& instance();

    OCR::StringMatchResult read_substring(
        Logger& logger,
        Language language,
        const ImageViewRGB32& image,
        const std::vector<OCR::TextColorRange>& text_color_ranges,
        double min_text_ratio = 0.01, double max_text_ratio = 0.50
    ) const;

private:
    ItemNameOCR();
};


}
}
}
#endif
