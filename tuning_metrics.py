"""Streaming, node-aware tuning scores, independent of plotting/compaction.

Integrals use every accepted physical point and piecewise-linear interpolation.
No controller reads this evaluator or the MPP oracle. Times are seconds.
"""
from __future__ import annotations
import math


def target_voltage_node(config, metadata=None):
    metadata = metadata or {}
    node = metadata.get('target_voltage_node')
    if node in ('PV_RAW', 'PV_FUSED', 'VIN'):
        return node
    model = config['algorithm'] == 'opensec' or (
        config['algorithm'] == 'custom' and config.get('custom_law') == 'model')
    return 'PV_RAW' if model or config.get('plant_mode') != 'c07' else 'PV_FUSED'


def voltage_at_node(observation, node):
    """Use physical nodes, never delayed ADC readings, for tracking evaluation."""
    return float(observation[{'PV_RAW':0, 'PV_FUSED':2, 'VIN':6}[node]])


def _abs_integral(a, b, dt):
    if a*b >= 0:
        return .5*(abs(a)+abs(b))*dt
    return .5*(a*a+b*b)/(abs(a)+abs(b))*dt


class _Tracking:
    def __init__(self, config, stop):
        self.start = config['step_ms']*.001
        self.stop = stop
        self.target = config['v_target']
        self.amplitude = abs(self.target-config['v_start'])
        self.direction = 1 if self.target > config['v_start'] else -1 if self.target < config['v_start'] else 0
        self.band = max(.2, .02*self.amplitude)
        self.tail_start = max(self.start,stop-max(.003,.15*(stop-self.start)))
        self.iae = self.ise = self.overshoot = 0.
        self.tail_min = math.inf; self.tail_max = -math.inf
        self.last_outside = None
        self.entered = self.start
        self.final = None
        self.last = None
        self.observed = 0

    def add(self, t, value):
        error = value-self.target
        if self.last is not None:
            old_t, old_e = self.last
            left = max(old_t,self.start); right = min(t,self.stop)
            if right > left and t > old_t:
                a = old_e+(error-old_e)*(left-old_t)/(t-old_t)
                b = old_e+(error-old_e)*(right-old_t)/(t-old_t)
                dt = right-left
                self.iae += _abs_integral(a,b,dt)
                self.ise += (a*a+a*b+b*b)*dt/3
                # Conservative accepted-point settling, not invented precision
                # between integration steps. Include the clipped left boundary.
                if abs(a)>self.band:self.last_outside=left;self.entered=None
                if abs(b)>self.band:self.last_outside=right;self.entered=None
                elif self.entered is None:self.entered=right
                self.overshoot=max(self.overshoot,self.direction*a,self.direction*b)
                tail_left=max(left,self.tail_start)
                if right>=tail_left:
                    ea=old_e+(error-old_e)*(tail_left-old_t)/(t-old_t)
                    self.tail_min=min(self.tail_min,ea,b)
                    self.tail_max=max(self.tail_max,ea,b)
        if self.start-1e-12<=t<=self.stop+1e-12:
            self.observed+=1
            self.final=error
            if abs(error)>self.band:self.last_outside=t;self.entered=None
            elif self.entered is None:self.entered=t
            self.overshoot=max(self.overshoot,self.direction*error)
            if t>=self.tail_start-1e-12:
                self.tail_min=min(self.tail_min,error);self.tail_max=max(self.tail_max,error)
        self.last=(t,error)

    def result(self, until, completed, hold):
        enter=self.entered
        settled=completed and self.observed>1 and enter is not None and until-enter>=hold-1e-12
        tail=self.tail_min!=math.inf
        return dict(iae_v_s=self.iae,ise_v2_s=self.ise,
            settling_ms=(max(0.,enter-self.start)*1000 if settled else None),
            overshoot_v=self.overshoot,final_error_v=self.final,
            tail_max_error_v=max(abs(self.tail_min),abs(self.tail_max)) if tail else None,
            tail_range_v=self.tail_max-self.tail_min if tail else None,
            amplitude_v=self.amplitude,evaluation_span_s=max(0.,until-self.start),
            voltage_band_v=self.band,tail_start_ms=self.tail_start*1000,
            tail_observed=tail,settling_hold_ms=hold*1000)


