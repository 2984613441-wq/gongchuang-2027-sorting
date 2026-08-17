#ifndef EC_SAFETY_ADAPTER_H
#define EC_SAFETY_ADAPTER_H

#include "ec_state_machine.h"

void ec_safety_apply(ec_action_t actions);
void ec_safety_port_stop_all(void);
void ec_safety_port_disable_drivers(void);
void ec_safety_port_inhibit_power(void);

#endif
