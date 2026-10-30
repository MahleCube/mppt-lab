/* Lab-only per-instance adapter. Frozen firmware core is compiled unchanged. */
#include "c07_control.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API
#endif
typedef struct {
 c07_controller control;
 c07_config config;
 c07_mppt_job job;
 c07_mppt_result result;
 int busy;
} lab_instance;
API void *c07_lab_new(void){
 lab_instance *p=calloc(1,sizeof(*p));if(!p)return NULL;
 c07_config_defaults(&p->config);
 p->config.MPPT_METHOD=2;p->config.MPPT_STEP_MODE=2;
 p->config.CONTROL_PERIOD_US=1001;p->config.MPPT_PERIOD_US=20000;
 p->config.MPPT_SETTLE_US=5000;p->config.MPPT_WINDOW_US=5000;
 p->config.MPPT_STEP_GAIN_V=.5;
 return p;
}
API void c07_lab_free(void *h){free(h);}
API int c07_lab_config(void *h,const char *name,double value){
 lab_instance *p=h;if(!p||!name||!isfinite(value))return -1;
#define REAL_SET(n,v) if(strcmp(name,#n)==0){p->config.n=value;return 0;}
 C07_CONFIG_REAL_FIELDS(REAL_SET)
#undef REAL_SET
#define TIME_SET(n,v) if(strcmp(name,#n)==0){if(value<0||value>UINT32_MAX||floor(value)!=value)return -2;p->config.n=(uint32_t)value;return 0;}
 C07_CONFIG_TIME_FIELDS(TIME_SET)
#undef TIME_SET
 return -3;
}
API double c07_lab_get(void *h,const char *name){
 lab_instance *p=h;if(!p||!name)return NAN;
#define GET(n,v) if(strcmp(name,#n)==0)return p->config.n;
 C07_CONFIG_REAL_FIELDS(GET)
 C07_CONFIG_TIME_FIELDS(GET)
#undef GET
 return NAN;
}
API int c07_lab_start(void *h,double voc,double vbat,double duty,double target){
 lab_instance *p=h;if(!p)return C07_ERR_ARGUMENT;
 int rc=c07_init(&p->control,&p->config);if(rc)return rc;
 p->control.duty=duty;rc=c07_start_tracking(&p->control,voc,vbat);
 p->control.mppt.target=target;p->busy=0;return rc;
}
API int c07_lab_step(void *h,const double *v,int span,unsigned dt,int mppt_enabled,double target,double *out){
 lab_instance *p=h;if(!p)return C07_ERR_ARGUMENT;
 c07_controller *s=&p->control;
 c07_sample sample={v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],true,span};
 uint32_t period=s->cfg.MPPT_PERIOD_US,reacquire=s->cfg.MPPT_REACQUIRE_US;
 if(!mppt_enabled){
  /* Lab voltage-step experiment: hold an external target. PI state is not reset. */
  if(s->mppt.target!=target){c07_mppt_invalidate(s,true);s->mppt.target=target;s->mppt.elapsed_us=0;}
  s->cfg.MPPT_PERIOD_US=UINT32_MAX;s->cfg.MPPT_REACQUIRE_US=UINT32_MAX;
 }
 unsigned outer=s->outer_elapsed_us;
 c07_real_t duty=0;int rc=c07_step(s,&sample,dt,true,&duty);
 s->cfg.MPPT_PERIOD_US=period;s->cfg.MPPT_REACQUIRE_US=reacquire;
 out[0]=duty;out[1]=s->current_target;out[2]=s->pv_voltage;out[3]=s->current;out[4]=s->mppt.target;
 out[5]=s->pv_pi.integral;out[6]=s->current_pi.integral;out[7]=s->cv_pi.integral;
 out[8]=s->cv_ceiling;out[9]=s->limited;out[10]=s->limit_reason;out[11]=s->mppt.updates;
 out[12]=s->reacquisitions;out[13]=s->restart_feedforward_pending;out[14]=s->mppt.step_v;out[15]=rc;
 out[16]=s->mppt.moves;out[17]=s->mppt.holds;out[18]=s->mppt.last_signal;
 out[19]=s->mppt.last_mean_voltage;out[20]=s->mppt.last_mean_current;
 out[21]=s->async.published;out[22]=s->async.applied;out[23]=s->async.rejected;
 out[24]=s->async.expired;out[25]=s->async.pending;
 out[26]=s->current_pi.kp*(s->current_target-s->current);
 out[27]=s->mppt.last_mean_power;out[28]=(double)s->async.clock_us;
 out[29]=(outer+dt>=s->cfg.VOLTAGE_PERIOD_US);
 out[30]=fmin(s->cfg.DUTY_MAX,fmax(0.,sample.vout/fmax(sample.vin,1.)));
 out[31]=s->cfg.PV_KD_A_S_PER_V*s->pv_derivative;out[32]=s->pv_derivative;
 return rc;
}
API int c07_lab_begin(void *h){
 lab_instance *p=h;if(!p||p->busy)return 0;
 p->busy=c07_mppt_begin(&p->control,&p->job);return p->busy;
}
API int c07_lab_finish(void *h){
 lab_instance *p=h;if(!p||!p->busy)return 0;
 int valid=c07_mppt_compute(&p->control.cfg,&p->job,&p->result);
 c07_mppt_publish(&p->control,&p->result);p->busy=0;return valid?1:-1;
}
