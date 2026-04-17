/*  Pokemon Champions Post-Match Screen Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the post-match summary screen with its three bottom buttons:
 *  Quit Battling / Edit Team / Continue Battling. "Continue Battling" is
 *  cursored by default and shows the selected-green highlight.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_PostMatchDetector_H
#define PokemonAutomation_PokemonChampions_PostMatchDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


enum class PostMatchButton{
    QUIT_BATTLING,
    EDIT_TEAM,
    CONTINUE_BATTLING,
};


class PostMatchScreenDetector : public StaticScreenDetector{
public:
    PostMatchScreenDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true. Which of the three bottom buttons
    //  is currently highlighted green.
    PostMatchButton cursored() const{ return m_cursored; }

private:
    ImageFloatBox m_buttons[3];
    PostMatchButton m_cursored = PostMatchButton::CONTINUE_BATTLING;
};


class PostMatchScreenWatcher : public DetectorToFinder<PostMatchScreenDetector>{
public:
    PostMatchScreenWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(300))
        : DetectorToFinder("PostMatchScreenWatcher", hold_duration)
    {}
};


}
}
}
#endif
