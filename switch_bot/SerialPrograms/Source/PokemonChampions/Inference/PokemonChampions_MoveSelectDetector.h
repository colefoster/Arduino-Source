/*  Pokemon Champions Move Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the 4-slot move selection menu that appears after pressing A on
 *  FIGHT in the action menu. Reports which slot (0-3) is currently cursored
 *  based on the distinctive bright-green "selected" gradient that appears
 *  behind the active slot.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_MoveSelectDetector_H
#define PokemonAutomation_PokemonChampions_MoveSelectDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Detects presence of the move-select menu. Returns true when the menu is
//  on-screen and at least one slot is rendering the selected-green color.
//
//  Use `cursor_slot()` after `detect()` returns true to read the slot index
//  (0 = top move, 3 = bottom move). Returns -1 if no slot is highlighted
//  (menu not shown or mid-animation).
class MoveSelectDetector : public StaticScreenDetector{
public:
    MoveSelectDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    int cursor_slot() const{ return m_cursor_slot; }

private:
    //  Test a slot region and return true if it matches the selected-green gradient.
    bool is_slot_selected(const ImageViewRGB32& screen, const ImageFloatBox& slot) const;

    ImageFloatBox m_slots[4];
    int m_cursor_slot = -1;
};


class MoveSelectWatcher : public DetectorToFinder<MoveSelectDetector>{
public:
    MoveSelectWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("MoveSelectWatcher", hold_duration)
    {}
};


}
}
}
#endif
