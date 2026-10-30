"""Compiled adaptive Dormand--Prince 5(4) for ONE constant-switch interval.

The caller owns PWM/ADC/controller timestamps and never passes a switching
edge inside an interval. The equations match engine.make_rhs. There is no
cycle averaging, cycle skipping, fastmath, or parameter-dependent model change.
The SciPy DOP853/Radau path remains the independent numerical reference.
"""
from __future__ import annotations

import math
import numpy as np

try:
    from numba import njit
except ImportError as exc:
    raise ImportError("The fast integrator requires numba. Install the app requirements.") from exc


@njit(cache=True, fastmath=False)
def _rhs(y, p, on, conducting, out):
    # p: Cin,L,Cout,Rl,Ron,Rb,Vbat,tau,Iph,Is,a
    v, i, vo, vs = y[0], y[1], y[2], y[3]
    ip = p[8] - p[9] * math.expm1(min(100.0, v / p[10]))
    ib = (vo - p[6]) / p[5]
    if on:
        di = (v - vo - (p[3] + p[4]) * i) / p[1]
        ii = i
        loss = (p[3] + p[4]) * i * i
    elif conducting:
        di = (-vo - 0.7 - p[3] * i) / p[1]
        ii = 0.0
        loss = p[3] * i * i + 0.7 * i
    else:
        di = 0.0
        ii = 0.0
        i = 0.0
        loss = 0.0
    out[0] = (ip - ii) / p[0]
    out[1] = di
    out[2] = (i - ib) / p[2]
    out[3] = (v - vs) / p[7] if p[7] > 0 else 0.0
    out[4] = v * ip
    out[5] = p[6] * ib
    out[6] = loss + p[5] * ib * ib


@njit(cache=True, fastmath=False)
def _step(y, h, p, on, conducting, k, stage, trial, error):
    """DOPRI 5(4), 7 RHS evaluations; error = fifth minus fourth order."""
    _rhs(y, p, on, conducting, k[0])
    for j in range(7): stage[j] = y[j] + h * k[0,j] / 5
    _rhs(stage, p, on, conducting, k[1])
    for j in range(7): stage[j] = y[j] + h * (3/40*k[0,j] + 9/40*k[1,j])
    _rhs(stage, p, on, conducting, k[2])
    for j in range(7):
        stage[j] = y[j] + h * (44/45*k[0,j] - 56/15*k[1,j] + 32/9*k[2,j])
    _rhs(stage, p, on, conducting, k[3])
    for j in range(7):
        stage[j] = y[j] + h * (19372/6561*k[0,j] - 25360/2187*k[1,j]
            + 64448/6561*k[2,j] - 212/729*k[3,j])
    _rhs(stage, p, on, conducting, k[4])
    for j in range(7):
        stage[j] = y[j] + h * (9017/3168*k[0,j] - 355/33*k[1,j]
            + 46732/5247*k[2,j] + 49/176*k[3,j] - 5103/18656*k[4,j])
    _rhs(stage, p, on, conducting, k[5])
    for j in range(7):
        trial[j] = y[j] + h * (35/384*k[0,j] + 500/1113*k[2,j]
            + 125/192*k[3,j] - 2187/6784*k[4,j] + 11/84*k[5,j])
    _rhs(trial, p, on, conducting, k[6])
    for j in range(7):
        error[j] = h * ((35/384-5179/57600)*k[0,j]
            + (500/1113-7571/16695)*k[2,j]
            + (125/192-393/640)*k[3,j]
            + (-2187/6784+92097/339200)*k[4,j]
            + (11/84-187/2100)*k[5,j] - 1/40*k[6,j])


@njit(cache=True, fastmath=False)
def _root_time(y, h, p, on, conducting, index, threshold, increasing,
               k, stage, trial, error):
    """Find a monotone endpoint-bracketed event by local reintegration."""
    lo, hi = 0.0, h
    evaluations = 0
    # Every shorter substep stays inside the accepted original switch interval.
    for _ in range(60):
        mid = (lo + hi) * 0.5
        _step(y, mid, p, on, conducting, k, stage, trial, error)
        evaluations += 7
        beyond = trial[index] >= threshold if increasing else trial[index] <= threshold
        if beyond: hi = mid
        else: lo = mid
        if hi - lo <= 5e-14: break
    return (lo + hi) * .5, evaluations


