"""Event-scheduled controller comparisons; every PWM edge is integrated.

True-panel MPP is an observer used only for scoring, never controller input.
ADC channels are acquired sequentially when adc_channel_us is nonzero.
"""
from __future__ import annotations
import heapq
import math
import time
from copy import deepcopy
from collections import Counter
import numpy as np
from controllers import make_controller, ALGORITHMS
from engine_legacy_v2 import Panel, SimulationCancelled
import plant
from waveform_summary import PWMMeanSummary, unavailable as waveform_unavailable
from tuning_metrics import TuningMetrics, voltage_at_node


def attach_signal_metadata(c, metadata):
    """Name physical, sensed, reference and scoring signals without remapping control."""
    extended=c['plant_mode']=='c07'
    sampled_node='PV_FUSED' if extended else 'PV_RAW'
    model_branch=c['algorithm']=='opensec' or (c['algorithm']=='custom' and c.get('custom_law')=='model')
    feedback='PV_RAW' if model_branch else sampled_node
    has_vref=not(c['experiment']=='irradiance' and c['algorithm'] in ('libresolar','fugu'))
    current_target=c['algorithm'] in ('ti','plexim','opensec','c07_r03','c07_r04')
    metadata.setdefault('feedback_voltage_node',feedback)
    metadata.setdefault('target_voltage_node',feedback if has_vref else None)
    metadata.setdefault('evaluation_voltage_node','PV_RAW')
    metadata.setdefault('feedback_current_node','L1')
    metadata.setdefault('target_current_node','L1' if current_target else None)
    metadata.setdefault('measurement_channels',{})
    channels={
        'v_pv':dict(node=sampled_node,source_series='v_sense',quantity='voltage',unit='V'),
        'i_l':dict(node='L1',source_series='i_l_sense',quantity='current',unit='A'),
        'v_out':dict(node='VOUT',source_series='vout_sense',quantity='voltage',unit='V'),
        'i_pv':dict(node='L2' if extended else 'PV_RAW',source_series='i_pv_sense',quantity='current',unit='A')}
    # This map describes the engine's actual ADC wiring, regardless of names
    # a controller happens to give its input variables.
    if c['algorithm'] in ('c07_r03','c07_r04'):
        channels.update(v_in=dict(node='VIN',source_series='v_in',quantity='voltage',unit='V'),
            v_bat=dict(node='BAT_PLUS',source_series='v_bat_plus',quantity='voltage',unit='V'),
            tbat=dict(node='BATTERY',quantity='fixed_temperature',unit='°C'),
            tsink=dict(node='HEATSINK',quantity='fixed_temperature',unit='°C'))
    metadata['adc_measurement_channels']=channels
    metadata['i_out_input_note']='i_outはi_lと同じADC値。L1電流であり、電池電流や出力コンデンサ後の負荷電流ではありません。'
    metadata.setdefault('mppt_power_basis',
        'VOUTセンサ電圧 × L1センサ電流（出力電力の近似。出力容量電流を分離しない）'
        if c['algorithm'] in ('libresolar','fugu') else
        '推定PV_RAW電圧 × 推定パネル端子電流' if model_branch else
        'PV_FUSEDセンサ電圧 × L2センサ電流' if extended else 'PV端子センサ電圧 × パネル電流')
    if c['algorithm']=='fugu':
        metadata['input_current_limit_basis']='入力電流ADC値は未使用。VOUT×IL1 / (PV測定電圧×0.97)から推定した電流で制限。'
    metadata['voltage_target_matches_scoring_node']=metadata['target_voltage_node'] in (None,'PV_RAW')
    metadata['voltage_comparison_note']=(
        '制御の電圧目標はPV_FUSED測定値相当。電圧応答の従来指標はPV_RAW端子で評価するため、同じ節点の偏差ではありません。'
        if metadata['target_voltage_node']=='PV_FUSED' else
        '制御の電圧目標と従来指標はPV_RAW端子相当。制御は測定・推定値を使い、評価はモデル真値を使います。'
        if metadata['target_voltage_node']=='PV_RAW' else
        'この通常MPPT方式には電圧目標がありません。モデルMPPとPV_RAW端子電力で評価します。')
    if c['algorithm']=='c07_r04':
        # r04 scores the target's physical node. Keep older profile metadata
        # unchanged here; this block only names the existing scoring behavior.
        scoring_node=metadata['target_voltage_node'] or feedback
        metadata['evaluation_voltage_node']=scoring_node
        metadata['voltage_target_matches_scoring_node']=metadata['target_voltage_node'] in (None,scoring_node)
        metadata['voltage_comparison_note']=(
            f'制御の電圧目標と追従指標は同じ節点 {scoring_node} で比較します。'
            '制御は測定値、評価はモデル真値を使います。パネル端子PV_RAWの波形と電力評価は別に保持します。')
    def item(label,node,kind,description,unit):return dict(label=label,node=node,kind=kind,description=description,unit=unit)
    return {
        'v_pv':item('パネル端子の真電圧','PV_RAW','physical','ヒューズ前のPV端子。モデルの真値で、ADC値ではありません。','V'),
        'i_pv':item('パネル端子の真電流','PV_RAW','physical','パネルから流れ出る電流。c07ではL2電流とコンデンサ電流・分圧負荷の分だけ異なります。','A'),
        'p_pv':item('パネル端子の真電力','PV_RAW','physical','同時刻のPV_RAW電圧×パネル端子電流。追従評価に使用します。','W'),
        'v_fused':item('ヒューズ後の真電圧' if extended else 'PV電圧（ヒューズ省略）',sampled_node,'physical','c07の電圧センサが見ている節点。センサRCを通る前です。','V'),
        'v_in':item('入力L2後・Buck入力の真電圧','VIN' if extended else 'PV_RAW','physical','スイッチ入力節点。c07ではPV_RAW/PV_FUSEDと異なります。','V'),
        'i_l2':item('入力コイルL2の真電流','L2' if extended else None,'physical' if extended else 'absent','c07の入力シャントが測る枝の真値。簡略BuckにはL2がないためnullです。','A'),
        'i_l':item('主コイルL1の真電流','L1','physical','スイッチ側からVOUTへ流れる向きを正とする主Buckコイル電流。','A'),
        'v_l':item('L1の理想インダクタ部分の電圧','L1_IDEAL','physical','スイッチ側→VOUTを正。Ldiff×dIL1/dt。巻線抵抗の電圧降下を除きます。','V'),
        'v_l_terminal':item('L1＋巻線抵抗の両端電圧','SW_MINUS_VOUT','physical','スイッチ節点電圧−VOUT。v_l＋R_L1×IL1。非導通OFF中は0です。','V'),
        'v_sense':item('PV電圧センサ出力（ADC前）',sampled_node,'sensor','アナログRC後の連続値。量子化や取得時刻保持はまだ含みません。','V'),
        'i_l_sense':item('L1電流センサ出力（ADC前）','L1','sensor','c07では電流RC後、簡略Buckでは真電流を直接使用。量子化前です。','A'),
        'i_pv_sense':item('L2電流センサ出力（ADC前）' if extended else 'パネル電流（ADC前）','L2' if extended else 'PV_RAW','sensor','制御変数名i_pvへ渡すセンサ値。c07の測定対象はパネル端子電流ではなくL2電流です。','A'),
        'vout_sense':item('VOUT電圧センサ出力（ADC前）','VOUT','sensor','c07では電圧RC後。ADC保持・量子化前の連続値です。','V'),
        'v_out':item('出力節点の真電圧','VOUT','physical','出力コンデンサのESRを含む外部端子電圧。内部容量電圧とは別です。','V'),
        'v_ref':item('制御器の電圧目標',metadata['target_voltage_node'],'reference',metadata['voltage_comparison_note'],'V'),
        'i_ref':item('制御器のL1電流目標',metadata['target_current_node'],'reference','電流目標を持つ方式だけ表示。真値IL1とセンサ値の時間遅れを区別します。','A'),
        'v_mpp':item('モデルMPPの端子電圧','PV_RAW','oracle','同じPVモデルから評価専用に求めた正解値。制御器には渡しません。','V'),
        'p_mpp':item('モデルMPPの端子電力','PV_RAW','oracle','評価専用の最大電力。入力センサの測定電力ではありません。','W')}


