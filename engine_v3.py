"""Public API for the switched PV lab; legacy fixtures retain their exact path."""
from __future__ import annotations
import math
import engine_legacy_v2 as legacy
from engine_legacy_v2 import Panel, SimulationCancelled, initial_state, make_rhs, stored_energy
from controllers import CONTROL_DEFAULTS, CONTROL_LIMITS, ALGORITHMS, validate_custom_configuration
from plant import PLANT_DEFAULTS, PLANT_LIMITS
from c07_r03 import validate as validate_c07_r03
from c07_r04 import validate as validate_c07_r04

EXPERIMENT_DEFAULTS = dict(algorithm='baseline', experiment='voltage',
    irradiance_after=400., ramp_ms=0., adc_channel_us=0., adc_bits=0.,
    adc_voltage_range_v=116.13636363636364, adc_current_range_a=50.,
    mppt_tolerance_pct=2., mppt_hold_ms=50.)
DEFAULTS = {**legacy.DEFAULTS, **CONTROL_DEFAULTS, **PLANT_DEFAULTS, **EXPERIMENT_DEFAULTS}
LIMITS = {**legacy.LIMITS, **CONTROL_LIMITS, **PLANT_LIMITS,
    # Public reference boards include 22/33 uH inductors; retain real values.
    'l_uh':(10,2000), 'cin_uf':(10,10000), 'cout_uf':(10,10000),
    'control_us':(10,100000), 'pwm_khz':(5,200), 'duration_ms':(5,10000),
    'step_ms':(0,9000), 'irradiance':(20,1400), 'irradiance_after':(20,1400),
    'ramp_ms':(0,5000), 'adc_channel_us':(0,1000), 'adc_bits':(0,16),
    'adc_voltage_range_v':(10,300), 'adc_current_range_a':(1,200),
    'mppt_tolerance_pct':(.1,20), 'mppt_hold_ms':(1,2000)}
PRESETS = [{**p,'config':{**DEFAULTS,**p['config']}} for p in legacy.PRESETS]


def configuration(values=None):
    c=dict(DEFAULTS)
    if values:
        unknown=set(values)-set(c)
        if unknown: raise ValueError('未対応の設定: '+', '.join(sorted(unknown)))
        c.update(values)
    allowed={
        'mode':('P','PI','PID'), 'algorithm':tuple(a['id'] for a in ALGORITHMS),
        'experiment':('voltage','irradiance'), 'plant_mode':('simple','c07'),
        'mppt_method':('inccond','po'),
        'custom_topology':('direct_duty','voltage_duty','voltage_current'),
        'custom_law':('pid','model'), 'voltage_mode':('P','PI','PID'),
        'current_mode':('P','PI','PID')}
    for key,options in allowed.items():
        if key in c and c[key] not in options:
            raise ValueError(f'{key}: '+', '.join(options)+' から選んでください。')
    for k,(lo,hi) in LIMITS.items():
        if k not in c: continue
        c[k]=float(c[k])
        if not math.isfinite(c[k]) or not lo<=c[k]<=hi:
            raise ValueError(f'{k}: {lo} ～ {hi} の範囲で設定してください。')
    if c['adc_bits']!=int(c['adc_bits']) or (0<c['adc_bits']<4):
        raise ValueError('ADC bit数は0（量子化なし）、または4〜16の整数です。')
    if not 0<c['pv_imp']<c['pv_isc'] or not 0<c['pv_vmp']<c['pv_voc']:
        raise ValueError('PV参照点は Imp < Isc、Vmp < Voc にしてください。')
    if c['step_ms']>=c['duration_ms']:
        raise ValueError('変化時刻は計算時間より短くしてください。')
    if c['experiment']=='irradiance' and c['step_ms']+c['ramp_ms']>=c['duration_ms']:
        raise ValueError('日照の変化が終わるより長い計算時間を設定してください。')
    if c['duration_ms']*c['pwm_khz']>400000:
        raise ValueError('全PWMを解くため最大400000周期です。時間またはPWM周波数を下げてください。')
    if c.get('duty_min',0)>=c.get('duty_max',.98):
        raise ValueError('Duty下限は上限より小さくしてください。')
    validate_custom_configuration(c)
    validate_c07_r03(c)
    validate_c07_r04(c)
    return c


def simulate(values=None, *, method='FAST', max_step_fraction=.25, timeout=45., cancelled=None):
    c=configuration(values)
    simple_defaults=all(c[k]==v for k,v in PLANT_DEFAULTS.items())
    if (c['algorithm']=='baseline' and c['experiment']=='voltage' and simple_defaults
        and c['algorithm_filter_ms']==0 and c['duty_min']==0 and c['duty_max']==.98
        and c['duty_response_gain']==1
        and c['adc_channel_us']==0 and c['adc_bits']==0 and c['duration_ms']<=200
        and c['duration_ms']*c['pwm_khz']<=6000):
        out=legacy.simulate({k:c[k] for k in legacy.DEFAULTS},method=method,
            max_step_fraction=max_step_fraction,timeout=timeout,cancelled=cancelled)
        from experiments import enrich_legacy
        return enrich_legacy(out,c)
    from experiments import simulate_experiment
    return simulate_experiment(c,method=method,max_step_fraction=max_step_fraction,
                               timeout=timeout,cancelled=cancelled)


if __name__=='__main__':
    import json
    r=simulate()
    print(json.dumps({'metrics':r['metrics'],'diagnostics':r['diagnostics']},ensure_ascii=False,indent=2))
