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
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "PokemonChampions_BattleModeDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


BattleModeDetector::BattleModeDetector()
    //  Format label at top of matchmaking / team select screen.
    //  Placeholder coordinates — update with pixel_inspector measurements.
    //  These cover the "Single Battle" / "Double Battle" text in the header.
    : m_format_label(0.250, 0.005, 0.300, 0.035)
{}


void BattleModeDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_YELLOW, m_format_label);
}


BattleMode BattleModeDetector::read_mode(
    Logger& logger, const ImageViewRGB32& screen
) const{
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
    //  We don't have a logger in the StaticScreenDetector interface,
    //  so we use a null logger for the detect() path.
    //  The read_mode() with a real logger is preferred for programs.
    m_mode = BattleMode::UNKNOWN;

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
