/*  Pokemon Champions Live Detector Trace
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Passive video-only watcher. Cole plays the game manually with a real
 *  controller; this program watches the capture card, runs the same
 *  detector/reader pipeline AutoLadder uses, assembles the engine view
 *  via BattleStateTracker::to_predict_json(), and POSTs state-change
 *  events to mac_dev_runner so the dashboard can render them live.
 *
 *  Phase 1 tracer bullet: loop at 4 Hz, run BattleHUDReader every tick,
 *  POST the engine view whenever it changes vs. the previous tick.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_LiveDetectorTrace_H
#define PokemonAutomation_PokemonChampions_LiveDetectorTrace_H

#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/StringOption.h"
#include "NintendoSwitch/NintendoSwitch_SingleSwitchProgram.h"
#include "PokemonChampions_BattleStateTracker.h"

namespace PokemonAutomation{

template <typename Type> class ControllerContext;

namespace NintendoSwitch{

class ProController;
using ProControllerContext = ControllerContext<ProController>;

namespace PokemonChampions{


class LiveDetectorTrace_Descriptor : public SingleSwitchProgramDescriptor{
public:
    LiveDetectorTrace_Descriptor();
};


class LiveDetectorTrace : public SingleSwitchProgramInstance{
public:
    LiveDetectorTrace();

    virtual void program(SingleSwitchProgramEnvironment& env, ProControllerContext& context) override;

private:
    SimpleIntegerOption<uint32_t> POLL_PERIOD_MILLISECONDS;
    StringOption SINK_URL;

    BattleStateTracker m_state_tracker;
};


}
}
}
#endif
