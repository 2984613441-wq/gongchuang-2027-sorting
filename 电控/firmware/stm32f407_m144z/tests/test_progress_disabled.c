#include "ec_app.h"
#include "test_support.h"

#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    /* The helper opens the same watchdog window used by the enabled target. */
    test_app_start_motion_at(1000U);

    test_set_tick(11000U);
    ec_app_progress_source_set_enabled(true);
    ec_app_note_observable_progress(1U);

    TEST_ASSERT(ec_app_test_watchdog_active());
    TEST_ASSERT(ec_app_test_last_observable_ms() == 1000U);
    puts("COMPILE-TIME PROGRESS SOURCE DISABLED: HARD NO-OP");
    return EXIT_SUCCESS;
}
