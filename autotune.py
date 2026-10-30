"""Bounded all-method tuning. Average screening and full-PWM acceptance differ.

No physical setting is replaced. This is a local finite experiment, not a
global optimum, stability certificate or reproduction of maker tuning.
"""
from __future__ import annotations
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import threading
import time
import numpy as np
from engine import configuration,SimulationCancelled
from tuning_design import (PROFILES,capability,clip_patch,calculation_candidates,
                          optimization_bounds,PD_BRANCHES)
from tuning_search import scenarios,measure,combine,r04_current_comparison

MAX_CHEAP_EVALUATIONS=8
MAX_EVALUATIONS=MAX_CHEAP_EVALUATIONS+8
MAX_WALL_SECONDS=240.
CHEAP_WALL_SECONDS=110.
MAX_FINALISTS=1
_CACHE=OrderedDict()
_CACHE_LOCK=threading.Lock()
_CACHE_LIMIT=384

def simulate_tuning(*args,**kwargs):
 from tuning_simulator import simulate_tuning as run
 return run(*args,**kwargs)

def simulate_detailed(*args,**kwargs):
 from tuning_simulator import simulate_detailed as run
 return run(*args,**kwargs)

def clear_cache():
 with _CACHE_LOCK:_CACHE.clear()

def source_identity():
 base=Path(__file__).resolve().parent
 names=['autotune.py','tuning_design.py','tuning_search.py','tuning_simulator.py','tuning_metrics.py',
        'controllers.py','plant.py','experiments.py','engine_v3.py','c07_r04.py',
        'native/c07_r04/c07_control.c','native/c07_r04/c07_control.h',
        'native/c07_r04/lab_bridge.c','native/c07_r04/c07_lab.dll']
 return hashlib.sha256(b''.join((base/name).read_bytes() for name in names if (base/name).exists())).hexdigest()

def _cache_key(c,kind,identity):
 return identity,kind,json.dumps(c,sort_keys=True,separators=(',',':'),allow_nan=False)

def _cached(key):
 with _CACHE_LOCK:
  if key not in _CACHE:return None
  item=_CACHE.pop(key);_CACHE[key]=item;return deepcopy(item)

def _remember(key,out):
 small={k:deepcopy(out[k]) for k in ('tuning_metrics','tuning_diagnostics','diagnostics') if k in out}
 if 'controller' in out:
  small['controller']={k:deepcopy(out['controller'][k]) for k in
   ('source_control_core_executed','source_firmware_executed','r04_async','r04_mppt',
    'core_sha256','core_library_sha256','native_configuration_readback') if k in out['controller']}
 with _CACHE_LOCK:
  _CACHE[key]=small;_CACHE.move_to_end(key)
  while len(_CACHE)>_CACHE_LIMIT:_CACHE.popitem(last=False)

def _signature(patch):return tuple((k,float(v)) for k,v in sorted(patch.items()))
class _BudgetEnded(Exception):pass

