"""Calculation-led seeds and explicit, architecture-specific tuning boundaries.

The sampled linearization is a local CCM seed model, not the acceptance model.
In particular, asynchronous ADC/CPU queues and different loop clocks are checked
by the actual-controller simulators, not certified by these seed calculations.
"""
from __future__ import annotations

import math
import numpy as np
from scipy.linalg import expm
from engine import LIMITS, Panel, configuration
import plant

PROFILES = {
 'balanced': dict(label='バランス',phase_deg=60.,overshoot_fraction=.15,
                  weights=(2.,.8,4.,3.,.15)),
 'speed': dict(label='速度重視',phase_deg=50.,overshoot_fraction=.30,
               weights=(4.,3.,1.,3.,.05)),
 'gentle': dict(label='行き過ぎを抑える',phase_deg=75.,overshoot_fraction=.05,
                weights=(1.,.25,15.,3.,.8)),
}
PD_BRANCHES = dict(VIN_MIN='vin',VOUT_MAX='vout',IIN_MAX='iin',IOUT_MAX='iout',POWER_MAX='power')

def modes(c):
 if c['algorithm']=='baseline':return c['mode'],None
 if c['algorithm'] in ('ti','plexim'):return 'PI','PI'
 if c['algorithm']=='c07_r04':return c['voltage_mode'],'PI'
 if c['algorithm']=='custom' and c['custom_law']=='pid' and c['custom_topology']!='direct_duty':
  return c['voltage_mode'], c['current_mode'] if c['custom_topology']=='voltage_current' else None
 return None,None

def tunable_keys(c):
 a=c['algorithm']; vm,im=modes(c); keys=[]
 if a=='c07_r03':return []
 if a=='baseline':
  keys=['kp']+(['ti_ms'] if vm!='P' else [])+(['td_ms'] if vm=='PID' else [])
 elif vm:
  for loop,mode in [('voltage',vm),('current',im)]:
   if mode: keys += [loop+'_kp']+([loop+'_ki'] if mode!='P' else [])+([loop+'_kd'] if mode=='PID' else [])
 elif a=='libresolar':keys=['libre_step_counts','mppt_period_ms']
 elif a=='fugu':
  keys=(['fugu_fast_speed','mppt_period_ms','fugu_slow_speed','fugu_slow_period_ms']
        if c['experiment']=='irradiance' else ['fugu_voltage_kp'])
  keys += ['fugu_'+name+'_'+term for name in PD_BRANCHES.values() for term in ('kp','kd')]
 elif a=='opensec' or a=='custom' and c['custom_law']=='model':
  keys=['model_voltage_gain','model_current_gain']
 elif a=='custom' and c['custom_topology']=='direct_duty':
  keys=['mppt_step_duty','mppt_period_ms']
 if a!='c07_r04' and c['experiment']=='irradiance' and (vm or a=='opensec' or a=='custom' and c['custom_law']=='model'):
  keys+=['mppt_step_v','mppt_period_ms']
  if a=='opensec':keys+=['opensec_max_step_v']
 return list(dict.fromkeys(keys))

