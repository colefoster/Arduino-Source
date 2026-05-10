/*  Pokemon Champions Pokemon Switch Reader
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include <cstdint>
#include <string>
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "PokemonChampions/Programs/PokemonChampions_BattleStateTracker.h"
#include "PokemonChampions_BattleHUDReader.h"   //  SpeciesNameOCR + raw_ocr_numbers + parse_fraction
#include "PokemonChampions_PokemonSwitchReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


PokemonSwitchReader::PokemonSwitchReader(Language language)
    : m_language(language)
{
    //  Boxes mirror dashboard CROP_DEFS["PokemonSwitchReader"]. Anchors
    //  and per-row deltas derived from user-drawn slot-0, slot-2, and slot-3
    //  references on screenshot-20260423-150442604167.png.
    for (uint8_t i = 0; i < 6; i++){
        m_own_species[i]   = ImageFloatBox(0.0610, 0.2291 + i*0.1185, 0.0893, 0.0395);
        m_own_hp_text[i]   = ImageFloatBox(0.0629, 0.2646 + i*0.1185, 0.0745, 0.0425);
        m_opp_hp_pct[i]    = ImageFloatBox(0.9131, 0.2622 + i*0.1170, 0.0356, 0.0345);
    }
    //  Lead-only highlight strips (slots 0-3 — switch screen is reached
    //  during a battle where only the 4 chosen leads are pickable). Drawn
    //  by user. Slots 4-5 get zero-area boxes so yellow_score returns -1
    //  and they never win the cursor pick.
    m_own_highlight[0] = ImageFloatBox(0.0284, 0.2402, 0.0036, 0.0638);
    m_own_highlight[1] = ImageFloatBox(0.0289, 0.3504, 0.0028, 0.0749);
    m_own_highlight[2] = ImageFloatBox(0.0289, 0.4693, 0.0025, 0.0682);
    m_own_highlight[3] = ImageFloatBox(0.0289, 0.5846, 0.0026, 0.0749);
    m_own_highlight[4] = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
    m_own_highlight[5] = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
}


//  Cursor / highlight: the selected own slot has a saturated yellow strip
//  on its left edge. Score "yellowness" per box and pick the highest.
static double yellow_score(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return -1.0;
    ImageStats st = image_stats(crop);
    int r = (int)st.average.r;
    int g = (int)st.average.g;
    int b = (int)st.average.b;
    int score = (r + g) / 2 - b;
    return score > 0 ? double(score) : 0.0;
}


PokemonSwitchResult PokemonSwitchReader::read(
    Logger& logger, const ImageViewRGB32& screen,
    const TeamCandidates* hint
) const{
    PokemonSwitchResult out;

    //  Selected own slot via highlight.
    double best_score = 0.0;
    for (uint8_t i = 0; i < 6; i++){
        double s = yellow_score(extract_box_reference(screen, m_own_highlight[i]));
        if (s > best_score && s >= 30.0){
            best_score = s;
            out.selected_own_slot = (int)i;
        }
    }

    //  Own per-slot reads.
    for (uint8_t i = 0; i < 6; i++){
        //  Species — text OCR via dictionary match.
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, m_own_species[i]);
            OCR::StringMatchResult result = SpeciesNameOCR::instance().read_substring(
                logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
            );
            if (!result.results.empty()){
                std::string token = result.results.begin()->second.token;
                if (hint != nullptr){
                    std::string snapped = team_bias_snap(token, hint->own_species, 2);
                    if (snapped != token){
                        logger.log(
                            "PokemonSwitchReader: team-bias slot " + std::to_string(i)
                            + " '" + token + "' -> '" + snapped + "'",
                            COLOR_PURPLE
                        );
                        token = snapped;
                    }
                }
                out.own[i].species = token;
            }
        }
        //  HP "X/Y".
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, m_own_hp_text[i]);
            std::string raw = raw_ocr_numbers(cropped);
            if (raw.find('/') != std::string::npos){
                auto frac = parse_fraction(raw);
                out.own[i].hp_current = frac.first;
                out.own[i].hp_max = frac.second;
            }
        }
    }

    //  Opp per-slot HP%.
    for (uint8_t i = 0; i < 6; i++){
        ImageViewRGB32 cropped = extract_box_reference(screen, m_opp_hp_pct[i]);
        std::string raw = raw_ocr_numbers(cropped);
        std::string digits;
        for (char c : raw){ if (c >= '0' && c <= '9') digits += c; }
        if (!digits.empty()){
            try {
                int n = std::stoi(digits);
                if (n >= 0 && n <= 100) out.opp[i].hp_pct = n;
            } catch (...) {}
        }
    }

    return out;
}


}}}
