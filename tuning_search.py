"""Scenario definitions and display-independent objective functions for tuning."""
from __future__ import annotations
import math
from engine import configuration,Panel
from tuning_design import PROFILES,modes,effective_timing

def scenarios(c):
 """Keep physical settings/limits fixed; describe diagnostic stimuli explicitly."""
 panel=Panel.from_config(c);vp,ip,delay=effective_timing(c)
 if c['experiment']=='voltage':
  pre=max(5.,4*vp*1000,6*c['sense_tau_us']*.001)
  period=c['mppt_period_ms'] if c['algorithm']=='libresolar' or c['algorithm']=='custom' and c['custom_topology']=='direct_duty' else vp*1000
  # A finite diagnostic window: at least 60 ms and enough actual loop/step
  # periods. Incomplete settling is rejected; no extrapolated passing time.
  post=max(120. if c['algorithm']=='c07_r04' else 60.,30*vp*1000,8*period,30*c['sense_tau_us']*.001)
  post=min(post,3000.)
  low=c['v_battery']+1.2; high=panel.voc-.3
  amplitude=min(2.,max(.5,c['v_start']*.03),.7*(c['v_start']-low),.7*(high-c['v_start']))
  if amplitude<.15:raise ValueError('初期電圧の両側に検証用の電圧変化を与えられる余裕がありません。')
  cases=[]
  for direction,label in ((-1,'voltage_down'),(1,'voltage_up')):
   cc={**c,'experiment':'voltage','v_target':c['v_start']+direction*amplitude,'step_ms':pre,'duration_ms':pre+post}
   cases.append(dict(id=label,config=configuration(cc),duration_ms=pre+post,
     description='初期点から'+('下降' if direction<0 else '上昇')+'する小電圧ステップ'))
 else:
  pre=max(10.,2*c['mppt_period_ms']);ramp=max(c['ramp_ms'],20.)
  post=max(300.,12*c['mppt_period_ms'],c['mppt_hold_ms']*3)
  post=min(post,3000.)
  end=pre+ramp+post
  after=c['irradiance_after'] if c['irradiance_after']!=c['irradiance'] else max(20.,.8*c['irradiance'])
  cases=[]
  for label,irr,rmp in [('irradiance_ramp',after,ramp),('irradiance_hold',c['irradiance'],0.)]:
   cc={**c,'experiment':'irradiance','irradiance_after':irr,'ramp_ms':rmp,'step_ms':pre,'duration_ms':end}
   cases.append(dict(id=label,config=configuration(cc),duration_ms=end,
     description='日射変化と回復' if rmp else '一定日射での探索と揺れ'))
 # The public exact simulator has a work limit. Refuse an incomplete test;
 # never shorten the observation window to manufacture a passing answer.
 for case in cases:
  if case['duration_ms']*c['pwm_khz']>400000:
   raise ValueError('必要な検証窓が詳細PWMの400000周期上限を超えます。今回の設定は適用せず、周期/観測時間を確認してください。')
 return cases

def finite(v):return isinstance(v,(int,float)) and math.isfinite(v)

