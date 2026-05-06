/*  Pokemon Champions Pokeball Alive Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the row of 6 pokeball indicators per side that show how many
 *  team mons are still alive in the current battle. Four states per
 *  slot:
 *    ALIVE          -- green/yellow filled ball (healthy)
 *    ALIVE_STATUSED -- orange filled ball (alive but statused -- PSN/PAR/BRN/SLP/FRZ)
 *    FAINTED        -- grey filled ball (defeated mon)
 *    EMPTY          -- small grey dot (slot was never on the brought team)
 *
 *  Own pokeballs sit in the bottom-left HUD strip (y ~ 0.815).
 *  Opp pokeballs sit in the top-right HUD strip (y ~ 0.167).
 *
 *  Detection is mean-channel-based (no OCR):
 *    g <  67       -> EMPTY
 *    g <  150      -> FAINTED (greys)
 *    g >= 150 + r>g -> ALIVE_STATUSED (orange dominates green)
 *    g >= 150 + r<g -> ALIVE (green dominates red)
 *  Measured separation across labeled frames is wide (orange r-g = +62,
 *  green r-g = -72 on sample frames).
 *
 */

#ifndef PokemonAutomation_PokemonChampions_PokeballAliveDetector_H
#define PokemonAutomation_PokemonChampions_PokeballAliveDetector_H

#include <array>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


enum class PokeballState : uint8_t{
    EMPTY          = 0,  //  Slot was never on the brought team -- small grey dot
    FAINTED        = 1,  //  Mon was on the team but is now defeated -- grey ball
    ALIVE          = 2,  //  Mon is on the team and not yet defeated -- green ball
    ALIVE_STATUSED = 3,  //  Alive but statused (PSN/PAR/BRN/SLP/FRZ) -- orange ball
};

const char* pokeball_state_name(PokeballState s);


struct PokeballAliveResult{
    //  6 slots per side. Index = slot 0..5 in the brought-team order
    //  (left-to-right as rendered on screen).
    std::array<PokeballState, 6> own;
    std::array<PokeballState, 6> opp;

    //  Convenience: count of ALIVE entries per side.
    uint8_t own_alive_count() const;
    uint8_t opp_alive_count() const;
};


class PokeballAliveDetector{
public:
    PokeballAliveDetector();

    void make_overlays(VideoOverlaySet& items) const;

    PokeballAliveResult read(const ImageViewRGB32& screen) const;

private:
    void init_boxes();

    std::array<ImageFloatBox, 6> m_own_boxes;
    std::array<ImageFloatBox, 6> m_opp_boxes;
};


}
}
}
#endif
