/*  Pokemon Champions Battle HUD Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Pixel measurements from ref_frames/1/frame_00080.jpg (1920x1080):
 *
 *  Opponent species badge (top-right):
 *    "Greninja" text:  x ~1716-1862, y ~30-56     (white on colored pill)
 *    HP "1%":          x ~1836-1880, y ~60-86      (white text)
 *
 *  Own Pokemon info (bottom-left):
 *    Nickname:         x ~110-230,  y ~944-966     (white text on blue bar)
 *    HP "41/187":      x ~82-196,   y ~984-1014    (green number / white number)
 *
 *  PP counts (right side of each move pill):
 *    Large number:     x ~1818-1870, y ~528-560    (slot 0, bold colored)
 *    Small "/12":      x ~1870-1900, y ~540-560    (slot 0, smaller gray)
 *    Spacing: same as move pills, ~130px vertical
 *
 */

#include <regex>
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_BattleHUDReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


// ─── Species Name OCR ────────────────────────────────────────────────

SpeciesNameOCR& SpeciesNameOCR::instance(){
    static SpeciesNameOCR reader;
    return reader;
}

SpeciesNameOCR::SpeciesNameOCR()
    : SmallDictionaryMatcher("PokemonChampions/PokemonSpeciesOCR.json")
{}

OCR::StringMatchResult SpeciesNameOCR::read_substring(
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


// ─── Helpers ─────────────────────────────────────────────────────────

//  OCR a cropped region and return raw text (single line).
static std::string raw_ocr_line(const ImageViewRGB32& crop){
    return OCR::ocr_read(Language::English, crop, OCR::PageSegMode::SINGLE_LINE);
}

//  Parse "41/187" or "41 / 187" → {41, 187}. Returns {-1,-1} on failure.
static std::pair<int, int> parse_fraction(const std::string& text){
    std::regex re(R"((\d+)\s*/\s*(\d+))");
    std::smatch m;
    if (std::regex_search(text, m, re)){
        return {std::stoi(m[1].str()), std::stoi(m[2].str())};
    }
    return {-1, -1};
}

//  Parse "45%" or "45 %" → 45. Returns -1 on failure.
static int parse_percentage(const std::string& text){
    std::regex re(R"((\d+)\s*%?)");
    std::smatch m;
    if (std::regex_search(text, m, re)){
        return std::stoi(m[1].str());
    }
    return -1;
}


// ─── BattleHUDReader ─────────────────────────────────────────────────

BattleHUDReader::BattleHUDReader(Language language)
    : m_language(language)
{
    //  Opponent species name: "Greninja" in top-right pink/red badge.
    //  x: 1600-1850 / 1920, y: 45-80 / 1080
    m_opponent_name_box = ImageFloatBox(0.833, 0.042, 0.130, 0.032);

    //  Opponent HP %: "1%" or "45%" below/right of the badge.
    //  x: 1850-1915 / 1920, y: 62-95 / 1080
    m_opponent_hp_box = ImageFloatBox(0.964, 0.057, 0.034, 0.031);

    //  Own HP "41/187" in bottom-left, below HP bar.
    //  x: 255-405 / 1920, y: 1020-1065 / 1080
    m_own_hp_box = ImageFloatBox(0.133, 0.944, 0.078, 0.042);

    //  PP counts — right end of each move pill.
    //  x: 1780-1890 / 1920, ~55px tall, same vertical spacing as moves.
    const double PP_X      = 0.927;
    const double PP_WIDTH  = 0.057;
    const double PP_HEIGHT = 0.051;
    const double Y_SLOTS[4] = {
        0.500,   //  slot 0: y = 540/1080
        0.620,   //  slot 1: y = 670/1080
        0.741,   //  slot 2: y = 800/1080
        0.861,   //  slot 3: y = 930/1080
    };
    for (size_t i = 0; i < 4; i++){
        m_pp_boxes[i] = ImageFloatBox(PP_X, Y_SLOTS[i], PP_WIDTH, PP_HEIGHT);
    }
}

void BattleHUDReader::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_MAGENTA, m_opponent_name_box);
    items.add(COLOR_MAGENTA, m_opponent_hp_box);
    items.add(COLOR_BLUE, m_own_hp_box);
    for (const ImageFloatBox& box : m_pp_boxes){
        items.add(COLOR_YELLOW, box);
    }
}


std::string BattleHUDReader::read_opponent_species(
    Logger& logger, const ImageViewRGB32& screen
) const{
    ImageViewRGB32 cropped = extract_box_reference(screen, m_opponent_name_box);
    OCR::StringMatchResult result = SpeciesNameOCR::instance().read_substring(
        logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
    );

    if (result.results.empty()){
        return "";
    }
    return result.results.begin()->second.token;
}

int BattleHUDReader::read_opponent_hp_pct(
    Logger& logger, const ImageViewRGB32& screen
) const{
    ImageViewRGB32 cropped = extract_box_reference(screen, m_opponent_hp_box);
    std::string text = raw_ocr_line(cropped);
    int pct = parse_percentage(text);
    if (pct < 0 || pct > 100){
        logger.log("BattleHUDReader: failed to parse opponent HP% from '" + text + "'", COLOR_RED);
        return -1;
    }
    return pct;
}

std::pair<int, int> BattleHUDReader::read_own_hp(
    Logger& logger, const ImageViewRGB32& screen
) const{
    ImageViewRGB32 cropped = extract_box_reference(screen, m_own_hp_box);
    std::string text = raw_ocr_line(cropped);
    auto hp = parse_fraction(text);
    if (hp.first < 0){
        logger.log("BattleHUDReader: failed to parse own HP from '" + text + "'", COLOR_RED);
    }
    return hp;
}

std::pair<int, int> BattleHUDReader::read_move_pp(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 4){
        return {-1, -1};
    }
    ImageViewRGB32 cropped = extract_box_reference(screen, m_pp_boxes[slot]);
    std::string text = raw_ocr_line(cropped);
    auto pp = parse_fraction(text);
    if (pp.first < 0){
        logger.log(
            "BattleHUDReader: failed to parse PP for slot " +
            std::to_string(slot) + " from '" + text + "'",
            COLOR_RED
        );
    }
    return pp;
}

BattleHUDState BattleHUDReader::read_all(
    Logger& logger, const ImageViewRGB32& screen
) const{
    BattleHUDState state;
    state.opponent_species = read_opponent_species(logger, screen);
    state.opponent_hp_pct  = read_opponent_hp_pct(logger, screen);

    auto own_hp = read_own_hp(logger, screen);
    state.own_hp_current = own_hp.first;
    state.own_hp_max     = own_hp.second;

    for (uint8_t i = 0; i < 4; i++){
        auto pp = read_move_pp(logger, screen, i);
        state.move_pp[i].current = pp.first;
        state.move_pp[i].max     = pp.second;
    }
    return state;
}


}
}
}
