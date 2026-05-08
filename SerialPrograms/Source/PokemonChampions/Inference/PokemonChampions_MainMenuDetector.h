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

#include <array>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


enum class MainMenuButton{
    BATTLE   = 0,
    BOX      = 1,
    TRAIN    = 2,
    RECRUIT  = 3,
    MISSIONS = 4,   //  bottom bar — leftmost
    MAILBOX  = 5,
    STYLE    = 6,
    SUB_MENU = 7,   //  bottom bar — rightmost
    UNKNOWN  = -1,
};


class MainMenuDetector : public StaticScreenDetector{
public:
    MainMenuDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true.
    MainMenuButton cursored() const{ return m_cursored; }
    int selected_index() const{ return (int)m_cursored; }

private:
    bool is_battle_selected(const ImageViewRGB32& screen) const;
    bool is_box_selected(const ImageViewRGB32& screen) const;

    ImageFloatBox m_battle_button;
    ImageFloatBox m_box_button;
    ImageFloatBox m_chrome;
    ImageFloatBox m_recruit_tile;
    //  Per-option cursor strips. 0..7 = Battle/Box/Train/Recruit/Missions/
    //  Mailbox/Style/SubMenu. Drawn by user.
    std::array<ImageFloatBox, 8> m_cursor_boxes;
    MainMenuButton m_cursored = MainMenuButton::UNKNOWN;
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
