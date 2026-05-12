/*  Pokemon Champions Battle Mode Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the format label from the top of the matchmaking or team select
 *  screen to determine Singles vs Doubles.
 *
 *  Matchmaking screen (frame_00400 / frame_00051):
 *    "Ranked Battles    Single Battle"  or  "Double Battle"
 *    The format text is in the header area near top-center.
 *
 *  Team select screen (frame_00010):
 *    "Ranked Battles    Single Battle"  at the very top of the screen.
 *
 *  Pixel measurements (1920x1080):
 *    Format label region:  x ~350-650, y ~10-40
 *    (This is a placeholder — will be updated with pixel_inspector measurements)
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonTools/Images/SolidColorTest.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "PokemonChampions_BattleModeDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  "Ranked Battles" header: blue-purple panel color.
//  Measured: avg RGB (128, 120, 250), ratio (0.26, 0.24, 0.50)
static const FloatPixel RANKED_HEADER_BLUE{0.26, 0.24, 0.50};


BattleModeDetector::BattleModeDetector()
    //  "Ranked Battles" header — used to confirm we're on the matchmaking screen.
    //  Measured from live capture: x=1083, y=146, w=246, h=46 (1920x1080)
    : m_ranked_header(0.5641, 0.1352, 0.1281, 0.0426)
    //  "Double Battle" or "Single Battle" text.
    //  Measured from live capture: x=1048, y=279, w=236, h=44 (1920x1080)
    , m_format_label(0.5458, 0.2583, 0.1229, 0.0407)
{}


void BattleModeDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_ranked_header);
    items.add(COLOR_YELLOW, m_format_label);
}


BattleMode BattleModeDetector::read_mode(
    Logger& logger, const ImageViewRGB32& screen
) const{
    //  First check if the "Ranked Battles" header is visible — confirms
    //  we're on the matchmaking screen. Skip OCR if not.
    const ImageStats header_stats = image_stats(extract_box_reference(screen, m_ranked_header));
    if (!is_solid(header_stats, RANKED_HEADER_BLUE, 0.18, 150)){
        return BattleMode::UNKNOWN;
    }

    ImageViewRGB32 cropped = extract_box_reference(screen, m_format_label);
    std::string text = OCR::ocr_read(Language::English, cropped, OCR::PageSegMode::SINGLE_LINE);

    //  Normalize: lowercase, strip whitespace.
    std::string lower;
    for (char c : text){
        if (c != '\n' && c != '\r'){
            lower += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
    }

    logger.log("BattleModeDetector: raw OCR = \"" + text + "\"");

    //  Check for "single" or "double" anywhere in the text.
    //  Lenient matching to handle OCR noise.
    if (lower.find("single") != std::string::npos){
        logger.log("BattleModeDetector: detected SINGLES", COLOR_GREEN);
        return BattleMode::SINGLES;
    }
    if (lower.find("double") != std::string::npos){
        logger.log("BattleModeDetector: detected DOUBLES", COLOR_GREEN);
        return BattleMode::DOUBLES;
    }

    //  Fallback: "singl" or "doubl" for partial OCR reads.
    if (lower.find("singl") != std::string::npos){
        return BattleMode::SINGLES;
    }
    if (lower.find("doubl") != std::string::npos){
        return BattleMode::DOUBLES;
    }

    return BattleMode::UNKNOWN;
}


bool BattleModeDetector::detect(const ImageViewRGB32& screen){
    m_mode = BattleMode::UNKNOWN;

    //  Gate: check for "Ranked Battles" header color first.
    const ImageStats header_stats = image_stats(extract_box_reference(screen, m_ranked_header));
    if (!is_solid(header_stats, RANKED_HEADER_BLUE, 0.18, 150)){
        return false;
    }

    ImageViewRGB32 cropped = extract_box_reference(screen, m_format_label);
    std::string text = OCR::ocr_read(Language::English, cropped, OCR::PageSegMode::SINGLE_LINE);

    std::string lower;
    for (char c : text){
        if (c != '\n' && c != '\r'){
            lower += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
    }

    if (lower.find("single") != std::string::npos || lower.find("singl") != std::string::npos){
        m_mode = BattleMode::SINGLES;
        return true;
    }
    if (lower.find("double") != std::string::npos || lower.find("doubl") != std::string::npos){
        m_mode = BattleMode::DOUBLES;
        return true;
    }
    return false;
}


}
}
}