def capability(values):
 c=configuration(values); keys=tunable_keys(c)
 supported=bool(keys) and c['duty_response_gain']>0
 pwm='有限PIO' if c.get('c07_pwm_packet_cycles',0)>0 else '連続PWM'
 reason=(f'r04の実C制御本体で外側のPV電圧{c["voltage_mode"]}と内側のL1電流PIのゲインを調整し、{pwm}の詳細波形で確認します。MPPT・周期・フィルター・目標重みは固定します。' if c['algorithm']=='c07_r04' else
          'c07 r03 は、ユーザー指定により今回の自動調整の対象から除外しています。' if c['algorithm']=='c07_r03' else
         'Duty反映倍率が0のため、追従補正を比較できません。' if not supported else
         'この方式で実際に使う係数・探索刻み・判断周期だけを調整し、詳細PWMで確認できた候補を返します。')
 result=dict(supported=supported,gain_keys=keys,tunable_keys=keys,
  parameter_specs={k:dict(min=LIMITS[k][0],max=LIMITS[k][1],integer=k=='libre_step_counts') for k in keys},
  objective='mpp' if c['experiment']=='irradiance' else 'voltage',
  stages=['calculation','averaged_screening','bounded_local_optimization','detailed_pwm_validation'],
  profiles=list(PROFILES),reason=reason)
 if c['algorithm']=='c07_r04':
  result.update(safety_model='Configured Vout trip and finite model/native execution; candidate physical L1/input-L2 current peaks must not exceed the baseline (PV_RAW input in the simple plant). This is a comparison rule, not a hardware current rating.',
   held_fixed=['physical circuit','ADC/IRQ/PIO timing','MPPT settings','reference weight','filters','CV gains','limits'],
   controller_implementation=f'r04 native C, weighted outer PV {c["voltage_mode"]} and inner L1 PI')
 return result

def clip_patch(c,patch):
 allowed=set(tunable_keys(c)); out={}
 for key,value in patch.items():
  if key not in allowed:raise ValueError('Inactive or physical tuning key: '+key)
  if not math.isfinite(float(value)):raise ValueError('Nonfinite tuning value: '+key)
  value=float(np.clip(value,*LIMITS[key]))
  out[key]=int(round(value)) if key=='libre_step_counts' else value
 if c['algorithm']=='opensec':
  # The controller clips base to maximum; retaining this order makes the two
  # independently exposed quantities interpretable instead of hiding clipping.
  if out.get('mppt_step_v',c['mppt_step_v'])>out.get('opensec_max_step_v',c['opensec_max_step_v']):
   out['mppt_step_v']=out.get('opensec_max_step_v',c['opensec_max_step_v'])
 return out

def components(c):
 vm,im=modes(c)
 if c['algorithm']=='baseline':
  return (c['kp'], c['kp']/(c['ti_ms']*.001) if vm!='P' else 0.,c['kp']*c['td_ms']*.001 if vm=='PID' else 0.),None
 return ((c['voltage_kp'],c['voltage_ki'] if vm!='P' else 0.,c['voltage_kd'] if vm=='PID' else 0.),
         (c['current_kp'],c['current_ki'] if im!='P' else 0.,c['current_kd'] if im=='PID' else 0.) if im else None)

def gains_patch(c,v,i=None):
 vm,im=modes(c); p,ki,kd=v
 if c['algorithm']=='baseline':
  patch={'kp':p}
  if vm!='P':patch['ti_ms']=1000*p/max(ki,1e-15)
  if vm=='PID':patch['td_ms']=1000*kd/max(p,1e-15)
 else:
  patch={}
  for prefix,mode,gains in [('voltage',vm,v),('current',im,i)]:
   if mode:
    patch[prefix+'_kp']=gains[0]
    if mode!='P':patch[prefix+'_ki']=gains[1]
    if mode=='PID':patch[prefix+'_kd']=gains[2]
 return clip_patch(c,patch)

def effective_timing(c):
 channels=8 if c['algorithm']=='c07_r04' else 4
 frame=(c['acquire_us']+(channels-1)*c['adc_channel_us']+c['transport_us'])*1e-6
 sample=max(c['control_us']*1e-6,frame if c['adc_channel_us'] else 0.,c['compute_us']*1e-6)
 def period(us):return max(1,math.ceil(us*1e-6/sample-1e-10))*sample
 vp=sample if c['algorithm']=='baseline' else period(c['voltage_period_us'])
 ip=period(c['current_period_us'])
 delay=frame+(c['compute_us']+c['apply_us'])*1e-6+.5/(c['pwm_khz']*1000)
 return vp,ip,delay

