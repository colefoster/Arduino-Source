/*  Pokemon Champions Ability/Item Overlay Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the mid-battle reveal overlay that shows when a Pokemon's ability
 *  triggers ("Garchomp's Rough Skin!") or its item activates / is held
 *  ("Tyranitar's Sitrus Berry").
 *
 *  The overlay text appears in one of two on-screen positions, depending on
 *  which side fired (left half vs right half). At most one fires at a time;
 *  singles and doubles use the same boxes.
 *
 *  Output is the existing manifest schema:
 *    {kind: "ability"|"item", name: "<slug>", pokemon: "<slug>"}
 *
 *  kind disambiguation goes through PokemonChampions_AbilityItemTable
 *  (PS-derived lookup of all known ability/item slugs).
 */

#ifndef PokemonAutomation_PokemonChampions_AbilityItemReader_H
#define PokemonAutomation_PokemonChampions_AbilityItemReader_H

#include <string>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"

namespace PokemonAutomation{
class ImageViewRGB32;
namespace NintendoSwitch{
namespace PokemonChampions{


//  Forward decl: optional bias snapshot from BattleStateTracker.
//  When provided, the parsed pokemon slug snaps to known own/opp
//  species, and the parsed ability/item slug snaps to the union of
//  scanned own/opp abilities/items — both within Levenshtein-2.
struct TeamCandidates;


struct AbilityItemReadout{
    bool detected = false;
    std::string raw_text;     //  OCR result, before parsing
    std::string pokemon;      //  slug, e.g. "garchomp"
    std::string name;         //  slug, e.g. "rough-skin"
    std::string kind;         //  "ability", "item", or "unknown"
    std::string side;         //  "left" or "right"
};


class AbilityItemReader{
public:
    AbilityItemReader();

    AbilityItemReadout read(
        Logger& logger, const ImageViewRGB32& screen,
        const TeamCandidates* hint = nullptr) const;

private:
    ImageFloatBox m_box_left;
    ImageFloatBox m_box_right;

    //  OCR one crop region. Returns empty string if no real text.
    std::string ocr_crop(const ImageViewRGB32& crop) const;
};


}}}
#endif
