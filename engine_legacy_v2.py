"""Explicit-switching PV buck teaching model. SI internally; no PWM averaging.

This is NOT the c07 circuit. See MODEL.md for topology, omitted components,
PV curve approximation, initial-state assumptions, and validation boundaries.
"""
from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq


DEFAULTS = dict(mode="PI", kp=0.003, ti_ms=2.0, td_ms=0.0,
    derivative_filter_ms=0.15, control_us=100.0, pwm_khz=20.0,
    v_start=64.0, v_target=60.0, step_ms=10.0, duration_ms=80.0,
    cin_uf=1420.0, l_uh=214.0, cout_uf=945.0, r_l_ohm=0.017,
    r_switch_ohm=0.01, r_battery_ohm=0.06, v_battery=51.2,
    pv_voc=74.2, pv_isc=13.73, pv_vmp=62.4, pv_imp=12.83,
    irradiance=700.0, sense_tau_us=0.0, acquire_us=0.0,
    transport_us=0.0, compute_us=0.0, apply_us=0.0,
    adc_phase=0.5, rtol=1e-5)

PRESETS = [
    dict(id="pi", label="PI：基本の追従", config=DEFAULTS),
    dict(id="p", label="P：定常偏差を見る", config={**DEFAULTS,"mode":"P"}),
    dict(id="pid", label="PID：D項を加える", config={**DEFAULTS,"mode":"PID","td_ms":0.15}),
    dict(id="delay", label="PI：測定の遅れ", config={**DEFAULTS,"transport_us":400,"sense_tau_us":150}),
]

LIMITS = dict(kp=(0,0.08),ti_ms=(0.05,100),td_ms=(0,10),
    derivative_filter_ms=(0.01,10),control_us=(20,5000),pwm_khz=(5,100),
    v_start=(5,150),v_target=(5,150),step_ms=(0,100),duration_ms=(5,200),
    cin_uf=(100,10000),l_uh=(50,2000),cout_uf=(100,10000),
    r_l_ohm=(0,0.5),r_switch_ohm=(0,0.5),r_battery_ohm=(0.01,1),
    v_battery=(5,100),pv_voc=(10,160),pv_isc=(0.1,30),pv_vmp=(5,150),
    pv_imp=(0.01,30),irradiance=(100,1200),sense_tau_us=(0,3000),
    acquire_us=(0,5000),transport_us=(0,5000),compute_us=(0,5000),
    apply_us=(0,5000),adc_phase=(0,0.99),rtol=(1e-9,1e-3))


def configuration(values=None):
    c = dict(DEFAULTS)
    if values:
        unknown = set(values)-set(c)
        if unknown:
            raise ValueError("未対応の設定: " + ", ".join(sorted(unknown)))
        c.update(values)
    if c["mode"] not in ("P","PI","PID"):
        raise ValueError("制御方式は P / PI / PID から選んでください。")
    for k,(lo,hi) in LIMITS.items():
        c[k] = float(c[k])
        if not math.isfinite(c[k]) or not lo <= c[k] <= hi:
            raise ValueError(f"{k}: {lo} ～ {hi} の範囲で設定してください。")
    if not 0 < c["pv_imp"] < c["pv_isc"] or not 0 < c["pv_vmp"] < c["pv_voc"]:
        raise ValueError("PV参照点は Imp < Isc、Vmp < Voc にしてください。")
    if c["step_ms"] >= c["duration_ms"]:
        raise ValueError("目標切替時刻は表示時間より短くしてください。")
    if c["duration_ms"]*c["pwm_khz"] > 6000:
        raise ValueError("初版は最大6000 PWM周期です。表示時間またはPWM周波数を下げてください。")
    return c


@dataclass(frozen=True)
class Panel:
    iph: float
    saturation: float
    scale: float
    voc: float

    @classmethod
    def from_config(cls,c):
        # Rs=0, Rsh=infinity single diode. Fits Isc, Voc and the (Vmp,Imp)
        # point at STC. The true maximum of this fitted curve is NOT forced.
        voc,isc,vmp,imp = (c[k] for k in ("pv_voc","pv_isc","pv_vmp","pv_imp"))
        ratio = 1-imp/isc
        def f(a):
            q = math.exp(-voc/a)
            return (math.exp((vmp-voc)/a)-q)/(1-q)-ratio
        try:
            a = brentq(f,voc/500,voc*100,xtol=1e-12)
        except ValueError as exc:
            raise ValueError("指定したPV参照点を今回の単一ダイオード近似に適合できません。") from exc
        sat = isc/math.expm1(voc/a)
        iph = isc*c["irradiance"]/1000
        return cls(iph,sat,a,a*math.log1p(iph/sat))

    def current(self,v):
        # Extends into forward diode absorption above Voc; no clipping to Isc/0.
        return self.iph-self.saturation*math.expm1(min(100.0,v/self.scale))


