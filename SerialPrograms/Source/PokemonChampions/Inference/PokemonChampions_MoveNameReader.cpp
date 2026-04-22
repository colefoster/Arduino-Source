/*  Pokemon Champions Move Name Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates measured from ref_frames/1/frame_00080.jpg (1920x1080).
 *
 *  The move-select panel has four stacked pill bars on the right side of
 *  the screen. Each pill contains:
 *    [type icon ~40px] [move name ~200px] [PP count ~80px]
 *
 *  We crop just the move-name text region to avoid feeding the type icon
 *  or PP numbers to the OCR engine.
 *
 *  Pixel measurements (1920x1080):
 *    Move name text x: ~1340 to ~1540  (after type icon, before PP)
 *    Slot 1 y: ~522-556
 *    Slot 2 y: ~652-686
 *    Slot 3 y: ~782-816
 *    Slot 4 y: ~912-946
 *    Spacing: ~130px vertical
 *
 *  The text is white on a gradient-colored pill background. We use
 *  WHITE_TEXT_FILTERS to isolate it.
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_MoveNameReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


MoveNameOCR& MoveNameOCR::instance(){
    static MoveNameOCR reader;
    return reader;
}

MoveNameOCR::MoveNameOCR()
    : SmallDictionaryMatcher("PokemonChampions/PokemonMovesOCR.json")
{}

OCR::StringMatchResult MoveNameOCR::read_substring(
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


MoveNameReader::MoveNameReader(Language language)
    : m_language(language)
{
    //  Move name text boxes — right side of screen, 4 stacked slots.
    //  Shifted right to exclude the type icon circle on the left.
    //  Measured from live capture (doubles frame_229, also works for singles).
    //  x: 1490-1720/1920, ~40px tall, ~126px vertical spacing.
    const double X      = 0.776;
    const double WIDTH  = 0.120;
    const double HEIGHT = 0.037;
    const double Y_SLOTS[4] = {
        0.519,   //  slot 0: y = 560/1080
        0.635,   //  slot 1: y = 686/1080
        0.752,   //  slot 2: y = 812/1080
        0.869,   //  slot 3: y = 938/1080
    };

    for (size_t i = 0; i < 4; i++){
        m_move_name_boxes[i] = ImageFloatBox(X, Y_SLOTS[i], WIDTH, HEIGHT);
    }
}

void MoveNameReader::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& box : m_move_name_boxes){
        items.add(COLOR_GREEN, box);
    }
}

std::string MoveNameReader::read_move(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 4){
        return "";
    }
    ImageViewRGB32 cropped = extract_box_reference(screen, m_move_name_boxes[slot]);
    OCR::StringMatchResult result = MoveNameOCR::instance().read_substring(
        logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
    );

    if (result.results.empty()){
        return "";
    }
    if (result.results.size() > 1){
        logger.log(
            "MoveNameReader: ambiguous match for slot " + std::to_string(slot) +
            " (" + std::to_string(result.results.size()) + " candidates)",
            COLOR_RED
        );
    }
    return result.results.begin()->second.token;
}

std::array<std::string, 4> MoveNameReader::read_all_moves(
    Logger& logger, const ImageViewRGB32& screen
) const{
    std::array<std::string, 4> moves;
    for (uint8_t i = 0; i < 4; i++){
        moves[i] = read_move(logger, screen, i);
    }
    return moves;
}


}
}
}
