#include "ec_diag.h"

int main(void)
{
    ec_diag_init();
    ec_diag_on_rx_byte((uint8_t)'X');
    ec_diag_process_line("STEP X");
    ec_diag_poll();
    ec_diag_tick(UINT32_C(1000));
    return 0;
}
