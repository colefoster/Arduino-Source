/*  Pokemon Champions Battle HUD Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads numeric and text elements from the battle HUD visible during the
 *  move-select screen:
 *
 *    Top-right:    Opponent species name badge, opponent HP%, pokeball row
 *    Bottom-left:  Own Pokemon nickname, own HP (current / max)
 *    Right panel:  PP counts (current / max) for each of the 4 moves
 *    Right panel:  Effectiveness labels below each move name
 *
 *  Coordinates measured from ref_frames/1/frame_00080.jpg (1920x1080).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_BattleHUDReader_H
#define PokemonAutomation_PokemonChampions_BattleHUDReader_H

#include <array>
#include <string>
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/OCR/OCR_SmallDictionaryMatcher.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Singleton dictionary matcher for Pokemon species names (Champions roster).
class SpeciesNameOCR : public OCR::SmallDictionaryMatcher{
    static constexpr double MAX_LOG10P = -1.40;
    static constexpr double MAX_LOG10P_SPREAD = 0.50;

public:
    static SpeciesNameOCR& instance();

    OCR::StringMatchResult read_substring(
        Logger& logger,
        Language language,
        const ImageViewRGB32& image,
        const std::vector<OCR::TextColorRange>& text_color_ranges,
        double min_text_ratio = 0.01, double max_text_ratio = 0.50
    ) const;

private:
    SpeciesNameOCR();
};


struct BattleHUDState{
    //  Opponent info (top-right badge).
    std::string opponent_species;   //  slug, e.g. "greninja"
    int         opponent_hp_pct;    //  0-100, or -1 if unreadable

    //  Own info (bottom-left bar).
    int         own_hp_current;     //  absolute HP, or -1 if unreadable
    int         own_hp_max;         //  absolute HP, or -1 if unreadable

    //  Per-move PP (4 slots, from move-select panel).
    struct MovePP{
        int current = -1;
        int max     = -1;
    };
    std::array<MovePP, 4> move_pp;
};


class BattleHUDReader{
public:
    BattleHUDReader(Language language = Language::English);

    void make_overlays(VideoOverlaySet& items) const;

    //  Read the opponent species name from the top-right badge.
    std::string read_opponent_species(Logger& logger, const ImageViewRGB32& screen) const;

    //  Read opponent HP percentage from the top-right badge (returns 0-100, or -1).
    int read_opponent_hp_pct(Logger& logger, const ImageViewRGB32& screen) const;

    //  Read own HP (current/max) from the bottom-left bar.
    //  Returns {current, max} or {-1, -1} on failure.
    std::pair<int, int> read_own_hp(Logger& logger, const ImageViewRGB32& screen) const;

    //  Read PP for a single move slot (0-3). Returns {current, max} or {-1, -1}.
    std::pair<int, int> read_move_pp(Logger& logger, const ImageViewRGB32& screen, uint8_t slot) const;

    //  Read everything at once.
    BattleHUDState read_all(Logger& logger, const ImageViewRGB32& screen) const;

private:
    Language m_language;

    //  Opponent species name in the top-right colored badge.
    ImageFloatBox m_opponent_name_box;
    //  Opponent HP % text just below the badge.
    ImageFloatBox m_opponent_hp_box;
    //  Own HP "current/max" text in bottom-left info bar.
    ImageFloatBox m_own_hp_box;
    //  PP "current/max" text at the right end of each move pill.
    std::array<ImageFloatBox, 4> m_pp_boxes;
};


}
}
}
#endif
