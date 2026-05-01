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

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "PokemonChampions_MegaEvolveDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


MegaEvolveDetector::MegaEvolveDetector()
    : m_toggle_region(0.5975, 0.9210, 0.0181, 0.0213)
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

    //  White-pixel-fraction is sufficient on its own. Empirically: visible
    //  pill ≥0.70, absent ≈0.00 — a wide separation. The earlier OCR step
    //  was unreliable because the binarized "R" comes out as white-on-black
    //  (a hole in the pill blob), which Tesseract mis-recognizes as "n".
    return white_pixel_fraction(crop) >= 0.50;
}


}
}
}
