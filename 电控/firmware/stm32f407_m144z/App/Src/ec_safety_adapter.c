#include "ec_safety_adapter.h"

void ec_safety_apply(ec_action_t actions)
{
    if ((actions & EC_ACTION_STOP_ALL) != 0U) {
        ec_safety_port_stop_all();
    }
    if ((actions & EC_ACTION_DISABLE_DRIVERS) != 0U) {
        ec_safety_port_disable_drivers();
    }
    if ((actions & EC_ACTION_INHIBIT_POWER) != 0U) {
        ec_safety_port_inhibit_power();
    }
}
