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
    //  Doubles 4-row layout. Anchors + per-row delta derived from user-
    //  drawn slot-0, slot-2, slot-3 references on
    //  test_images/doubles_switch/20260423-150442604167.png.
    for (uint8_t i = 0; i < 6; i++){
        m_doubles.species[i] = ImageFloatBox(0.0610, 0.2291 + i*0.1185, 0.0893, 0.0395);
        m_doubles.hp_text[i] = ImageFloatBox(0.0629, 0.2646 + i*0.1185, 0.0745, 0.0425);
    }
    m_doubles.highlight[0] = ImageFloatBox(0.0284, 0.2402, 0.0036, 0.0638);
    m_doubles.highlight[1] = ImageFloatBox(0.0289, 0.3504, 0.0028, 0.0749);
    m_doubles.highlight[2] = ImageFloatBox(0.0289, 0.4693, 0.0025, 0.0682);
    m_doubles.highlight[3] = ImageFloatBox(0.0289, 0.5846, 0.0026, 0.0749);
    m_doubles.highlight[4] = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
    m_doubles.highlight[5] = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
    //  Split current / max HP boxes for doubles. User drew slots 0 and 2;
    //  slots 1 + 3 extrapolated using the slot-0 → slot-2 delta (0.1152).
    //  Drawn on test_images/doubles_switch/20260423-150442604167.png.
    m_doubles.hp_current[0] = ImageFloatBox(0.0640, 0.2699, 0.0453, 0.0355);
    m_doubles.hp_current[1] = ImageFloatBox(0.0640, 0.3851, 0.0444, 0.0375);
    m_doubles.hp_current[2] = ImageFloatBox(0.0639, 0.5003, 0.0434, 0.0394);
    m_doubles.hp_current[3] = ImageFloatBox(0.0640, 0.6155, 0.0444, 0.0375);
    m_doubles.hp_max[0]     = ImageFloatBox(0.1099, 0.2777, 0.0294, 0.0261);
    m_doubles.hp_max[1]     = ImageFloatBox(0.1092, 0.3937, 0.0310, 0.0265);
    m_doubles.hp_max[2]     = ImageFloatBox(0.1085, 0.5098, 0.0325, 0.0269);
    m_doubles.hp_max[3]     = ImageFloatBox(0.1092, 0.6258, 0.0310, 0.0265);
    for (uint8_t i = 4; i < 6; i++){
        m_doubles.hp_current[i] = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
        m_doubles.hp_max[i]     = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
    }
    m_doubles.active_slot_count = 4;

    //  Singles 3-row layout. Boxes drawn by user 2026-05-10 on
    //  test_images/singles_switch/20260509-154834669879.png. HP boxes
    //  span the full "X/Y" text (per user note); name boxes the species
    //  text. Cursor strips ("mon_X") are wider than doubles because the
    //  user drew them as the full pill-left swatch rather than just the
    //  hairline yellow edge — yellow_score still discriminates fine.
    m_singles.species[0]   = ImageFloatBox(0.0620, 0.2321, 0.0828, 0.0367);
    m_singles.species[1]   = ImageFloatBox(0.0621, 0.3492, 0.0848, 0.0314);
    m_singles.species[2]   = ImageFloatBox(0.0627, 0.4659, 0.0734, 0.0344);
    m_singles.hp_text[0]   = ImageFloatBox(0.0694, 0.2635, 0.0682, 0.0429);
    m_singles.hp_text[1]   = ImageFloatBox(0.0650, 0.3854, 0.0736, 0.0362);
    m_singles.hp_text[2]   = ImageFloatBox(0.0633, 0.5029, 0.0763, 0.0358);
    m_singles.highlight[0] = ImageFloatBox(0.0429, 0.2308, 0.0184, 0.0255);
    m_singles.highlight[1] = ImageFloatBox(0.0388, 0.3506, 0.0239, 0.0255);
    m_singles.highlight[2] = ImageFloatBox(0.0421, 0.4658, 0.0191, 0.0209);
    //  Split current / max HP boxes for singles. User drew slots 1 and 2;
    //  slot 0 extrapolated using the per-row delta from existing species
    //  anchors (0.117 in singles). Drawn on
    //  test_images/singles_switch/20260509-154834669879.png.
    m_singles.hp_current[0] = ImageFloatBox(0.0604, 0.2676, 0.0480, 0.0383);
    m_singles.hp_current[1] = ImageFloatBox(0.0604, 0.3846, 0.0480, 0.0383);
    m_singles.hp_current[2] = ImageFloatBox(0.0619, 0.5039, 0.0502, 0.0356);
    m_singles.hp_max[0]     = ImageFloatBox(0.1111, 0.2787, 0.0282, 0.0240);
    m_singles.hp_max[1]     = ImageFloatBox(0.1111, 0.3957, 0.0282, 0.0240);
    m_singles.hp_max[2]     = ImageFloatBox(0.1117, 0.5117, 0.0253, 0.0242);
    for (uint8_t i = 3; i < 6; i++){
        m_singles.species[i]    = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
        m_singles.hp_text[i]    = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
        m_singles.hp_current[i] = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
        m_singles.hp_max[i]     = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
        m_singles.highlight[i]  = ImageFloatBox(0.0, 0.0, 0.0, 0.0);
    }
    m_singles.active_slot_count = 3;

    for (uint8_t i = 0; i < 6; i++){
        m_opp_hp_pct[i] = ImageFloatBox(0.9131, 0.2622 + i*0.1170, 0.0356, 0.0345);
    }
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

    //  Pick a layout: score the cursor on both singles + doubles boxes,
    //  use whichever maxes out higher. The forced-switch UI shifts row
    //  positions when the user only brought 3 leads (singles) vs 4
    //  (doubles); a single fixed-y reader misses cursor reads on the
    //  off-mode screen and the suggester loops Down forever
    //  (livetrace bug 2026-05-10).
    auto score_layout = [&](const OwnLayout& L){
        double best = 0.0;
        int best_slot = -1;
        for (uint8_t i = 0; i < 6; i++){
            double s = yellow_score(extract_box_reference(screen, L.highlight[i]));
            if (s > best && s >= 30.0){
                best = s;
                best_slot = (int)i;
            }
        }
        return std::make_pair(best, best_slot);
    };
    auto [doubles_best, doubles_slot] = score_layout(m_doubles);
    auto [singles_best, singles_slot] = score_layout(m_singles);
    const OwnLayout& L = (singles_best > doubles_best) ? m_singles : m_doubles;
    out.selected_own_slot = (singles_best > doubles_best) ? singles_slot : doubles_slot;

    //  Own per-slot reads using the picked layout's species/HP boxes.
    for (uint8_t i = 0; i < 6; i++){
        //  Species — text OCR via dictionary match.
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, L.species[i]);
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
        //  HP — split-box read (preferred). OCR current + max separately;
        //  if both parse as digits, use them. If either is empty, fall back
        //  to the combined "X/Y" box and parse_fraction. The split boxes
        //  give cleaner crops than the combined slash-containing one,
        //  which Tesseract sometimes mis-segments.
        auto digits_only = [](const std::string& s){
            std::string out_s;
            for (char c : s){ if (c >= '0' && c <= '9') out_s += c; }
            return out_s;
        };
        std::string cur_raw, max_raw;
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, L.hp_current[i]);
            cur_raw = raw_ocr_numbers(cropped);
            out.own[i].hp_current_raw = cur_raw;
        }
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, L.hp_max[i]);
            max_raw = raw_ocr_numbers(cropped);
            out.own[i].hp_max_raw = max_raw;
        }
        std::string cur_digits = digits_only(cur_raw);
        std::string max_digits = digits_only(max_raw);
        bool split_ok = false;
        if (!cur_digits.empty() && !max_digits.empty()){
            try {
                int cur = std::stoi(cur_digits);
                int mx  = std::stoi(max_digits);
                if (cur >= 0 && mx > 0 && cur <= mx){
                    out.own[i].hp_current = cur;
                    out.own[i].hp_max = mx;
                    split_ok = true;
                }
            } catch (...) {}
        }
        if (!split_ok){
            //  Combined "X/Y" fallback.
            ImageViewRGB32 cropped = extract_box_reference(screen, L.hp_text[i]);
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
