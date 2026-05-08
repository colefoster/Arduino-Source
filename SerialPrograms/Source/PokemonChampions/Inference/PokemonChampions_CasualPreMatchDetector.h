/*  Pokemon Champions Casual Pre-Match Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the casual pre-match staging screen (Single Battle / Team N /
 *  Change Music / Begin Matchmaking column). Visually distinct from the
 *  ranked PreMatchDetector — different theming, no white sprite-strip
 *  team card, lighter pills.
 *
 *  Three pill cursor strips:
 *    0 = Team Select
 *    1 = Change Music
 *    2 = Begin Matchmaking
 *  The cursored pill renders bright yellow; the other two render bright
 *  white. Detector fires when all three pill regions are bright (yellow or
 *  white) and at most one is yellow. selected_index() returns the yellow
 *  one, or -1 if none (cursor on a footer button outside these three).
 */

#ifndef PokemonAutomation_PokemonChampions_CasualPreMatchDetector_H
#define PokemonAutomation_PokemonChampions_CasualPreMatchDetector_H

#include <array>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class CasualPreMatchDetector : public StaticScreenDetector{
public:
    CasualPreMatchDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  0=Team Select, 1=Change Music, 2=Begin Matchmaking, -1=elsewhere.
    int selected_index() const{ return m_selected_index; }

private:
    std::array<ImageFloatBox, 3> m_pill_boxes;
    int m_selected_index = -1;
};


class CasualPreMatchWatcher : public DetectorToFinder<CasualPreMatchDetector>{
public:
    CasualPreMatchWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("CasualPreMatchWatcher", hold_duration)
    {}
};


}
}
}
#endif
