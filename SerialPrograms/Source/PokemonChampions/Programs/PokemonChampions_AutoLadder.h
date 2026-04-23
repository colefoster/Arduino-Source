/*  Pokemon Champions Auto Ladder
 *
 *  From: https://github.com/PokemonAutomation/
 *
 */

#ifndef PokemonAutomation_PokemonChampions_AutoLadder_H
#define PokemonAutomation_PokemonChampions_AutoLadder_H

#include <memory>
#include "Common/Cpp/Options/SimpleIntegerOption.h"
#include "Common/Cpp/Options/EnumDropdownOption.h"
#include "Common/Cpp/Options/BooleanCheckBoxOption.h"
#include "Common/Cpp/Options/StringOption.h"
#include "Common/Cpp/Options/TextEditOption.h"
#include "Common/Cpp/Options/ButtonOption.h"
#include "CommonFramework/Notifications/EventNotificationsTable.h"
#include "NintendoSwitch/NintendoSwitch_SingleSwitchProgram.h"
#include "NintendoSwitch/Options/NintendoSwitch_GoHomeWhenDoneOption.h"
#include "PokemonChampions_BattleStateTracker.h"
#include "PokemonChampions_InferenceClient.h"

namespace PokemonAutomation{

template <typename Type> class ControllerContext;

namespace NintendoSwitch{

class ProController;
using ProControllerContext = ControllerContext<ProController>;

namespace PokemonChampions{


//  Move-selection strategy for the battle loop. Type-aware logic will be
//  added once the battle-menu OCR layer is in.
enum class MoveStrategy{
    AlwaysFirstMove,
    RoundRobin,
    RandomMove,
    MashA,
    AI,             //  Query the inference server for move decisions.
};

//  Team-selection strategy for bring-6-pick-3. Pokemon Champions is a
//  Singles format where you bring 6 and pick 3 at the start of each match.
enum class TeamStrategy{
    FirstThree,     //  Always pick slots 1, 2, 3
    LastThree,      //  Always pick slots 4, 5, 6
    RandomThree,    //  Pick 3 random distinct slots each match
};


class AutoLadder_Descriptor : public SingleSwitchProgramDescriptor{
public:
    AutoLadder_Descriptor();

    class Stats;
    virtual std::unique_ptr<StatsTracker> make_stats() const override;
};


class AutoLadder : public SingleSwitchProgramInstance{
public:
    AutoLadder();

    virtual void program(SingleSwitchProgramEnvironment& env, ProControllerContext& context) override;

private:
    //  One full match: queue -> team select -> preparing -> battle loop -> post-match.
    //  Returns true if we completed the match cleanly.
    bool run_one_match(SingleSwitchProgramEnvironment& env, ProControllerContext& context);

    //  Starting from the Battle Mode Select screen (cursor assumed parked on
    //  Ranked Battles), press A to enter matchmaking and wait for the team
    //  select screen to appear.
    void enter_matchmaking(SingleSwitchProgramEnvironment& env, ProControllerContext& context);

    //  From the team select screen, pick 3 mons per TEAM_STRATEGY and confirm
    //  the "Done" button.
    void do_team_select(SingleSwitchProgramEnvironment& env, ProControllerContext& context);

    //  Wait for the "Preparing for Battle" lock-in screen, then for the
    //  action menu to appear (battle begins).
    void wait_for_battle_start(SingleSwitchProgramEnvironment& env, ProControllerContext& context);

    //  Main battle loop: repeatedly pick a move on each turn until the match
    //  resolves. Returns whether the player won.
    bool run_battle_loop(SingleSwitchProgramEnvironment& env, ProControllerContext& context);

    //  From the action menu, press A on FIGHT, then navigate to and confirm
    //  the chosen move slot based on MOVE_STRATEGY.
    void select_next_move(SingleSwitchProgramEnvironment& env, ProControllerContext& context);

    //  AI move selection: OCR the screen, query inference server, execute action.
    void select_move_ai(SingleSwitchProgramEnvironment& env, ProControllerContext& context);

    //  Execute a model action index (0-13) as button presses.
    void execute_action(SingleSwitchProgramEnvironment& env, ProControllerContext& context, uint8_t action_idx);

    //  At the post-match screen, confirm "Continue Battling" (or Quit if we
    //  want to stop). Returns true if we're re-queueing, false if quitting.
    bool handle_post_match(SingleSwitchProgramEnvironment& env, ProControllerContext& context);

    //  Helper: pick the 3 indices (0-5) to send into battle for this match
    //  based on TEAM_STRATEGY.
    void compute_team_picks(uint8_t picks[3]);

    //  AI: grab a screenshot and attempt to read the full team from the
    //  "View Details -> Moves & More" screen. Populates m_state_tracker on
    //  success. Returns the number of Pokemon loaded (0-6), or -1 if the
    //  Moves & More screen was not detected.
    int scan_team_from_game(SingleSwitchProgramEnvironment& env);

    //  AI: poll for the pre-battle Team Preview screen for up to wait_seconds.
    //  On detection, OCRs own items (filling the gap left by Moves & More)
    //  and sprite-matches opponent species into m_state_tracker.
    //  Returns number of opponent species identified (0-6), or -1 on timeout.
    int scan_team_preview(
        SingleSwitchProgramEnvironment& env,
        ProControllerContext& context,
        int wait_seconds = 20
    );

private:
    DeferredStopButtonOption STOP_AFTER_CURRENT;
    SimpleIntegerOption<uint32_t> NUM_MATCHES;
    EnumDropdownOption<TeamStrategy> TEAM_STRATEGY;
    EnumDropdownOption<MoveStrategy> MOVE_STRATEGY;
    BooleanCheckBoxOption ALLOW_MEGA;
    GoHomeWhenDoneOption GO_HOME_WHEN_DONE;

    //  AI-specific options (only used when MOVE_STRATEGY == AI).
    StringOption AI_SERVER_URL;
    BooleanCheckBoxOption AI_SCAN_TEAM_FROM_GAME;
    TextEditOption AI_TEAM_PASTE;

    EventNotificationOption NOTIFICATION_STATUS_UPDATE;
    EventNotificationOption NOTIFICATION_MATCH_FINISHED;
    EventNotificationsOption NOTIFICATIONS;

    //  Per-match state.
    uint8_t m_rr_cursor = 0;

    //  AI state (created when strategy is AI).
    BattleStateTracker m_state_tracker;
    std::unique_ptr<InferenceClient> m_inference_client;
};



}
}
}
#endif
