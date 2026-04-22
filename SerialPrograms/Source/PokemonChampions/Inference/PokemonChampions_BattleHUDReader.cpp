/*  Pokemon Champions Battle HUD Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Mode-aware HUD reader. Coordinates differ between Singles and Doubles:
 *
 *  SINGLES (measured from ref_frames/1/frame_00080.jpg):
 *    Opponent name:  (0.833, 0.042, 0.130, 0.032)   — 1 badge top-right
 *    Opponent HP%:   (0.964, 0.057, 0.034, 0.031)
 *    Own HP:         (0.133, 0.944, 0.078, 0.042)    — 1 bar bottom-left
 *    PP boxes:       right edge of 4 move pills
 *
 *  DOUBLES (measured from live capture frame_116):
 *    Opponent 1 name: (0.440, 0.050, 0.110, 0.030)   — left badge top-center
 *    Opponent 2 name: (0.580, 0.050, 0.110, 0.030)   — right badge
 *    Opponent 1 HP%:  (0.465, 0.082, 0.055, 0.028)
 *    Opponent 2 HP%:  (0.610, 0.082, 0.055, 0.028)
 *    Own 1 HP:        (0.040, 0.900, 0.105, 0.040)   — left bar bottom-left
 *    Own 2 HP:        (0.175, 0.900, 0.105, 0.040)   — right bar
 *
 *  NOTE: Doubles coordinates are estimated from the captured frames and
 *  may need fine-tuning with the pixel inspector.
 *
 */

#include <regex>
#include <vector>
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "CommonTools/OCR/OCR_Routines.h"
#include "PokemonChampions_BattleHUDReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


// ─── Species Name OCR ────────────────────────────────────────────

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


// ─── Helpers ─────────────────────────────────────────────────────

static std::string raw_ocr_line(const ImageViewRGB32& crop){
    //  Upscale small crops for better Tesseract accuracy.
    //  If the crop is under 200px wide, scale up to ~300px.
    if (crop.width() < 200 && crop.width() > 0){
        size_t scale = 300 / crop.width() + 1;
        ImageRGB32 scaled = crop.scale_to(crop.width() * scale, crop.height() * scale);
        return OCR::ocr_read(Language::English, scaled, OCR::PageSegMode::SINGLE_LINE);
    }
    return OCR::ocr_read(Language::English, crop, OCR::PageSegMode::SINGLE_LINE);
}

//  Extract all digit sequences from OCR text.
//  "1757175" -> {175, 7175} if we split on non-digit
//  "175/175" -> {175, 175}
//  "100%"    -> {100}
static std::vector<int> extract_numbers(const std::string& text){
    std::vector<int> nums;
    std::string current;
    for (char c : text){
        if (c >= '0' && c <= '9'){
            current += c;
        }else{
            if (!current.empty()){
                try{ nums.push_back(std::stoi(current)); } catch(...){}
                current.clear();
            }
        }
    }
    if (!current.empty()){
        try{ nums.push_back(std::stoi(current)); } catch(...){}
    }
    return nums;
}

static std::pair<int, int> parse_fraction(const std::string& text){
    //  Try the clean regex first: "175/175" or "175 / 175"
    std::regex re(R"((\d+)\s*/\s*(\d+))");
    std::smatch m;
    if (std::regex_search(text, m, re)){
        return {std::stoi(m[1].str()), std::stoi(m[2].str())};
    }

    //  Fallback: extract all numbers. If we get exactly 2, assume current/max.
    //  Handles "1757175" (where Tesseract dropped the slash).
    auto nums = extract_numbers(text);
    if (nums.size() == 2){
        return {nums[0], nums[1]};
    }
    //  If we get 1 number, return it as current with unknown max.
    if (nums.size() == 1){
        return {nums[0], -1};
    }
    return {-1, -1};
}

static int parse_percentage(const std::string& text){
    //  Extract all digit sequences and take the first one that's 0-100.
    auto nums = extract_numbers(text);
    for (int n : nums){
        if (n >= 0 && n <= 100) return n;
    }
    return -1;
}