def r04_candidates(c,profile):
 """Local gain probes around the configured native controller.

 Weighted reference P, measurement D, tracking integrators, CV selection and
 finite PIO holding are not the generic sampled PI seed model. We therefore
 probe a bounded neighborhood and compute joint numerical search steps using
 the actual native controller. No pole/phase-margin claim is made here.
 """
 v,i=components(c);vp,ip,delay=effective_timing(c)
 factors={'speed':(1.,1.35,1.1),'balanced':(1.,.5,1.),'gentle':(1.,.3,1.)}[profile]
 def scale(vs,ins=1.):
  return gains_patch(c,tuple(x*s for x,s in zip(v,vs)),tuple(x*ins for x in i))
 candidates=[('native r04 profile-directed local probe',scale(factors)),
             ('native r04 lower integral probe',scale((1.,.3,1.))),
             ('native r04 current-loop damping probe',scale((1.,1.,1.),.7))]
 info=dict(method='native-controller local gain probes followed by bounded joint numerical optimization',
  analytic_gain_solution=False,feedback_node='PV_FUSED' if c['plant_mode']=='c07' else 'PV_RAW',
  current_feedback_node='L1',outer_mode=c['voltage_mode'],inner_mode='PI',
  reference_weight=c['c07_reference_weight'],derivative='filtered PV measurement derivative; no reference derivative',
  voltage_period_s=vp,current_period_s=ip,adc_frame_s=(c['acquire_us']+7*c['adc_channel_us']+c['transport_us'])*1e-6,
  adc_channels=8,nominal_measurement_to_command_delay_s=delay,
  packet_cycles=c['c07_pwm_packet_cycles'],
  timing_scope='Eight sequential ADC channels, native IRQ/background and finite PIO hold are simulated, not replaced by a uniform-delay PI model.',
  scope='Local probes, not stored absolute gain sets or an analytic optimum; final acceptance uses independent detailed PWM.')
 return candidates,info

def local_linearization(c):
 """Central derivative at the simulator's initialized average equilibrium."""
 panel=Panel.from_config(c); y,duty=plant.initial_state(c,panel); packed=plant.prepare(c,panel)
 indices=[0,1,2]
 if c['sense_tau_us']>0:indices.append(3)
 if c['plant_mode']=='c07':
  indices += [7,8,9,10]
  if c['current_sense_tau_us']>0:indices += [11,12]
  if c['sense_tau_us']>0:indices += [13]
 def f(x,on):return plant.rhs(0.,x,c,panel,on,prepared=packed)[indices]
 def output(x,on):
  o=plant.observe(c,panel,x,on,prepared=packed);return np.array([o['v_sense'],o['i_sense']])
 n=len(indices); a=np.zeros((n,n)); cc=np.zeros((2,n))
 for col,idx in enumerate(indices):
  eps=max(1.,abs(y[idx]))*1e-5; yp=y.copy();ym=y.copy();yp[idx]+=eps;ym[idx]-=eps
  a[:,col]=(duty*(f(yp,True)-f(ym,True))+(1-duty)*(f(yp,False)-f(ym,False)))/(2*eps)
  cc[:,col]=(duty*(output(yp,True)-output(ym,True))+(1-duty)*(output(yp,False)-output(ym,False)))/(2*eps)
 b=f(y,True)-f(y,False); feed=output(y,True)-output(y,False)
 residual=duty*f(y,True)+(1-duty)*f(y,False)
 normalized_residual=float(max(abs(residual)/np.maximum(1.,abs(y[indices]))))
 o=plant.observe(c,panel,y,True,prepared=packed)
 info=dict(states=n,state_indices=indices,duty=duty,voltage_in=o['v_in'],inductance_h=o['l_diff_h'],
           capacitance_f=c['cin_uf']*1e-6,normalized_equilibrium_residual_per_s=normalized_residual,
           scope='CCM local average derivative; exact ZOH for seed only; real clock/limits checked by simulation',
           feedback_node='PV_FUSED' if c['plant_mode']=='c07' else 'PV_RAW',
           timing_scope='Uniform effective sample period and fixed mean latch delay for seed only; asynchronous queues not certified')
 return a,b,cc,feed,info

