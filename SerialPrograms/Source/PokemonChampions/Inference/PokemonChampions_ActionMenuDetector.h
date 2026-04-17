/*  Pokemon Champions Action Menu Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the two-button action menu (FIGHT / POKÉMON) that appears at the
 *  start of each turn before the move-select menu. Reports which button is
 *  cursored based on the selected-green highlight.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_ActionMenuDetector_H
#define PokemonAutomation_PokemonChampions_ActionMenuDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


enum class ActionMenuButton{
    FIGHT,
    POKEMON,
};


class ActionMenuDetector : public StaticScreenDetector{
public:
    ActionMenuDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true.
    ActionMenuButton cursored() const{ return m_cursored; }

private:
    bool is_fight_selected(const ImageViewRGB32& screen) const;
    bool is_pokemon_selected(const ImageViewRGB32& screen) const;

    ImageFloatBox m_fight_button;
    ImageFloatBox m_pokemon_button;
    ActionMenuButton m_cursored = ActionMenuButton::FIGHT;
};


class ActionMenuWatcher : public DetectorToFinder<ActionMenuDetector>{
public:
    ActionMenuWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("ActionMenuWatcher", hold_duration)
    {}
};


}
}
}
#endif