def tune_gains(values,profile='balanced',cancelled=None,progress=None):
 """Preserves async job API; gain_keys includes algorithm steps and PD gains."""
 if profile not in PROFILES:raise ValueError('調整方針は balanced / speed / gentle から選んでください。')
 c=configuration(deepcopy(values));cap=capability(c);started=time.perf_counter();identity=source_identity()
 result=dict(status='unsupported',profile=profile,patch={},changes={},before=None,after=None,trial=None,cases=[],
  gain_keys=cap['gain_keys'],tunable_keys=cap['tunable_keys'],capability=cap,notes=[],evaluations=[],
  detailed_validated=False,pwm_validated=False,source_sha256=identity,
  method='局所計算 → 実制御器の平均モデル探索 → 詳細PWMで独立した複数条件の確認',
  validation_scope=dict(summary='選択回路・固定物理値での有限時間局所検証。全域最適・実機保証ではありません。'),
  approximation=dict(screening='CCM ON/OFF average, actual controller and modeled ADC/CPU/latch schedule',
   acceptance='Detailed explicit PWM, independent all-point metrics',global_optimum=False))
 if not cap['supported']:result['reason']=cap['reason'];return result
 if c['algorithm']=='c07_r04':
  pwm='有限PIO' if c['c07_pwm_packet_cycles']>0 else '連続PWM'
  pwm_en='finite-PIO packets' if c['c07_pwm_packet_cycles']>0 else 'continuous PWM'
  result['safety_model']=cap['safety_model']
  result['method']=f'r04実C制御の局所候補 → 平均モデルで数値探索 → {pwm}の詳細波形で両方向/日射を確認'
  result['approximation']['screening']=f'Native r04 C core, 8-channel ADC, IRQ/background, configured {pwm_en}; averaged switch edges only'
  result['approximation']['acceptance']=f'Native r04 C core and explicit {pwm_en}, independent physical-node all-point metrics'
 def check():
  if cancelled and cancelled():raise SimulationCancelled()
 def report(stage,message):
  check()
  if progress:progress(dict(stage=stage,completed=len(result['evaluations']),total=MAX_EVALUATIONS,message=message))
 def remaining():return MAX_WALL_SECONDS-(time.perf_counter()-started)
 check();report('calculation','使う係数と、両方向または日射・一定条件の検証を準備しています。')
 try:cases=scenarios(c)
 except ValueError as exc:
  result.update(status='validation_failed',reason=str(exc),elapsed_ms=(time.perf_counter()-started)*1000,evaluation_count=0)
  return result
 result['cases']=[dict(id=x['id'],description=x['description'],**{k:x['config'][k] for k in
   ('v_start','v_target','irradiance','irradiance_after','step_ms','ramp_ms','duration_ms')}) for x in cases]
 result['trial']=result['cases'][0]
 result['validation_scope'].update(cases=[x['id'] for x in cases],
  parameters_held_fixed='Physical circuit, sensors, ADC/CPU/PWM timing, limits, controller mode, model delay',
  target_policy='Actual controller target node for voltage; physical PV_RAW energy for MPPT',
  mppt_stimulus_note='Diagnostic irradiance ramp is at least 20 ms; original stimulus remains in UI configuration.')
 screening_cases=[deepcopy(cases[0])]
 if c['experiment']=='voltage' and c['algorithm'] not in ('libresolar','fugu') and not (c['algorithm']=='custom' and c['custom_topology']=='direct_duty'):
  from tuning_design import effective_timing
  vp,_,_=effective_timing(c)
  short_end=screening_cases[0]['config']['step_ms']+max(90. if c['algorithm']=='c07_r04' else 55.,20*vp*1000,20*c['sense_tau_us']*.001)
  screening_cases[0]['config']['duration_ms']=min(screening_cases[0]['config']['duration_ms'],short_end)
 result['validation_scope']['screening']='One representative disturbance, possibly shorter window; detailed acceptance always uses every listed case.'
 original={k:c[k] for k in cap['tunable_keys']};cheap=[];seen=set();cache_hits=full_calls=cheap_calls=0
 baseline_rows={}

 def run_one(cc,kind,case_id,*,capture=False,snapshot=None,end_ms=None):
  nonlocal cache_hits,full_calls,cheap_calls
  check()
  if remaining()<.1:raise _BudgetEnded()
  key=_cache_key(cc,kind,identity)
  out=_cached(key) if not capture and snapshot is None and end_ms is None else None
  if out is not None:cache_hits+=1
  else:
   runner=simulate_tuning if kind=='averaged' else simulate_detailed
   timeout=max(.05,min(35. if kind=='averaged' and capture else (5. if kind=='averaged' else 30.),remaining()))
   kwargs=dict(timeout=timeout,cancelled=cancelled,detail='summary')
   if capture:kwargs['capture_state']=True
   if snapshot is not None:kwargs['initial_snapshot']=snapshot
   if end_ms is not None:kwargs['duration_override']=end_ms
   try:out=runner(cc,**kwargs)
   except SimulationCancelled:raise
   except (ValueError,ArithmeticError,OverflowError,RuntimeError) as exc:
    out={'tuning_metrics':{},'diagnostics':{'error':str(exc)}}
   if kind=='averaged':cheap_calls+=1
   else:full_calls+=1
   if out.get('tuning_metrics',{}).get('completed') and not capture and snapshot is None and end_ms is None:_remember(key,out)
  measured=measure(out,cc,profile);measured.update(case_id=case_id)
  uncertainty=bool(out.get('diagnostics',{}).get('dcm_domain_warning'))
  measured['averaged_domain_warning']=uncertainty
  if kind=='averaged' and uncertainty:
   measured['accepted']=False
   measured['fidelity_note']='CCM average reached a possible DCM boundary; only detailed PWM can accept this candidate.'
  if 'error' in out.get('diagnostics',{}):measured['error']=out['diagnostics']['error']
  return measured,out

 def evaluate(label,patch,kind='averaged'):
  patch=clip_patch(c,{**original,**patch});signature=_signature(patch)
  if kind=='averaged':
   if signature in seen:return next((x for x in cheap if x['signature']==signature),None)
   if len(cheap)>=MAX_CHEAP_EVALUATIONS or time.perf_counter()-started>CHEAP_WALL_SECONDS:raise _BudgetEnded()
   seen.add(signature)
  report('optimization' if kind=='averaged' else 'pwm_validation',
   ('平均モデルで候補を比較しています。' if kind=='averaged' else '詳細PWMで複数条件を確認しています。')+' '+label)
  rows=[];diagnostics=[]
  for case in screening_cases if kind=='averaged' else cases:
   cc=configuration({**case['config'],**patch});row,out=run_one(cc,kind,case['id']);rows.append(row)
   if c['algorithm']=='c07_r04' and kind=='detailed_pwm':
    baseline_key=(kind,case['id'])
    if signature==_signature(original):baseline_rows[baseline_key]=deepcopy(row)
    else:r04_current_comparison(row,baseline_rows.get(baseline_key,{}))
   diagnostics.append(out.get('tuning_diagnostics',{}))
  item=dict(index=len(result['evaluations'])+1,label=label,stage=kind,patch=patch,**combine(rows),
            diagnostics=diagnostics,signature=signature)
  result['evaluations'].append({k:v for k,v in item.items() if k!='signature'})
  if kind=='averaged':cheap.append(item)
  return item

 def long_fugu(patch,label):
  cc=configuration({**c,**patch,'experiment':'irradiance','irradiance_after':c['irradiance'],
   'ramp_ms':0.,'step_ms':10.,'duration_ms':min(1000.,400000/c['pwm_khz'])})
  report('history','FUGUの30秒を超える履歴と速度切替を確認しています。 '+label)
  assessed,out=run_one(cc,'averaged','fugu_history',capture=True,end_ms=35000.)
  diag=out.get('tuning_diagnostics',{})
  summary=dict(label=label,completed=bool(out.get('tuning_metrics',{}).get('completed')),
   slow_enter_ms=diag.get('slow_enter_ms'),slow_samples=diag.get('slow_samples',0),diagnostics=diag,
   history_solver='averaged; requested 35000 ms without skipping controller clocks',
   requested_end_ms=35000.,observed_end_ms=out.get('tuning_metrics',{}).get('interval',{}).get('end_ms'),
   metrics=out.get('tuning_metrics',{}),patch=patch)
  summary['averaged_domain_warning']=assessed.get('averaged_domain_warning',False)
  summary['history_valid']=bool(summary['completed'] and not summary['averaged_domain_warning'])
  # A short switched continuation cannot repair an invalid preceding average
  # history. Retain its receipt, but do not use that physical/controller state.
  return summary,out.get('snapshot') if summary['history_valid'] else None

 history=[];long_states={};active=set(cap['tunable_keys'])
 try:
  first=evaluate('current settings',original)
  seeds,model=calculation_candidates(c,profile);result['seed_model']=model
  if c['algorithm']=='fugu':
   limiting=set()
   for diag in first['diagnostics']:limiting.update(k for k,n in diag.get('pd_limiting_counts',{}).items() if n>0)
   if c['experiment']=='irradiance':
    h,snap=long_fugu(original,'current settings');history.append(h);long_states[_signature(original)]=(h,snap)
    limiting.update(k for k,n in h['diagnostics'].get('pd_limiting_counts',{}).items() if n>0)
    active-={'fugu_slow_speed','fugu_slow_period_ms'}
   for branch,prefix in PD_BRANCHES.items():
    if branch not in limiting:active-={'fugu_'+prefix+'_kp','fugu_'+prefix+'_kd'}
    else:
     for factor in (.6,1.4):seeds.append(('observed '+branch+' PD',{'fugu_'+prefix+'_kp':c['fugu_'+prefix+'_kp']*factor,'fugu_'+prefix+'_kd':c['fugu_'+prefix+'_kd']*factor}))
   result['active_branches']=sorted(limiting)
   result['inactive_parameters_held']=[k for k in cap['tunable_keys'] if k not in active]
  result['optimized_keys']=sorted(active)
  for label,patch in seeds[:3]:
   patch={k:v for k,v in patch.items() if k in active}
   if patch:evaluate(label,patch)
  # Integer compare counts use neighboring lattice points, not a continuous
  # variable whose hidden rounding would make an alleged gradient meaningless.
  if 'libre_step_counts' in active:
   best=min(cheap,key=lambda x:x['score'])
   for offset in (-1,1):evaluate('integer CCR neighboring count',{**best['patch'],'libre_step_counts':best['patch']['libre_step_counts']+offset})
  best=min(cheap,key=lambda x:x['score']);keys=sorted(active-{'libre_step_counts'})
  boxes={k:optimization_bounds({**c,**best['patch']},k) for k in keys}
  def encode(k,v):
   lo,hi=boxes[k]
   if lo>0:return math.log(max(lo,min(hi,v))/lo)/math.log(hi/lo) if hi>lo else .5
   if hi<0:return math.log(abs(max(lo,min(hi,v)))/abs(hi))/math.log(abs(lo/hi)) if lo<hi else .5
   return (v-lo)/(hi-lo) if hi>lo else .5
  def decode(k,x):
   lo,hi=boxes[k]
   if lo>0:return lo*(hi/lo)**x
   if hi<0:return hi*(lo/hi)**x
   return lo+x*(hi-lo)
  base=dict(best['patch'])
  def objective(x):
   check();item=evaluate('bounded continuous local search',{**base,**{k:decode(k,float(v)) for k,v in zip(keys,x)}})
   return item['score'] if item else 1e6
  if keys and len(cheap)<MAX_CHEAP_EVALUATIONS:
   # A very short coordinate line search would spend the entire budget on
   # the first gain. Two-sided simultaneous perturbation probes every active
   # coordinate, then computes a bounded continuous joint step. The gradient
   # estimate is noisy for switched/nonsmooth objectives; keep every better
   # observed candidate and never call this a convergence/global certificate.
   x=np.array([encode(k,base[k]) for k in keys]);iterations=0;searched=set()
   rng=np.random.default_rng(20261031)
   while MAX_CHEAP_EVALUATIONS-len(cheap)>=3 and iterations<2:
    direction=rng.choice(np.array([-1.,1.]),size=len(keys));radius=.12/(iterations+1)**.101
    xp=np.clip(x+radius*direction,0.,1.);xm=np.clip(x-radius*direction,0.,1.)
    fp=objective(xp);fm=objective(xm);searched.update(k for k,p,m in zip(keys,xp,xm) if p!=m)
    delta=xp-xm;gradient=np.divide(fp-fm,delta,out=np.zeros_like(delta),where=abs(delta)>1e-12)
    norm=float(np.linalg.norm(gradient))
    if norm>0:
     proposal=np.clip(x-.22/(iterations+1)**.602*gradient/norm,0.,1.)
     objective(proposal)
    else:
     # Flat objective is explicitly flat, not an invented improvement.
     break
    best_local=min(cheap,key=lambda row:row['score']);x=np.array([encode(k,best_local['patch'][k]) for k in keys])
    iterations+=1
   result['optimizer']=dict(method='bounded two-sided simultaneous perturbation and continuous joint steps',
    success=False,message='Finite local budget; convergence is not certified',iterations=iterations,
    continuous_keys=keys,searched_keys=sorted(searched),local_bounds=boxes,random_seed=20261031,
    global_optimum=False)
 except _BudgetEnded:result['notes'].append('平均モデル探索の計算量・時間上限に達したため、完了した候補から選びます。')
 check()
 if not cheap:
  result.update(status='validation_failed',reason='平均モデルの比較を完了できませんでした。設定は変更しません。')
 else:
  try:
   before=evaluate('current settings: detailed PWM',original,'detailed_pwm')
   result['before']={k:v for k,v in before.items() if k not in ('signature','patch','index','label','stage')}
   finalists=[x for x in sorted(cheap,key=lambda x:x['score']) if x['signature']!=_signature(original)][:MAX_FINALISTS]
   best_full=before;slow_improves=False
   for candidate in finalists:
    full=evaluate(candidate['label']+': detailed PWM',candidate['patch'],'detailed_pwm')
    if c['algorithm']=='c07_r04':
     result['candidate_validation']=dict(accepted=full['accepted'],cases=deepcopy(full['cases']),patch=full['patch'])
     reasons=list(dict.fromkeys(reason for row in full['cases'] for reason in row.get('rejection_reasons',[])))
     if reasons:result['notes'].append('r04候補の不採用条件: '+' / '.join(reasons))
    if full['accepted'] and (not best_full['accepted'] or full['score']<best_full['score']):best_full=full
   if c['algorithm']=='fugu' and c['experiment']=='irradiance':
    selected_patch=best_full['patch'];selected_sig=_signature(selected_patch)
    if selected_sig not in long_states:
     h,snap=long_fugu(selected_patch,'best fast candidate');history.append(h);long_states[selected_sig]=(h,snap)
    h,snap=long_states[selected_sig]
    if h.get('completed') and h.get('slow_samples',0)>0 and snap is not None:
     slow_candidates=[original] if selected_sig!=_signature(original) else []
     slow_candidates.append(selected_patch)
     for key,factor in [('fugu_slow_speed',.6),('fugu_slow_period_ms',1.5)]:
      slow_candidates.append(clip_patch(c,{**selected_patch,key:selected_patch[key]*factor}))
     slow_best=None;overlaps={}
     for patch in slow_candidates:
      sig=_signature(patch)
      if sig not in long_states:
       hh,ss=long_fugu(patch,'slow branch candidate');history.append(hh);long_states[sig]=(hh,ss)
      hh,ss=long_states[sig]
      if not hh['completed'] or hh['slow_samples']==0 or ss is None:continue
      end_ms=float(ss['t'])*1000+max(700.,3*patch['fugu_slow_period_ms'])
      row,overlap_out=run_one(ss['config'],'detailed_pwm','fugu_slow_overlap',snapshot=ss,end_ms=end_ms)
      row['slow_samples']=overlap_out.get('tuning_diagnostics',{}).get('slow_samples',0)
      row['accepted']=bool(row['accepted'] and row['slow_samples']>0)
      overlaps[sig]=row
      hh['pwm_overlap']=row;hh['pwm_overlap_scope']='Only continuation window is explicit PWM; preceding 35 s is averaged.'
      if row['accepted'] and (slow_best is None or row['score']<slow_best[0]):slow_best=(row['score'],patch,row)
     if slow_best:
      chosen=slow_best[1]
      if _signature(chosen)!=_signature(best_full['patch']):
       full=evaluate('slow candidate: short detailed cases',chosen,'detailed_pwm')
       if full['accepted'] and full['score']<=best_full['score']*1.01:
        base_overlap=long_states[selected_sig][0].get('pwm_overlap',{})
        if not base_overlap.get('accepted') or slow_best[0]<base_overlap.get('score',1e6)*.99:best_full=full
      chosen_overlap=overlaps.get(_signature(best_full['patch']),{})
      original_overlap=overlaps.get(_signature(original),{})
      if not chosen_overlap.get('accepted'):
       best_full=before
       result['notes'].append('採用候補のslow継続窓が合格しないため、設定は変更しません。')
      else:
       result['validation_scope']['fugu_slow_overlap']=chosen_overlap
       result['validation_scope']['fugu_original_slow_overlap']=original_overlap
       slow_improves=(best_full is not before and best_full['score']<=before['score']*1.01 and
        (not original_overlap.get('accepted') or chosen_overlap['score']<original_overlap.get('score',1e6)*.99))
     else:
      best_full=before;result['notes'].append('FUGUのslow履歴からの詳細PWM継続検証が不成立のため、候補を適用しません。')
    else:
     result['notes'].append('要求した35秒の履歴でslow動作の完了確認ができませんでした。実際の終了時刻は履歴に表示し、slow速度・周期は変更せず、検証範囲をfastに限定します。')
    result['fugu_history']=history
   improves=best_full is not before and best_full['accepted'] and (not before['accepted'] or best_full['score']<before['score']*.99 or slow_improves)
   result['slow_objective_improved']=bool(slow_improves)
   result['status']='ok' if improves else 'no_improvement';selected=best_full if improves else before
   result['after']={k:v for k,v in selected.items() if k not in ('signature','patch','index','label','stage')}
   result['detailed_validated']=result['pwm_validated']=bool(selected['accepted'])
   if improves:
    result['patch']={k:v for k,v in best_full['patch'].items() if v!=c[k]}
    result['changes']={k:dict(before=c[k],after=v) for k,v in result['patch'].items()}
   result['reason']=('詳細PWMの全条件を満たし、現在より評価が改善した候補が見つかりました。' if improves else
    '今回の有限な探索範囲では、詳細PWMの全条件を満たす改善を確認できませんでした。設定は変更しません。')
  except _BudgetEnded:
   result.update(status='candidate_only',reason='詳細PWMの全条件を時間内に確認できなかったため、候補は適用しません。',patch={},changes={},detailed_validated=False,pwm_validated=False)
 result['notes'] += [
  '順位は選択した回路・初期点・検証時間に対するものです。全動作範囲での最適値、遅延余裕、実機の安定性を保証しません。',
  '平均モデルにはPWMリップルがありません。採用判定の電流・電圧ピークは詳細PWMの全受理点で確認します。',
  ('回路値、測定/演算/PWM時刻、安全限界、制御構造、MPPT設定は固定し、r04のPV電圧/L1電流ゲインだけを返します。' if c['algorithm']=='c07_r04' else
   '回路値、測定/演算/PWM時刻、安全限界、制御構造、model_delayは固定します。制御係数と探索刻み・判断周期だけを返します。'),
  '検証で作動しなかった制限器や、FUGUの未到達の履歴状態の改善は主張しません。']
 if c['algorithm']=='c07_r04':
  result['notes'] += ['r04は外側PV電圧PID/PIと内側L1電流PIのゲインだけを調整します。MPPTの設定・参照重み・フィルター・CVゲイン・周期・有限PIOパケットは固定です。',
   '15 Aは電流目標上限、57.1 VはCV目標です。瞬時ピークの部品許容値には置き換えません。候補のL1/入力L2電流ピークは同じ条件の変更前以下（数値誤差許容を明記）を要求します。',
   '実行するのは正常ON時のC制御本体です。基板の起動、ARM/割り込み実行、故障ラッチ、実部品のピーク電流許容を検証した結果ではありません。']
 result.update(elapsed_ms=(time.perf_counter()-started)*1000,evaluation_count=len(result['evaluations']),
  candidate_counts=dict(averaged_candidates=len(cheap),averaged_runs=cheap_calls,detailed_runs=full_calls,cache_hits=cache_hits),
  cache_policy='Source+complete config+solver keyed, profile-independent all-point metrics; no chart/snapshot caching')
 report('complete',result.get('reason','自動調整の検証を終了しました。'))
 json.dumps(result,allow_nan=False)
 return result

_measure=measure
