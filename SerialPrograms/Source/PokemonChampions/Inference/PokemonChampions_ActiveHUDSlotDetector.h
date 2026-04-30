/*  Pokemon Champions Active HUD Slot Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  In doubles, when selecting a move the game highlights the HUD pill of
 *  the Pokemon currently being commanded with a bright lime-green outline
 *  along its top edge. The non-active partner's pill keeps a plain white
 *  border. Sampling a thin strip across the top of each pill gives a
 *  ~150-unit-per-channel separation, so detection is unambiguous.
 *
 *  Use to disambiguate which mon's moves are visible in MoveNameReader.
 *
 *  Measured from doubles move_select captures (1920x1080):
 *    Active   top edge: avg RGB ~(173, 255,   0)   bright lime
 *    Inactive top edge: avg RGB ~(255, 254, 255)   near white
 *
 */

#ifndef PokemonAutomation_PokemonChampions_ActiveHUDSlotDetector_H
#define PokemonAutomation_PokemonChampions_ActiveHUDSlotDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Detects which own HUD slot is "active" (currently being commanded) in
//  doubles. detect() returns true if exactly one slot shows the lime-green
//  active outline. After detect() returns true, active_slot() reports
//  0 (left) or 1 (right). Returns -1 if neither matches.
class ActiveHUDSlotDetector : public StaticScreenDetector{
public:
    ActiveHUDSlotDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    int active_slot() const{ return m_active_slot; }

private:
    ImageFloatBox m_slot_strips[2];
    int m_active_slot = -1;
};


class ActiveHUDSlotWatcher : public DetectorToFinder<ActiveHUDSlotDetector>{
public:
    ActiveHUDSlotWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(150))
        : DetectorToFinder("ActiveHUDSlotWatcher", hold_duration)
    {}
};


}
}
}
#endif
