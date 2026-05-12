/*  Pokemon Champions Target Select Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the doubles target-select screen. Surfaces:
 *    - own_moves[2]:        which move each own active mon has chosen
 *    - opp_targeted[2]:     whether each opponent slot is the chosen target
 *    - own_targeted[2]:     whether each own slot is the chosen target
 *    - opp_effectiveness[2] & own_effectiveness[2]: super-effective /
 *      not-very-effective / no-effect / neutral, OCR'd from the label
 *      strip above each candidate target
 *
 *  Targeted-ness is detected by sampling the colored selector strip beside
 *  each target: yellow/green = targeted; red/blue = not targeted. No OCR.
 *
 *  Coordinates were drawn by the user via the Inspector and saved to
 *  tools/box_definitions.json. own_1 move name + own_X effectiveness
 *  boxes were extrapolated from opp deltas.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TargetSelectReader_H
#define PokemonAutomation_PokemonChampions_TargetSelectReader_H

#include <array>
#include <string>
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"

namespace PokemonAutomation{
class ImageViewRGB32;
namespace NintendoSwitch{
namespace PokemonChampions{


struct TargetSelectReadout{
    std::array<std::string, 2> own_moves{};             //  move slugs
    std::array<bool, 2>        opp_targeted{};
    std::array<bool, 2>        own_targeted{};
    std::array<std::string, 2> opp_effectiveness{};     //  enum slugs (see below)
    std::array<std::string, 2> own_effectiveness{};
    //  Raw pre-classification reads (debug / gallery view).
    std::array<std::string, 2> own_moves_raw{};         //  pre-slug Tesseract output
    std::array<std::string, 2> opp_effectiveness_raw{}; //  pre-classify text
    std::array<std::string, 2> own_effectiveness_raw{};
};


//  Effectiveness enum strings used by the reader output:
//    "super-effective", "not-very-effective", "no-effect", "neutral"
//  "" = OCR returned no recognizable label (skip in tests).


class TargetSelectReader{
public:
    TargetSelectReader(Language language = Language::English);

    TargetSelectReadout read(Logger& logger, const ImageViewRGB32& screen) const;

private:
    Language m_language;
    std::array<ImageFloatBox, 2> m_opp_is_targeted;
    std::array<ImageFloatBox, 2> m_own_is_targeted;
    std::array<ImageFloatBox, 2> m_opp_effectiveness;
    std::array<ImageFloatBox, 2> m_own_effectiveness;
    std::array<ImageFloatBox, 2> m_own_move_name;
};


}}}
#endif
