/*  Pokemon Champions Team Preview Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonTools/OCR/OCR_RawOCR.h"
#include "PokemonChampions_TeamPreviewDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


TeamPreviewDetector::TeamPreviewDetector()
    //  "Select 4 Pokemon to send into battle" title text region, center of screen.
    //  Measured from screenshots/team_preview_3804.png (1920x1080).
    : m_title_text(0.3604, 0.2037, 0.1375, 0.0778)
{}


void TeamPreviewDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_title_text);
}


bool TeamPreviewDetector::detect(const ImageViewRGB32& screen){
    ImageViewRGB32 cropped = extract_box_reference(screen, m_title_text);
    std::string text = OCR::ocr_read(Language::English, cropped);

    std::string lower;
    for (char c : text){
        if (c != '\n' && c != '\r'){
            lower += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        }
    }

    //  Look for "select" — the title is "Select 4 Pokemon to send into battle".
    //  Lenient to handle OCR noise.
    if (lower.find("select") != std::string::npos){
        return true;
    }
    if (lower.find("selec") != std::string::npos){
        return true;
    }
    return false;
}


}
}
}