@njit(cache=True, fastmath=False)
def _integrate(t, end, initial, p, on, conducting, max_step, rtol):
    times = np.empty(64, dtype=np.float64)
    states = np.empty((64, 7), dtype=np.float64)
    times[0] = t
    states[0] = initial
    n = 1
    y = initial.copy()
    k = np.empty((7,7), dtype=np.float64)
    stage = np.empty(7, dtype=np.float64)
    trial = np.empty(7, dtype=np.float64)
    error = np.empty(7, dtype=np.float64)
    atol = np.array([1e-8,1e-9,1e-8,1e-8,1e-10,1e-10,1e-10])
    # Codes: 0=end, 1=zero, 2=reverse, 3=collapse, 4=overcurrent, -1=failed.
    if y[0] <= .1: return times[:n], states[:n].T.copy(), 0, 0, 3
    if y[1] >= 60.: return times[:n], states[:n].T.copy(), 0, 0, 4
    if on and y[1] <= -.01: return times[:n], states[:n].T.copy(), 0, 0, 2
    if not on and conducting and y[1] <= 0.:
        states[0,1] = 0.
        return times[:n], states[:n].T.copy(), 0, 0, 1
    h = min(end-t, max_step)
    evaluations = 0
    attempts = 0
    steps = 0
    while t < end:
        attempts += 1
        if attempts > 20000 or steps >= 10000:
            return times[:n], states[:n].T.copy(), evaluations, steps, -1
        remaining = end-t
        h = min(h, max_step, remaining)
        if h <= 0. or t+h == t:
            return times[:n], states[:n].T.copy(), evaluations, steps, -1
        _step(y, h, p, on, conducting, k, stage, trial, error)
        evaluations += 7
        error_norm = 0.
        for j in range(7):
            scale = atol[j] + rtol * max(abs(y[j]), abs(trial[j]))
            z = error[j] / scale
            error_norm += z*z
            if not math.isfinite(trial[j]): error_norm = math.inf
        error_norm = math.sqrt(error_norm / 7)
        if not math.isfinite(error_norm) or error_norm > 1.:
            factor = max(.1, .9 * error_norm**(-.2)) if math.isfinite(error_norm) else .1
            h *= factor
            continue

        # Stop at the first physical/domain event, never step beyond it.
        code = 0
        first = h
        if trial[0] <= .1:
            root, count = _root_time(y,h,p,on,conducting,0,.1,False,k,stage,trial,error)
            evaluations += count
            if root <= first: first, code = root, 3
        # Root searches overwrite trial, so recompute the accepted endpoint.
        if code: _step(y,h,p,on,conducting,k,stage,trial,error); evaluations += 7
        if trial[1] >= 60.:
            root,count = _root_time(y,h,p,on,conducting,1,60.,True,k,stage,trial,error)
            evaluations += count
            if root <= first: first, code = root, 4
            _step(y,h,p,on,conducting,k,stage,trial,error); evaluations += 7
        threshold = -.01 if on else 0.
        if (on or conducting) and trial[1] <= threshold:
            root,count = _root_time(y,h,p,on,conducting,1,threshold,False,k,stage,trial,error)
            evaluations += count
            if root <= first: first, code = root, (2 if on else 1)
        if code:
            _step(y,first,p,on,conducting,k,stage,trial,error)
            evaluations += 7
            if code==1: trial[1]=0.
            elif code==2: trial[1]=-.01
            elif code==3: trial[0]=.1
            else: trial[1]=60.
            h=first
        t_next = end if not code and h >= remaining else t+h
        if t_next <= t:
            return times[:n],states[:n].T.copy(),evaluations,steps,-1
        t=t_next
        y=trial.copy()
        if n >= len(times):
            new_times=np.empty(min(10002,2*len(times)),dtype=np.float64)
            new_states=np.empty((len(new_times),7),dtype=np.float64)
            new_times[:n]=times[:n]; new_states[:n]=states[:n]
            times=new_times; states=new_states
        times[n]=t; states[n]=y; n+=1; steps+=1
        if code:
            return times[:n],states[:n].T.copy(),evaluations,steps,code
        h *= 5. if error_norm == 0. else min(5.,max(.2,.9*error_norm**(-.2)))
    return times[:n],states[:n].T.copy(),evaluations,steps,0


def prepare(c,panel):
    """Pack immutable coefficients once per experiment, outside the event loop."""
    return np.array([c['cin_uf']*1e-6,c['l_uh']*1e-6,c['cout_uf']*1e-6,
        c['r_l_ohm'],c['r_switch_ohm'],c['r_battery_ohm'],c['v_battery'],
        c['sense_tau_us']*1e-6,panel.iph,panel.saturation,panel.scale],dtype=float)


def integrate_interval(t,end,y,c,panel,on,conducting,max_step_fraction=.25,*,prepared=None):
    p = prepare(c,panel) if prepared is None else prepared
    max_step=1/(c['pwm_khz']*1000)*max_step_fraction
    times,states,nfev,steps,code=_integrate(float(t),float(end),np.asarray(y,dtype=float),
        p,bool(on),bool(conducting),max_step,c['rtol'])
    statuses={0:'end',1:'zero',2:'reverse',3:'collapse',4:'overcurrent',-1:'failed'}
    return dict(t=times,y=states,nfev=int(nfev),steps=int(steps),status=statuses[int(code)])


def warmup():
    """Compile/load cache before serving slider requests; not a numerical result."""
    p=np.array([.00142,.000214,.000945,.017,.01,.06,51.2,0.,9.611,1e-7,4.])
    y=np.array([64.,10.,51.8,64.,0.,0.,0.])
    _integrate(0.,1e-6,y,p,True,True,1e-6,1e-5)
