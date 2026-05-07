/*  Pokemon Champions Own Status Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Color classifier walks a small candidate table and returns the first
 *  status whose distinctive color matches the sample box. "none" if none
 *  matches.
 *
 *  Pixel measurements (1920x1080) — slot 0:
 *    Box: x=129, y=922, w=22, h=22 → fractions (0.0672, 0.8534, 0.0115, 0.0205)
 *    Burn: avg RGB (147, 46, 47)         — saturated red flame
 *    No status: avg RGB (191, 194, 209)  — neutral lavender (pill body / mon icon area)
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "PokemonChampions_OwnStatusReader.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


OwnStatusReader::OwnStatusReader()
    //  Slot 0 box is corpus-validated (status_symbol_0 in box_definitions.json).
    //  Slot 1 is a mirror estimate (slot 0 offset of 0.0145 within the strip
    //  applied to slot 1's strip start at 0.2628). Refine when a slot-1
    //  status sample lands in the corpus.
    : m_boxes{
        ImageFloatBox(0.0672, 0.8534, 0.0115, 0.0205),
        ImageFloatBox(0.2773, 0.8534, 0.0115, 0.0205),
      }
    , m_box_validated{true, false}
{}


void OwnStatusReader::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_boxes[0]);
    //  Slot 1 box is provisional — render in a different color so it's
    //  obvious in the overlay that it hasn't been corpus-tuned.
    items.add(COLOR_YELLOW, m_boxes[1]);
}


//  Classify a sampled color into a status slug. Thresholds chosen to
//  cleanly separate the corpus' burn sample from the no-status baselines
//  and leave generous room for future status colors. Add a candidate row
//  per status as corpus samples become available.
static std::string classify_status(const ImageStats& stats){
    const double r = stats.average.r;
    const double g = stats.average.g;
    const double b = stats.average.b;

    //  Burn: saturated red flame. Corpus burn = (147, 46, 47); baselines
    //  read (191, 194, 209) [neutral] and (134, 124, 211) [purple pill],
    //  both of which have r ≈ g and r < b. Requiring r dominant by ≥ 50
    //  over both g and b cleanly separates.
    if (r >= g + 50.0 && r >= b + 50.0 && r >= 100.0){
        return "burn";
    }

    //  TODO: poison (purple, b dominant), paralysis (yellow, r+g high b
    //  low), sleep (dark blue), freeze (cyan). Add when corpus has a
    //  representative sample for each.

    return "none";
}


std::string OwnStatusReader::read(const ImageViewRGB32& screen, uint8_t slot) const{
    if (slot >= 2) return "";
    if (!m_box_validated[slot]) return "";
    const ImageStats stats = image_stats(extract_box_reference(screen, m_boxes[slot]));
    return classify_status(stats);
}


}
}
}
