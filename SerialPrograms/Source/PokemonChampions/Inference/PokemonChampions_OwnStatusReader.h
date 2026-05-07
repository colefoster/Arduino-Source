/*  Pokemon Champions Own Status Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the status-condition symbol on each own HUD pill. Output is a
 *  short slug per slot: "burn" / "poison" / "paralysis" / "sleep" /
 *  "freeze" / "none". Empty string means no box defined for that slot.
 *
 *  The symbol icon is small (~22x22 in 1080p) and sits over the left edge
 *  of the HUD pill. We sample a tight crop on the most distinctive part of
 *  the icon (e.g. the flame inside the burn symbol) and classify by color.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_OwnStatusReader_H
#define PokemonAutomation_PokemonChampions_OwnStatusReader_H

#include <array>
#include <string>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"

namespace PokemonAutomation{
class ImageViewRGB32;

namespace NintendoSwitch{
namespace PokemonChampions{


class OwnStatusReader{
public:
    OwnStatusReader();

    void make_overlays(VideoOverlaySet& items) const;

    //  Returns one of: "burn", "poison", "paralysis", "sleep", "freeze",
    //  "none", or "" (slot has no defined box yet — caller should skip).
    std::string read(const ImageViewRGB32& screen, uint8_t slot) const;

private:
    std::array<ImageFloatBox, 2> m_boxes;
    //  slot 1 box is a mirror estimate from slot 0 — flag so callers /
    //  tests know to treat it as provisional. Set true once we have
    //  corpus-validated coordinates.
    std::array<bool, 2> m_box_validated;
};


}
}
}
#endif
