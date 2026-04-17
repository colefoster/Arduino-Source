/*  Pokemon Champions Main Menu Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the main menu and reports which button is currently
 *  selected based on the bright yellow highlight glow.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_MainMenuDetector_H
#define PokemonAutomation_PokemonChampions_MainMenuDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


enum class MainMenuButton{
    BATTLE,
    BOX,
};


class MainMenuDetector : public StaticScreenDetector{
public:
    MainMenuDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true.
    MainMenuButton cursored() const{ return m_cursored; }

private:
    bool is_battle_selected(const ImageViewRGB32& screen) const;
    bool is_box_selected(const ImageViewRGB32& screen) const;

    ImageFloatBox m_battle_button;
    ImageFloatBox m_box_button;
    MainMenuButton m_cursored = MainMenuButton::BATTLE;
};


class MainMenuWatcher : public DetectorToFinder<MainMenuDetector>{
public:
    MainMenuWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("MainMenuWatcher", hold_duration)
    {}
};


}
}
}
#endif
