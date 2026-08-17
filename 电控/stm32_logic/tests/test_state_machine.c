#include "ec_state_machine.h"
#include "test_support.h"

static ec_event_t event_of(ec_event_type_t type)
{
    ec_event_t event = {0};
    event.type = type;
    return event;
}

static bool has_actions(ec_action_t actions, ec_action_t required)
{
    return (actions & required) == required;
}

static ec_transition_t consume_in_state(ec_state_machine_t *machine,
                                        ec_dedup_t *dedup,
                                        ec_state_t state,
                                        ec_event_type_t event_type)
{
    ec_event_t event = event_of(event_type);

    ec_sm_init(machine, dedup);
    machine->state = state;
    machine->fault_reason = EC_FAULT_NONE;
    machine->actions = EC_ACTION_NONE;
    return ec_sm_consume(machine, &event);
}

void test_state_machine(void)
{
    ec_dedup_entry_t storage[2];
    ec_dedup_t dedup;
    ec_state_machine_t machine;
    ec_event_t event;
    ec_transition_t transition;

    (void)ec_dedup_init(&dedup, storage, 2U);
    (void)ec_dedup_observe(&dedup, (ec_dedup_key_t){9U, 9U, 9U});

    TEST_CASE_BEGIN("C-SM-BOOT-001");
    ec_sm_init(&machine, &dedup);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, machine.state);
    EXPECT_EQ_U32(EC_FAULT_RESTART_CONTEXT_UNPROVEN, machine.fault_reason);
    EXPECT_TRUE(has_actions(machine.actions, EC_ACTION_SAFE_LOCK));

    TEST_CASE_BEGIN("C-SM-BOOT-002");
    event = event_of(EC_EVENT_ITEM_TASK_ACCEPTED);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));
    event = event_of(EC_EVENT_MOTION_DONE);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    event = event_of(EC_EVENT_DISPLAY_ACK_VALIDATED);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);

    TEST_CASE_BEGIN("C-SM-RESET-001");
    event = event_of(EC_EVENT_MANUAL_NEW_ROUND_CONFIRMED);
    event.round_id = 1U;
    event.round_closed = true;
    event.danger_area_clear = false;
    event.estop_released = true;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_EQ_U32(1U, dedup.used);

    TEST_CASE_BEGIN("C-SM-RESET-002");
    event.danger_area_clear = true;
    event.round_id = machine.round_id;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_EQ_U32(1U, dedup.used);

    TEST_CASE_BEGIN("C-SM-RESET-003");
    event.round_id = machine.round_id + 1U;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_POWER_ON, transition.state);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_BEGIN_POST));
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));
    EXPECT_EQ_U32(0U, dedup.used);

    TEST_CASE_BEGIN("C-SM-RESET-004");
    event = event_of(EC_EVENT_POST_PASSED);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_HOMING, transition.state);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_BEGIN_HOMING));
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));
    event = event_of(EC_EVENT_ITEM_TASK_ACCEPTED);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_HOMING, transition.state);

    event = event_of(EC_EVENT_HOMING_PASSED);
    (void)ec_sm_consume(&machine, &event);
    event = event_of(EC_EVENT_BARRIER_AVOIDANCE_VERIFIED);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, transition.state);

    TEST_CASE_BEGIN("C-SM-GATE-001");
    event = event_of(EC_EVENT_ITEM_TASK_ACCEPTED);
    event.identity = (ec_dedup_key_t){1U, 2U, 3U};
    event.round_id = machine.round_id;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, transition.state);
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));

    TEST_CASE_BEGIN("C-SM-ONCE-001");
    transition = ec_sm_consume(&machine, &event);
    EXPECT_TRUE(has_actions(transition.actions,
                            EC_ACTION_RESEND_CACHED_RESPONSE));
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));

    TEST_CASE_BEGIN("C-SM-GATE-002");
    event = event_of(EC_EVENT_TASK_SAFETY_VALIDATED);
    event.identity = machine.current_item;
    event.round_id = machine.round_id;
    event.content_validated = true;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_EXECUTING, transition.state);
    EXPECT_EQ_U32(EC_ACTION_START_MOTION, transition.actions);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));

    TEST_CASE_BEGIN("C-SM-EVENT-001");
    event = event_of(EC_EVENT_MOTION_DONE);
    event.identity = machine.current_item;
    event.round_id = machine.round_id;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_ITEM_RESULT, transition.state);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_EMIT_MOTION_DONE));

    TEST_CASE_BEGIN("C-SM-EVENT-002");
    event = event_of(EC_EVENT_ITEM_RESULT_RECORDED);
    event.identity = machine.current_item;
    event.round_id = machine.round_id;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, transition.state);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_EMIT_ITEM_RESULT));

    TEST_CASE_BEGIN("C-SM-ACK-001");
    event = event_of(EC_EVENT_DISPLAY_ACK_VALIDATED);
    event.identity = (ec_dedup_key_t){1U, 99U, 3U};
    event.round_id = machine.round_id;
    event.content_validated = true;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, transition.state);
    event.identity = machine.current_item;
    event.content_validated = false;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, transition.state);

    TEST_CASE_BEGIN("C-SM-ACK-002");
    event.content_validated = true;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_PREPARE_BARRIER, transition.state);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_PREPARE_BARRIER));

    TEST_CASE_BEGIN("C-SM-ACK-003");
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_PREPARE_BARRIER, transition.state);
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));
    event = event_of(EC_EVENT_BARRIER_AVOIDANCE_VERIFIED);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, transition.state);

    TEST_CASE_BEGIN("C-SM-ONCE-002");
    event = event_of(EC_EVENT_ITEM_TASK_ACCEPTED);
    event.identity = (ec_dedup_key_t){1U, 2U, 4U};
    event.round_id = machine.round_id;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));

    TEST_CASE_BEGIN("C-SM-CAP-001");
    ec_sm_init(&machine, &dedup);
    machine.state = EC_STATE_WAIT_TASK;
    machine.fault_reason = EC_FAULT_NONE;
    (void)ec_dedup_init(&dedup, storage, 2U);
    (void)ec_dedup_observe(&dedup, (ec_dedup_key_t){7U, 1U, 1U});
    (void)ec_dedup_observe(&dedup, (ec_dedup_key_t){8U, 1U, 1U});
    event = event_of(EC_EVENT_ITEM_TASK_ACCEPTED);
    event.identity = (ec_dedup_key_t){9U, 1U, 1U};
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_EQ_U32(EC_FAULT_DEDUP_CAPACITY_EXHAUSTED,
                  transition.fault_reason);
    EXPECT_EQ_U32(2U, dedup.used);

    TEST_CASE_BEGIN("C-SM-REVIEW-INVALID-DEDUP-001");
    ec_sm_init(&machine, NULL);
    machine.state = EC_STATE_WAIT_TASK;
    machine.fault_reason = EC_FAULT_NONE;
    event = event_of(EC_EVENT_ITEM_TASK_ACCEPTED);
    event.identity = (ec_dedup_key_t){40U, 1U, 1U};
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_EQ_U32(EC_FAULT_DEDUP_CAPACITY_EXHAUSTED,
                  transition.fault_reason);
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));

    TEST_CASE_BEGIN("C-SM-REVIEW-OLD-ROUND-001");
    (void)ec_dedup_init(&dedup, storage, 2U);
    ec_sm_init(&machine, &dedup);
    machine.state = EC_STATE_WAIT_TASK;
    machine.fault_reason = EC_FAULT_NONE;
    machine.round_id = 5U;
    event = event_of(EC_EVENT_ITEM_TASK_ACCEPTED);
    event.identity = (ec_dedup_key_t){20U, 1U, 1U};
    event.round_id = 4U;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_TASK, transition.state);
    EXPECT_EQ_U32(0U, dedup.used);
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));

    TEST_CASE_BEGIN("C-SM-REVIEW-SAFETY-CONTEXT-001");
    machine.state = EC_STATE_VALIDATE_TASK;
    machine.current_item = (ec_dedup_key_t){20U, 1U, 1U};
    machine.has_current_item = true;
    event = event_of(EC_EVENT_TASK_SAFETY_VALIDATED);
    event.identity = machine.current_item;
    event.round_id = 4U;
    event.content_validated = true;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, transition.state);
    event.round_id = machine.round_id;
    event.identity = (ec_dedup_key_t){21U, 1U, 1U};
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, transition.state);
    event.identity = machine.current_item;
    event.content_validated = false;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_VALIDATE_TASK, transition.state);
    event.content_validated = true;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_EXECUTING, transition.state);
    EXPECT_EQ_U32(EC_ACTION_START_MOTION, transition.actions);

    TEST_CASE_BEGIN("C-SM-REVIEW-PROGRESS-CONTEXT-001");
    event = event_of(EC_EVENT_MOTION_DONE);
    event.identity = (ec_dedup_key_t){99U, 1U, 1U};
    event.round_id = machine.round_id;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_EXECUTING, transition.state);
    event.identity = machine.current_item;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_ITEM_RESULT, transition.state);
    event = event_of(EC_EVENT_ITEM_RESULT_RECORDED);
    event.identity = machine.current_item;
    event.round_id = machine.round_id + 1U;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_ITEM_RESULT, transition.state);
    event.round_id = machine.round_id;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_WAIT_DISPLAY_ACK, transition.state);

    TEST_CASE_BEGIN("C-SM-REVIEW-NONWAIT-DEDUP-001");
    (void)ec_dedup_init(&dedup, storage, 2U);
    (void)ec_dedup_observe(&dedup, (ec_dedup_key_t){30U, 1U, 1U});
    (void)ec_dedup_observe(&dedup, (ec_dedup_key_t){31U, 1U, 1U});
    machine.state = EC_STATE_EXECUTING;
    machine.fault_reason = EC_FAULT_NONE;
    event = event_of(EC_EVENT_ITEM_TASK_ACCEPTED);
    event.identity = (ec_dedup_key_t){32U, 1U, 1U};
    event.round_id = machine.round_id;
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_EXECUTING, transition.state);
    EXPECT_EQ_U32(2U, dedup.used);
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));

    TEST_CASE_BEGIN("C-SM-ESTOP-001");
    for (ec_state_t state = EC_STATE_POWER_ON; state <= EC_STATE_COMPLETE;
         state = (ec_state_t)(state + 1)) {
        transition = consume_in_state(&machine, &dedup, state,
                                      EC_EVENT_EMERGENCY_STOP);
        EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
        EXPECT_EQ_U32(EC_FAULT_EMERGENCY_STOP, transition.fault_reason);
        EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_SAFE_LOCK));
    }

    TEST_CASE_BEGIN("C-SM-POWER-001");
    transition = consume_in_state(&machine, &dedup, EC_STATE_EXECUTING,
                                  EC_EVENT_POWER_PERMISSION_LOST);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_EQ_U32(EC_FAULT_POWER_PERMISSION_LOST, transition.fault_reason);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_SAFE_LOCK));

    TEST_CASE_BEGIN("C-SM-TIME-001");
    transition = consume_in_state(&machine, &dedup, EC_STATE_WAIT_DISPLAY_ACK,
                                  EC_EVENT_DEADLINE_EXPIRED);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_EQ_U32(EC_FAULT_DEADLINE_EXPIRED, transition.fault_reason);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_SAFE_LOCK));

    TEST_CASE_BEGIN("C-SM-LOCK-001");
    ec_sm_init(&machine, &dedup);
    event = event_of(EC_EVENT_EMERGENCY_STOP);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_SAFE_LOCK));
    event = event_of(EC_EVENT_TASK_SAFETY_VALIDATED);
    transition = ec_sm_consume(&machine, &event);
    EXPECT_EQ_U32(EC_STATE_FAULT_LOCK, transition.state);
    EXPECT_TRUE(has_actions(transition.actions, EC_ACTION_SAFE_LOCK));
    EXPECT_FALSE(has_actions(transition.actions, EC_ACTION_START_MOTION));
}