def irradiance_at(c, t):
    if c['experiment'] != 'irradiance' or t < c['step_ms']*.001:
        return c['irradiance']
    ramp=c['ramp_ms']*.001
    a=1. if ramp<=0 else min(1.,max(0.,(t-c['step_ms']*.001)/ramp))
    return c['irradiance']+a*(c['irradiance_after']-c['irradiance'])


def true_mpp(panel, irradiance, initial_irradiance):
    """Solve d(VI)/dV=0 for the actual fitted single-diode curve."""
    iph=panel.iph*irradiance/initial_irradiance
    z=math.log1p(iph/panel.saturation)
    u=max(0.,z-math.log1p(z))
    for _ in range(12):
        du=(u+math.log1p(u)-z)/(1.+1./(1.+u))
        u=max(0.,u-du)
        if abs(du)<1e-13: break
    v=panel.scale*u
    cur=iph-panel.saturation*math.expm1(u)
    return v,cur,v*cur


class ReferencePower:
    """Independent MPP oracle and its time integral (J, measured from t=0)."""
    def __init__(self,c,panel):
        self.c=c; self.panel=panel
        self.start=c['step_ms']*.001
        self.ramp=c['ramp_ms']*.001 if c['experiment']=='irradiance' else 0.
        self.before=true_mpp(panel,c['irradiance'],c['irradiance'])
        self.after=true_mpp(panel,irradiance_at(c,self.start+self.ramp+1e-9),c['irradiance'])
        if self.ramp:
            self.grid=np.linspace(0.,self.ramp,4097)
            p=np.array([true_mpp(panel,irradiance_at(c,self.start+x),c['irradiance'])[2] for x in self.grid])
            self.integral=np.r_[0.,np.cumsum((p[:-1]+p[1:])*.5*np.diff(self.grid))]

    def at(self,t):
        if t<self.start or self.c['experiment']!='irradiance': return self.before
        if not self.ramp or t>=self.start+self.ramp: return self.after
        return true_mpp(self.panel,irradiance_at(self.c,t),self.c['irradiance'])

    def energy(self,t):
        if t<=self.start or self.c['experiment']!='irradiance': return t*self.before[2]
        x=t-self.start
        if not self.ramp:return self.start*self.before[2]+x*self.after[2]
        return (self.start*self.before[2]+float(np.interp(min(x,self.ramp),self.grid,self.integral))
                +max(0.,x-self.ramp)*self.after[2])


def enrich_legacy(out,c):
    """Keep legacy trajectories and metrics byte-for-byte numerically unchanged."""
    panel=Panel.from_config(c); oracle=ReferencePower(c,panel); s=out['series']
    n=len(s['t_ms']); vm,im,pm=oracle.before
    s.update(i_pv=[panel.current(v) for v in s['v_pv']],p_pv=[v*panel.current(v) for v in s['v_pv']],
             p_mpp=[pm]*n,v_mpp=[vm]*n,i_ref=[None]*n,
             irradiance=[c['irradiance']]*n,energy_deficit_j=[None]*n)
    terminal=[(vp-c['r_switch_ohm']*il-vo if on else -c['diode_vf']-vo if il>0 else 0.)
              for vp,vo,il,on in zip(s['v_pv'],s['v_out'],s['i_l'],s['pwm'])]
    s.update(i_l2=[None]*n,v_fused=list(s['v_pv']),v_l_terminal=terminal,
             v_l=[v-c['r_l_ohm']*il if on or il>0 else 0. for v,il,on in zip(terminal,s['i_l'],s['pwm'])],
             i_l_sense=list(s['i_l']),i_pv_sense=list(s['i_pv']),vout_sense=list(s['v_out']))
    out['config']=c
    out['controller']=dict(next(a for a in ALGORITHMS if a['id']=='baseline'))
    out['signal_map']=attach_signal_metadata(c,out['controller'])
    out['waveform_summary']=waveform_unavailable()
    out['metrics'].update(mppt_settling_ms=None,tracking_efficiency_pct=None,energy_deficit_j=None)
    out['diagnostics'].update(algorithm='baseline',experiment='voltage',legacy_exact_path=True)
    return out


