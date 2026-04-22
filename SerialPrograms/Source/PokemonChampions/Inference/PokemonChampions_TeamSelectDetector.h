/*  Pokemon Champions Team Select Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects the team select screen that appears after matchmaking finds
 *  an opponent. This screen shows all 6 own Pokemon on the left side
 *  with a "0/4 Done" (doubles) or "0/3 Done" (singles) counter.
 *
 *  Detection strategy:
 *    1. Check for the "Ranked Battles" blue header (shared with matchmaking)
 *    2. Check for the dark left panel where team slots are displayed
 *    3. OCR the "Done" counter text at the bottom-right
 *
 */

#ifndef PokemonAutomation_PokemonChampions_TeamSelectDetector_H
#define PokemonAutomation_PokemonChampions_TeamSelectDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


class TeamSelectDetector : public StaticScreenDetector{
public:
    TeamSelectDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

private:
    //  "Ranked Battles" header — blue panel, confirms we're on a ranked screen.
    ImageFloatBox m_ranked_header;

    //  Dark left panel where team Pokemon are listed.
    //  Used as a secondary gate — the team select has a distinctive dark
    //  panel on the left half of the screen.
    ImageFloatBox m_left_panel;

    //  "Done" counter text region at bottom-right (e.g. "0/4 Done").
    ImageFloatBox m_done_counter;
};


class TeamSelectWatcher : public DetectorToFinder<TeamSelectDetector>{
public:
    TeamSelectWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(250))
        : DetectorToFinder("TeamSelectWatcher", hold_duration)
    {}
};


}
}
}
#endif