def sampled_response(a,b,cc,feed,period,delay):
 """Exact ZOH of this local A/B with a fixed fractional command delay.

 The delay approximation is explicit. Splitting B_old/B_new integrates the
 old command during [0,r] and new command during [r,T]. No rounded delay.
 """
 n=len(b)
 def zoh(t):
  aug=np.zeros((n+1,n+1));aug[:n,:n]=a;aug[:n,n]=b
  z=expm(aug*t);return z[:n,:n],z[:n,n]
 ad,bd=zoh(period); whole=int(delay//period);r=delay-whole*period
 _,bn=zoh(period-r);bo=bd-bn
 def response(w):
  z=np.exp(1j*w*period)
  effective_b=(bn+bo/z)*z**(-whole)
  return cc@np.linalg.solve(z*np.eye(n)-ad,effective_b)+feed*z**(-whole)
 return response

def discrete_pi_at(g,omega,period,phase_deg,mode):
 """Solve Re/Im exactly for parallel PI using current-error integration.

 P-only can meet magnitude but does not get a fictitious requested phase.
 A PID seed has D=0; local numerical search handles the implemented filter.
 """
 if abs(g)<1e-14 or not np.isfinite(g):raise ValueError('Zero/nonfinite local sensitivity')
 if mode=='P':return (1/abs(g),0.,0.)
 z=np.exp(1j*omega*period);q=period/(1-1/z)
 if abs(q.imag)<1e-14:raise ValueError('Degenerate PI design frequency')
 w=np.exp(1j*math.radians(-180+phase_deg))/g
 ki=w.imag/q.imag;kp=w.real-ki*q.real
 if kp<0 or ki<0:raise ValueError('Requested crossover/phase requires negative PI gains')
 return float(kp),float(ki),0.

def calculation_candidates(c,profile,_phase=None):
 if c['algorithm']=='c07_r04':return r04_candidates(c,profile)
 vm,im=modes(c); candidates=[];info={}
 if vm:
  try:
   a,b,cc,feed,info=local_linearization(c);vp,ip,delay=effective_timing(c)
   if info['normalized_equilibrium_residual_per_s']>1.:
    raise ValueError('Average initialization is not sufficiently stationary for a local gain calculation')
   gv=sampled_response(a,b,cc,feed,vp,delay);gi=sampled_response(a,b,cc,feed,ip,delay)
   natural=info['duty']/math.sqrt(info['inductance_h']*info['capacitance_f']);gain=c['duty_response_gain']
   phase=PROFILES[profile]['phase_deg'] if _phase is None else _phase
   if not im:
    for factor in (.25,.5,.8,1.,1.2,1.5,2.):
     w=natural*factor
     if w*vp>.7 or w*delay>.8:continue
     g=-gv(w)[0]*gain
     if c['algorithm_filter_ms']>0 and (c['algorithm']=='baseline'):
      alpha=1-math.exp(-c['control_us']*1e-6/(c['algorithm_filter_ms']*.001));z=np.exp(1j*w*vp)
      g*=alpha/(1-(1-alpha)/z)
     try:candidates.append((f'discrete PI crossover {w:.3g} rad/s',gains_patch(c,discrete_pi_at(g,w,vp,phase,vm))))
     except ValueError:pass
   else:
    wi0=min(4*natural,.5/max(delay+ip,1e-8))
    for factor in (.7,1.):
     wi=wi0*factor
     try:ig=discrete_pi_at(gi(wi)[1]*gain,wi,ip,phase,im)
     except ValueError:continue
     for outer in (.12,.2):
      w=min(wi*outer,.2/max(delay+vp,1e-8));z=np.exp(1j*w*ip)
      ci=ig[0]+ig[1]*ip/(1-1/z)
      vv,ii=gi(w);closed=-vv*ci*gain/(1+ii*ci*gain)
      # Outer ZOH/clock separation is only an approximate seed for multirate.
      closed*=np.exp(-1j*w*max(0.,vp-ip)/2)
      try:candidates.append((f'inner-first discrete PI {w:.3g}/{wi:.3g}',gains_patch(c,discrete_pi_at(closed,w,vp,phase,vm),ig)))
      except ValueError:pass
  except (ValueError,ArithmeticError,np.linalg.LinAlgError) as exc:info['seed_warning']=str(exc)
  v,i=components(c)
  for factor in (.65,1.4):candidates.append((f'local gain start {factor}',gains_patch(c,tuple(x*factor for x in v),tuple(x*factor for x in i) if i else None)))
  if vm=='PID' or im=='PID':
   vp,ip,_=effective_timing(c)
   vd=(v[0],v[1],max(v[2],v[0]*vp*.25)) if vm=='PID' else v
   ider=(i[0],i[1],max(i[2],i[0]*ip*.25)) if im=='PID' else i
   candidates.append(('filtered derivative start',gains_patch(c,vd,ider)))
 elif c['algorithm']=='opensec' or c['algorithm']=='custom' and c['custom_law']=='model':
  # alpha is a local frozen-state Euler error factor, not an exact pole or
  # physical delay. Actual simulator closes both coupled equations.
  for v,i in ((.005,.1),(.02,.15),(.04,.3)):
   candidates.append(('model error contraction seed',dict(model_voltage_gain=v,model_current_gain=i)))
 elif c['algorithm']=='fugu' and c['experiment']=='voltage':
  for factor in (.5,1.5):candidates.append(('FUGU voltage speed slope',{'fugu_voltage_kp':c['fugu_voltage_kp']*factor}))
 # Integer/step/period candidates are explicitly algorithm coordinates.
 if c['algorithm']=='libresolar':step='libre_step_counts'
 elif c['algorithm']=='custom' and c['custom_topology']=='direct_duty':step='mppt_step_duty'
 elif c['algorithm']=='fugu':step='fugu_fast_speed' if c['experiment']=='irradiance' else None
 else:step='mppt_step_v' if c['experiment']=='irradiance' else None
 if step:
  for scale,period_scale in ((.5,1.),(1.5,1.),(1.,.5),(1.,1.5)):
   candidates.append(('MPPT/direct step-period mesh',clip_patch(c,{step:c[step]*scale,'mppt_period_ms':c['mppt_period_ms']*period_scale})))
 if vm and im and _phase is None:
  # Crossover phase alone does not determine reference-step overshoot. Give
  # the finite screening budget both the requested and a more damped phase
  # design, with a strong-inner-loop alternative, instead of three nearly
  # identical damping ratios. These are recalculated, not stored gain sets.
  higher=min(85.,PROFILES[profile]['phase_deg']+15.)
  damped,_=calculation_candidates(c,profile,_phase=higher)
  calculated=[x for x in candidates if x[0].startswith('inner-first')]
  alternative=[(f'phase {higher:g} '+label,p) for label,p in damped if label.startswith('inner-first')]
  if calculated and alternative:
   picked=[calculated[0],alternative[0],alternative[min(2,len(alternative)-1)]]
   candidates=picked+[x for x in candidates if x not in picked]
   info['phase_targets_deg']=[PROFILES[profile]['phase_deg'],higher]
 return [(label,clip_patch(c,p)) for label,p in candidates],info

def optimization_bounds(c,key):
 """Finite local trust box in physical parameter units (not preset choices)."""
 lo,hi=LIMITS[key];v=c[key]
 if key=='libre_step_counts':return max(lo,math.floor(v/3)),min(hi,math.ceil(max(3,v*3)))
 if key.startswith('fugu_vin_'):
  return max(lo,min(v*3,-1.)),min(hi,v/3)
 floors={'voltage_kd':1e-5,'current_kd':1e-6,'td_ms':.2,'kp':.003,
         'voltage_kp':.01,'current_kp':.001,'voltage_ki':1.,'current_ki':.1,
         'model_voltage_gain':.01,'model_current_gain':.1}
 if v==0:return max(lo,0.),min(hi,floors.get(key,1.))
 return max(lo,v/4),min(hi,v*4)