def simulate_experiment(c,*,method='FAST',max_step_fraction=.25,timeout=45.,cancelled=None,
                        _backend=None,_summary_only=False,_controller_config=None,
                        _capture_state=False,_initial_snapshot=None):
    tic=time.perf_counter(); panel=Panel.from_config(c)
    packed=plant.prepare(c,panel); y,d0=plant.initial_state(c,panel)
    if not 0.02<d0<.98: raise ValueError('初期動作点のDutyが2～98%の範囲外です。')
    if c['experiment']=='voltage' and not c['v_battery']<c['v_target']<panel.voc:
        raise ValueError('目標PV電圧は電池電圧より高く、現在の日照のVoc未満にしてください。')
    r03=c['algorithm'] in ('c07_r03','c07_r04')
    packet_cycles=int(c.get('c07_pwm_packet_cycles',0)) if r03 else 0
    finite_pwm=packet_cycles>0
    legacy_r03_metrics=c['algorithm']=='c07_r03'
    averaged=_backend is not None
    if r03 and (_capture_state or _initial_snapshot is not None):
        # A ctypes handle owns a live C controller. Copying it cannot produce
        # an independent controller state and risks a duplicate native free.
        raise ValueError('Native firmware controllers do not support tuning snapshots or resume')
    if legacy_r03_metrics and averaged:
        raise ValueError('c07_r03 remains excluded from averaged autotuning')
    controller=make_controller(_controller_config or c,d0,c['v_start']); oracle=ReferencePower(c,panel)
    attach_signal_metadata(c,controller.metadata)
    adc_channels=('v_in','v_pv','i_pv','i_l','v_out','v_bat','tbat','tsink') if r03 else ('v_pv','i_l','v_out','i_pv')
    ts=1/(c['pwm_khz']*1000); tu=controller.sample_period_s
    if finite_pwm:
        ts=round(ts/8e-9)*8e-9
        if tu<packet_cycles*ts+40e-9:raise ValueError('Control period is shorter than the finite PIO packet.')
    current_summary=PWMMeanSummary(ts) if not _summary_only and not averaged else None
    # Bound display-only staging memory and avoid Python/NumPy validation for
    # every tiny physics segment. Preserve all points, their order and repeats.
    summary_times=np.empty(4096,dtype=np.float64)
    summary_values=np.empty((4096,5),dtype=np.float64)
    summary_count=0
    def summarize_points(times,values):
        nonlocal summary_count
        offset=0
        while offset<len(times):
            count=min(len(times)-offset,len(summary_times)-summary_count)
            summary_times[summary_count:summary_count+count]=times[offset:offset+count]
            summary_values[summary_count:summary_count+count]=values[offset:offset+count]
            summary_count+=count;offset+=count
            if summary_count==len(summary_times):
                current_summary.add_points(summary_times,summary_values)
                summary_count=0
    stop=c['duration_ms']*.001; change=c['step_ms']*.001
    ramp_end=change+(c['ramp_ms']*.001 if c['experiment']=='irradiance' else 0.)
    energy0=plant.stored_energy(c,y); step_energy=None
    queue=[]; sequence=0
    def push(tt,priority,kind,payload=None):
        nonlocal sequence
        if tt<=stop+1e-12 or _capture_state or _initial_snapshot is not None:
            sequence+=1; heapq.heappush(queue,(max(0.,tt),priority,sequence,kind,payload))
    if not finite_pwm:push(0,1,'frame',0)
    push(c['adc_phase']*ts,3,'request',0)
    push(change,2,'change'); push(ramp_end,2,'ramp_end'); push(stop,9,'end')
    t=0.; on=False; conducting=True; applied=command=ready=d0; ready_id=None
    pterm=iterm=dterm=0.; vref=c['v_start']; iref=None
    if c['experiment']=='irradiance' and c['algorithm'] in ('libresolar','fugu'):vref=None
    cpu_free=adc_free=0.; frames=steps=nfev=raw_count=0
    records=[]; timings=[]; by_id={}; events=[]; warnings=[]; stopped=False
    event_counts=Counter(); mode_counts=Counter();pd_selected=Counter();pd_limiting=Counter()
    packet_active=False;packet_generation=0;packet_pending=None;packet_windows=[]
    def physical_duty():
        if not finite_pwm:return applied
        if not on:return 0.
        # Finite PIO packet: first rise is at +56 ns, packet end at
        # N*T +40 ns. Preserve total high time N*high_ticks*8 ns while
        # averaging only that envelope; the inter-packet idle remains OFF.
        return applied*packet_cycles*ts/(packet_cycles*ts-16e-9)
    slow_samples=0;slow_enter_ms=None;was_slow=False;controller_calls=0
    resumed_at=None;timing_phase=-1;phase_time=None
    if _initial_snapshot is not None:
        snap=deepcopy(_initial_snapshot)
        if snap.get('version')!=1:raise ValueError('Unsupported tuning snapshot version')
        if snap['config']['algorithm']!=c['algorithm']:raise ValueError('Snapshot controller differs')
        # Only end time may change. A continuation is not a fresh gain trial.
        for key,value in snap['config'].items():
            if key!='duration_ms' and c.get(key)!=value:raise ValueError('Snapshot configuration changed: '+key)
        for key,value in snap['controller'].c.items():
            if key!='duration_ms' and (_controller_config or c).get(key)!=value:
                raise ValueError('Snapshot controller estimate/configuration changed: '+key)
        controller=snap['controller'];y=snap['y'];t=snap['t'];resumed_at=t
        if stop<=t:raise ValueError('Resume end time must follow snapshot time')
        queue=snap['queue'];sequence=snap['sequence'];by_id=snap['by_id']
        queue=[x for x in queue if x[3]!='end'];heapq.heapify(queue);push(stop,9,'end')
        applied,command,ready,ready_id=(snap[k] for k in ('applied','command','ready','ready_id'))
        cpu_free,adc_free=(snap[k] for k in ('cpu_free','adc_free'))
        on,conducting=(snap[k] for k in ('on','conducting'))
        vref,iref=controller.v_ref,controller.i_ref
        pterm,iterm,dterm=controller.p,controller.i,controller.d
        energy0=plant.stored_energy(c,y)-y[4]+y[5]+y[6]
        step_energy=float(y[4]);change=t;ramp_end=t
        if not averaged and snap['averaged']:
            # Averaged states start a switched overlap window; ripple rebuilds
            # physically. Do not claim the preceding history was full PWM.
            frame=math.floor(t/ts+1e-10);edge=frame*ts+applied*ts
            on=t<edge-1e-12 and applied>0;conducting=on or y[1]>1e-10
            queue=[x for x in queue if x[3] not in ('frame','off')];heapq.heapify(queue)
            if on and edge>t+1e-12:push(edge,1,'off')
            push((frame+1)*ts,1,'frame',frame+1)
    evaluator_config={**c,'step_ms':change*1000,'ramp_ms':0. if resumed_at is not None else c['ramp_ms']}
    # A resumed FUGU slow loop must be observed over its actual slow cycle,
    # not merely the fast MPPT period. This affects scoring only, not control.
    slow_hold=(2*c['fugu_slow_period_ms']*.001 if resumed_at is not None and
               c['algorithm']=='fugu' and bool(getattr(controller,'slow',False)) else 0.)
    evaluator=None if legacy_r03_metrics else TuningMetrics(evaluator_config,controller.metadata,oracle,
        source='accepted_averaged_points' if averaged else 'accepted_switched_points',minimum_hold_s=slow_hold)
    next_display=t
    last_voltage_outside=None; last_mppt_outside=None; peak_current=0.; overshoot=0.
    band=max(.2,abs(c['v_target']-c['v_start'])*.02)
    step_direction=float(np.sign(c['v_target']-c['v_start']))
    reference_energy_at_change=oracle.energy(change)
    last_observation_key=None; last_observation_values=None
    last_metric_key=None
    columns='t_ms v_pv v_ref v_sense duty duty_command i_l v_out p i d pwm p_pv p_mpp v_mpp i_ref irradiance energy_deficit_j v_in v_bat_plus i_pv i_l2 v_fused v_l v_l_terminal i_l_sense i_pv_sense vout_sense'.split()
    def ref(tt): return c['v_target'] if tt>=change-1e-12 else c['v_start']
    def log(kind,**values):
        event_counts[kind]+=1
        if len(events)<(1000 if _summary_only else 50000): events.append(dict(t_ms=t*1000,kind=kind,**values))
    def compact():
        # Plot-only reduction. Metrics and electrical integration precede this.
        nonlocal records
        kept=[]
        # Uniform TIME buckets avoid repeatedly erasing old transients while
        # keeping recent samples dense. A bucket retains the actual extrema.
        width=max(records[-1][0]-records[0][0],1e-12)/2000
        origin=records[0][0]; k=0
        while k<len(records):
            bucket=int((records[k][0]-origin)/width); end=k+1
            while end<len(records) and int((records[end][0]-origin)/width)==bucket:end+=1
            block=records[k:end]; indices={0,len(block)-1}
            for col in (1,4,6,12):
                indices.add(min(range(len(block)),key=lambda j:block[j][col]))
                indices.add(max(range(len(block)),key=lambda j:block[j][col]))
            kept.extend(block[j] for j in sorted(indices))
            k=end
        records=kept
    def record(tt,state,observation=None):
        nonlocal raw_count,peak_current,last_voltage_outside,last_mppt_outside,overshoot
        nonlocal last_observation_key,last_observation_values,next_display,last_metric_key
        key=(tt,on,conducting)
        if observation is None:
            # Events such as CPU completion change command/history, not plant
            # state. Reuse only at the identical time and switch/conduction mode.
            observation=last_observation_values if key==last_observation_key else (
                _backend.record(float(tt),state,packed,physical_duty()).tolist() if averaged else
                plant.record_observation(float(tt),state,packed,on,conducting).tolist())
        last_observation_key,last_observation_values=key,observation
        vp,ip,vf,il2,vl,vl_terminal,vin,vo,vbp,il,vs,isense,ipsense,vosense,pvpower=observation
        if not packed[34]:il2=None
        metric_key=(float(tt),vp,vf,vin,vo,il,pvpower,applied)
        if _summary_only and metric_key==last_metric_key:return
        vm,im,pm=oracle.at(tt)
        if evaluator is not None and metric_key!=last_metric_key:
            evaluator.add(float(tt),observation,applied,energy_pv=float(state[4]),mpp_power=pm);last_metric_key=metric_key
        peak_current=max(peak_current,il)
        tracking_voltage=vp if legacy_r03_metrics else voltage_at_node(observation,evaluator.node)
        if tt>=change-1e-12:
            if abs(tracking_voltage-c['v_target'])>band:last_voltage_outside=tt
            overshoot=max(overshoot,step_direction*(tracking_voltage-c['v_target']))
        if tt>=ramp_end-1e-12 and pvpower<pm*(1-c['mppt_tolerance_pct']/100):
            last_mppt_outside=tt
        raw_count+=1
        if _summary_only and records and tt<next_display-1e-12 and tt<stop-1e-12:return
        next_display=tt+max((stop-(resumed_at or 0.))/1000,1e-6)
        deficit=None if step_energy is None else oracle.energy(tt)-reference_energy_at_change-(state[4]-step_energy)
        vals=(tt*1000,vp,vref,vs,applied,command,il,vo,
              pterm,iterm,dterm,float(on),pvpower,pm,vm,iref,irradiance_at(c,tt),deficit,vin,vbp,ip,
              il2,vf,vl,vl_terminal,isense,ipsense,vosense)
        if not records or records[-1]!=vals:
            records.append(vals)
        if len(records)>60000:compact()
    def quantize(value,current=False):
        if not c['adc_bits']:return float(value)
        width=c['adc_current_range_a'] if current else c['adc_voltage_range_v']
        low=-width/2 if current else 0.
        if r03:
            # MCP3208 nominal conversion: physical units -> floor(code) -> units.
            codes=2**int(c['adc_bits'])
            return low+min(codes-1,max(0,math.floor((value-low)/width*codes)))*width/codes
        codes=2**int(c['adc_bits'])-1
        return low+round(min(1.,max(0.,(value-low)/width))*codes)*width/codes
    def background_finish_time(start,work):
        # Lowest-priority work runs only in gaps between the modeled IRQs.
        # It cannot postpone an ADC/PI event, even when work spans many ticks.
        cursor=start; origin=c['adc_phase']*ts; occupancy=c['c07_irq_occupancy_us']*1e-6
        while work>1e-12:
            tick=math.floor((cursor-origin+1e-12)/tu)
            irq=origin+tick*tu
            if cursor<irq+occupancy-1e-12:cursor=irq+occupancy
            next_irq=irq+tu
            available=max(0.,next_irq-cursor)
            if work<=available+1e-12:return cursor+work
            work-=available;cursor=next_irq+occupancy
        return cursor
    spacing=c['adc_channel_us']*1e-6
    bus_period=c['acquire_us']*1e-6+(len(adc_channels)-1)*spacing+c['transport_us']*1e-6
    def schedule_packet(start,value,sid):
        nonlocal packet_active,packet_generation,applied,on,conducting
        packet_active=True;packet_generation+=1;gen=packet_generation
        # c07 PIO executes at 125 MHz. Its packed high count is truncated.
        ticks=round(ts/8e-9);high_ticks=int(value*ticks);low_ticks=ticks-high_ticks
        if high_ticks<2 or high_ticks>4097 or low_ticks<8 or low_ticks>16391:
            raise ValueError('Duty/PWM frequency exceeds c07 PIO high/low count fields.')
        high=high_ticks*8e-9
        if averaged:
            # Skip individual PWM edges, not the finite-packet latch/idle
            # structure. ADC, fast IRQ and background clocks are unchanged.
            rise=start+56e-9
            packet_windows.append([rise,start+packet_cycles*ts+40e-9])
            if rise>=-1e-12:push(rise,1,'packet_on',(gen,value,sid,0))
        else:
            for cycle in range(packet_cycles):
                rise=start+56e-9+cycle*ts
                if rise>=-1e-12:push(rise,1,'packet_on',(gen,value,sid,cycle))
                if rise+high>=-1e-12:push(rise+high,1,'packet_off',gen)
        push(start+packet_cycles*ts+40e-9,1,'packet_end',gen)
        if start<0:
            phase=(-start-56e-9)%ts
            applied=high_ticks/ticks
            on=(start+56e-9<=0<start+packet_cycles*ts+40e-9) if averaged else phase<high
            conducting=on or y[1]>1e-10
    if finite_pwm:
        # Normal-ON initialization: previous frame's already-running packet.
        # Starting a fresh packet at zero instead introduces a FIFO phase
        # catch-up transient that does not represent this periodic warm state.
        submit_phase=c['adc_phase']*ts+bus_period+(c['compute_us']+c['apply_us'])*1e-6
        schedule_packet(submit_phase-tu,d0,None)
        controller.metadata['pwm_model']='Finite c07 PIO packets, 125 MHz tick counts, 56 ns first rise and 40 ns packet overhead; fixed modeled CPU phases.'
        controller.metadata['pwm_initialization']='Previous normal-ON packet begins at submit_phase minus control_period; not board startup.'
        controller.metadata['pwm_packet_cycles']=packet_cycles
        if averaged:
            controller.metadata['pwm_model']='Finite c07 PIO packet-envelope average: quantized Duty and total high time preserved; packet first-rise/end/idle events retained; individual PWM ripple omitted.'
    if spacing and bus_period>tu+1e-12:
        warnings.append(f'{len(adc_channels)}チャネルADC占有 {bus_period*1e6:g} µs が要求周期 {tu*1e6:g} µs を超えるため測定が待ち行列になります。')
    if r03:
        warnings.extend(controller.metadata['configuration_warnings'])
        if c['experiment']=='irradiance' and stop-ramp_end<max(.5,10*c['mppt_period_ms']*.001):
            warnings.append('この日照試験は短時間です。MPPへの探索と保持を評価するには、変化後を長めに観測してください。')
    if c['compute_us']*1e-6>tu:warnings.append('演算時間が測定要求周期を超えるためCPU待ち行列が発生します。')
    if c['plant_mode']=='c07':warnings.append('c07は保存資料からの正常ON縮約モデルです。起動・故障・保護回路・ゲート駆動の完全再現ではありません。')
    if c['experiment']=='voltage' and c['algorithm'] in ('libresolar','fugu'):
        warnings.append('この方式の電圧追従試験にはLab追加の電圧目標アダプタを使用しています。元実装の追従性能そのものではありません。')
    if c['experiment']=='irradiance' and c['algorithm']=='baseline':warnings.append('従来PIDにLab独自のP&O電圧目標探索を追加した比較基準です。')
    record(t,y)
    while queue and not stopped and t<stop-1e-13:
        if cancelled is not None and cancelled():raise SimulationCancelled()
        if time.perf_counter()-tic>timeout:
            warnings.append('計算時間の上限に達しました。途中結果の整定時間は判定しません。');break
        end=queue[0][0]
        while end-t>2e-13:
            seg=(_backend.integrate(t,end,y,packed,physical_duty()) if averaged else
                plant.integrate_interval(t,end,y,c,panel,on,conducting,
                    max_step_fraction=max_step_fraction,prepared=packed,method=method))
            nfev+=seg['nfev'];steps+=seg['steps']
            observed=(_backend.records(seg['t'],seg['y'],packed,physical_duty()) if averaged else
                plant.record_observations(seg['t'],seg['y'],packed,on,conducting))
            # Display-only time integrals receive every accepted point before
            # any plot compaction. They never supply control or scoring values.
            if current_summary is not None:summarize_points(seg['t'],observed[:,[9,1,3,12,11]])
            observations=observed.tolist()
            for j,tt in enumerate(seg['t']):record(float(tt),seg['y'][:,j],observations[j])
            t=float(seg['t'][-1]);y=seg['y'][:,-1].copy()
            if seg['status']=='zero':
                y[1]=0.;conducting=False;log('diode_zero');continue
            if seg['status']!='end':
                warnings.append('モデル適用範囲または数値計算限界で停止: '+seg['status']);stopped=True;break
        if stopped:break
        t=end
        while queue and queue[0][0]<=t+1e-12:
            _,priority,_,kind,payload=heapq.heappop(queue)
            if phase_time is None or abs(t-phase_time)>1e-12:phase_time=t;timing_phase=-1
            timing_phase=max(timing_phase,priority)
            if kind=='frame':
                applied=ready;on=applied>0;conducting=on or y[1]>1e-10;frames+=1
                if ready_id is not None and by_id[ready_id]['applied_ms'] is None:
                    by_id[ready_id].update(applied_ms=t*1000,status='applied')
                log('pwm_latch',duty=applied,sample_id=ready_id)
                if not averaged:
                    if 0<applied<1:push(payload*ts+applied*ts,1,'off')
                    push((payload+1)*ts,1,'frame',payload+1)
            elif kind=='packet_on':
                gen,value,sid,cycle=payload
                if gen!=packet_generation:continue
                ticks=round(ts/8e-9);applied=int(value*ticks)/ticks
                on=True;conducting=True;frames+=packet_cycles if averaged else 1
                if cycle==0:
                    if sid is not None and sid in by_id:
                        by_id[sid].update(applied_ms=t*1000,status='applied')
                    log('pwm_packet',duty=applied,commanded_duty=value,sample_id=sid,cycles=packet_cycles,generation=gen)
            elif kind=='packet_off':
                if payload!=packet_generation:continue
                on=False;conducting=y[1]>1e-10
                if not conducting:y[1]=0.
            elif kind=='packet_end':
                if payload!=packet_generation:continue
                packet_active=False;on=False;conducting=y[1]>1e-10
                if packet_pending is not None:
                    value,sid=packet_pending;packet_pending=None;schedule_packet(t,value,sid)
            elif kind=='off':
                on=False;conducting=y[1]>1e-10
                if not conducting:y[1]=0.
            elif kind=='change':step_energy=float(y[4]);log('experiment_change')
            elif kind=='request':
                sid=payload;start=max(t,adc_free) if spacing else t
                acq=start+c['acquire_us']*1e-6
                arrival=acq+(len(adc_channels)-1)*spacing+c['transport_us']*1e-6
                if spacing:adc_free=arrival
                trace=dict(sample_id=sid,request_ms=t*1000,bus_start_ms=start*1000,
                    acquire_ms=None,arrival_ms=None,compute_start_ms=None,compute_end_ms=None,
                    ready_ms=None,applied_ms=None,measurement=None,output=None,status='pending',
                    superseded_by=None,channel_times_ms={},measurements={},analog_measurements={})
                if not _summary_only or len(timings)<2000:timings.append(trace)
                by_id[sid]=trace
                for k,key in enumerate(adc_channels):push(acq+k*spacing,3,'acquire',(sid,key))
                push(arrival,4,'arrival',sid)
                push((sid+1)*tu+c['adc_phase']*ts,3,'request',sid+1)
            elif kind=='acquire':
                sid,key=payload;tr=by_id[sid]
                ob=(_backend.observe(c,panel,y,t,packed,physical_duty()) if averaged else
                    plant.observe(c,panel,y,on,t=t,conducting=conducting,prepared=packed))
                if key in ('tbat','tsink'):
                    value=25. if key=='tbat' else 35.
                    tr['analog_measurements'][key]=value
                    codes=2**int(c['adc_bits']) if c['adc_bits'] else 0
                    tr['measurements'][key]=(math.floor((.5+.01*value)/2.5*codes)*2.5/codes-.5)*100 if codes else value
                else:
                    source={'v_pv':'v_sense','i_l':'i_sense','v_out':'vout_sense','i_pv':'ipv_sense','v_in':'v_in','v_bat':'v_bat_plus'}[key]
                    tr['analog_measurements'][key]=float(ob[source])
                    tr['measurements'][key]=quantize(ob[source],key.startswith('i_'))
                tr['channel_times_ms'][key]=t*1000
                if key=='v_pv':tr.update(acquire_ms=t*1000,measurement=tr['measurements'][key])
            elif kind=='arrival':
                tr=by_id[payload];tr['arrival_ms']=t*1000
                start=max(t,cpu_free);cpu_free=start+c['compute_us']*1e-6
                if r03:tr['compute_start_ms']=start*1000
                push(cpu_free if r03 else start,5,'compute',payload)
            elif kind=='compute':
                sid=payload;tr=by_id[sid]
                if not r03:tr['compute_start_ms']=t*1000
                m={**tr['measurements'],'i_out':tr['measurements']['i_l'],
                   'measurement_timestamp_s':tr['acquire_ms']*.001,
                   'channel_times_s':{k:v*.001 for k,v in tr['channel_times_ms'].items()},
                   'applied_duty':applied}
                if r03:
                    # Firmware's validity field is a software transfer bound,
                    # not the distance between the two ADC sample apertures.
                    m['pv_pair_span_us']=2*spacing*1e6
                result=controller.update(t,m,ref(t))
                controller_calls+=1;mode_counts[result['mode']]+=1
                is_slow=bool(getattr(controller,'slow',False))
                if is_slow:
                    slow_samples+=1
                    if not was_slow and slow_enter_ms is None:slow_enter_ms=t*1000
                was_slow=is_slow
                vref,iref=result['v_ref'],result['i_ref']
                pterm,iterm,dterm=result['p'],result['i'],result['d']
                tr.update(output=result['duty'],duty_updated=result['duty_updated'],mode=result['mode'])
                for ev in result['events']:
                    if ev.get('stage')=='parallel_pd':
                        pd_selected[ev['selected']]+=1
                        if ev.get('output',0)<0:pd_limiting[ev['selected']]+=1
                    log('controller',**ev)
                # Controller history remains bounded; complete event count is in metadata.
                if len(controller.events)>10000:controller.events.clear()
                push(t if r03 else t+c['compute_us']*1e-6,0,'complete',(sid,result['duty'],result['duty_updated']))
            elif kind=='complete':
                sid,value,changed=payload;tr=by_id[sid];tr['compute_end_ms']=t*1000
                if changed:command=value;push(t+c['apply_us']*1e-6,0,'ready',(sid,value))
                else:
                    tr['status']='held'
                    if _summary_only and not r03:by_id.pop(sid,None)
                if r03:push(max(t,tr['request_ms']*.001+c['c07_irq_occupancy_us']*1e-6),6,'background_begin')
            elif kind=='background_begin':
                if controller.begin_background(t):
                    log('controller',**controller.events[-1])
                    push(background_finish_time(t,c['c07_background_us']*1e-6),6,'background_finish')
            elif kind=='background_finish':
                controller.finish_background(t)
                log('controller',**controller.events[-1])
            elif kind=='ready':
                sid,value=payload
                if not finite_pwm and ready_id is not None and by_id[ready_id]['applied_ms'] is None:
                    by_id[ready_id].update(status='superseded',superseded_by=sid)
                if _summary_only and not finite_pwm and ready_id is not None and ready_id!=sid:by_id.pop(ready_id,None)
                ready_id,ready=sid,value;by_id[sid]['ready_ms']=t*1000
                if finite_pwm:
                    if value==0:
                        # board pwm_off stops an in-flight packet immediately.
                        packet_generation+=1;packet_active=False;packet_pending=None
                        if averaged and packet_windows:packet_windows[-1][1]=min(packet_windows[-1][1],t)
                        applied=0.;on=False;conducting=y[1]>1e-10
                        tr=by_id[sid];tr.update(applied_ms=t*1000,status='applied')
                        log('pwm_stop',sample_id=sid)
                    elif not packet_active:schedule_packet(t,value,sid)
                    elif packet_pending is None:packet_pending=(value,sid)
                    else:
                        raise ValueError('c07 PIO packet queue is full: control timing exceeds the modeled single pending packet.')
                elif averaged:
                    boundary=math.ceil(t/ts-1e-10)
                    # A compute/acquire event at an exact PWM boundary occurs
                    # after the already elapsed frame. A previously queued
                    # complete/ready event (priority0) occurs before it.
                    if abs(boundary*ts-t)<=1e-12 and timing_phase>=1:boundary+=1
                    latch_time=boundary*ts
                    if not any(q[3]=='frame' and abs(q[0]-latch_time)<1e-12 for q in queue):
                        push(latch_time,1,'frame',boundary)
            if averaged:last_observation_key=None
            record(t,y)
    completed=t>=stop-1e-10 and not stopped
    if not completed:warnings.append('指定終了時刻まで未計算のため、整定・MPP到達は未判定です。')
    voltage_settle=mppt_settle=None
    v_enter=change if last_voltage_outside is None else last_voltage_outside
    m_enter=ramp_end if last_mppt_outside is None else last_mppt_outside
    if completed and c['experiment']=='voltage' and t-v_enter>=max(5*tu,.002):
        voltage_settle=(v_enter-change)*1000
    hold=max(c['mppt_hold_ms']*.001,2*c['mppt_period_ms']*.001)
    if completed and c['experiment']=='irradiance' and t-m_enter>=hold:mppt_settle=(m_enter-ramp_end)*1000
    available=oracle.energy(t)-oracle.energy(change) if step_energy is not None else None
    extracted=float(y[4]-step_energy) if step_energy is not None else None
    deficit=available-extracted if available is not None else None
    residual=plant.stored_energy(c,y)-energy0-y[4]+y[5]+y[6]
    residual_pct=abs(residual)/max(abs(y[4]),1e-9)*100
    if residual_pct>.1:warnings.append('エネルギー収支残差が0.1%を超えています。計算精度を確認してください。')
    while len(records)>24000:compact()
    series={k:[row[j] for row in records] for j,k in enumerate(columns)}
    final=(_backend.observe(c,panel,y,t,packed,physical_duty()) if averaged else
        plant.observe(c,panel,y,on,t=t,conducting=conducting,prepared=packed))
    signal_map=attach_signal_metadata(c,controller.metadata)
    if averaged and finite_pwm:
        # Count the carrier periods represented in the returned interval,
        # including a partial previous/last packet, without queuing each edge.
        frames=sum(max(0,min(packet_cycles-1,math.floor((min(t,end)-rise)/ts+1e-9))-
            max(0,math.ceil(-rise/ts-1e-9))+1) for rise,end in packet_windows)
    if summary_count and current_summary is not None:
        current_summary.add_points(summary_times[:summary_count],summary_values[:summary_count])
    tuning=evaluator.result(completed,sample_period_s=tu) if evaluator is not None else None
    final_tracking_voltage=final['v_pv'] if legacy_r03_metrics else final[{'PV_RAW':'v_pv','PV_FUSED':'v_fused','VIN':'v_in'}[evaluator.node]]
    if not legacy_r03_metrics:
        controller.metadata['tracking_evaluation_voltage_node']=evaluator.node
        controller.metadata['voltage_comparison_note']='グラフのPV_RAW端子電圧は従来どおり。追従指標は制御目標と同じ真の節点 '+evaluator.node+' で評価します。'
    result=dict(config=c,series=series,timings=timings,events=events,controller=controller.metadata,signal_map=signal_map,
      waveform_summary=current_summary.snapshot() if current_summary is not None else waveform_unavailable('Tuning summary/averaged path does not retain PWM ripple display data.'),
      metrics=dict(completed=completed,settling_ms=voltage_settle,mppt_settling_ms=mppt_settle,
        tracking_efficiency_pct=100*extracted/available if available and c['experiment']=='irradiance' else None,
        energy_deficit_j=deficit if c['experiment']=='irradiance' else None,
        final_error_v=final_tracking_voltage-c['v_target'] if c['experiment']=='voltage' else None,
        overshoot_v=float(overshoot) if c['experiment']=='voltage' else None,
        peak_current_a=peak_current,elapsed_ms=(time.perf_counter()-tic)*1000,
        energy_residual_pct=float(residual_pct),initial_duty=float(d0),voltage_band_v=band,
        simulated_until_ms=t*1000,energy_in_j=float(y[4]),energy_battery_j=float(y[5]),
        energy_loss_j=float(y[6]),energy_residual_j=float(residual),actual_voc=panel.voc,
        evaluation_start_ms=change*1000,evaluation_end_ms=t*1000,mppt_hold_ms=hold*1000,
        mppt_settling_definition=f'日照変化終了後、真のMPP電力の{100-c["mppt_tolerance_pct"]:g}%以上を最後まで保持。最低{hold*1000:g}ms観測。全受理計算点で判定。',
        tracking_efficiency_definition='日照変化開始から終了までの実PV入力エネルギー ÷ 同区間のモデル真MPPエネルギー。変換効率ではありません。',
        energy_deficit_definition='同評価区間のモデル真MPPエネルギー − 実PV入力エネルギー。'),
      diagnostics=dict(warnings=warnings,solver='DOPRI5(4) / Numba' if method=='FAST' else method,
        accepted_steps=steps,nfev=nfev,pwm_cycles=frames,raw_points=raw_count,plot_points=len(records),
        averaging=averaged,model=('調整専用CCM平均化・詳細PWMではない' if averaged else 'c07保存資料由来・正常ON縮約・明示PWM' if c['plant_mode']=='c07' else '基本非同期Buck・明示PWM'),
        algorithm=c['algorithm'],experiment=c['experiment'],adc_frame_us=bus_period*1e6,
        adc_policy=f'{len(adc_channels)}ch serial with queue' if spacing else 'ideal simultaneous channels',
        timing_origin=('Normal-ON previous PIO packet; ADC requests k*control_period+phase*PWM_period; each completed duty submits one finite packet.' if finite_pwm else 'PWM starts t=0; ADC requests k*control_period+phase*PWM_period; controller clocks start on first delivered sample.'),
        clock_policy=controller.metadata['clock_policy'],gain_policy=controller.metadata['gain_policy'],
        plotting='評価は表示間引きの前の全受理点。調整専用summaryはグラフ点を約1000点に限定。' if _summary_only else '全PWMと受理計算点で評価。表示点のみブロック内の電圧・電流・電力・Dutyの極値を保持して削減。'))
    if not legacy_r03_metrics:
        result['tuning_metrics']=tuning
        if c['experiment']=='voltage':
            result['metrics']['settling_ms']=tuning['tracking']['settling_ms']
        result['metrics']['tracking_node']=evaluator.node
        result['metrics']['raw_final_error_v']=final['v_pv']-c['v_target'] if c['experiment']=='voltage' else None
        result['tuning_diagnostics']=dict(mode_counts=dict(mode_counts),pd_selected_counts=dict(pd_selected),
            pd_limiting_counts=dict(pd_limiting),slow_samples=slow_samples,slow_enter_ms=slow_enter_ms,
            controller_calls=controller_calls,event_counts=dict(event_counts),resumed_at_ms=None if resumed_at is None else resumed_at*1000)
    if averaged:
        result['diagnostics'].update(solver='L-stable SDIRK2 with step doubling',
            approximation=('CCM finite-packet envelope average; quantized Duty, packet high-time, first-rise/end/idle and native 8ch ADC/IRQ/background preserved; no PWM ripple' if finite_pwm else 'CCM state-space ON/OFF average; no PWM ripple; same discrete controller and ADC/CPU/latch event order'),
            missing_ripple_peak=True,dcm_domain_warning=_backend.domain_warning,
            effective_pwm_frames=frames if finite_pwm else int(math.floor(t/ts+1e-9))+1)
    if resumed_at is not None:
        result['diagnostics']['history_scope']='Resumed controller/ADC/duty/physical state. Only the returned interval uses this solver; previous averaged history is not full-PWM validation.'
    if _capture_state:
        result['snapshot']=deepcopy(dict(version=1,config=dict(c),controller=controller,y=y.copy(),t=t,
            queue=queue,sequence=sequence,by_id=by_id,applied=applied,command=command,ready=ready,ready_id=ready_id,
            cpu_free=cpu_free,adc_free=adc_free,on=on,conducting=conducting,averaged=averaged))
    return result