def initial_state(c,panel):
    v=c["v_start"]; ip=panel.current(v)
    if v <= c["v_battery"]+0.8 or ip <= 0:
        raise ValueError(f"初期PV電圧は電池電圧+0.8 Vより高く、現在の日射でのVoc ({panel.voc:.2f} V) 未満にしてください。")
    vf=0.7
    a=v+vf; b=c["v_battery"]+vf+c["r_switch_ohm"]*ip
    d=(b+math.sqrt(b*b+4*a*(c["r_l_ohm"]+c["r_battery_ohm"])*ip))/(2*a)
    if not 0.02 < d < .98:
        raise ValueError("初期動作点に必要なDutyが2～98%の範囲外です。初期電圧を上げるか電池電圧を下げてください。")
    il=ip/d
    # Cycle-balance initial estimate only. Subsequent evolution resolves every edge.
    return np.array([v,il,c["v_battery"]+c["r_battery_ohm"]*il,v,0.,0.,0.]),d


def make_rhs(c,panel,on,conducting=True):
    cin=c["cin_uf"]*1e-6; ind=c["l_uh"]*1e-6; cout=c["cout_uf"]*1e-6
    rl=c["r_l_ohm"]; ron=c["r_switch_ohm"]; rb=c["r_battery_ohm"]; vb=c["v_battery"]
    tau=c["sense_tau_us"]*1e-6
    def fun(t,y):
        v,i,vo,vs=y[:4]
        ip=panel.current(v); ib=(vo-vb)/rb
        if on:
            di=(v-vo-(rl+ron)*i)/ind
            ii=i; loss=(rl+ron)*i*i
        elif conducting:
            di=(-vo-0.7-rl*i)/ind
            ii=0.; loss=rl*i*i+0.7*i
        else:
            di=0.; ii=0.; i=0.; loss=0.
        return [(ip-ii)/cin,di,(i-ib)/cout,(v-vs)/tau if tau else 0.,
                v*ip,vb*ib,loss+rb*ib*ib]
    return fun


def stored_energy(c,y):
    return .5*(c["cin_uf"]*1e-6*y[0]**2+c["l_uh"]*1e-6*y[1]**2+c["cout_uf"]*1e-6*y[2]**2)


class SimulationCancelled(Exception):
    """A newer slider setting superseded this computation."""


