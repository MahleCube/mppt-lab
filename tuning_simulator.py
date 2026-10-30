"""Private averaged auxiliary model for tuning, not a replacement PWM solver.

Uses the unchanged controller and the experiments event scheduler. Only the
power stage is averaged. Stiff SDIRK integration resolves physical states;
controller/ADC/background events are never accelerated or skipped.
"""
from __future__ import annotations
import math
import numpy as np
from numba import njit, types
from numba.typed import Dict
import plant


@njit(cache=True)
def _rhs(t,y,p,duty):
    a=np.empty_like(y);b=np.empty_like(y)
    plant._rhs(t,y,p,True,True,a)
    plant._rhs(t,y,p,False,True,b)
    return duty*a+(1-duty)*b


@njit(cache=True)
def _jacobian(t,y,p,duty):
    n=len(y);a=np.zeros((n,n))
    # Energy accumulators never feed back. Avoid spurious finite-difference
    # columns and preserve their independent physical integral equations.
    for j in range(n):
        if 4<=j<=6:continue
        h=max(1.,abs(y[j]))*1e-6
        yp=y.copy();ym=y.copy();yp[j]+=h;ym[j]-=h
        a[:,j]=(_rhs(t,yp,p,duty)-_rhs(t,ym,p,duty))/(2*h)
    return a


@njit(cache=True)
def _sdirk(t,y,h,p,duty,inverse):
    """Two-stage L-stable SDIRK2 with shared modified-Newton Jacobian."""
    gamma=1-1/math.sqrt(2.)
    stage=y.copy()
    for _ in range(7):
        residual=stage-y-gamma*h*_rhs(t+gamma*h,stage,p,duty)
        delta=inverse@(-residual);stage+=delta
        if np.max(np.abs(delta)/(1+np.abs(stage)))<1e-10:break
    k1=_rhs(t+gamma*h,stage,p,duty)
    base=y+(1-gamma)*h*k1
    stage=base+gamma*h*k1
    for _ in range(7):
        residual=stage-base-gamma*h*_rhs(t+h,stage,p,duty)
        delta=inverse@(-residual);stage+=delta
        if np.max(np.abs(delta)/(1+np.abs(stage)))<1e-10:break
    residual=stage-base-gamma*h*_rhs(t+h,stage,p,duty)
    return stage,np.max(np.abs(residual)/(1+np.abs(stage)))<1e-8


@njit(cache=True)
def _inverse(h,jac,cache):
    # Only the modified-Newton preconditioner is cached. The residual still
    # uses the exact h/RHS, and must converge before an integration step passes.
    key=int(round(h*1e15))
    if key not in cache:
        if len(cache)>256:cache.clear()
        cache[key]=np.ascontiguousarray(np.linalg.inv(np.eye(len(jac))-(1-1/math.sqrt(2.))*h*jac))
    return cache[key]


@njit(cache=True)
def _integrate(t,end,y,p,duty,rtol,max_step,jac,cache):
    n=len(y);capacity=64;times=np.empty(capacity);states=np.empty((capacity,n))
    times[0]=t;states[0]=y;count=1;attempts=0
    h=min(max_step,end-t)
    while t<end-1e-14 and attempts<100000:
        h=min(h,end-t);attempts+=1
        inv_full=_inverse(h,jac,cache)
        inv_half=_inverse(h*.5,jac,cache)
        whole,ok1=_sdirk(t,y,h,p,duty,inv_full)
        half,ok2=_sdirk(t,y,h*.5,p,duty,inv_half)
        fine,ok3=_sdirk(t+h*.5,half,h*.5,p,duty,inv_half)
        if not(ok1 and ok2 and ok3):
            jac=_jacobian(t,y,p,duty);cache.clear();h*=.5
            if h<1e-12:return times[:count],states[:count].T.copy(),attempts,-1,jac
            continue
        error=0.
        for j in range(n):
            if 4<=j<=6:continue
            e=abs(fine[j]-whole[j])/(3*(1e-7+rtol*max(abs(y[j]),abs(fine[j]))))
            error=max(error,e)
            if not math.isfinite(fine[j]):error=math.inf
        if error>1:
            h*=max(.15,.8*error**(-1/3)) if math.isfinite(error) else .15
            if h<1e-12:return times[:count],states[:count].T.copy(),attempts,-1,jac
            continue
        t=end if end-t<=h else t+h;y=fine
        if count==capacity:
            capacity*=2;nt=np.empty(capacity);ns=np.empty((capacity,n))
            nt[:count]=times;ns[:count]=states;times=nt;states=ns
        times[count]=t;states[count]=y;count+=1
        if y[0]<=.1:return times[:count],states[:count].T.copy(),attempts,3,jac
        if y[1] < -1e-8:return times[:count],states[:count].T.copy(),attempts,1,jac
        if y[1] >= (30 if p[34] and p[28]>=.5 else 60):return times[:count],states[:count].T.copy(),attempts,4,jac
        if p[34] and p[29]>=.5 and y[2]>=60:return times[:count],states[:count].T.copy(),attempts,5,jac
        h=min(max_step,h*(2. if error<1e-12 else min(2.,max(.5,.85*error**(-1/3)))))
    return times[:count],states[:count].T.copy(),attempts,0 if t>=end-1e-13 else -1,jac


