"""Per-instance access to the unchanged c07 r03 C regulation core.

This does not execute the ARM image, supervisor, board drivers or finite PIO.
ADC/CPU/background/PWM events are supplied by the Lab event scheduler.
"""
from pathlib import Path
import ctypes as C
import hashlib
import math
import weakref

EXTRA_DEFAULTS = dict(
 c07_mppt_settle_ms=5.,c07_mppt_window_ms=5.,c07_mppt_max_step_v=.5,
 c07_mppt_step_gain_v=.5,c07_mppt_power_deadband_w=.2,
 c07_mppt_voltage_deadband_v=.02835360440340909,c07_mppt_current_deadband_a=.01220703125,
 c07_current_rise_a_s=20.,c07_mppt_settle_v=.3,c07_mppt_settle_a=.3,
 c07_current_filter_ms=0.,c07_cv_kp=4.,c07_cv_ki=5.,c07_pv_headroom_v=5.,
 c07_vout_trip_v=58.,c07_background_us=50.,c07_irq_occupancy_us=444.)
EXTRA_LIMITS = {
 **{k:(0.,10000.) for k in EXTRA_DEFAULTS},
 'c07_mppt_window_ms':(.001,1000.),'c07_mppt_max_step_v':(.0001,10.),
 'c07_current_rise_a_s':(.001,1000.),'c07_vout_trip_v':(1.,200.),
 'c07_background_us':(0.,100000.),'c07_irq_occupancy_us':(1.,100000.)}
TIMING_FIELDS = ['control_us','pwm_khz','acquire_us','adc_channel_us','transport_us','compute_us','apply_us',
 'adc_phase','adc_bits','adc_voltage_range_v','adc_current_range_a','duty_response_gain']
PRESET = dict(EXTRA_DEFAULTS,algorithm='c07_r03',mppt_method='inccond',
 control_us=1001.,current_period_us=1001.,voltage_period_us=5000.,mppt_period_ms=20.,
 voltage_kp=.3,voltage_ki=8.,current_kp=.002,current_ki=1.,
 algorithm_filter_ms=1.,mppt_step_v=.05,duty_min=.03,duty_max=.9,
 current_limit_a=13.8,output_voltage_limit_v=57.1,input_current_limit_a=13.5,
 duty_response_gain=1.,voltage_kd=0.,current_kd=0.,voltage_mode='PI',current_mode='PI',
 pwm_khz=50.,acquire_us=11.632,adc_channel_us=25.7062857142857,transport_us=82.424,
 compute_us=120.584,apply_us=0.,adc_phase=0.,adc_bits=12.,
 adc_voltage_range_v=116.13636363636364,adc_current_range_a=50.)
FIELDS = ['voltage_period_us','mppt_period_ms','voltage_kp','voltage_ki','current_kp','current_ki',
 'algorithm_filter_ms','mppt_step_v','duty_min','duty_max','current_limit_a',
 'output_voltage_limit_v','input_current_limit_a']+list(EXTRA_DEFAULTS)
REAL_MAP = dict(duty_min='DUTY_MIN',duty_max='DUTY_MAX',current_limit_a='CHARGE_CURRENT_A',
 output_voltage_limit_v='CHARGE_VOLTAGE_V',input_current_limit_a='INPUT_CURRENT_LIMIT_A',
 voltage_kp='PV_KP_A_PER_V',voltage_ki='PV_KI_A_PER_V_S',current_kp='IL_KP_DUTY_PER_A',
 current_ki='IL_KI_DUTY_PER_A_S',mppt_step_v='MPPT_STEP_MIN_V',
 c07_mppt_max_step_v='MPPT_STEP_MAX_V',c07_mppt_step_gain_v='MPPT_STEP_GAIN_V',
 c07_mppt_power_deadband_w='POWER_DEADBAND_W',c07_mppt_voltage_deadband_v='MPPT_VOLTAGE_DEADBAND_V',
 c07_mppt_current_deadband_a='MPPT_CURRENT_DEADBAND_A',c07_current_rise_a_s='IL_RISE_A_PER_S',
 c07_mppt_settle_v='MPPT_SETTLE_V',c07_mppt_settle_a='MPPT_SETTLE_A',
 c07_cv_kp='CV_KP_A_PER_V',c07_cv_ki='CV_KI_A_PER_V_S',c07_pv_headroom_v='PV_HEADROOM_V',
 c07_vout_trip_v='VOUT_TRIP_V')
TIME_MAP = dict(control_us=('CONTROL_PERIOD_US',1.),voltage_period_us=('VOLTAGE_PERIOD_US',1.),
 mppt_period_ms=('MPPT_PERIOD_US',1000.),algorithm_filter_ms=('VOLTAGE_FILTER_US',1000.),
 c07_current_filter_ms=('IL_FILTER_US',1000.),c07_mppt_settle_ms=('MPPT_SETTLE_US',1000.),
 c07_mppt_window_ms=('MPPT_WINDOW_US',1000.))
LIMIT_NAMES = ['STOPPED','STARTUP','MPPT','CV','VOLTAGE_LIMIT','INPUT_CURRENT','INPUT_FOLDBACK',
 'BUCK_UNREACHABLE','THERMAL','CURRENT_LIMIT','MIN_DUTY','MAX_DUTY']