def measure(out,c,profile):
 """Only authoritative all-point metrics; never reconstruct from chart arrays."""
 m=out.get('tuning_metrics',{});p=PROFILES[profile]
 if not m.get('available') or not m.get('display_independent'):
  return dict(completed=False,accepted=False,score=1e6,error='Independent tuning metrics missing')
 complete=bool(m.get('completed') and m.get('finite'))
 peak=m.get('peak_current_a');vo=m.get('peak_output_voltage_v')
 r04=c['algorithm']=='c07_r04'
 if r04:
  # CHARGE_CURRENT_A is a reference ceiling; CHARGE_VOLTAGE_V is CV's
  # target. Neither is an instantaneous physical current/voltage trip.
  # There is no qualified L1 peak rating here. A separate matched-baseline
  # non-increase rule below compares actual L1/L2 peaks without inventing one.
  checks={'l1_current_finite':finite(peak),'input_current_finite':finite(m.get('peak_input_current_a')),
          'output_voltage_trip':finite(vo) and vo<c['c07_vout_trip_v'],
          'native_control_core_executed':out.get('controller',{}).get('source_control_core_executed') is True}
  physical=all(checks.values())
 else:
  physical=finite(peak) and finite(vo) and peak<=c['current_limit_a'] and vo<=c['output_voltage_limit_v']
  checks={'output_current':finite(peak) and peak<=c['current_limit_a'],
          'output_voltage':finite(vo) and vo<=c['output_voltage_limit_v']}
 if c['algorithm'] in ('libresolar','fugu'):
  ii=m.get('peak_input_current_a');vin=m.get('minimum_input_voltage_v')
  checks.update(input_current=finite(ii) and ii<=c['input_current_limit_a'],
                input_minimum_voltage=finite(vin) and vin>=c['input_voltage_limit_v'])
 if c['algorithm']=='fugu':
  power=m.get('peak_output_power_w');checks['output_power']=finite(power) and power<=c['power_limit_w']
 physical=bool(physical and all(checks.values()))
 result=dict(completed=complete,accepted=False,score=1e6,target_node=m.get('target_node'),
  evaluated_node=m.get('evaluation_power_node','PV_RAW') if c['experiment']=='irradiance' else m.get('target_node'),
  peak_current_a=peak,peak_output_voltage_v=vo,
  physical_limits_passed=physical,metrics_source=m.get('source'),display_independent=True,
  limit_checks=checks,limits_basis='Physical instantaneous extrema at all accepted points, including initial point; no ripple exemption or raised limits',
  peak_input_current_a=m.get('peak_input_current_a'),peak_output_power_w=m.get('peak_output_power_w'),
  minimum_input_voltage_v=m.get('minimum_input_voltage_v'),
  tracking=m.get('tracking'),raw_tracking=m.get('raw_tracking'),mppt=m.get('mppt'),
  duty_variation=m.get('duty_variation'),interval=m.get('interval'))
 if r04:
  result.update(limits_basis='Configured Vout trip plus finite native/model execution. L1/L2 physical current peaks are compared with the same-condition baseline; no hardware peak-current limit is inferred.',
   limit_semantics=dict(current_reference_ceiling_a=c['current_limit_a'],cv_target_v=c['output_voltage_limit_v'],
    output_voltage_trip_v=c['c07_vout_trip_v'],input_foldback_target_a=c['input_current_limit_a'],
    peak_current_node='L1',peak_input_current_node='L2' if c['plant_mode']=='c07' else 'PV_RAW',
    hardware_current_safety_verified=False),
   current_reference_exceeded=finite(peak) and peak>c['current_limit_a'],
   input_foldback_target_exceeded=finite(m.get('peak_input_current_a')) and m['peak_input_current_a']>c['input_current_limit_a'],
   native_control_core_executed=checks['native_control_core_executed'])
 a,b,d,e,r=p['weights']
 if c['experiment']=='voltage':
  t=m.get('tracking',{});amp=max(t.get('amplitude_v',0.),.1);span=max(t.get('evaluation_span_s',0.),1e-9)
  required=['iae_v_s','tail_max_error_v','tail_range_v','overshoot_v','final_error_v']
  if not all(finite(t.get(k)) for k in required):return result
  iae=t['iae_v_s']/(amp*span);tail=t['tail_max_error_v']/amp;over=max(0.,t['overshoot_v'])/amp
  settle=t.get('settling_ms');stationary=(modes(c)[0]=='P' and t['tail_range_v']<=max(.05,.04*amp) and tail<=.5)
  allowed=max(.2,.08*amp,c['voltage_deadband_v'] if c['algorithm']=='libresolar' or c['algorithm']=='custom' and c['custom_topology']=='direct_duty' else 0.)
  accepted=bool(complete and physical and t.get('tail_observed') and (settle is not None or stationary)
    and (t['tail_max_error_v']<=allowed or stationary) and t['overshoot_v']<=max(.03,p['overshoot_fraction']*amp))
  score=a*iae+b*(settle/(1000*span) if finite(settle) else 2.)+d*over+e*tail+r*min(20.,float(m.get('duty_variation') or 0.))
  result.update(settling_ms=settle,overshoot_pct=100*over,final_error_v=t['final_error_v'],
    tail_max_error_v=t['tail_max_error_v'],mean_absolute_error_v=iae*amp,stationary_with_offset=stationary and settle is None,
    voltage_band_v=t.get('voltage_band_v'),overshoot_limit_pct=100*p['overshoot_fraction'])
 else:
  t=m.get('mppt',{});energy=t.get('available_energy_j');eff=t.get('tracking_efficiency_pct')
  if not finite(energy) or energy<=0 or not finite(eff):return result
  mean=t.get('hold_power_mean_w');ripple=t.get('hold_power_range_w')
  interval=m.get('interval',{})
  interval_span=max(0.,(interval.get('end_ms',c['duration_ms'])-interval.get('start_ms',c['step_ms']))*.001)
  required_hold=t.get('hold_required_s')
  hold=bool(finite(required_hold) and required_hold>0 and
            t.get('hold_observed_s',0.)+1e-9>=required_hold)
  ripple_norm=ripple/max(mean,1.) if finite(ripple) and finite(mean) else 10.
  loss=max(0.,t['energy_deficit_j']/energy);recovery=t.get('recovery_ms')
  span=max(.001,interval_span)
  # 90% is a finite diagnostic gate, not a global MPP or all-weather claim.
  # Current/CV-limited cases may not reach it; never move those safety limits.
  ripple_cap={'speed':.20,'balanced':.12,'gentle':.06}[profile]
  accepted=bool(complete and physical and hold and eff>=90. and ripple_norm<=ripple_cap)
  score=a*loss+b*(recovery/(1000*span) if finite(recovery) else 1.5)+d*ripple_norm+r*min(20.,float(m.get('duty_variation') or 0.))
  result.update(tracking_efficiency_pct=eff,energy_deficit_j=t['energy_deficit_j'],recovery_ms=recovery,
    hold_observed=hold,hold_power_ripple_fraction=ripple_norm,hold_ripple_limit_fraction=ripple_cap)
 if not accepted:score+=100.+(0. if complete else 100.)+(0. if physical else 100.)
 result.update(accepted=accepted,score=float(score))
 if r04:
  reasons=[]
  if not complete:reasons.append('計算または観測窓が未完了')
  if not physical:reasons.append('有限値・C制御実行・出力電圧停止しきい値の確認不成立')
  if c['experiment']=='voltage':
   if not t.get('tail_observed'):reasons.append('終端の観測不足')
   if settle is None and not stationary:reasons.append('所定の誤差帯で20 ms以上の保持を確認できない')
   if t['tail_max_error_v']>allowed and not stationary:reasons.append('終端の電圧誤差が許容帯を超える')
   if t['overshoot_v']>max(.03,p['overshoot_fraction']*amp):reasons.append('選択方針の行き過ぎ条件を超える')
  else:
   if not hold:reasons.append('一定日射時の保持窓が不足')
   if eff<90.:reasons.append('MPP捕集率が検証条件90%に届かない')
   if ripple_norm>ripple_cap:reasons.append('一定日射時の電力の揺れが選択方針の条件を超える')
  result['rejection_reasons']=reasons
 return result

