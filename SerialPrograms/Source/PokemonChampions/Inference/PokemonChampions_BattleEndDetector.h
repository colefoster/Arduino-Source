/*  Pokemon Champions Battle End Detector
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Signals that the match is over and the result banner is about to appear.
 *  Fires on either end-text variant we've observed:
 *    - "You defeated <NAME>!"             (win by KO)
 *    - "The battle has ended due to a forfeit."   (win by opponent forfeit)
 *
 *  The first-pass detection doesn't OCR the text — instead it looks for the
 *  persistent dark-overlay message box that hosts this text in the lower
 *  quadrant of the battle scene. A full OCR pass can be layered later to
 *  split "win-by-KO" vs "win-by-forfeit" in stats.
 *
 *  NOTE: this detector can false-positive on other mid-battle dialog lines
 *  that use the same text box (e.g. "X's Rough Skin", "sent out Kingambit!").
 *  The caller should sequence this AFTER the last action/move selection,
 *  not use it as a general-purpose in-battle detector.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_BattleEndDetector_H
#define PokemonAutomation_PokemonChampions_BattleEndDetector_H

#include "CommonFramework/ImageTools/ImageBoxes.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "CommonTools/VisualDetector.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{


//  Detects the **result screen** (WON!/LOST! split view) which *always*
//  follows the battle-end text. This is a more reliable signal than the
//  battle-end text itself because the colored result banner fills large
//  screen regions that are easy to detect.
class ResultScreenDetector : public StaticScreenDetector{
public:
    ResultScreenDetector();

    virtual void make_overlays(VideoOverlaySet& items) const override;
    virtual bool detect(const ImageViewRGB32& screen) override;

    bool won() const{ return m_won; }

private:
    //  Sampled from the yellow "WON!" glow region on the left half.
    ImageFloatBox m_left_won_glow;
    //  Sampled from the "LOST..." gray region on the right half.
    ImageFloatBox m_right_lost_glow;
    //  Sampled from the red "LOST..." banner region when loser is on the left.
    ImageFloatBox m_left_lost_banner;
    //  Sampled from the right side "WON!" region when winner is the opponent.
    ImageFloatBox m_right_won_glow;

    bool m_won = false;
};


class ResultScreenWatcher : public DetectorToFinder<ResultScreenDetector>{
public:
    ResultScreenWatcher(std::chrono::milliseconds hold_duration = std::chrono::milliseconds(500))
        : DetectorToFinder("ResultScreenWatcher", hold_duration)
    {}
};


}
}
}
#endif
