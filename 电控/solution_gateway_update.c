/* BU-FIX 2026-09-18: Add to ec_protocol_gateway.c
 * Insert after ec_gateway_init() function */

void ec_gateway_update_safety_state(ec_gateway_t *g,
                                    bool danger_area_clear,
                                    bool estop_released)
{
    if (g == NULL) {
        return;
    }
    g->last_danger_area_clear = danger_area_clear;
    g->last_estop_released = estop_released;
}

/* Add declaration to ec_protocol_gateway.h public API section:
 *
 * void ec_gateway_update_safety_state(ec_gateway_t *g,
 *                                     bool danger_area_clear,
 *                                     bool estop_released);
 */