def r04_current_comparison(candidate,baseline):
 """Finite matched-case non-regression policy, NOT a hardware ampere rating.

 A 1 mA absolute / 0.01% relative tolerance covers tiny deterministic solver
 differences; it is reported, not presented as permission for extra current.
 Baseline completeness and current values are required for each case.
 """
 checks={};valid=bool(baseline.get('completed'))
 for key in ('peak_current_a','peak_input_current_a'):
  old=baseline.get(key);new=candidate.get(key)
  tolerance=max(.001,abs(old)*1e-4) if finite(old) else .001
  passed=bool(valid and finite(old) and finite(new) and new<=old+tolerance)
  checks[key]=dict(baseline_a=old,candidate_a=new,tolerance_a=tolerance,passed=passed)
 ok=all(x['passed'] for x in checks.values())
 candidate['comparison_checks']=checks
 candidate['current_peak_comparison_passed']=ok
 candidate['current_peak_comparison_basis']='Same-condition L1 and input L2 (PV_RAW in simple plant) maxima; numerical tolerance only, not a hardware current safety rating.'
 if not ok:
  candidate['accepted']=False;candidate['score']+=100.
  candidate.setdefault('rejection_reasons',[]).append('L1または入力L2電流ピークが同じ条件の変更前を超える')
 return candidate

def combine(rows):
 if not rows:return dict(accepted=False,completed=False,score=1e6,cases=[])
 # Worst-case term prevents an improvement in one direction hiding damage in
 # the opposite direction. All scenarios must independently pass.
 scores=[r['score'] for r in rows]
 result=dict(accepted=all(r['accepted'] for r in rows),completed=all(r['completed'] for r in rows),
             score=sum(scores)/len(scores)+.25*max(scores),cases=rows)
 nodes=list(dict.fromkeys(r.get('evaluated_node') for r in rows))
 result['evaluated_node']=nodes[0] if len(nodes)==1 else nodes
 targets=list(dict.fromkeys(r.get('target_node') for r in rows))
 result['target_node']=targets[0] if len(targets)==1 else targets
 for key in ('settling_ms','overshoot_pct','peak_current_a','peak_input_current_a','peak_output_voltage_v','tail_max_error_v',
             'energy_deficit_j','recovery_ms','hold_power_ripple_fraction'):
  vals=[r.get(key) for r in rows if finite(r.get(key))]
  result[key]=max(vals) if vals else None
 for key in ('tracking_efficiency_pct',):
  vals=[r.get(key) for r in rows if finite(r.get(key))];result[key]=min(vals) if vals else None
 result['mpp_settling_ms']=result.get('recovery_ms')
 return result