def simulate(values=None, *, method="FAST", max_step_fraction=0.25, timeout=25., cancelled=None):
    tic=time.perf_counter(); c=configuration(values); panel=Panel.from_config(c)
    y,d0=initial_state(c,panel); energy0=stored_energy(c,y)
    if c["v_target"] <= c["v_battery"] or c["v_target"] >= panel.voc:
        raise ValueError(f"目標電圧は電池電圧より高く、現在のVoc ({panel.voc:.2f} V) 未満にしてください。")
    ts=1/(c["pwm_khz"]*1000); tu=c["control_us"]*1e-6
    stop=c["duration_ms"]*.001; target_time=c["step_ms"]*.001
    duration_samples=int(stop/tu)+1
    queue=[]; sequence=0
    def push(t,priority,kind,payload=None):
        nonlocal sequence
        if t <= stop+1e-12:
            sequence+=1; heapq.heappush(queue,(max(0.,t),priority,sequence,kind,payload))
    push(0.,1,"frame",0)
    for k in range(duration_samples):
        push(k*tu+c["adc_phase"]*ts,3,"request",k)
    push(target_time,2,"target")
    push(stop,9,"end")
    columns="t_ms v_pv v_ref v_sense duty duty_command i_l v_out p i d pwm".split()
    records=[]; events=[]; timings=[]; by_id={}
    if method=="FAST":
        from fast_integrator import integrate_interval, prepare
        packed=prepare(c,panel)
    t=0.; on=False; conducting=True; applied=d0; command=d0; ready=d0
    ready_id=None
    pterm=iterm=dterm=0.; integral=0.; filtered_rate=0.; previous_measurement=c["v_start"]
    previous_acq=None; cpu_free=0.; steps=nfev=frames=0; warnings=[]; stopped=False
    last_sample=c["v_start"]
    if c["compute_us"]>c["control_us"]:
        warnings.append("演算時間が制御周期を超えています。単一CPUの待ち行列により、古い測定値の処理が蓄積します。")
    if c["sense_tau_us"]:
        warnings.append(f"測定経路に時定数 {c['sense_tau_us']:g} µs の一次RCフィルタを明示的に適用しています。")
    def ref(time_s): return c["v_target"] if time_s >= target_time-1e-12 else c["v_start"]
    def record(time_s,state):
        vals=(time_s*1000,state[0],ref(time_s),state[3] if c["sense_tau_us"] else state[0],
              applied,command,state[1],state[2],pterm,iterm,dterm,float(on))
        # Identical state/event records add no waveform information. Keep both
        # sides of actual discontinuities, all accepted integration endpoints.
        if records and records[-1]==vals:
            return
        records.append(vals)
    def log(kind,**kw):
        if len(events)<30000: events.append(dict(t_ms=t*1000,kind=kind,**kw))
    def zero_current(time_s,state): return state[1]
    zero_current.direction=-1; zero_current.terminal=True
    def reverse_current(time_s,state): return state[1]+0.01
    reverse_current.direction=-1; reverse_current.terminal=True
    def collapse(time_s,state): return state[0]-0.1
    collapse.direction=-1; collapse.terminal=True
    def overcurrent(time_s,state): return 60-state[1]
    overcurrent.direction=-1; overcurrent.terminal=True

    while queue and not stopped:
        if cancelled is not None and cancelled():
            raise SimulationCancelled()
        if time.perf_counter()-tic > timeout:
            warnings.append("計算時間の上限に達したため、ここまでの結果を表示します。表示時間を短くしてください。")
            break
        end=queue[0][0]
        while end-t > 2e-13:
            if method=="FAST":
                segment=integrate_interval(t,end,y,c,panel,on,conducting,
                    max_step_fraction=max_step_fraction,prepared=packed)
                nfev+=segment["nfev"]; steps+=segment["steps"]
                times=segment["t"]; states=segment["y"]; outcome=segment["status"]
            else:
                rhs=make_rhs(c,panel,on,conducting)
                ev=[collapse,overcurrent]
                if on: ev.append(reverse_current)
                elif conducting: ev.append(zero_current)
                sol=solve_ivp(rhs,(t,end),y,method=method,rtol=c["rtol"],
                    atol=np.array([1e-8,1e-9,1e-8,1e-8,1e-10,1e-10,1e-10]),
                    max_step=ts*max_step_fraction,events=ev,dense_output=True)
                nfev+=sol.nfev; steps+=len(sol.t)-1
                outcome="end" if sol.success else "failed"
                if sol.status==1:
                    outcome="zero" if not on and conducting and len(sol.t_events[2]) else "outside"
                times=np.unique(np.r_[sol.t,np.linspace(t,float(sol.t[-1]),5)])
                states=sol.sol(times)
            if outcome=="failed":
                warnings.append("数値解法が収束しませんでした。表示済み範囲以降は未計算です。")
                stopped=True; break
            for j,tt in enumerate(times): record(tt,states[:,j])
            t=float(times[-1]); y=states[:,-1].copy()
            if outcome!="end":
                if outcome=="zero":
                    y[1]=0.; conducting=False; log("diode_zero"); continue
                warnings.append("モデル適用範囲を外れたため停止しました（PV電圧低下、60 A超過、または逆電流）。続きの波形は推定していません。")
                stopped=True; break
        if stopped: break
        t=end
        while queue and queue[0][0] <= t+1e-12:
            _,_,_,kind,payload=heapq.heappop(queue)
            if kind=="frame":
                frame=payload; applied=ready; on=True; conducting=True; frames+=1
                if ready_id is not None and by_id[ready_id]["applied_ms"] is None:
                    by_id[ready_id]["applied_ms"]=t*1000
                    by_id[ready_id]["status"]="applied"
                log("pwm_latch",duty=applied,sample_id=ready_id)
                if applied<=0: on=False; conducting=y[1]>1e-10
                elif applied<1: push(frame*ts+applied*ts,1,"off")
                push((frame+1)*ts,1,"frame",frame+1)
            elif kind=="off":
                on=False; conducting=y[1]>1e-10
                if not conducting: y[1]=0.
            elif kind=="request":
                trace=dict(sample_id=payload,request_ms=t*1000,acquire_ms=None,arrival_ms=None,
                    compute_start_ms=None,compute_end_ms=None,ready_ms=None,applied_ms=None,
                    measurement=None,output=None,status="pending",superseded_by=None)
                timings.append(trace); by_id[payload]=trace
                log("request",sample_id=payload)
                push(t+c["acquire_us"]*1e-6,3,"acquire",payload)
            elif kind=="acquire":
                sample=float(y[3] if c["sense_tau_us"] else y[0]); last_sample=sample
                by_id[payload].update(acquire_ms=t*1000,measurement=sample)
                log("adc_acquire",sample=sample,sample_id=payload)
                push(t+c["transport_us"]*1e-6,3,"arrival",(t,sample,payload))
            elif kind=="arrival":
                by_id[payload[2]]["arrival_ms"]=t*1000
                log("arrival",sample_id=payload[2])
                start=max(t,cpu_free); cpu_free=start+c["compute_us"]*1e-6
                push(start,4,"compute_start",payload)
            elif kind=="compute_start":
                acq,measurement,sid=payload
                by_id[sid]["compute_start_ms"]=t*1000
                dt=tu if previous_acq is None else max(1e-12,acq-previous_acq)
                error=measurement-ref(t)
                pterm=c["kp"]*error
                raw_rate=(measurement-previous_measurement)/dt
                alpha=math.exp(-dt/(c["derivative_filter_ms"]*.001))
                filtered_rate=alpha*filtered_rate+(1-alpha)*raw_rate
                dterm=c["kp"]*c["td_ms"]*.001*filtered_rate if c["mode"]=="PID" else 0.
                ki=c["kp"]/(c["ti_ms"]*.001) if c["mode"]!="P" else 0.
                trial=integral+ki*error*dt
                raw=d0+pterm+trial+dterm
                # Conditional integration anti-windup. No automatic gain change.
                if not ((raw>.98 and error>0) or (raw<0 and error<0)):
                    integral=trial
                iterm=integral
                output=min(.98,max(0.,d0+pterm+iterm+dterm))
                by_id[sid]["output"]=output
                previous_acq=acq; previous_measurement=measurement
                log("pid",sample_id=sid,acquired_ms=acq*1000,measurement=measurement,
                    error=error,p=pterm,i=iterm,d=dterm,output=output)
                push(t+c["compute_us"]*1e-6,0,"complete",(sid,output))
            elif kind=="complete":
                sid,command=payload; by_id[sid]["compute_end_ms"]=t*1000
                log("command",duty=command,sample_id=sid)
                push(t+c["apply_us"]*1e-6,0,"ready",payload)
            elif kind=="ready":
                sid,value=payload
                if ready_id is not None and by_id[ready_id]["applied_ms"] is None:
                    by_id[ready_id].update(status="superseded",superseded_by=sid)
                ready_id=sid; ready=value; by_id[sid]["ready_ms"]=t*1000
                log("pwm_ready",duty=ready,sample_id=sid)
            record(t,y)
    matrix=np.asarray(records,dtype=float)
    if not len(records): raise RuntimeError("計算結果がありません。")
    arr={k:matrix[:,j] for j,k in enumerate(columns)}
    if not len(arr["t_ms"]): raise RuntimeError("計算結果がありません。")
    band=max(.2,abs(c["v_target"]-c["v_start"])*.02)
    after=arr["t_ms"]>=c["step_ms"]-1e-9
    tt=arr["t_ms"][after]; vv=arr["v_pv"][after]
    completed=arr["t_ms"][-1]>=c["duration_ms"]-1e-7
    settling=None; overshoot=None
    if len(tt):
        outside=np.flatnonzero(np.abs(vv-c["v_target"])>band)
        k=int(outside[-1]+1) if len(outside) else 0
        if completed and k<len(tt) and tt[-1]-tt[k]>=max(5*tu*1000,2):
            settling=float(tt[k]-c["step_ms"])
        direction=np.sign(c["v_target"]-c["v_start"])
        overshoot=float(max(0,np.max(direction*(vv-c["v_target"]))))
    residual=stored_energy(c,y)-energy0-y[4]+y[5]+y[6]
    energy_pct=abs(residual)/max(abs(y[4]),1e-9)*100
    if energy_pct>0.1: warnings.append("エネルギー収支の数値残差が0.1%を超えています。精度を上げて確認してください。")
    if not completed: warnings.append("指定した終了時刻まで計算できていません。整定時間は判定しません。")
    return dict(config=c,series={k:v.tolist() for k,v in arr.items()},events=events,timings=timings,
        metrics=dict(settling_ms=settling,overshoot_v=overshoot,
            final_error_v=float(arr["v_pv"][-1]-c["v_target"]),
            peak_current_a=float(np.max(arr["i_l"])),elapsed_ms=(time.perf_counter()-tic)*1000,
            energy_residual_pct=float(energy_pct),initial_duty=float(d0),voltage_band_v=band,
            simulated_until_ms=float(arr["t_ms"][-1]),completed=bool(completed),
            energy_in_j=float(y[4]),energy_battery_j=float(y[5]),energy_loss_j=float(y[6]),
            energy_residual_j=float(residual),actual_voc=panel.voc),
        diagnostics=dict(warnings=warnings,solver="DOPRI5(4) / Numba" if method=="FAST" else method,accepted_steps=steps,nfev=nfev,
            pwm_cycles=frames,raw_points=len(arr["t_ms"]),averaging=False,
            model="c07代表値を参考にした学習用の非同期Buck。c07全回路の再現・実機検証ではありません。",
            plotting="全PWMを計算。高速版は受理計算点、参照版は計算点と補間点。描画時のみ極値を保持して点数調整。"))


if __name__=="__main__":
    import json
    result=simulate()
    print(json.dumps({"metrics":result["metrics"],"diagnostics":result["diagnostics"]},ensure_ascii=False,indent=2))
