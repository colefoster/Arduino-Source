/*  Pokemon Champions Battle Mode Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Detects whether the current game mode is Singles (BSS) or Doubles (VGC)
 *  by reading the format text on the matchmaking / team select screen.
 *
 *  The text "Single Battle" or "Double Battle" appears at the top of:
 *    - The matchmaking screen (before queueing)
 *    - The team select screen (after opponent found)
 *
 *  This detection is critical because the battle HUD layout differs
 *  significantly between the two modes:
 *    - Singles: 1 own mon (bottom-left), 1 opponent (top-right), 4 moves (right pills)
 *    - Doubles: 2 own mons (bottom-left), 2 opponents (top-right), FIGHT circle (bottom-right)
 *
 */

#ifndef PokemonAutomation_PokemonChampions_BattleModeDetector_H
#define PokemonAutomation_PokemonChampions_BattleModeDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/Logging/Logger.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


enum class BattleMode{
    UNKNOWN,
    SINGLES,    //  BSS — bring 6 pick 3, 1v1
    DOUBLES,    //  VGC — bring 6 pick 4, 2v2
};


//  Detects the battle mode from the matchmaking or team select screen.
//  Looks for "Single Battle" or "Double Battle" text in the header area.
//
//  The detector reads the format label region via OCR and string-matches
//  against known format strings.
class BattleModeDetector : public StaticScreenDetector{
public:
    BattleModeDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    //  Valid after detect() returns true.
    BattleMode mode() const{ return m_mode; }

    //  OCR the format text and return the detected mode.
    //  Can be called standalone without the detect() state machine.
    BattleMode read_mode(Logger& logger, const ImageViewRGB32& screen) const;

private:
    //  "Ranked Battles" header — blue panel, used to confirm we're on the
    //  matchmaking screen before attempting OCR on the format label.
    ImageFloatBox m_ranked_header;

    //  The format label: "Single Battle" or "Double Battle" text.
    ImageFloatBox m_format_label;

    BattleMode m_mode = BattleMode::UNKNOWN;
};


class BattleModeWatcher : public DetectorToFinder<BattleModeDetector>{
public:
    BattleModeWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(250))
        : DetectorToFinder("BattleModeWatcher", hold_duration)
    {}
};


//  Utility: return a human-readable string for the mode.
inline const char* battle_mode_str(BattleMode mode){
    switch (mode){
    case BattleMode::SINGLES: return "Singles";
    case BattleMode::DOUBLES: return "Doubles";
    default:                  return "Unknown";
    }
}


}
}
}
#endif
