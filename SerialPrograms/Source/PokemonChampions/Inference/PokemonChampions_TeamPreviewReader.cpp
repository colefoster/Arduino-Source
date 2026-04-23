/*  Pokemon Champions Team Preview Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Coordinates measured via tools/pixel_inspector.py --measure from
 *  screenshots/team_preview_3804.png (1920x1080).
 *
 *  Own side (left): species + item text in rows 0..5. Row 0 at y=0.1574
 *  and row 5 at y=0.7398; rows 1..4 interpolated.
 *
 *  Opp side (right): 6 sprite cells in rows 0..5. Row 0 at y=0.1509,
 *  row 5 at y=0.7407.
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "CommonTools/ImageMatch/ImageMatchResult.h"
#include "PokemonChampions_TeamPreviewReader.h"
#include "PokemonChampions_BattleHUDReader.h"      //  SpeciesNameOCR
#include "PokemonChampions_ItemNameReader.h"        //  ItemNameOCR
#include "PokemonChampions_SpriteMatcher.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Own species/item text on the Team Preview screen has TWO states:
//    1. Highlighted slot (yellow-green pill): dark-navy text, RGB ~(5, 55, 115).
//    2. Unhighlighted slots (light-purple pill): medium-purple text,
//       RGB ~(110, 100, 185) on a light-purple background (R~131, G~114, B~255).
//
//  Filter 1 (tight navy): catches highlighted-slot text.
//  Filter 2 (purple-on-light): catches unhighlighted text without
//       including the near-white background. B ceiling raised to ~210
//       but RG kept low to reject the pale-lavender background itself.
static const std::vector<OCR::TextColorRange>& own_text_filters(){
    static const std::vector<OCR::TextColorRange> filters{
        {0xff000000, 0xff6080a0},   // tight navy (highlighted)
        {0xff000000, 0xff8c7dd2},   // purple text on light-purple bg
        {0xff000000, 0xffa091e0},   // looser purple (anti-aliased edges)
    };
    return filters;
}


TeamPreviewReader::TeamPreviewReader(Language language)
    : m_language(language)
{
    //  --- Own species text boxes ---
    //  Measured anchors (re-measured 2026-04-22 with tighter crops):
    //    slot 0: (0.0760, 0.1565, 0.0969, 0.0389)   -- Glimmora (longer word)
    //    slot 2: (0.0729, 0.3898, 0.0844, 0.0352)   -- Rotom (shorter; midpoint
    //                                                  validates linear y-spacing)
    //    slot 5: (0.0724, 0.7389, 0.0922, 0.0361)   -- Kingambit
    //  Row spacing is linear at ~0.1165 per slot.
    //  Use min-X and max-W/H so every word fits within the box regardless
    //  of length; extra pill background is filtered out by OCR.
    const double OWN_SP_X = 0.0724;
    const double OWN_SP_W = 0.0969;
    const double OWN_SP_H = 0.0389;
    const double OWN_SP_Y0 = 0.1565;
    const double OWN_SP_Y5 = 0.7389;
    const double OWN_SP_STEP = (OWN_SP_Y5 - OWN_SP_Y0) / 5.0;

    //  --- Own item text boxes ---
    //  Re-measured anchors:
    //    slot 0: (0.0964, 0.1981, 0.0786, 0.0333)   -- Focus Sash
    //    slot 2: (0.0974, 0.4343, 0.0802, 0.0296)   -- Choice Scarf
    //    slot 5: (0.0995, 0.7852, 0.0823, 0.0306)   -- Bright Powder (longer)
    const double OWN_IT_X = 0.0964;
    const double OWN_IT_W = 0.0823;
    const double OWN_IT_H = 0.0333;
    const double OWN_IT_Y0 = 0.1981;
    const double OWN_IT_Y5 = 0.7852;
    const double OWN_IT_STEP = (OWN_IT_Y5 - OWN_IT_Y0) / 5.0;

    //  --- Opp sprite boxes ---
    //  opp_sprite_0 at (0.8380, 0.1509, 0.0578, 0.0917)
    //  opp_sprite_5 at (0.8411, 0.7407, 0.0583, 0.0880)
    const double OPP_X = 0.8380;
    const double OPP_W = 0.0583;
    const double OPP_H = 0.0917;
    const double OPP_Y0 = 0.1509;
    const double OPP_Y5 = 0.7407;
    const double OPP_STEP = (OPP_Y5 - OPP_Y0) / 5.0;

    for (uint8_t i = 0; i < 6; i++){
        m_own_species_boxes[i] = ImageFloatBox(
            OWN_SP_X, OWN_SP_Y0 + i * OWN_SP_STEP, OWN_SP_W, OWN_SP_H);
        m_own_item_boxes[i] = ImageFloatBox(
            OWN_IT_X, OWN_IT_Y0 + i * OWN_IT_STEP, OWN_IT_W, OWN_IT_H);
        m_opp_sprite_boxes[i] = ImageFloatBox(
            OPP_X, OPP_Y0 + i * OPP_STEP, OPP_W, OPP_H);
    }
}


void TeamPreviewReader::make_overlays(VideoOverlaySet& items) const{
    for (uint8_t i = 0; i < 6; i++){
        items.add(COLOR_GREEN, m_own_species_boxes[i]);
        items.add(COLOR_YELLOW, m_own_item_boxes[i]);
        items.add(COLOR_MAGENTA, m_opp_sprite_boxes[i]);
    }
}


TeamPreviewResult TeamPreviewReader::read(
    Logger& logger,
    const ImageViewRGB32& screen,
    double opp_match_threshold
) const{
    TeamPreviewResult result;

    //  --- OWN SIDE: OCR species + item ---
    for (uint8_t i = 0; i < 6; i++){
        //  Species
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, m_own_species_boxes[i]);
            OCR::StringMatchResult r = SpeciesNameOCR::instance().read_substring(
                logger, m_language, cropped, own_text_filters()
            );
            if (!r.results.empty()){
                result.own[i].species = r.results.begin()->second.token;
            }
        }
        //  Item
        {
            ImageViewRGB32 cropped = extract_box_reference(screen, m_own_item_boxes[i]);
            OCR::StringMatchResult r = ItemNameOCR::instance().read_substring(
                logger, m_language, cropped, own_text_filters()
            );
            if (!r.results.empty()){
                result.own[i].item = r.results.begin()->second.token;
            }
        }
        logger.log(
            "TeamPreview: own slot " + std::to_string(i) +
            " species=\"" + result.own[i].species +
            "\" item=\"" + result.own[i].item + "\""
        );
    }

    //  --- OPP SIDE: sprite match ---
    const PokemonSpriteMatcher& matcher = PokemonSpriteMatcher::instance();
    for (uint8_t i = 0; i < 6; i++){
        //  CroppedImageDictionaryMatcher::match takes (ImageViewRGB32, alpha_spread).
        //  We pre-extract the sprite region; matcher auto-crops the pill away.
        ImageViewRGB32 sprite_crop = extract_box_reference(screen, m_opp_sprite_boxes[i]);
        ImageMatch::ImageMatchResult match = matcher.match(sprite_crop, /* alpha_spread */ 0.05);
        if (match.results.empty()){
            logger.log("TeamPreview: opp slot " + std::to_string(i) + " sprite match: no result", COLOR_RED);
            continue;
        }
        double best_alpha = match.results.begin()->first;
        const std::string& best_slug = match.results.begin()->second;
        if (best_alpha > opp_match_threshold){
            logger.log(
                "TeamPreview: opp slot " + std::to_string(i) +
                " sprite match rejected (alpha " + std::to_string(best_alpha) +
                " > threshold " + std::to_string(opp_match_threshold) +
                ", would have been \"" + best_slug + "\")",
                COLOR_YELLOW
            );
            continue;
        }
        result.opp_species[i] = best_slug;
        logger.log(
            "TeamPreview: opp slot " + std::to_string(i) +
            " = \"" + best_slug + "\"  (alpha=" + std::to_string(best_alpha) + ")",
            COLOR_GREEN
        );
    }

    return result;
}


}
}
}
