/*  Pokemon Champions Battle HUD Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads numeric and text elements from the battle HUD. Mode-aware:
 *
 *  SINGLES (BSS):
 *    Top-right:    1 opponent species badge + HP%
 *    Bottom-left:  1 own Pokemon name + HP (current/max)
 *    Right panel:  4 move pills with PP counts
 *
 *  DOUBLES (VGC):
 *    Top-right:    2 opponent species badges + HP%
 *    Bottom-left:  2 own Pokemon names + HP (current/max)
 *    Bottom-right: FIGHT / POKEMON circle buttons (no move pills on action screen)
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
#include "PokemonChampions_BattleModeDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Run number-tuned OCR on an arbitrary crop. White-text filter, 3x upscale,
//  inverted-binary preprocessing. Returns the raw Tesseract output (digits and
//  noise). Used by HP/PP readers and the --ocr-crop debug entry.
std::string raw_ocr_numbers(const ImageViewRGB32& crop);

//  Parse "current/max" from raw OCR text. Returns {-1, -1} on failure.
std::pair<int, int> parse_fraction(const std::string& text);


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


//  Per-slot Pokemon info read from the HUD.
struct HUDPokemonInfo{
    std::string species;    //  slug, e.g. "greninja". Empty if unreadable.
    int         hp_current = -1;    //  absolute HP or -1
    int         hp_max     = -1;    //  absolute HP or -1
    int         hp_pct     = -1;    //  0-100 or -1 (opponents show % only)
};

struct BattleHUDState{
    BattleMode mode = BattleMode::UNKNOWN;

    //  Opponent slots (1 for singles, 2 for doubles).
    std::array<HUDPokemonInfo, 2> opponents;

    //  Own slots (1 for singles, 2 for doubles).
    std::array<HUDPokemonInfo, 2> own;

    //  Per-move PP (4 slots, singles only — doubles shows moves after selecting FIGHT).
    struct MovePP{
        int current = -1;
        int max     = -1;
    };
    std::array<MovePP, 4> move_pp;

    //  How many active slots for the current mode.
    uint8_t slot_count() const{
        return (mode == BattleMode::DOUBLES) ? 2 : 1;
    }
};


class BattleHUDReader{
public:
    BattleHUDReader(Language language = Language::English,
                    BattleMode mode = BattleMode::SINGLES);

    //  Change mode at runtime (updates which boxes are active).
    void set_mode(BattleMode mode);
    BattleMode mode() const{ return m_mode; }

    void make_overlays(VideoOverlaySet& items) const;

    //  Read opponent species name from badge (slot 0 or 1).
    std::string read_opponent_species(Logger& logger, const ImageViewRGB32& screen, uint8_t slot = 0) const;

    //  Read opponent HP% (slot 0 or 1). Returns 0-100 or -1.
    int read_opponent_hp_pct(Logger& logger, const ImageViewRGB32& screen, uint8_t slot = 0) const;

    //  Read own HP current/max (slot 0 or 1). Returns {current, max} or {-1, -1}.
    std::pair<int, int> read_own_hp(Logger& logger, const ImageViewRGB32& screen, uint8_t slot = 0) const;

    //  Read PP for a move slot (0-3). Singles only.
    std::pair<int, int> read_move_pp(Logger& logger, const ImageViewRGB32& screen, uint8_t slot) const;

    //  Read everything at once.
    BattleHUDState read_all(Logger& logger, const ImageViewRGB32& screen) const;

private:
    void init_singles_boxes();
    void init_doubles_boxes();

    Language m_language;
    BattleMode m_mode;

    //  Up to 2 opponent name badges and HP% boxes.
    std::array<ImageFloatBox, 2> m_opponent_name_boxes;
    std::array<ImageFloatBox, 2> m_opponent_hp_boxes;

    //  Up to 2 own Pokemon HP boxes — split into separate current/max
    //  digit regions per slot. The slash glyph between them is OCR-hostile
    //  (often misread as 7/1/I), so reading each number independently and
    //  combining gives much cleaner output.
    std::array<ImageFloatBox, 2> m_own_hp_current_boxes;
    std::array<ImageFloatBox, 2> m_own_hp_max_boxes;

    //  PP boxes (singles only, 4 slots).
    std::array<ImageFloatBox, 4> m_pp_boxes;
};


}
}
}
#endif