// ─── Box initialization ─────────────────────────────────────────

void BattleHUDReader::init_singles_boxes(){
    //  Singles: 1 opponent top-right, 1 own bottom-left.
    //  Measured from ref_frames/1/frame_00080.jpg

    m_opponent_name_boxes[0] = ImageFloatBox(0.833, 0.042, 0.130, 0.032);
    m_opponent_hp_boxes[0]   = ImageFloatBox(0.964, 0.057, 0.034, 0.031);
    m_opponent_name_boxes[1] = ImageFloatBox(0, 0, 0, 0);  // unused
    m_opponent_hp_boxes[1]   = ImageFloatBox(0, 0, 0, 0);

    m_own_hp_boxes[0] = ImageFloatBox(0.133, 0.944, 0.078, 0.042);
    m_own_hp_boxes[1] = ImageFloatBox(0, 0, 0, 0);  // unused

    //  PP boxes — right edge of each move pill.
    const double PP_X      = 0.927;
    const double PP_WIDTH  = 0.057;
    const double PP_HEIGHT = 0.051;
    const double PP_Y[4] = { 0.500, 0.620, 0.741, 0.861 };
    for (size_t i = 0; i < 4; i++){
        m_pp_boxes[i] = ImageFloatBox(PP_X, PP_Y[i], PP_WIDTH, PP_HEIGHT);
    }
}

void BattleHUDReader::init_doubles_boxes(){
    //  Doubles: 2 opponents top-center/right, 2 own bottom-left.
    //  Measured from live capture frame_00116 (1920x1080).
    //
    //  Opponent badges: pink pills in the top area.
    //    Opp 1 "Hawlucha":  name ~x=850-1020, y=52-80   (after sprite)
    //    Opp 2 "Hydreigon": name ~x=1120-1310, y=52-80
    //    Opp 1 HP%:         x=900-980,  y=82-110
    //    Opp 2 HP%:         x=1170-1250, y=82-110
    //
    //  Own bars: blue gradient bars at bottom-left.
    //    Own 1 "Kingambit":  HP x=75-230,  y=968-1008
    //    Own 2 "Glimmora":   HP x=320-480, y=968-1008
    //
    //  NOTE: These are estimated — update with pixel inspector for precision.

    //  Measured with pixel_inspector on live capture frame_00116.
    m_opponent_name_boxes[0] = ImageFloatBox(0.6172, 0.0454, 0.1219, 0.0417);
    m_opponent_name_boxes[1] = ImageFloatBox(0.8286, 0.0481, 0.1151, 0.0417);
    m_opponent_hp_boxes[0]   = ImageFloatBox(0.6917, 0.1139, 0.0573, 0.0454);
    m_opponent_hp_boxes[1]   = ImageFloatBox(0.8984, 0.1130, 0.0563, 0.0426);

    m_own_hp_boxes[0] = ImageFloatBox(0.1313, 0.9324, 0.0766, 0.0407);
    m_own_hp_boxes[1] = ImageFloatBox(0.3365, 0.9315, 0.0786, 0.0463);

    //  No PP boxes on the doubles action menu screen.
    //  (Moves are shown after pressing FIGHT, in a different layout.)
    for (size_t i = 0; i < 4; i++){
        m_pp_boxes[i] = ImageFloatBox(0, 0, 0, 0);
    }
}


// ─── BattleHUDReader ─────────────────────────────────────────────

BattleHUDReader::BattleHUDReader(Language language, BattleMode mode)
    : m_language(language)
    , m_mode(mode)
{
    if (mode == BattleMode::DOUBLES){
        init_doubles_boxes();
    }else{
        init_singles_boxes();
    }
}

void BattleHUDReader::set_mode(BattleMode mode){
    if (mode == m_mode) return;
    m_mode = mode;
    if (mode == BattleMode::DOUBLES){
        init_doubles_boxes();
    }else{
        init_singles_boxes();
    }
}

