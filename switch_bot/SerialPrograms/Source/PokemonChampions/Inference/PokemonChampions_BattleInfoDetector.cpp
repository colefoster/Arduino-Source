/*  Pokemon Champions Battle Info Tab Detector
 *
 *  From: https://github.com/PokemonAutomation/
 */

#include "CommonFramework/ImageTypes/ImageViewRGB32.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "PokemonChampions_BattleInfoDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


BattleInfoDetector::BattleInfoDetector(){
    //  "Active Statuses & Effects" dark-red header strip on the right panel.
    m_header_strip = ImageFloatBox(0.5275, 0.1820, 0.3500, 0.0500);
    //  Left panel pink species banner (just below the species name row).
    m_left_panel   = ImageFloatBox(0.1900, 0.2150, 0.1700, 0.0500);
}


void BattleInfoDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_RED, m_header_strip);
    items.add(COLOR_RED, m_left_panel);
}


bool BattleInfoDetector::detect(const ImageViewRGB32& screen){
    //  Header strip: dark red/burgundy. Average ~ (140, 40, 60). Loose
    //  ratios because the strip has yellow accent text running through it.
    ImageStats header = image_stats(extract_box_reference(screen, m_header_strip));
    if (header.average.r < 100) return false;
    if (header.average.r < header.average.g + 30) return false;
    if (header.average.r < header.average.b + 30) return false;

    //  Left panel: pink/magenta-ish (own) or purple-ish (opp) — both have
    //  R and B both > G. Brightness floor rejects dim ratio-twins.
    ImageStats left = image_stats(extract_box_reference(screen, m_left_panel));
    if (left.average.r + left.average.g + left.average.b < 220) return false;
    if (left.average.r < left.average.g + 20) return false;
    if (left.average.b < left.average.g + 20) return false;

    return true;
}


}}}