class _CycleTail:
    """Complete PWM-cycle means in the final evaluation window; no bins/logs."""
    def __init__(self,period,start):
        self.period=period
        self.start=math.ceil(start/period-1e-10)*period
        self.cycle=round(self.start/period);self.area_v=self.area_p=0.
        self.count=0;self.vmin=self.pmin=math.inf;self.vmax=self.pmax=-math.inf
        self.sum_p=0.;self.previous=None

    def add(self,t,v,p):
        if self.previous is not None:
            old,a,b=self.previous
            left=max(old,self.start)
            tolerance=max(1e-13,abs(t)*5e-15)
            while t-left>tolerance:
                boundary=(self.cycle+1)*self.period;right=min(t,boundary)
                if right<=left+tolerance:
                    self.cycle+=1;continue
                f0=(left-old)/(t-old);f1=(right-old)/(t-old)
                self.area_v+=(a+(v-a)*.5*(f0+f1))*(right-left)
                self.area_p+=(b+(p-b)*.5*(f0+f1))*(right-left)
                left=right
                if right>=boundary-tolerance:
                    vm=self.area_v/self.period;pm=self.area_p/self.period
                    self.vmin=min(self.vmin,vm);self.vmax=max(self.vmax,vm)
                    self.pmin=min(self.pmin,pm);self.pmax=max(self.pmax,pm)
                    self.sum_p+=pm;self.count+=1;self.cycle+=1
                    self.area_v=self.area_p=0.
        self.previous=(t,v,p)