CORE_HASH='950d667a89a8865da36b372d256b26d5e7676344ad3e6281ec69d1afcea0a323'
HEADER_HASH='98a3c86c2b43e16f10b5b4cd9e52faada522a3c6cdacfe5f69fb891d2a30e9af'
NATIVE=Path(__file__).resolve().parent/'native/c07_r03'

def validate(c):
 if c.get('algorithm')!='c07_r03':return
 if c['c07_current_rise_a_s']<=0:raise ValueError('c07 r03の電流上昇制限は0より大きくしてください。無効化はr04で対応しています。')
 if c['duty_response_gain']!=1:raise ValueError('c07 r03ではDuty反映倍率を1倍にしてください。')
 if c['mppt_method']!='inccond':raise ValueError('c07 r03はIncCond固定です。')
 if c['voltage_mode']!='PI' or c['current_mode']!='PI' or c['voltage_kd']!=0 or c['current_kd']!=0:
  raise ValueError('c07 r03の電圧・電流追従はPI固定です。D項は0にしてください。')
 if c['current_period_us']!=c['control_us']:raise ValueError('c07 r03の電流周期は測定・制御周期と同じ値にしてください。')
 if not 0<c['control_us']<=5000:raise ValueError('c07 r03の制御周期は0超～5000 µsです。')
 if c['voltage_period_us']<c['control_us'] or c['mppt_period_ms']*1000<=c['voltage_period_us']:
  raise ValueError('c07 r03はMPPT周期 > 電圧周期 >= 電流周期にしてください。')
 if c['mppt_step_v']>c['c07_mppt_max_step_v']:raise ValueError('c07 r03のMPPT最小幅が最大幅を超えています。')
 if c['duty_min']<=0:raise ValueError('c07 r03のDuty下限は0より大きい値です。停止時は別にDuty=0を使います。')
 if c['c07_vout_trip_v']<=c['output_voltage_limit_v']:raise ValueError('c07 r03の電圧停止値はCV目標より高くしてください。')
 for k,(_,scale) in TIME_MAP.items():
  if abs(c[k]*scale-round(c[k]*scale))>1e-7:raise ValueError(f'{k}: c07 r03内部の時間は整数µsで指定してください。')
 if all(k in c for k in ('acquire_us','adc_channel_us','transport_us','compute_us')):
  finish=c['acquire_us']+7*c['adc_channel_us']+c['transport_us']+c['compute_us']
  if finish>c['c07_irq_occupancy_us']+1e-7 or c['c07_irq_occupancy_us']>=c['control_us']:
   raise ValueError('c07 r03の8ch取得＋演算時間 <= 割込み占有時間 < 制御周期にしてください。')

class Native:
 def __init__(self,c,duty,target):
  if (hashlib.sha256((NATIVE/'c07_control.c').read_bytes()).hexdigest()!=CORE_HASH or
      hashlib.sha256((NATIVE/'c07_control.h').read_bytes()).hexdigest()!=HEADER_HASH):
   raise RuntimeError('c07 r03制御本体の識別値が不一致です。')
  self.lib=C.CDLL(str(NATIVE/'c07_lab.dll'))
  for name,args,result in [
   ('c07_lab_new',[],C.c_void_p),('c07_lab_free',[C.c_void_p],None),
   ('c07_lab_config',[C.c_void_p,C.c_char_p,C.c_double],C.c_int),
   ('c07_lab_get',[C.c_void_p,C.c_char_p],C.c_double),
   ('c07_lab_start',[C.c_void_p]+[C.c_double]*4,C.c_int),
   ('c07_lab_step',[C.c_void_p,C.POINTER(C.c_double),C.c_int,C.c_uint,C.c_int,C.c_double,C.POINTER(C.c_double)],C.c_int),
   ('c07_lab_begin',[C.c_void_p],C.c_int),('c07_lab_finish',[C.c_void_p],C.c_int)]:
   fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=result
  self.handle=self.lib.c07_lab_new()
  if not self.handle:raise MemoryError('c07 r03 instance allocation failed')
  self._close=weakref.finalize(self,self.lib.c07_lab_free,self.handle)
  for k,name in REAL_MAP.items():
   if self.lib.c07_lab_config(self.handle,name.encode(),c[k]):raise ValueError('c07 configuration: '+k)
  for k,(name,scale) in TIME_MAP.items():
   if self.lib.c07_lab_config(self.handle,name.encode(),round(c[k]*scale)):raise ValueError('c07 configuration: '+k)
  rc=self.lib.c07_lab_start(self.handle,c.get('pv_voc',80.),c.get('v_battery',51.2),duty,target)
  if rc:raise ValueError('c07 r03 core rejected configuration: '+str(rc))
 def settings(self):
  return {k:self.lib.c07_lab_get(self.handle,name.encode()) for k,name in REAL_MAP.items()}|{
   k:self.lib.c07_lab_get(self.handle,name.encode())/scale for k,(name,scale) in TIME_MAP.items()}
 def step(self,measurement,dt,mppt,target):
  keys=('v_in','i_pv','v_out','i_l','tbat','tsink','v_bat','v_pv')
  v=[float(measurement[k]) for k in keys]
  if not all(map(math.isfinite,v)):raise ValueError('c07 r03 measurement is not finite')
  out=(C.c_double*31)()
  rc=self.lib.c07_lab_step(self.handle,(C.c_double*8)(*v),round(measurement.get('pv_pair_span_us',51)),round(dt*1e6),int(mppt),target,out)
  if rc:raise ValueError('c07 r03 core rejected sample/time: '+str(rc))
  return list(out)
 def begin(self):return bool(self.lib.c07_lab_begin(self.handle))
 def finish(self):return self.lib.c07_lab_finish(self.handle)

