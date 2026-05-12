/*  Pokemon Champions Team Stats Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the Stats tab on the View Details screen — the sibling of the
 *  Moves & More tab. 2x3 card grid; each card shows 6 stats:
 *    HP / Atk / Def  (left column)    SpA / SpD / Spe  (right column)
 *
 *  Per stat, three sub-fields:
 *    - actual: final stat value (digit OCR)
 *    - evs:    EV count (digit OCR — small number to the right of actual)
 *    - nature: small chevron icon left of actual
 *              up arrow (red/orange) = nature boost  (+10%)
 *              down arrow (light blue) = nature drop (-10%)
 *              no arrow (purple bg)   = neutral
 *
 *  HP has no nature modifier (Pokemon doesn't have natures that
 *  boost/lower HP). 17 boxes per slot total = 102 across the team.
 *
 *  TeamStatsTabDetector: same shape as MovesMoreDetector but keys on
 *  the Stats tab being yellow-green-highlighted.
 *
 *  Coordinates measured 2026-05-06 from
 *    test_images/team_stats/whimsicott_incineroar_kingambit_floette_basculegion_sneasler.png
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamStatsReader_H
#define PokemonAutomation_PokemonChampions_TeamStatsReader_H

#include <array>
#include <cstdint>
#include <string>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


enum class NatureMod{ NEUTRAL, BOOST, DROP };
const char* nature_mod_name(NatureMod m);

//  Indices into the 6-stat array. Keep HP first so neutral skips on it.
//  These match the order used in PokemonChampions_BattleStateTracker boost
//  arrays, but here apply to the *base-stat nature modifier*.
enum class StatSlot : uint8_t{ HP=0, ATK=1, DEF=2, SPA=3, SPD=4, SPE=5 };
const char* stat_slot_name(StatSlot s);


struct StatRead{
    int actual = 0;            //  Final stat value (e.g. 184). 0 = OCR fail.
    int evs = 0;               //  EV count. 0 = OCR fail or actually 0.
    NatureMod nature = NatureMod::NEUTRAL;  //  Always NEUTRAL for HP.
    std::string raw_actual;    //  Pre-parse OCR (debug).
    std::string raw_evs;       //  Pre-parse OCR (debug).
    int blue_pixel_count = 0;  //  Nature classifier debug
    int red_pixel_count = 0;   //  Nature classifier debug
};


struct TeamStatsInfo{
    //  Stat reads in StatSlot order (HP, ATK, DEF, SPA, SPD, SPE).
    std::array<StatRead, 6> stats;

    //  Inferred nature slug ("Adamant", "Timid", ..., "Hardy" for neutral).
    //  Empty if the boost/drop pair is invalid (e.g. two boosts).
    std::string nature_slug;
};


//  Detector for the Stats tab. Same shape as MovesMoreDetector — purple
//  card-bg gate, but keys on the Stats tab label being yellow-green
//  (the active tab) instead of the Moves & More label.
class TeamStatsTabDetector : public StaticScreenDetector{
public:
    TeamStatsTabDetector();
    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    ImageFloatBox m_card_bg;
    ImageFloatBox m_tab_label;
};


class TeamStatsReader{
public:
    TeamStatsReader();

    void make_overlays(VideoOverlaySet& items) const;

    //  Read one card (0..5). Always returns 6 StatRead entries.
    TeamStatsInfo read_card(Logger& logger, const ImageViewRGB32& screen, uint8_t slot) const;

    //  Read all 6 cards in one pass.
    std::array<TeamStatsInfo, 6> read_team(Logger& logger, const ImageViewRGB32& screen) const;

    //  Infer the Pokemon's nature slug from boost/drop pattern.
    //  Returns "" if (boost, drop) doesn't map to a real nature, or
    //  "Hardy" if all stats are NEUTRAL.
    static std::string infer_nature(const std::array<StatRead, 6>& stats);

private:
    //  [slot][stat_slot] for each of the 3 sub-fields.
    std::array<std::array<ImageFloatBox, 6>, 6> m_actual_boxes;
    std::array<std::array<ImageFloatBox, 6>, 6> m_evs_boxes;
    std::array<std::array<ImageFloatBox, 6>, 6> m_nature_boxes;
};


}
}
}
#endif
