#include <stdio.h>
#include "ec_step_profile.h"
int main(void) {
    const unsigned rates[] = {5000, 7500, 10000};
    const unsigned lengths[] = {2496, 4992, 6000, 7192, 8000};
    for (unsigned a=0; a<3; ++a) for (unsigned n=0; n<5; ++n) {
        ec_step_profile_t p;
        if (!ec_step_profile_plan(&p,lengths[n],200,5000,200,rates[a],rates[a])) return 1;
        double seconds=0;
        for (unsigned k=0;k<p.total_steps;++k)
            seconds += (ec_step_profile_reload_at(&p,k,100000)+1)/100000.0;
        printf("a=%u N=%u peak=%u accel=%u cruise=%u decel=%u timer_s=%.5f\n",
          rates[a],lengths[n],p.cruise_hz,p.accel_steps,p.cruise_steps,p.decel_steps,seconds);
    }
    return 0;
}