@njit(cache=True)
def _observe(t,y,p,duty):
    a=plant.record_observation(t,y,p,True,True)
    b=plant.record_observation(t,y,p,False,True)
    return duty*a+(1-duty)*b


@njit(cache=True)
def _observations(times,states,p,duty):
    result=np.empty((len(times),15))
    for j in range(len(times)):result[j]=_observe(times[j],states[:,j],p,duty)
    return result


class AveragedPlant:
    averaged=True
    def __init__(self,config,*,rtol=2e-4,max_step_s=.001):
        self.rtol=rtol;self.max_step_s=max_step_s;self.domain_warning=False
        self.jac=self.jac_state=None;self.jac_time=-math.inf;self.jac_duty=None
        self.inverse_cache=Dict.empty(key_type=types.int64,value_type=types.float64[:,::1])

    def integrate(self,t,end,y,p,duty):
        if p[38]==1 and t<p[36] and end<=p[36]:
            p=p.copy();p[38]=0.
        if (self.jac is None or abs(self.jac_duty-duty)>.025 or t-self.jac_time>.05 or
                np.max(np.abs(y[:4]-self.jac_state[:4]))>.5):
            self.jac=_jacobian(t,y,p,duty);self.jac_state=y.copy();self.jac_time=t;self.jac_duty=duty
            self.inverse_cache.clear()
        ts,ys,attempts,code,self.jac=_integrate(t,end,y,p,duty,self.rtol,self.max_step_s,self.jac,self.inverse_cache)
        status={0:'end',1:'averaged_dcm_outside_domain',3:'collapse',4:'overcurrent',5:'curve_range',-1:'failed'}[code]
        # A CCM model does not resolve the zero-current interval. Estimate the
        # ripple lower envelope only to flag missing fidelity, never as a peak
        # certificate. Final candidates always require the switched model.
        last=ys[:,-1];on=plant._nodes(float(ts[-1]),last,p,True,True)
        ind=plant._l_value(last[1],p) if p[34] else p[39]
        rise=max(0.,(on[3]-on[4]-(p[3]+p[4])*last[1])/ind)*duty/p[41]
        if last[1] <= .5*rise+1e-8:self.domain_warning=True
        return dict(t=ts,y=ys,nfev=int(attempts)*3,steps=len(ts)-1,status=status)

    @staticmethod
    def record(t,y,p,duty):return _observe(float(t),y,p,duty)

    @staticmethod
    def records(times,states,p,duty):return _observations(times,states,p,duty)

    @staticmethod
    def observe(c,panel,y,t,p,duty):
        a=_observe(t,y,p,duty)
        return dict(v_pv=a[0],i_pv=a[1],v_fused=a[2],v_in=a[6],v_out=a[7],
            v_bat_plus=a[8],i_l=a[9],v_sense=a[10],i_sense=a[11],ipv_sense=a[12],
            vout_sense=a[13],p_pv=a[14])


