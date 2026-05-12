/*  Pokemon Champions Team Preview Leads Reader
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Reads the 4 yellow lead-order tags (digits 1-4) on the locked-in
 *  team-preview screen ("Preparing for Battle"). Each of the 6 own-team
 *  slots either has a numbered tag (lead, in send-out order) or no tag
 *  (bench).
 *
 *  Output: ordered slot indices (own_team_index of leads[0] = first sent
 *  out, etc.). Up to 4 entries; bench slots are excluded.
 *
 *  Pipeline (per-slot):
 *    crop -> 3x upscale -> yellow→white + invert + flood-fill outside
 *    -> Tesseract SINGLE_CHAR -> normalize confusables (7|/ → 1).
 */

#ifndef PokemonAutomation_PokemonChampions_TeamPreviewLeadsReader_H
#define PokemonAutomation_PokemonChampions_TeamPreviewLeadsReader_H

#include <array>
#include <vector>
#include <cstdint>
#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"

namespace PokemonAutomation{
class ImageViewRGB32;
namespace NintendoSwitch{
namespace PokemonChampions{


struct TeamPreviewLeadsResult{
    //  digit_per_slot[i] = '1','2','3','4' if slot i shows that lead-order
    //  digit, else 0 (bench / unread).
    std::array<char, 6> digit_per_slot = {};

    //  leads[0] = own-team slot index of the first-out lead, [1] = second, etc.
    //  Length 0-4. Filled from digit_per_slot in send-out order.
    std::vector<uint8_t> leads;

    //  Per-slot raw OCR text (for debugging).
    std::array<std::string, 6> raw_ocr = {};
};


class TeamPreviewLeadsReader{
public:
    //  Default = locked-in screen boxes.
    TeamPreviewLeadsReader();

    //  Custom box set — used to read the same digit badges on the
    //  team_preview_selecting screen, where the digit-tag region sits at
    //  different coords.
    explicit TeamPreviewLeadsReader(const std::array<ImageFloatBox, 6>& boxes);

    TeamPreviewLeadsResult read(Logger& logger, const ImageViewRGB32& screen) const;

    //  Box accessors for dashboard / OcrSuggest dispatch.
    const ImageFloatBox& box(uint8_t slot) const { return m_slot_boxes[slot]; }

    //  Pre-built box set for the team_preview_selecting screen (yellow
    //  digit circles on the left edge of each card).
    static std::array<ImageFloatBox, 6> selecting_screen_boxes();

private:
    //  6 own-team icon slots, top-to-bottom. Either the locked-in screen
    //  (small icon tab) or the selecting screen (yellow digit circle on
    //  the card edge), depending on which ctor is used.
    std::array<ImageFloatBox, 6> m_slot_boxes;
};


}}}
#endif
