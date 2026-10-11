/* Evidence-only adapter: existing app tests replace the axis driver, but
 * currently omit its new diagnostic accessor. Never link into firmware. */
#include "ec_axis_driver.h"
const ec_axis_driver_diag_t *ec_axis_driver_diag(void) {
    static const ec_axis_driver_diag_t empty = {0};
    return &empty;
}
