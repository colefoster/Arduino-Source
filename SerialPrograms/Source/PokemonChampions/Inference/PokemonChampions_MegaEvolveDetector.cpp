/*  Pokemon Champions Mega Evolve Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  The Mega Evolve toggle on the move-select screen is a small white
 *  pill with a black "R" inside. Visible only when the active mon can
 *  Mega Evolve and the option hasn't been used yet this battle.
 *
 *  Two-stage detection:
 *    1. Cheap white-pixel fraction check — when the pill isn't showing,
 *       this region is part of the dark battle background, so few/no
 *       pixels in the box are white.
 *    2. OCR confirmation — must read a clean "R".
 *
 *  Box tuned via inspector: (0.5968, 0.9198, 0.0194, 0.0325).
 *
 */

#include <cctype>
#include <string>
#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "PokemonChampions_BattleHUDReader.h"   //  raw_ocr_numbers
#include "PokemonChampions_MegaEvolveDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


MegaEvolveDetector::MegaEvolveDetector()
    : m_toggle_region(0.5987, 0.9123, 0.0169, 0.0203)
{}

void MegaEvolveDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_YELLOW, m_toggle_region);
}

//  Fraction of pixels in the crop that look white (high brightness, low
//  saturation). The pill is solid white; absent → dark battle scene.
static double white_pixel_fraction(const ImageViewRGB32& crop){
    size_t w = crop.width();
    size_t h = crop.height();
    if (w == 0 || h == 0) return 0.0;
    size_t white = 0;
    size_t total = w * h;
    for (size_t y = 0; y < h; y++){
        for (size_t x = 0; x < w; x++){
            uint32_t px = crop.pixel(x, y);
            uint8_t r = (px >> 0)  & 0xFF;
            uint8_t g = (px >> 8)  & 0xFF;
            uint8_t b = (px >> 16) & 0xFF;
            uint8_t mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
            uint8_t mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
            if (mn > 200 && (mx - mn) < 30) white++;
        }
    }
    return (double)white / (double)total;
}

bool MegaEvolveDetector::detect(const ImageViewRGB32& screen){
    ImageViewRGB32 crop = extract_box_reference(screen, m_toggle_region);

    //  Stage 1: cheap white-fraction filter.
    //  The pill is mostly white background with a small dark "R" carved
    //  out — empirically the white fraction sits well above 0.40 when
    //  visible, near 0 otherwise.
    if (white_pixel_fraction(crop) < 0.30) return false;

    //  Stage 2: OCR must read "R" (raw_ocr_numbers binarizes white
    //  pixels to black, leaving the "R" carved out cleanly).
    std::string text = raw_ocr_numbers(crop);
    for (char c : text){
        if (c == 'R' || c == 'r') return true;
    }
    return false;
}


}
}
}