def _configuration(values,duration_override,plant_truth_overrides,controller_estimates):
    from engine_v3 import configuration,DEFAULTS,LIMITS
    values=dict(values or {})
    if values.get('algorithm','baseline')=='c07_r03':
        raise ValueError('c07_r03 is excluded from the current autotuning improvement.')
    duration=values.get('duration_ms',DEFAULTS['duration_ms']) if duration_override is None else duration_override
    if not math.isfinite(float(duration)) or not 5<=duration<=60000:
        raise ValueError('Private tuning duration must be 5..60000 ms')
    # Validate unchanged public fields through its entry point with a temporary
    # legal duration. Only this private evaluation endpoint expands the limit.
    step=float(values.get('step_ms',DEFAULTS['step_ms']))
    ramp=float(values.get('ramp_ms',DEFAULTS['ramp_ms'])) if values.get('experiment')=='irradiance' else 0.
    if step+ramp>=duration:raise ValueError('Tuning experiment must include a post-change interval')
    check=dict(values,duration_ms=min(1000.,400000/float(values.get('pwm_khz',DEFAULTS['pwm_khz']))),step_ms=0.,ramp_ms=0.)
    c=configuration(check);c.update(duration_ms=float(duration),step_ms=step,ramp_ms=ramp)
    if not math.isfinite(step) or step<0 or not math.isfinite(ramp) or ramp<0:raise ValueError('Invalid private experiment time')
    from parameter_sets import PARAMETER_KEYS
    forbidden={'v_start','v_target','irradiance','irradiance_after','ramp_ms','pwm_khz','acquire_us','transport_us','compute_us','apply_us','adc_channel_us','adc_phase','adc_bits'}
    allowed=(set(plant.PLANT_DEFAULTS)|{'cin_uf','cout_uf','l_uh','r_l_ohm','r_switch_ohm','r_battery_ohm','v_battery','pv_voc','pv_isc','pv_vmp','pv_imp','sense_tau_us'})-forbidden
    truth=dict(c);estimate=dict(c)
    for dest,patch in ((truth,plant_truth_overrides),(estimate,controller_estimates)):
        patch=patch or {}
        if set(patch)-allowed:raise ValueError('Only explicit physical model values may be overridden: '+', '.join(sorted(set(patch)-allowed)))
        dest.update(patch)
        for key,value in patch.items():
            if key in LIMITS and not LIMITS[key][0]<=float(value)<=LIMITS[key][1]:raise ValueError('Model override outside range: '+key)
    return truth,estimate


def simulate_tuning(config,*,duration_override=None,cancelled=None,timeout=20.,detail='summary',
                    plant_truth_overrides=None,controller_estimates=None,capture_state=False,
                    initial_snapshot=None,rtol=2e-4,max_step_s=.001):
    """duration_override is absolute end time in ms (private maximum 60 s)."""
    from experiments import simulate_experiment
    truth,estimate=_configuration(config,duration_override,plant_truth_overrides,controller_estimates)
    return simulate_experiment(truth,timeout=timeout,cancelled=cancelled,
        _backend=AveragedPlant(truth,rtol=rtol,max_step_s=max_step_s),_summary_only=detail=='summary',
        _controller_config=estimate,_capture_state=capture_state,_initial_snapshot=initial_snapshot)


def simulate_detailed(config,*,duration_override=None,cancelled=None,timeout=45.,detail='summary',
                      plant_truth_overrides=None,controller_estimates=None,capture_state=False,
                      initial_snapshot=None,method='FAST',max_step_fraction=.25):
    """Full PWM final evaluation; bypass legacy compacted-series-only scoring."""
    from experiments import simulate_experiment
    truth,estimate=_configuration(config,duration_override,plant_truth_overrides,controller_estimates)
    return simulate_experiment(truth,method=method,max_step_fraction=max_step_fraction,
        timeout=timeout,cancelled=cancelled,_summary_only=detail=='summary',_controller_config=estimate,
        _capture_state=capture_state,_initial_snapshot=initial_snapshot)


def warmup():
    from engine_v3 import DEFAULTS,Panel
    c=dict(DEFAULTS);pnl=Panel.from_config(c);y,d=plant.initial_state(c,pnl);p=plant.prepare(c,pnl)
    cache=Dict.empty(key_type=types.int64,value_type=types.float64[:,::1])
    _integrate(0.,1e-6,y,p,d,2e-4,.001,_jacobian(0.,y,p,d),cache);_observe(0.,y,p,d)
