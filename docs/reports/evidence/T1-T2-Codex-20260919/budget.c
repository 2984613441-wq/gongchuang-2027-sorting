#include "ec_step_profile.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static double leg(unsigned n, unsigned v, unsigned a) {
    ec_step_profile_t p;
    unsigned i;
    unsigned long long ticks = 0;
    if (!n) return 0;
    assert(ec_step_profile_plan(&p,n,200,v,200,a,a));
    assert(p.accel_steps+p.cruise_steps+p.decel_steps==n);
    for(i=0;i<n;i++) ticks += ec_step_profile_reload_at(&p,i,100000)+1;
    return (double)ticks/100000;
}
static double motion(unsigned v,unsigned a) {
    const unsigned n[]={4256,5632,4944,3768,9200,9400};
    double t=0; unsigned i;
    for(i=0;i<6;i++) t+=leg(n[i],v,a);
    return t;
}
int main(int argc, char **argv) {
    unsigned q,v,a,w,x,y;
    unsigned settle_ms=argc>1?(unsigned)strtoul(argv[1],NULL,10):200;
    double servo=3.0*settle_ms/1000.0;
    double base=motion(5000,10000)+2.6;
    double overhead=14.063-base; /* observed ACK segment 1.163 + baseline residual */
    const unsigned vs[]={5000,6000,6250,7000};
    printf("scenario_servo_settle_ms=%u; calibration remains original WAIT2000/settle200 observation\n",settle_ms);
    printf("baseline_done=%.6f ack_segment=1.163 residual=%.6f overhead=%.6f\n",base,overhead-1.163,overhead);
    for(q=0;q<4;q++) {
        ec_step_profile_t p;
        assert(ec_step_profile_plan(&p,20000,200,vs[q],200,10000,10000));
        unsigned arr=ec_step_profile_reload_at(&p,p.accel_steps,100000);
        printf("quant requested=%u ARR=%u ticks=%u effective=%.6f done=%.6f\n",vs[q],arr,arr+1,100000.0/(arr+1),motion(vs[q],10000)+2.6);
    }
    puts("v,a,wait,done,round,margin,save,sum_limit_15,sum_limit_14,far_round");
    for(v=5000;v<=6250;v+=1250) for(a=10000;a<=15000;a+=5000) {
        double xt[901],yt[926],worst[1826]={0};
        double fixed=leg(4256,v,a)+leg(5632,v,a)+servo+overhead;
        for(x=0;x<=900;x++) xt[x]=leg((x+418)*8,v,a)+leg((x+950)*8,v,a);
        for(y=0;y<=925;y++) yt[y]=leg((y+271)*8,v,a)+leg((y+975)*8,v,a);
        for(x=0;x<=900;x++) for(y=0;y<=925;y++) {
            double t=fixed+xt[x]+yt[y];
            if(t>worst[x+y]) worst[x+y]=t;
        }
        for(w=2000;w>=200;w-=1800) {
            int lim15=-1,lim14=-1; double maxsofar=0;
            for(q=0;q<=1825;q++) {
                if(worst[q]>maxsofar) maxsofar=worst[q];
                if(maxsofar+w/1000.0<15) lim15=(int)q;
                if(maxsofar+w/1000.0<=14) lim14=(int)q;
            }
            double done=motion(v,a)+servo+w/1000.0,round=done+overhead;
            printf("%u,%u,%u,%.6f,%.6f,%.6f,%.6f,%.1f,%.1f,%.6f\n",v,a,w,done,round,15-round,14.063-round,lim15/10.0,lim14/10.0,worst[1825]+w/1000.0);
            if(w==200) break;
        }
    }
    return 0;
}
