/*  Pokemon Champions Target Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include <algorithm>

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "PokemonChampions_TargetSelectDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Strict "selected" classifier for the detector. The reader uses a looser
//  g>=150 && g>=b test which is good enough to pick targeted-vs-untargeted
//  ONCE we know we're on the modal — but on its own that loose test
//  false-positives on yellow buttons (post-match Continue, action menu HP
//  bars, etc.) at the strip x/y coords. Real selected strips on the modal
//  read raw RGB ~ (170-255, 255, 0) → mean g >= 220 and mean b <= 80. Every
//  observed FP reads g <= 200 OR b >= 80 — tight gap.
static bool is_selected_strip(const ImageStats& s){
    return s.average.g >= 220.0 && s.average.b <= 80.0;
}


//  A "saturated strip color" — anything that looks like a target selector,
//  whether currently selected or not. Untargeted reads either red-orange
//  (high R, low G/B) or blue-cyan (low R, high B). Both have one channel
//  clearly dominating the others. Background HUD pixels at these positions
//  read either dark / desaturated, so the gap test rejects them.
static bool is_strip_color(const ImageStats& s){
    double r = s.average.r;
    double g = s.average.g;
    double b = s.average.b;
    double mx = std::max({r, g, b});
    double mn = std::min({r, g, b});

    //  Brightness floor — strips always have at least one channel bright.
    if (mx < 110.0) return false;
    //  Saturation floor — strips are always saturated; background is gray.
    if (mx - mn < 40.0) return false;
    return true;
}


TargetSelectDetector::TargetSelectDetector()
    //  Reused verbatim from TargetSelectReader. Order: opp_a, opp_b,
    //  own_a, own_b — matches selected_index() doc.
    : m_strips{
        ImageFloatBox(0.4741, 0.2355, 0.0062, 0.1172),  //  opp_a
        ImageFloatBox(0.7338, 0.2340, 0.0045, 0.1228),  //  opp_b
        ImageFloatBox(0.4741, 0.5832, 0.0053, 0.1030),  //  own_a
        ImageFloatBox(0.7334, 0.5714, 0.0053, 0.1117),  //  own_b
    }
{}


void TargetSelectDetector::make_overlays(VideoOverlaySet& items) const{
    for (const ImageFloatBox& strip : m_strips){
        items.add(COLOR_YELLOW, strip);
    }
}


bool TargetSelectDetector::detect(const ImageViewRGB32& screen){
    int selected_count = 0;
    int strip_count = 0;
    int8_t selected_idx = -1;

    for (size_t i = 0; i < m_strips.size(); i++){
        ImageStats s = image_stats(extract_box_reference(screen, m_strips[i]));
        bool is_strip = is_strip_color(s);
        bool is_sel = is_strip && is_selected_strip(s);
        if (is_strip) strip_count++;
        if (is_sel){
            selected_count++;
            selected_idx = static_cast<int8_t>(i);
        }
    }

    //  Fire iff exactly one strip is in the selected (yellow/green) state,
    //  AND at least one OTHER position also reads as a saturated strip
    //  color. The companion check is what rejects false positives where a
    //  single coincidentally-yellow region on action_menu / move_select /
    //  post_match etc. lines up with one strip box but no others.
    //
    //  Self-target moves (e.g. Protect) don't render opp strips at all, so
    //  we tolerate fewer than 4 strips total — but still need >= 2.
    if (selected_count != 1) return false;
    if (strip_count < 2) return false;

    m_selected = selected_idx;
    return true;
}


}
}
}
