/*  Pokemon Champions Detector Test
 *
 *  From: https://github.com/PokemonAutomation/
 *
 *  Runs all PokemonChampions detectors in a loop, drawing overlay boxes and
 *  logging which detectors fire on each frame. Infers a "current screen"
 *  label from the combination of detectors that fire.
 *
 *  Does NOT send any controller input.
 *
 */

#include "CommonFramework/VideoPipeline/VideoFeed.h"
#include "CommonFramework/VideoPipeline/VideoOverlayScopes.h"
#include "Pokemon/Pokemon_Strings.h"

#include "PokemonChampions/Inference/PokemonChampions_ActionMenuDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_MoveSelectDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PreparingForBattleDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_BattleEndDetector.h"
#include "PokemonChampions/Inference/PokemonChampions_PostMatchDetector.h"
#include "PokemonChampions_DetectorTest.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonChampions{

using namespace Pokemon;


DetectorTest_Descriptor::DetectorTest_Descriptor()
    : SingleSwitchProgramDescriptor(
        "PokemonChampions:DetectorTest",
        STRING_POKEMON + " Champions", "Detector Test",
        "Programs/PokemonChampions/DetectorTest.html",
        "Dev tool: visualise all detector overlays and log which ones fire. "
        "Does NOT press any buttons.",
        ProgramControllerClass::StandardController_NoRestrictions,
        FeedbackType::REQUIRED,
        AllowCommandsWhenRunning::DISABLE_COMMANDS
    )
{}


DetectorTest::DetectorTest(){}


void DetectorTest::program(SingleSwitchProgramEnvironment& env, ProControllerContext& context){
    //  Create all detectors.
    ActionMenuDetector       action_menu;
    MoveSelectDetector       move_select;
    PreparingForBattleDetector preparing;
    ResultScreenDetector     result_screen;
    PostMatchScreenDetector  post_match;

    //  Register overlays so boxes appear on the video feed.
    VideoOverlaySet overlay_set(env.console.overlay());
    action_menu.make_overlays(overlay_set);
    move_select.make_overlays(overlay_set);
    preparing.make_overlays(overlay_set);
    result_screen.make_overlays(overlay_set);
    post_match.make_overlays(overlay_set);

    env.console.log("Detector Test running. Navigate the game - watch overlays + log.");
    env.console.log("Press Stop to end.");
    env.console.log("");
    env.console.log("Screen labels:");
    env.console.log("  ACTION_MENU  = FIGHT/POKEMON buttons visible (start of turn)");
    env.console.log("  MOVE_SELECT  = 4-move panel visible (after pressing FIGHT)");
    env.console.log("  PREPARING    = Both teams shown, Standing By pills visible");
    env.console.log("  RESULT       = WON!/LOST! split screen");
    env.console.log("  POST_MATCH   = Quit/Edit/Continue buttons");
    env.console.log("  UNKNOWN      = No detector matched this frame");
    env.console.log("");

    std::string last_screen;

    //  Poll loop.
    while (true){
        context.wait_for(std::chrono::milliseconds(500));

        VideoSnapshot snapshot = env.console.video().snapshot();
        if (!snapshot){
            continue;
        }
        const ImageViewRGB32& frame = snapshot;

        //  Run all detectors.
        bool d_action     = action_menu.detect(frame);
        bool d_move       = move_select.detect(frame);
        bool d_preparing  = preparing.detect(frame);
        bool d_result     = result_screen.detect(frame);
        bool d_post       = post_match.detect(frame);

        //  Determine screen label from priority order.
        //  Priority: specific screens first, generic last.
        std::string screen;
        std::string detail;

        if (d_post){
            screen = "POST_MATCH";
            switch (post_match.cursored()){
            case PostMatchButton::QUIT_BATTLING:     detail = "cursor=Quit"; break;
            case PostMatchButton::EDIT_TEAM:         detail = "cursor=Edit"; break;
            case PostMatchButton::CONTINUE_BATTLING: detail = "cursor=Continue"; break;
            }
        }else if (d_result){
            screen = "RESULT";
            detail = result_screen.won() ? "WON" : "LOST";
        }else if (d_preparing){
            screen = "PREPARING";
            detail = "both Standing By pills detected";
        }else if (d_move){
            screen = "MOVE_SELECT";
            detail = "cursor=slot" + std::to_string(move_select.cursor_slot());
        }else if (d_action){
            screen = "ACTION_MENU";
            detail = (action_menu.cursored() == ActionMenuButton::FIGHT)
                ? "cursor=FIGHT" : "cursor=POKEMON";
        }else{
            screen = "UNKNOWN";
            detail = "no detector matched";
        }

        //  Only log when the screen changes (avoid flooding).
        std::string full_label = screen + " (" + detail + ")";
        if (full_label != last_screen){
            Color color = (screen == "UNKNOWN") ? COLOR_RED : COLOR_GREEN;
            env.console.log("[Screen] " + full_label, color);
            last_screen = full_label;
        }
    }
}


}
}
}
