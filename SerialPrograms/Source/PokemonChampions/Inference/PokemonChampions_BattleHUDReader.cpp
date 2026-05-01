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

#include <array>
#include <memory>
#include <regex>
#include <vector>
#include "CommonFramework/Globals.h"
#include "CommonFramework/ImageTypes/ImageRGB32.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/ImageMatch/ExactImageMatcher.h"
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

//  OCR a crop region with upscaling for small text.
static std::string raw_ocr_line(const ImageViewRGB32& crop){
    if (crop.width() > 0 && crop.width() < 400){
        size_t scale = 400 / crop.width() + 1;
        ImageRGB32 scaled = crop.scale_to(crop.width() * scale, crop.height() * scale);
        return OCR::ocr_read(Language::English, scaled, OCR::PageSegMode::SINGLE_LINE);
    }
    return OCR::ocr_read(Language::English, crop, OCR::PageSegMode::SINGLE_LINE);
}

//  OCR a crop region after converting to high-contrast black-on-white.
//  For HP numbers: the text is bright (white/green/yellow) on dark bg.
//  Threshold the brightness channel, invert, then upscale for Tesseract.
//  Public — also used by --ocr-crop debug mode to exercise an arbitrary box.
std::string raw_ocr_numbers(const ImageViewRGB32& crop){
    if (crop.width() == 0 || crop.height() == 0) return "";

    //  Create a high-contrast version: any pixel with max(R,G,B) > threshold
    //  becomes white text on black bg, then invert to black text on white bg.
    size_t w = crop.width();
    size_t h = crop.height();
    size_t scale = 3;
    ImageRGB32 bw(w * scale, h * scale);

    for (size_t y = 0; y < h; y++){
        for (size_t x = 0; x < w; x++){
            uint32_t pixel = crop.pixel(x, y);
            uint8_t r = (pixel >> 0) & 0xFF;
            uint8_t g = (pixel >> 8) & 0xFF;
            uint8_t b = (pixel >> 16) & 0xFF;

            //  White-only filter: HP% text is white, so all channels must be
            //  bright AND close to each other (low saturation).
            //  This rejects colored glows (yellow/green HP bar) that the old
            //  max-brightness filter would pick up as noise.
            uint8_t mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
            uint8_t mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
            bool is_white = (mn > 180) && (mx - mn < 50);
            uint32_t out = is_white ? 0xFF000000 : 0xFFFFFFFF;

            //  Fill the scaled pixel block.
            for (size_t sy = 0; sy < scale; sy++){
                for (size_t sx = 0; sx < scale; sx++){
                    bw.pixel(x * scale + sx, y * scale + sy) = out;
                }
            }
        }
    }

    return OCR::ocr_read(Language::English, bw, OCR::PageSegMode::SINGLE_LINE);
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

//  Strip everything except digits and '/' from OCR text.
//  Handles cases where Tesseract reads "WK ¥iri" instead of "118/125"
//  by extracting only the numeric characters: "118125" or "118/125".
static std::string digits_only(const std::string& text){
    std::string out;
    for (char c : text){
        if ((c >= '0' && c <= '9') || c == '/'){
            out += c;
        }
    }
    return out;
}

std::pair<int, int> parse_fraction(const std::string& text){
    //  First strip to digits + slash only.
    std::string clean = digits_only(text);

    //  Try the clean regex: "175/175"
    std::regex re(R"((\d+)/(\d+))");
    std::smatch m;
    if (std::regex_search(clean, m, re)){
        return {std::stoi(m[1].str()), std::stoi(m[2].str())};
    }

    //  Fallback: extract all digit runs.
    auto nums = extract_numbers(clean);
    if (nums.size() == 2){
        return {nums[0], nums[1]};
    }
    if (nums.size() == 1){
        return {nums[0], -1};
    }

    //  Last resort: try on the original text (might have digit-like chars).
    nums = extract_numbers(text);
    if (nums.size() >= 2){
        return {nums[0], nums[1]};
    }
    if (nums.size() == 1){
        return {nums[0], -1};
    }
    return {-1, -1};
}

static int parse_percentage(const std::string& text){
    std::string clean = digits_only(text);

    //  In percentage context, '/' is never a fraction separator —
    //  it's always a misread '7' (similar glyph shape).
    for (char& c : clean){
        if (c == '/') c = '7';
    }

    auto nums = extract_numbers(clean);
    for (int n : nums){
        if (n >= 0 && n <= 100) return n;
        //  Common OCR misreads of "100":
        //  "700" — Tesseract reads '1' as '7' with surrounding noise
        if (n == 700) return 100;
        //  Trailing noise: "217" is "21" + junk, "2171" is "21" + more junk.
        //  Progressively strip trailing digits.
        for (int t = n / 10; t > 0; t /= 10){
            if (t >= 0 && t <= 100) return t;
        }
    }
    //  Fallback to original text.
    nums = extract_numbers(text);
    for (int n : nums){
        if (n >= 0 && n <= 100) return n;
        if (n == 700) return 100;
        for (int t = n / 10; t > 0; t /= 10){
            if (t >= 0 && t <= 100) return t;
        }
    }
    return -1;
}


// ─── Digit Template Matching ────────────────────────────────────
//
//  Replaces Tesseract OCR for opponent HP% reading.
//  Pipeline: crop → 3x upscale → binarize → segment → template match.

//  Binarize a crop to black text on white background.
//  Same logic as raw_ocr_numbers() but returns the image instead of OCR text.
static ImageRGB32 binarize_crop(const ImageViewRGB32& crop){
    size_t w = crop.width();
    size_t h = crop.height();
    size_t scale = 3;
    ImageRGB32 bw(w * scale, h * scale);

    for (size_t y = 0; y < h; y++){
        for (size_t x = 0; x < w; x++){
            uint32_t pixel = crop.pixel(x, y);
            uint8_t r = (pixel >> 0) & 0xFF;
            uint8_t g = (pixel >> 8) & 0xFF;
            uint8_t b = (pixel >> 16) & 0xFF;

            uint8_t mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
            uint8_t mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
            bool is_white = (mn > 180) && (mx - mn < 50);
            //  Text pixels → black (0xFF000000), background → white (0xFFFFFFFF)
            uint32_t out = is_white ? 0xFF000000 : 0xFFFFFFFF;

            for (size_t sy = 0; sy < scale; sy++){
                for (size_t sx = 0; sx < scale; sx++){
                    bw.pixel(x * scale + sx, y * scale + sy) = out;
                }
            }
        }
    }
    return bw;
}

//  Check if a pixel is foreground (black text = 0xFF000000).
static bool is_fg(uint32_t pixel){
    return (pixel & 0x00FFFFFF) == 0;
}

//  Segment a binarized image into individual digit crops via column projection.
//  Uses valley detection: finds the deepest valleys in column sums to split digits.
//  Returns sub-images left-to-right.
static std::vector<ImageRGB32> segment_digits(const ImageRGB32& bw){
    size_t w = bw.width();
    size_t h = bw.height();

    //  Column projection: count foreground pixels per column.
    std::vector<size_t> col_sums(w, 0);
    for (size_t x = 0; x < w; x++){
        for (size_t y = 0; y < h; y++){
            if (is_fg(bw.pixel(x, y))) col_sums[x]++;
        }
    }

    //  Find content bounds (first/last nonzero column).
    size_t first_col = w, last_col = 0;
    for (size_t x = 0; x < w; x++){
        if (col_sums[x] > 0){
            if (first_col == w) first_col = x;
            last_col = x;
        }
    }
    if (first_col >= last_col) return {};

    size_t content_w = last_col - first_col + 1;

    //  Find vertical content bounds.
    size_t first_row = h, last_row = 0;
    for (size_t y = 0; y < h; y++){
        for (size_t x = first_col; x <= last_col; x++){
            if (is_fg(bw.pixel(x, y))){
                if (first_row == h) first_row = y;
                last_row = y;
                break;
            }
        }
    }
    if (first_row >= last_row) return {};

    size_t content_h = last_row - first_row + 1;

    //  Estimate digit count from aspect ratio.
    //  Each digit is roughly 0.8-1.0x as wide as it is tall.
    //  Content width / height gives approximate digit count.
    double aspect = (double)content_w / (double)content_h;
    int n_digits;
    if (aspect < 0.5){
        return {};  //  Too narrow to be a digit.
    }else if (aspect < 1.2){
        n_digits = 1;
    }else if (aspect < 2.2){
        n_digits = 2;
    }else{
        n_digits = 3;
    }

    //  For single digit, just crop to content bounds.
    if (n_digits == 1){
        ImageRGB32 digit(content_w, content_h);
        for (size_t y = 0; y < content_h; y++){
            for (size_t x = 0; x < content_w; x++){
                digit.pixel(x, y) = bw.pixel(first_col + x, first_row + y);
            }
        }
        std::vector<ImageRGB32> result;
        result.push_back(std::move(digit));
        return result;
    }

    //  For multiple digits, find valleys (local minima in column sums).
    //  Work within the content region only.
    std::vector<size_t> content_cols(content_w);
    for (size_t i = 0; i < content_w; i++){
        content_cols[i] = col_sums[first_col + i];
    }

    //  Find all local minima (use a window to avoid noise).
    size_t window = content_w / (n_digits * 2);
    if (window < 2) window = 2;

    //  For each potential split zone, find the column with minimum sum.
    std::vector<size_t> splits;
    for (int d = 1; d < n_digits; d++){
        //  Expected split position: d * content_w / n_digits
        size_t expected = d * content_w / n_digits;
        size_t search_lo = expected > window ? expected - window : 0;
        size_t search_hi = expected + window < content_w ? expected + window : content_w - 1;

        size_t best_col = expected;
        size_t best_val = SIZE_MAX;
        for (size_t x = search_lo; x <= search_hi; x++){
            if (content_cols[x] < best_val){
                best_val = content_cols[x];
                best_col = x;
            }
        }
        splits.push_back(best_col);
    }

    //  Build digit crops from split points.
    std::vector<size_t> boundaries = {0};
    for (size_t s : splits) boundaries.push_back(s);
    boundaries.push_back(content_w);

    std::vector<ImageRGB32> digits;
    for (size_t i = 0; i < boundaries.size() - 1; i++){
        size_t sx = boundaries[i];
        size_t ex = boundaries[i + 1];
        if (ex <= sx) continue;

        //  Trim to tight horizontal bounds within this strip.
        size_t trim_left = ex, trim_right = sx;
        for (size_t x = sx; x < ex; x++){
            if (content_cols[x] > 0){
                if (x < trim_left) trim_left = x;
                trim_right = x;
            }
        }
        if (trim_left > trim_right) continue;

        size_t dw = trim_right - trim_left + 1;
        ImageRGB32 digit(dw, content_h);
        for (size_t y = 0; y < content_h; y++){
            for (size_t x = 0; x < dw; x++){
                digit.pixel(x, y) = bw.pixel(first_col + trim_left + x, first_row + y);
            }
        }
        digits.push_back(std::move(digit));
    }

    return digits;
}

//  Lazy-loaded digit templates (0-9) using ExactImageMatcher.
struct HPDigitTemplates{
    std::array<std::unique_ptr<ImageMatch::ExactImageMatcher>, 10> matchers;
    bool any_loaded = false;

    HPDigitTemplates(){
        std::string dir = RESOURCE_PATH() + "PokemonChampions/DigitTemplates/";
        for (int d = 0; d < 10; d++){
            std::string path = dir + std::to_string(d) + ".png";
            try{
                ImageRGB32 img(path);
                if (img.width() > 0){
                    matchers[d] = std::make_unique<ImageMatch::ExactImageMatcher>(
                        std::move(img)
                    );
                    any_loaded = true;
                }
            }catch (...){
                //  Template missing — slot stays nullptr.
            }
        }
    }

    static const HPDigitTemplates& get(){
        static HPDigitTemplates instance;
        return instance;
    }
};

//  Compute pixel agreement between two binarized images.
//  Scales the input to match the template size, then counts matching pixels.
//  Returns fraction of matching pixels (0.0 to 1.0).
static double pixel_agreement(const ImageRGB32& input, const ImageRGB32& tmpl){
    //  Scale input to template dimensions.
    ImageRGB32 scaled = input.scale_to(tmpl.width(), tmpl.height());
    size_t w = tmpl.width();
    size_t h = tmpl.height();
    size_t match = 0;
    size_t total = w * h;

    for (size_t y = 0; y < h; y++){
        for (size_t x = 0; x < w; x++){
            bool input_fg = is_fg(scaled.pixel(x, y));
            bool tmpl_fg = is_fg(tmpl.pixel(x, y));
            if (input_fg == tmpl_fg) match++;
        }
    }

    return (double)match / (double)total;
}

//  Match a single digit segment against all templates.
//  Returns the digit (0-9) or -1 if no match.
static int match_digit(const ImageRGB32& segment, double min_agreement = 0.80){
    const HPDigitTemplates& templates = HPDigitTemplates::get();
    if (!templates.any_loaded) return -1;

    double best_score = 0.0;
    int best_digit = -1;

    for (int d = 0; d < 10; d++){
        if (!templates.matchers[d]) continue;
        double score = pixel_agreement(segment, templates.matchers[d]->image_template());
        if (score > best_score){
            best_score = score;
            best_digit = d;
        }
    }

    if (best_score < min_agreement) return -1;
    return best_digit;
}

//  Read HP% from a crop using template matching.
//  Returns 0-100 on success, -1 on failure.
static int read_hp_pct_template(
    Logger& logger, const ImageViewRGB32& crop, uint8_t slot
){
    if (crop.width() == 0 || crop.height() == 0) return -1;

    //  Step 1: Binarize.
    ImageRGB32 bw = binarize_crop(crop);

    //  Step 2: Segment into individual digits.
    std::vector<ImageRGB32> segments = segment_digits(bw);
    if (segments.empty()){
        logger.log(
            "BattleHUDReader: opponent HP% slot " + std::to_string(slot) +
            " template: no digits found", COLOR_RED
        );
        return -1;
    }
    if (segments.size() > 3){
        segments.resize(3);  //  Cap at 3 digits (max "100").
    }

    //  Step 3: Match each segment.
    std::string match_detail;
    std::string result_str;
    const HPDigitTemplates& templates = HPDigitTemplates::get();

    for (size_t i = 0; i < segments.size(); i++){
        //  Log all scores for debugging.
        std::string scores_str;
        double best_score = 0.0;
        int best_digit = -1;
        for (int d = 0; d < 10; d++){
            if (!templates.matchers[d]) continue;
            double score = pixel_agreement(segments[i], templates.matchers[d]->image_template());
            if (!scores_str.empty()) scores_str += " ";
            scores_str += std::to_string(d) + ":" +
                std::to_string(score).substr(0, 5);
            if (score > best_score){
                best_score = score;
                best_digit = d;
            }
        }
        logger.log(
            "BattleHUDReader: segment[" + std::to_string(i) +
            "] " + std::to_string(segments[i].width()) + "x" +
            std::to_string(segments[i].height()) +
            " scores: " + scores_str
        );

        if (best_score < 0.80 || best_digit < 0){
            logger.log(
                "BattleHUDReader: opponent HP% slot " + std::to_string(slot) +
                " template: segment " + std::to_string(i) + " no match (best=" +
                std::to_string(best_score).substr(0, 5) + ")", COLOR_RED
            );
            return -1;
        }
        result_str += std::to_string(best_digit);
        if (!match_detail.empty()) match_detail += ",";
        match_detail += std::to_string(best_digit);
    }

    //  Step 4: Parse and validate.
    int value = std::stoi(result_str);

    //  "00" must be "100": a fainted Pokemon (0%) shows no badge at all,
    //  so the only way to read two zeros is if the narrow "1" was merged
    //  into the first "0" during segmentation.
    if (result_str == "00"){
        value = 100;
        match_detail = "1,0,0 (00->100)";
    }

    if (value < 0 || value > 100){
        logger.log(
            "BattleHUDReader: opponent HP% slot " + std::to_string(slot) +
            " template: digits=[" + match_detail + "] -> " +
            std::to_string(value) + " (out of range)", COLOR_RED
        );
        return -1;
    }

    logger.log(
        "BattleHUDReader: opponent HP% slot " + std::to_string(slot) +
        " template: digits=[" + match_detail + "] -> " + std::to_string(value)
    );
    return value;
}


// ─── Box initialization ─────────────────────────────────────────

void BattleHUDReader::init_singles_boxes(){
    //  Singles: 1 opponent top-right, 1 own bottom-left.
    //  Measured from ref_frames/1/frame_00080.jpg

    //  Singles opponent badge + HP sit at the same screen position as
    //  doubles slot 1 (far right). Reuse those tuned coords.
    m_opponent_name_boxes[0] = ImageFloatBox(0.8286, 0.0481, 0.1151, 0.0417);
    m_opponent_hp_boxes[0]   = ImageFloatBox(0.9002, 0.1176, 0.0420, 0.0349);
    m_opponent_name_boxes[1] = ImageFloatBox(0, 0, 0, 0);  // unused
    m_opponent_hp_boxes[1]   = ImageFloatBox(0, 0, 0, 0);

    //  Singles own HP sits at the same position as doubles slot 0 —
    //  reuse those tuned coords (see init_doubles_boxes).
    m_own_hp_current_boxes[0] = ImageFloatBox(0.1304, 0.9338, 0.0448, 0.0362);
    m_own_hp_max_boxes[0]     = ImageFloatBox(0.1746, 0.9464, 0.0335, 0.0229);
    m_own_hp_current_boxes[1] = ImageFloatBox(0, 0, 0, 0);  // unused
    m_own_hp_max_boxes[1]     = ImageFloatBox(0, 0, 0, 0);

    //  Own species name sits in the bar above the HP digits.
    //  Tuned via inspector against move_select frames.
    m_own_name_boxes[0] = ImageFloatBox(0.0814, 0.8705, 0.0918, 0.0272);
    m_own_name_boxes[1] = ImageFloatBox(0, 0, 0, 0);  // unused

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

    //  Measured with pixel_inspector on multiple doubles frames.
    //  Opponent species badges: pink pills in the top area.
    m_opponent_name_boxes[0] = ImageFloatBox(0.6172, 0.0454, 0.1219, 0.0417);
    m_opponent_name_boxes[1] = ImageFloatBox(0.8286, 0.0481, 0.1151, 0.0417);

    //  HP% digits: white text below species badges.
    //  Tuned via inspector "Test OCR" against multiple doubles frames.
    //  Singles re-uses slot 1's coords (HP appears right-aligned in singles).
    m_opponent_hp_boxes[0]   = ImageFloatBox(0.6932, 0.1174, 0.0429, 0.0354);
    m_opponent_hp_boxes[1]   = ImageFloatBox(0.9002, 0.1176, 0.0420, 0.0349);

    //  Own HP bars: bottom-left, "current/max" split into independent
    //  digit regions. Tuned via inspector saves on doubles frames; max
    //  boxes intentionally include the slash glyph (parse takes the first
    //  integer found, so the slash is harmless noise).
    m_own_hp_current_boxes[0] = ImageFloatBox(0.1304, 0.9338, 0.0448, 0.0362);
    m_own_hp_max_boxes[0]     = ImageFloatBox(0.1746, 0.9464, 0.0335, 0.0229);
    m_own_hp_current_boxes[1] = ImageFloatBox(0.3363, 0.9342, 0.0450, 0.0361);
    m_own_hp_max_boxes[1]     = ImageFloatBox(0.3800, 0.9473, 0.0340, 0.0215);

    //  Own species name sits in the bar above the HP digits.
    //  Tuned via inspector against move_select doubles frames.
    m_own_name_boxes[0] = ImageFloatBox(0.0814, 0.8705, 0.0918, 0.0272);
    m_own_name_boxes[1] = ImageFloatBox(0.2901, 0.8705, 0.0835, 0.0267);

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
        if (m_own_hp_current_boxes[i].width > 0){
            items.add(COLOR_BLUE, m_own_hp_current_boxes[i]);
        }
        if (m_own_hp_max_boxes[i].width > 0){
            items.add(COLOR_BLUE, m_own_hp_max_boxes[i]);
        }
        if (m_own_name_boxes[i].width > 0){
            items.add(COLOR_CYAN, m_own_name_boxes[i]);
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

std::string BattleHUDReader::read_own_species(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 2 || m_own_name_boxes[slot].width == 0) return "";
    ImageViewRGB32 cropped = extract_box_reference(screen, m_own_name_boxes[slot]);
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
    int v = read_hp_pct_template(logger, cropped, slot);
    if (v >= 0) return v;

    //  Tesseract fallback for cases the template matcher rejects (typically
    //  "100" where the narrow "1" doesn't segment cleanly, or low-contrast
    //  digits that fall under the 0.80 agreement threshold). raw_ocr_numbers
    //  is the same path the inspector "Test OCR" uses.
    std::string text = raw_ocr_numbers(cropped);
    int parsed = parse_percentage(text);
    if (parsed >= 0){
        logger.log(
            "BattleHUDReader: opponent HP% slot " + std::to_string(slot) +
            " template failed, tesseract -> " + std::to_string(parsed) +
            " (raw='" + text + "')"
        );
    }
    return parsed;
}

std::pair<int, int> BattleHUDReader::read_own_hp(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 2) return {-1, -1};

    //  Each box reads one number; parse_fraction on a single number returns
    //  {N, -1}, so .first is the integer (or -1 on failure).
    auto read_one = [&](const ImageFloatBox& box) -> int {
        if (box.width == 0) return -1;
        ImageViewRGB32 cropped = extract_box_reference(screen, box);
        std::string text = raw_ocr_numbers(cropped);
        return parse_fraction(text).first;
    };

    int cur = read_one(m_own_hp_current_boxes[slot]);
    int max_ = read_one(m_own_hp_max_boxes[slot]);
    if (cur < 0 && max_ < 0) return {-1, -1};
    if (cur < 0 || max_ < 0){
        logger.log(
            "BattleHUDReader: partial own HP read slot " + std::to_string(slot) +
            " (current=" + std::to_string(cur) + ", max=" + std::to_string(max_) + ")",
            COLOR_RED
        );
    }
    return {cur, max_};
}

std::pair<int, int> BattleHUDReader::read_move_pp(
    Logger& logger, const ImageViewRGB32& screen, uint8_t slot
) const{
    if (slot >= 4 || m_pp_boxes[slot].width == 0) return {-1, -1};
    ImageViewRGB32 cropped = extract_box_reference(screen, m_pp_boxes[slot]);
    std::string text = raw_ocr_numbers(cropped);
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

        state.own[i].species    = read_own_species(logger, screen, i);
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
