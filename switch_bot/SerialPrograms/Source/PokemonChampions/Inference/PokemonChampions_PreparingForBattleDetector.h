/*  Pokemon Champions "Preparing for Battle" Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the between-team-select-and-battle lock-in screen that displays
 *  both teams with the 3 chosen mons highlighted and "Standing By"
 *  indicators on both sides. Firing this detector means we've successfully
 *  confirmed our team and should stop pressing A.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_PreparingForBattleDetector_H
#define PokemonAutomation_PokemonChampions_PreparingForBattleDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class PreparingForBattleDetector : public StaticScreenDetector{
public:
    PreparingForBattleDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    //  6 boxes on the player's team card number badges (left column).
    ImageFloatBox m_left_standing_by;   // kept for legacy overlay compat
    ImageFloatBox m_right_standing_by;  // kept for legacy overlay compat
    ImageFloatBox m_card_slots[6];
};


class PreparingForBattleWatcher : public DetectorToFinder<PreparingForBattleDetector>{
public:
    PreparingForBattleWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(300))
        : DetectorToFinder("PreparingForBattleWatcher", hold_duration)
    {}
};


}
}
}
#endif
