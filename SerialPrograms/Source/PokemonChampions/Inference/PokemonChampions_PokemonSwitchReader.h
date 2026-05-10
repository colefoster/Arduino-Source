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
    Language m_language;
    std::array<ImageFloatBox, 6> m_own_species;
    std::array<ImageFloatBox, 6> m_own_hp_text;
    std::array<ImageFloatBox, 6> m_own_highlight;
    std::array<ImageFloatBox, 6> m_opp_hp_pct;
};


}}}
#endif