void BattleHUDReader::make_overlays(VideoOverlaySet& items) const{
    uint8_t slots = (m_mode == BattleMode::DOUBLES) ? 2 : 1;
    for (uint8_t i = 0; i < slots; i++){
        if (m_opponent_name_boxes[i].width > 0){
            items.add(COLOR_MAGENTA, m_opponent_name_boxes[i]);
        }
        if (m_opponent_hp_boxes[i].width > 0){
            items.add(COLOR_MAGENTA, m_opponent_hp_boxes[i]);
        }
        if (m_own_hp_boxes[i].width > 0){
            items.add(COLOR_BLUE, m_own_hp_boxes[i]);
        }
    }
    if (m_mode != BattleMode::DOUBLES){
        for (const ImageFloatBox& box : m_pp_boxes){
            if (box.width > 0){
                items.add(COLOR_YELLOW, box);
            }
        }
    }
}


std::string BattleHUDReader::read_opponent_species(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 2 || m_opponent_name_boxes[slot].width == 0) return "";
    ImageViewRGB32 cropped = extract_box_reference(screen, m_opponent_name_boxes[slot]);
    OCR::StringMatchResult result = SpeciesNameOCR::instance().read_substring(
        logger, m_language, cropped, OCR::WHITE_TEXT_FILTERS()
    );
    if (result.results.empty()) return "";
    return result.results.begin()->second.token;
}

int BattleHUDReader::read_opponent_hp_pct(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 2 || m_opponent_hp_boxes[slot].width == 0) return -1;
    ImageViewRGB32 cropped = extract_box_reference(screen, m_opponent_hp_boxes[slot]);
    std::string text = raw_ocr_line(cropped);
    int pct = parse_percentage(text);
    if (pct < 0 || pct > 100){
        logger.log("BattleHUDReader: failed to parse opponent HP% slot " +
                   std::to_string(slot) + " from '" + text + "'", COLOR_RED);
        return -1;
    }
    return pct;
}

std::pair<int, int> BattleHUDReader::read_own_hp(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 2 || m_own_hp_boxes[slot].width == 0) return {-1, -1};
    ImageViewRGB32 cropped = extract_box_reference(screen, m_own_hp_boxes[slot]);
    std::string text = raw_ocr_line(cropped);
    auto hp = parse_fraction(text);
    if (hp.first < 0){
        logger.log("BattleHUDReader: failed to parse own HP slot " +
                   std::to_string(slot) + " from '" + text + "'", COLOR_RED);
    }
    return hp;
}

std::pair<int, int> BattleHUDReader::read_move_pp(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 4 || m_pp_boxes[slot].width == 0) return {-1, -1};
    ImageViewRGB32 cropped = extract_box_reference(screen, m_pp_boxes[slot]);
    std::string text = raw_ocr_line(cropped);
    auto pp = parse_fraction(text);
    if (pp.first < 0){
        logger.log("BattleHUDReader: failed to parse PP slot " +
                   std::to_string(slot) + " from '" + text + "'", COLOR_RED);
    }
    return pp;
}

BattleHUDState BattleHUDReader::read_all(
    Logger& logger, const ImageViewRGB32& screen
) const{
    BattleHUDState state;
    state.mode = m_mode;

    uint8_t slots = state.slot_count();

    for (uint8_t i = 0; i < slots; i++){
        state.opponents[i].species = read_opponent_species(logger, screen, i);
        state.opponents[i].hp_pct  = read_opponent_hp_pct(logger, screen, i);

        auto own_hp = read_own_hp(logger, screen, i);
        state.own[i].hp_current = own_hp.first;
        state.own[i].hp_max     = own_hp.second;
    }

    //  PP only in singles.
    if (m_mode != BattleMode::DOUBLES){
        for (uint8_t i = 0; i < 4; i++){
            auto pp = read_move_pp(logger, screen, i);
            state.move_pp[i].current = pp.first;
            state.move_pp[i].max     = pp.second;
        }
    }

    return state;
}


}
}
}