def make_class(Base):
 class C07R03(Base):
  def __init__(self,*args):
   super().__init__(*args);validate(self.c)
   self.native=Native(self.c,self.duty,self.v_ref);self._updates=0;self._job_active=False
   self.metadata.update(source_control_core_executed=True,source_firmware_executed=False,
    core_sha256=CORE_HASH,core_library_sha256=hashlib.sha256((NATIVE/'c07_lab.dll').read_bytes()).hexdigest(),
    control_chain='IncCond → PV電圧PI → 制限/CV → L1電流PI → Duty',
    initial_policy='Lab正常ON動作点から開始。実機の起動シーケンスは実行しない。',
    clock_policy='C fast step at modeled compute completion; separate background begin/finish; next fast-end consumes result',
    gain_policy='r03のSI設定。編集時は保存値との差を表示。D項なし。Duty反映倍率は1固定。',
    fidelity_note='r03の同じC制御本体を実行。Labの正常ON回路・連続PWM・8ch時刻近似を使用。ARM割込み/50pulse PIO/起動/故障ラッチは再現しない。',
    temperature_policy='Tbat=25°C、Tsink=35°Cを固定取得。熱回路は未モデル化。',
    open_circuit_bound_policy='初期Voc上限には設定のpv_vocを使用。起動時の開放電圧測定は再現しない。モデル真MPPは入力しない。',
    numeric_type='double (same C07_REAL_TYPE as the r03 ARM build; host arithmetic is not ARM execution)',
    native_configuration_readback=self.native.settings(),
    configuration_warnings=['c07 r03の同じC制御本体を使いますが、実機全体の再現ではありません。'],
    r03_preset_modified=[k for k,v in PRESET.items() if k in self.c and self.c[k]!=v])
  def update(self,t_s,measurement,external_vref):
   t=float(t_s)
   if not math.isfinite(t) or self.last_t is not None and t<self.last_t:raise ValueError('Controller time order')
   if not self.mppt_enabled and (external_vref is None or not math.isfinite(external_vref)):raise ValueError('External PV voltage target required')
   dt=self.sample_period_s if self.last_t is None else t-self.last_t
   before=len(self.events)
   if self.started is None:self.started=t
   target=self.v_ref if self.mppt_enabled else float(external_vref)
   result=self.native.step(measurement,dt,self.mppt_enabled,target)
   self.duty,self.i_ref,self.v_ref=result[0],result[1],result[4]
   self.p,self.i,self.d=result[26],result[6],0.
   self.mppt_updated=result[11]>self._updates;self._updates=result[11];self.duty_updated=True
   self.mode='C07_R03_'+LIMIT_NAMES[int(result[10])]
   if result[29]:self.emit(t,'voltage_pi',i_ref=self.i_ref,integral=result[5],cv_integral=result[7],cv_ceiling=result[8])
   self.emit(t,'current_pi',i_ref=self.i_ref,current=result[3],duty=self.duty,p=self.p,i=self.i,d=0.,feedforward=result[30])
   if self.mppt_updated:self.emit(t,'mppt',method='inccond',v_ref=self.v_ref,step_v=result[14],signal=result[18],voltage=result[19],current=result[20],power=result[27])
   self.metadata['r03_async']=dict(zip(['published','applied','rejected','expired','pending'],result[21:26]))
   self.metadata['r03_mppt']=dict(updates=result[11],moves=result[16],holds=result[17],reacquisitions=result[12])
   self.last_t=t
   raw={k:measurement[k] for k in ('v_pv','i_pv','i_l','v_out','i_out','v_in','v_bat','tbat','tsink')}
   return dict(duty=self.duty,v_ref=self.v_ref,i_ref=self.i_ref,p=self.p,i=self.i,d=0.,
    mppt_updated=self.mppt_updated,duty_updated=True,mode=self.mode,events=self.events[before:],
    measurements=dict(raw=raw,filtered=dict(v_pv=result[2],i_l=result[3])),stages=dict(self.stages))
  def begin_background(self,t):
   if not self.mppt_enabled or self._job_active:return False
   self._job_active=self.native.begin()
   if self._job_active:self.emit(t,'mppt_background_begin')
   return self._job_active
  def finish_background(self,t):
   if not self._job_active:return
   valid=self.native.finish();self._job_active=False
   self.emit(t,'mppt_background_publish',valid=valid==1)
 return C07R03
