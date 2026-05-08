/*  Pokemon Champions Battle Info Tab Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Mid-battle Battle Info screen — opened from the action menu / move
 *  select via the in-game info button. Shows per-mon stats, boosts,
 *  ability/item (own only), types, and a list of active field statuses.
 *
 *  Detection: dark-red header strip behind "Active Statuses & Effects"
 *  text, co-evidence with the pink/purple panel background on the left.
 */

#ifndef PokemonAutomation_PokemonChampions_BattleInfoDetector_H
#define PokemonAutomation_PokemonChampions_BattleInfoDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
class ImageViewRGB32;
namespace NintendoSwitch{
namespace PokemonChampions{


class BattleInfoDetector : public StaticScreenDetector{
public:
    BattleInfoDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    ImageFloatBox m_header_strip;   //  "Active Statuses & Effects" dark-red bar
    ImageFloatBox m_left_panel;     //  pink/purple species panel bg
};


}}}
#endif
