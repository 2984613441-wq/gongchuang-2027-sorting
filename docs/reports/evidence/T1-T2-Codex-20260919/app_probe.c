#include "test_app.c"
#include <stdio.h>
static void poll_at(uint32_t t) { test_set_tick(t); ec_app_poll(t); }
static void show(const char *label) {
    printf("%s state=%u tx=%u ACK=%u barrier=%u moving=%u watchdog=%u\n",label,
        (unsigned)ec_app_state(),tx_record_count,
        tx_count(EC_CMD_ACK,EC_ACK_REASON_ACCEPTED,1),
        tx_count(EC_CMD_BARRIER_READY,TX_ANY,TX_ANY),
        fake_axis_state==EC_AXIS_STATE_MOVING,ec_app_test_watchdog_active());
}
int main(void) {
    fake_active_inputs=0; test_set_tick(0); ec_app_init(); tx_records_reset();
    show("reset"); poll_at(9263); show("idle9263");
    poll_at(25637); show("idle25637");
    TEST_ASSERT(ec_app_state()==EC_STATE_FAULT_LOCK);
    feed_item_task(); show("first_ITEM");
    TEST_ASSERT(tx_record_count==0);
    poll_at(25687); poll_at(26187); show("startup_done");
    TEST_ASSERT(ec_app_state()==EC_STATE_WAIT_TASK);
    feed_item_task(); show("resend_after_barrier");
    TEST_ASSERT(tx_count(EC_CMD_ACK,EC_ACK_REASON_ACCEPTED,1)==1);
    poll_at(31188); feed_item_task(); show("retry_5s");
    poll_at(36189); feed_item_task(); show("retry_10s");
    TEST_ASSERT(tx_count(EC_CMD_ACK,EC_ACK_REASON_ACCEPTED,1)==3);
    TEST_ASSERT(tx_records[1].frame_seq==tx_records[2].frame_seq);
    TEST_ASSERT(tx_records[2].frame_seq==tx_records[3].frame_seq);
    TEST_ASSERT(ec_app_state()==EC_STATE_EXECUTING);
    puts("APP_PROBE PASS; board/axis are host doubles");
    return 0;
}
