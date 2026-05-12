/*  Pokemon Champions Detector Test
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Dev tool: runs all detectors in a loop, draws overlays on the video feed,
 *  and logs which detectors fire. Never presses any buttons — safe to run
 *  while navigating the game manually.
 *
 */

#ifndef PokemonAutomation_PokemonChampions_DetectorTest_H
#define PokemonAutomation_PokemonChampions_DetectorTest_H

#include "Common/Cpp/Options/BooleanCheckBoxOption.h"
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "NintendoSwitch/NintendoSwitch_SingleSwitchProgram.h"

namespace PokemonAutomation{

template <typename Type> class ControllerContext;

namespace NintendoSwitch{

class ProController;
using ProControllerContext = ControllerContext<ProController>;

namespace PokemonChampions{


class DetectorTest_Descriptor : public SingleSwitchProgramDescriptor{
public:
    DetectorTest_Descriptor();
};


class DetectorTest : public SingleSwitchProgramInstance{
public:
    DetectorTest();

    virtual void program(SingleSwitchProgramEnvironment& env, ProControllerContext& context) override;

private:
    BooleanCheckBoxOption AUTO_SCREENSHOT;
    SimpleIntegerOption<uint16_t> SCREENSHOT_INTERVAL_MS;
    BooleanCheckBoxOption SAVE_LABELED_TESTS;
};


}
}
}
#endif
