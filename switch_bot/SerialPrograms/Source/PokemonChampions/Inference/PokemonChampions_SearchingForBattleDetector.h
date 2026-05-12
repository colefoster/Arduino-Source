/*  Pokemon Champions Searching For Battle Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the "Matchmaking in Progress" modal that appears after pressing
 *  Begin Matchmaking. The modal is a large, centered, saturated-purple panel
 *  with a yellow Pokéball ring icon and "Matchmaking in Progress" text.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_SearchingForBattleDetector_H
#define PokemonAutomation_PokemonChampions_SearchingForBattleDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class SearchingForBattleDetector : public StaticScreenDetector{
public:
    SearchingForBattleDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    ImageFloatBox m_modal_left;
    ImageFloatBox m_modal_right;
};


class SearchingForBattleWatcher : public DetectorToFinder<SearchingForBattleDetector>{
public:
    SearchingForBattleWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("SearchingForBattleWatcher", hold_duration)
    {}
};


}
}
}
#endif
