/*  Pokemon Champions Team Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the team select screen by checking:
 *    1. "Ranked Battles" blue header (same as BattleModeDetector)
 *    2. Dark left panel color (team slot area)
 *    3. "Done" text in the bottom-right counter
 *
 *  Pixel measurements (1920x1080) — placeholder, tune with pixel_inspector:
 *    Ranked header: same as BattleModeDetector (x=1083, y=146, w=246, h=46)
 *    Left panel: x~40, y~200, w~450, h~100 (dark region)
 *    Done counter: x~1650, y~980, w~200, h~50
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "PokemonChampions_TeamSelectDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  "Ranked Battles" header: blue-purple panel color (same as BattleModeDetector).
static const FloatPixel RANKED_HEADER_BLUE{0.26, 0.24, 0.50};

//  The dark left panel where team Pokemon are displayed.
//  Expected to be a very dark blue/gray.
static const FloatPixel LEFT_PANEL_DARK{0.20, 0.20, 0.30};


TeamSelectDetector::TeamSelectDetector()
    //  "Ranked Battles" header — reuses the same region as BattleModeDetector.
    //  Measured from live capture: x=1083, y=146, w=246, h=46 (1920x1080)
    : m_ranked_header(0.5641, 0.1352, 0.1281, 0.0426)
    //  Dark left panel — area where team slots are listed.
    //  Placeholder: x=40, y=250, w=440, h=80 (1920x1080)
    , m_left_panel(0.0208, 0.2315, 0.2292, 0.0741)
    //  "Done" counter — bottom-right area.
    //  Placeholder: x=1650, y=980, w=200, h=50 (1920x1080)
    , m_done_counter(0.8594, 0.9074, 0.1042, 0.0463)
{}


void TeamSelectDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_ranked_header);
    items.add(COLOR_MAGENTA, m_left_panel);
    items.add(COLOR_YELLOW, m_done_counter);
}


bool TeamSelectDetector::detect(const ImageViewRGB32& screen){
    //  Gate 1: "Ranked Battles" header must be visible.
    const ImageStats header_stats = image_stats(extract_box_reference(screen, m_ranked_header));
    if (!is_solid(header_stats, RANKED_HEADER_BLUE, 0.18, 150)){
        return false;
    }

    //  Gate 2: Left panel should be dark (team slot area).
    const ImageStats panel_stats = image_stats(extract_box_reference(screen, m_left_panel));
    if (panel_stats.average.sum() > 200){
        //  Too bright — probably not the team select screen.
        return false;
    }

    //  Gate 3: OCR the "Done" counter region for the word "done".
    ImageViewRGB32 cropped = extract_box_reference(screen, m_done_counter);
    std::string text = OCR::ocr_read(Language::English, cropped, OCR::PageSegMode::SINGLE_LINE);

    std::string lower;
    for (char c : text){
        if (c != '\n' && c != '\r'){
            lower += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
    }

    //  Look for "done" or partial OCR like "don".
    if (lower.find("done") != std::string::npos || lower.find("don") != std::string::npos){
        return true;
    }

    //  Also accept digit/digit pattern (e.g. "0/4", "2/3").
    for (size_t i = 0; i + 2 < lower.size(); i++){
        if (std::isdigit(static_cast<unsigned char>(lower[i])) &&
            lower[i + 1] == '/' &&
            std::isdigit(static_cast<unsigned char>(lower[i + 2]))){
            return true;
        }
    }

    return false;
}


}
}
}
