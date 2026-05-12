/*  Pokemon Champions Pokemon Switch Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the POKEMON menu (reached from action_menu's POKEMON button).
 *  This screen is the only place where HP for non-active own mons is
 *  visible at once — the in-battle HUD only shows the 1-2 active slots.
 *  We harvest:
 *    - Own column: species name (text OCR) + HP fraction "X/Y" per slot
 *    - Opp column: HP percentage per slot
 *    - Selected slot index via the yellow highlight
 *
 *  Up to 6 own slots and 6 opp slots; empty slots return -1 sentinels.
 *
 *  Box layout mirrors dashboard CROP_DEFS["PokemonSwitchReader"].
 */

#ifndef PokemonAutomation_PokemonChampions_PokemonSwitchReader_H
#define PokemonAutomation_PokemonChampions_PokemonSwitchReader_H

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


//  Forward decl: optional bias snapshot from BattleStateTracker.
//  When provided, own-slot species OCR snaps to a member of
//  hint->own_species within Levenshtein-2 (the registered team is
//  fixed, so a near-miss is virtually always a misread).
struct TeamCandidates;


struct PokemonSwitchSlot{
    std::string species;            //  slug; empty if unread
    int hp_current = -1;            //  own only
    int hp_max     = -1;            //  own only
    int hp_pct     = -1;            //  opp only
    //  Raw OCR strings for split current/max HP boxes. Empty if the
    //  per-slot box was zero-area (slot beyond layout's active count)
    //  or OCR produced no output. Surfaced on the dashboard for tuning.
    std::string hp_current_raw;     //  own only
    std::string hp_max_raw;         //  own only
};


struct PokemonSwitchResult{
    std::array<PokemonSwitchSlot, 6> own;
    std::array<PokemonSwitchSlot, 6> opp;
    int selected_own_slot = -1;     //  0-5 or -1 if no highlight
};


class PokemonSwitchReader{
public:
    explicit PokemonSwitchReader(Language language = Language::English);

    PokemonSwitchResult read(
        Logger& logger, const ImageViewRGB32& screen,
        const TeamCandidates* hint = nullptr) const;

private:
    //  Per-row boxes for one layout (singles 3-row OR doubles 4-row).
    //  Slots beyond the layout's active count get zero-area boxes so
    //  yellow_score returns 0 and they never win the cursor pick.
    struct OwnLayout{
        std::array<ImageFloatBox, 6> species;
        std::array<ImageFloatBox, 6> hp_text;        //  combined "X/Y" — legacy
        std::array<ImageFloatBox, 6> hp_current;     //  split — just the current number
        std::array<ImageFloatBox, 6> hp_max;         //  split — just the max number (post-slash)
        std::array<ImageFloatBox, 6> highlight;
        int active_slot_count = 0;  //  3 (singles) or 4 (doubles)
    };

    Language m_language;
    OwnLayout m_doubles;
    OwnLayout m_singles;
    std::array<ImageFloatBox, 6> m_opp_hp_pct;
};


}}}
#endif
