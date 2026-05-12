/*  Pokemon Champions Battle Info Tab Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the mid-battle Battle Info tab: per-mon species/HP/types/ability/
 *  item, 5 main-stat boost multipliers, and the first row of the Active
 *  Statuses & Effects list.
 *
 *  The screen shows ONE focused mon at a time (cycled via L/R). The
 *  selected_slot field tells the caller which of own[0]/own[1]/opp[0]/
 *  opp[1] this read pertains to — detected via the yellow background of
 *  the focused icon in the top L/R bar.
 */

#ifndef PokemonAutomation_PokemonChampions_BattleInfoReader_H
#define PokemonAutomation_PokemonChampions_BattleInfoReader_H

#include <array>
#include <string>
#include <cstdint>
#include "CommonFramework/Language.h"
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"

namespace PokemonAutomation{
class ImageViewRGB32;
namespace NintendoSwitch{
namespace PokemonChampions{


//  side='own'/'opp', slot=0/1, valid=false until the icon-bar yellow detect
//  fires. SOLO uses slot=0 (singles maps internally to own_active[0]).
struct FocusedSlot{
    bool valid = false;
    std::string side;       //  "own" | "opp"
    uint8_t slot = 0;       //  0 or 1
};


struct BattleInfoResult{
    FocusedSlot focused;

    //  Identity (focused mon).
    std::string species;        //  slug (lowercase, hyphenated)
    int hp_current = -1;        //  -1 if unread (opp panel only shows %)
    int hp_max = -1;
    int hp_pct = -1;            //  -1 if unread (own panel shows X/Y)
    std::array<std::string, 2> types;   //  e.g. ["fire","flying"]
    std::string ability;        //  own only
    std::string item;           //  own only

    //  Boosts: index by atk/def/spa/spd/spe (5 entries; accuracy/evasion
    //  read but discarded for now since BattleStateTracker has no slots).
    //  Each value is a stage in [-6, +6]; 0 if unread or neutral.
    std::array<int8_t, 5> boosts = {};

    //  First row of Active Statuses & Effects ("Harsh Sunlight 2/5").
    std::string status_text;
    int status_turns_current = -1;
    int status_turns_max = -1;
};


class BattleInfoReader{
public:
    explicit BattleInfoReader(Language language = Language::English);

    BattleInfoResult read(Logger& logger, const ImageViewRGB32& screen) const;

private:
    Language m_language;

    //  Top icon bar — singles + doubles layouts.
    std::array<ImageFloatBox, 2> m_own_icon;     //  doubles slots 0/1
    ImageFloatBox m_own_icon_solo;               //  singles centered
    std::array<ImageFloatBox, 2> m_opp_icon;     //  doubles slots 0/1

    //  Focused mon panel (left).
    ImageFloatBox m_species_name;
    ImageFloatBox m_hp_text;
    std::array<ImageFloatBox, 2> m_type;
    ImageFloatBox m_ability;
    ImageFloatBox m_item;

    //  7 boost-multiplier text boxes (atk/def/spa/spd/spe/acc/eva).
    std::array<ImageFloatBox, 7> m_multiplier;

    //  Active Statuses & Effects — first row (text + turn counter).
    ImageFloatBox m_status_first;
    ImageFloatBox m_status_first_duration;
};


}}}
#endif
