/*  Pokemon Champions Move Name Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  OCR reader for the four move-name labels on the move-select screen.
 *  Uses a SmallDictionaryMatcher loaded from the Champions move vocabulary
 *  (~475 moves). Each slot is cropped to the text-only region (excluding
 *  the type icon on the left and the PP numbers on the right) and run
 *  through Tesseract with white-text color filters.
 *
 *  Coordinates measured from ref_frames/1/frame_00080.jpg (1920x1080).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_MoveNameReader_H
#define PokemonAutomation_PokemonChampions_MoveNameReader_H

#include <array>
#include <string>
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/OCR/OCR_SmallDictionaryMatcher.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Singleton dictionary matcher for Champions move names.
class MoveNameOCR : public OCR::SmallDictionaryMatcher{
    static constexpr double MAX_LOG10P = -1.30;
    static constexpr double MAX_LOG10P_SPREAD = 0.50;

public:
    static MoveNameOCR& instance();

    OCR::StringMatchResult read_substring(
        Logger& logger,
        Language language,
        const ImageViewRGB32& image,
        const std::vector<OCR::TextColorRange>& text_color_ranges,
        double min_text_ratio = 0.01, double max_text_ratio = 0.50
    ) const;

private:
    MoveNameOCR();
};


//  Bundles the four read move names with the doubles "active slot"
//  context (which own mon the moves belong to). active_slot is 0 or 1
//  in doubles, or -1 for singles / when no lime-green active outline
//  is detected on either HUD pill.
struct MoveSelectionRead{
    int active_slot = -1;
    std::array<std::string, 4> moves{};
};


//  Reads all four move names from a move-select screen capture.
class MoveNameReader{
public:
    MoveNameReader(Language language = Language::English);

    void make_overlays(VideoOverlaySet& items) const;

    //  Read a single move slot (0-3). Returns the matched slug, or "" on failure.
    std::string read_move(Logger& logger, const ImageViewRGB32& screen, uint8_t slot) const;

    //  Read all four move slots. Returns slugs; empty string for any failed read.
    std::array<std::string, 4> read_all_moves(Logger& logger, const ImageViewRGB32& screen) const;

    //  Doubles helper: returns which own HUD pill is highlighted (0 or 1),
    //  or -1 if no active outline is detected.
    int read_active_slot(Logger& logger, const ImageViewRGB32& screen) const;

    //  Read moves + active slot in one pass. In singles, active_slot will be -1.
    MoveSelectionRead read_all(Logger& logger, const ImageViewRGB32& screen) const;

private:
    Language m_language;
    std::array<ImageFloatBox, 4> m_move_name_boxes;
};


}
}
}
#endif
