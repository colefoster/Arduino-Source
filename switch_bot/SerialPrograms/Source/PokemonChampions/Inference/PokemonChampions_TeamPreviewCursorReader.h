/*  Pokemon Champions Team Preview Cursor Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  On the team_preview_selecting screen, identifies which of the 6 own
 *  slots the cursor is currently on. The selected card has a saturated
 *  yellow ▶ arrow + yellow-tinted highlight on its left edge; the
 *  unselected cards are flat purple. Score "yellowness" per slot and
 *  pick the highest, with a floor to reject all-cold reads.
 *
 *  Returns selected_slot ∈ {0..5} on success, -1 on no confident pick.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamPreviewCursorReader_H
#define PokemonAutomation_PokemonChampions_TeamPreviewCursorReader_H

#include <array>
#include <cstdint>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"

namespace PokemonAutomation{

class Logger;
class ImageViewRGB32;

namespace NintendoSwitch{
namespace PokemonChampions{


class TeamPreviewCursorReader{
public:
    TeamPreviewCursorReader();

    void make_overlays(VideoOverlaySet& items) const;

    //  Returns 0..5 for the 6 mon slots, 6 for the Done button, or -1 if no
    //  cursor target scored above the floor.
    int read(Logger& logger, const ImageViewRGB32& screen) const;

private:
    std::array<ImageFloatBox, 7> m_highlight;
};


}
}
}
#endif