class TuningMetrics:
    """Bounded-memory evaluator fed *before* display data is compacted."""
    def __init__(self, config, metadata, oracle, *, source='accepted_switched_points',minimum_hold_s=0.):
        self.c=config;self.oracle=oracle;self.source=source
        self.node=target_voltage_node(config,metadata)
        self.stop=config['duration_ms']*.001;self.start=config['step_ms']*.001
        self.ramp_end=self.start+(config['ramp_ms']*.001 if config['experiment']=='irradiance' else 0.)
        self.tracking=_Tracking(config,self.stop);self.raw=_Tracking(config,self.stop)
        if not math.isfinite(minimum_hold_s) or minimum_hold_s<0:
            raise ValueError('Evaluation-only minimum hold must be finite and nonnegative')
        self.minimum_hold_s=float(minimum_hold_s)
        self.hold=max(config['mppt_hold_ms']*.001,2*config['mppt_period_ms']*.001,self.minimum_hold_s)
        self.mppt_tail_start=max(self.ramp_end,self.stop-self.hold)
        self.cycle_tail=_CycleTail(1/(config['pwm_khz']*1000),self.mppt_tail_start)
        self.peak_i=0.;self.peak_vo=-math.inf;self.min_i=math.inf
        self.peak_iin=self.peak_pout=-math.inf;self.min_vin=math.inf
        self.pv_energy=0.;self.energy_start=None;self.energy_until=None
        self.prev=None;self.last_duty=None;self.duty_variation=0.
        self.last_outside_mpp=None;self.mpp_entered=None;self.last_t=0.;self.points=0
        self.tail_v_min=self.tail_p_min=math.inf
        self.tail_v_max=self.tail_p_max=-math.inf
        self.tail_p_area=self.tail_span=0.
        self.finite=True

    def add(self,t,observation,applied_duty,*,energy_pv=None,mpp_power=None):
        vp=float(observation[0]);vo=float(observation[7]);il=float(observation[9]);power=float(observation[14])
        voltage=voltage_at_node(observation,self.node)
        iin=float(observation[3] if self.c.get('plant_mode')=='c07' else observation[1])
        vin=float(observation[2] if self.c.get('plant_mode')=='c07' else observation[0])
        pout=vo*il
        vals=(t,vp,vo,il,power,voltage,applied_duty,iin,vin,pout)
        if not all(math.isfinite(x) for x in vals):
            self.finite=False;return
        if self.points and t<self.last_t-1e-12:raise ValueError('Metric timestamps must not go backwards')
        self.points+=1;self.last_t=t
        self.cycle_tail.add(t,vp,power)
        if self.c['experiment']=='voltage':
            self.tracking.add(t,voltage);self.raw.add(t,vp)
        self.peak_i=max(self.peak_i,il);self.min_i=min(self.min_i,il);self.peak_vo=max(self.peak_vo,vo)
        self.peak_iin=max(self.peak_iin,iin);self.peak_pout=max(self.peak_pout,pout);self.min_vin=min(self.min_vin,vin)
        if self.last_duty is not None:self.duty_variation+=abs(applied_duty-self.last_duty)
        self.last_duty=applied_duty
        pm=self.oracle.at(t)[2] if mpp_power is None else mpp_power
        if t>=self.ramp_end-1e-12:
            if power<pm*(1-self.c['mppt_tolerance_pct']/100):self.last_outside_mpp=t;self.mpp_entered=None
            elif self.mpp_entered is None:self.mpp_entered=t
        if self.prev is not None:
            old_t,old_p,old_v,old_energy=self.prev
            left=max(old_t,self.start);right=min(t,self.stop)
            if right>left and t>old_t:
                pa=old_p+(power-old_p)*(left-old_t)/(t-old_t)
                pb=old_p+(power-old_p)*(right-old_t)/(t-old_t)
                self.pv_energy+=.5*(pa+pb)*(right-left)
            tail_left=max(old_t,self.mppt_tail_start);tail_right=min(t,self.stop)
            if tail_right>tail_left and t>old_t:
                fraction=(tail_left-old_t)/(t-old_t)
                pa=old_p+(power-old_p)*fraction;va=old_v+(vp-old_v)*fraction
                pb=old_p+(power-old_p)*(tail_right-old_t)/(t-old_t)
                vb=old_v+(vp-old_v)*(tail_right-old_t)/(t-old_t)
                self.tail_p_area+=.5*(pa+pb)*(tail_right-tail_left)
                self.tail_span+=tail_right-tail_left
                self.tail_v_min=min(self.tail_v_min,va,vb);self.tail_v_max=max(self.tail_v_max,va,vb)
                self.tail_p_min=min(self.tail_p_min,pa,pb);self.tail_p_max=max(self.tail_p_max,pa,pb)
            if self.energy_start is None and energy_pv is not None and old_energy is not None and old_t<=self.start<=t and t>old_t:
                self.energy_start=old_energy+(energy_pv-old_energy)*(self.start-old_t)/(t-old_t)
        if energy_pv is not None:
            if abs(t-self.start)<=1e-12:self.energy_start=float(energy_pv)
            self.energy_until=float(energy_pv)
        if t>=self.mppt_tail_start-1e-12:
            self.tail_v_min=min(self.tail_v_min,vp);self.tail_v_max=max(self.tail_v_max,vp)
            self.tail_p_min=min(self.tail_p_min,power);self.tail_p_max=max(self.tail_p_max,power)
        self.prev=(t,power,vp,energy_pv)

    def result(self,completed,*,sample_period_s=None):
        until=self.last_t;completed=bool(completed and self.finite)
        period=sample_period_s if sample_period_s is not None else self.c['control_us']*1e-6
        tracking_hold=max(5*period,.020 if self.c['algorithm']=='c07_r04' else .002)
        tracking=self.tracking.result(until,completed,tracking_hold)
        raw=self.raw.result(until,completed,tracking_hold)
        available=max(0.,self.oracle.energy(until)-self.oracle.energy(min(until,self.start)))
        extracted=(self.energy_until-self.energy_start if self.energy_until is not None and self.energy_start is not None else self.pv_energy)
        enter=self.mpp_entered
        recovery=max(0.,enter-self.ramp_end)*1000 if completed and enter is not None and until-enter>=self.hold-1e-12 else None
        tail=self.tail_span>0
        return dict(version=1,available=True,completed=completed,finite=self.finite,
            target_node=self.node,evaluation_power_node='PV_RAW',source=self.source,
            display_independent=True,accepted_points=self.points,tracking=tracking,raw_tracking=raw,
            peak_current_a=self.peak_i,min_current_a=self.min_i if self.min_i!=math.inf else None,
            peak_output_voltage_v=self.peak_vo if self.peak_vo!=-math.inf else None,
            peak_input_current_a=self.peak_iin if self.peak_iin!=-math.inf else None,
            peak_output_power_w=self.peak_pout if self.peak_pout!=-math.inf else None,
            minimum_input_voltage_v=self.min_vin if self.min_vin!=math.inf else None,
            limits_basis=dict(kind='Instantaneous physical extrema at all accepted points; no ADC filtering or latency',
                input_current_node='L2' if self.c.get('plant_mode')=='c07' else 'PV_RAW',
                input_voltage_node='PV_FUSED' if self.c.get('plant_mode')=='c07' else 'PV_RAW',
                output_power_definition='Vout * L1 current, matching the FUGU protected quantity'),
            duty_variation=self.duty_variation,
            mppt=dict(energy_deficit_j=available-extracted,available_energy_j=available,
                extracted_energy_j=extracted,tracking_efficiency_pct=100*extracted/available if available>0 else None,
                recovery_ms=recovery,
                recovery_basis='First accepted inside point after the last outside point, held on instantaneous physical PV power',
                hold_voltage_range_v=self.cycle_tail.vmax-self.cycle_tail.vmin if self.cycle_tail.count else None,
                hold_power_range_w=self.cycle_tail.pmax-self.cycle_tail.pmin if self.cycle_tail.count else None,
                hold_power_mean_w=self.cycle_tail.sum_p/self.cycle_tail.count if self.cycle_tail.count else None,
                hold_complete_pwm_cycles=self.cycle_tail.count,
                hold_basis='Complete PWM-cycle time-weighted means; no instantaneous ripple penalty',
                hold_instant_voltage_range_v=self.tail_v_max-self.tail_v_min if tail else None,
                hold_instant_power_range_w=self.tail_p_max-self.tail_p_min if tail else None,
                hold_observed_s=self.tail_span,hold_required_s=self.hold,
                evaluation_only_minimum_hold_s=self.minimum_hold_s),
            interval=dict(start_ms=self.start*1000,end_ms=until*1000,requested_end_ms=self.stop*1000),
            numerical_definition='Time-weighted piecewise-linear integral over every accepted point; peaks at accepted points, before plot compaction. Energy uses physical integral state when supplied.')
