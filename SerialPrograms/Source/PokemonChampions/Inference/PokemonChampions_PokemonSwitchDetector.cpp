/*  Pokemon Champions Pokemon Switch Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Center-panel tabs ("Moves & More" left, "Stats" right). Active tab is
 *  filled with a lime/yellow highlight; inactive tab is dark blue. Two
 *  sample points per tab (left + right). Accept iff exactly one tab reads
 *  active-on-both-points and the other reads inactive-on-both-points.
 *  Rejects: both active, both inactive, or any mixed/partial state.
 *
 *  Sample averages (1920x1080, on a real switch screen with Moves & More
 *  active):
 *    Moves left/right:  ~(170, 255,   0)   lime
 *    Stats  left/right: ~( 30,  23, 100)   dark blue
 *
 */

#include "Common/Cpp/Color.h"
#include "CommonFramework/ImageTools/ImageStats.h"
#include "CommonFramework/VideoPipeline/VideoOverlay.h"
#include "PokemonChampions_PokemonSwitchDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Active = lime green or yellow: very low blue + strong green channel.
//  Lime ~(170,255,0); Yellow ~(255,220,0). Both have b near 0, g >= 200.
static bool is_active_highlight(const ImageStats& s){
    return s.average.b < 60.0 && s.average.g > 150.0;
}

//  Inactive = dark blue panel: dominant blue, low red & green.
static bool is_inactive_blue(const ImageStats& s){
    return s.average.b > 80.0 && s.average.r < 80.0 && s.average.g < 80.0;
}


PokemonSwitchDetector::PokemonSwitchDetector()
    //  4 boxes inside the two tabs at the top of the center panel.
    //  Moves & More tab: left + right samples.
    : m_moves_left (0.3977, 0.1079, 0.0221, 0.0273)
    , m_moves_right(0.5137, 0.1136, 0.0198, 0.0258)
    //  Stats tab: left + right samples.
    , m_stats_left (0.5581, 0.1122, 0.0246, 0.0244)
    , m_stats_right(0.6419, 0.1114, 0.0282, 0.0258)
{}


void PokemonSwitchDetector::make_overlays(VideoOverlaySet& items) const{
    items.add(COLOR_CYAN, m_moves_left);
    items.add(COLOR_CYAN, m_moves_right);
    items.add(COLOR_CYAN, m_stats_left);
    items.add(COLOR_CYAN, m_stats_right);
}


bool PokemonSwitchDetector::detect(const ImageViewRGB32& screen){
    const ImageStats ml = image_stats(extract_box_reference(screen, m_moves_left));
    const ImageStats mr = image_stats(extract_box_reference(screen, m_moves_right));
    const ImageStats sl = image_stats(extract_box_reference(screen, m_stats_left));
    const ImageStats sr = image_stats(extract_box_reference(screen, m_stats_right));

    const bool moves_active   = is_active_highlight(ml) && is_active_highlight(mr);
    const bool moves_inactive = is_inactive_blue(ml)    && is_inactive_blue(mr);
    const bool stats_active   = is_active_highlight(sl) && is_active_highlight(sr);
    const bool stats_inactive = is_inactive_blue(sl)    && is_inactive_blue(sr);

    return (moves_active && stats_inactive) || (moves_inactive && stats_active);
}


}
}
}
