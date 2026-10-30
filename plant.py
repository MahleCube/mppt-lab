"""Explicit-PWM normal-ON c07-derived plant; not the complete native c07 circuit.

The caller owns switch/ADC/control events. No PWM cycle is averaged or skipped.
See C07_MODEL_EXTENSION.md for reductions, source values and validity limits.
"""
from __future__ import annotations

import math
import numpy as np
from numba import njit
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

PLANT_DEFAULTS = dict(
    plant_mode="simple", input_l_uh=62., l2_dcr_ohm=.00522,
    pv_fuse_ohm=.01, input_shunt_ohm=.001, input_protection_ohm=.0096,
    pv_node_c_uf=.1, pv_node_esr_ohm=1e-6,
    cin_esr_ohm=3.5998306466501406e-7, cout_esr_ohm=.016330399136462944,
    out_protection_ohm=.0123, battery_fuse_ohm=.01,
    bat_node_c_uf=330., bat_node_esr_ohm=.01,
    bat_aux_c_uf=11., bat_aux_r_ohm=.02, bat_aux_esr_ohm=2e-7,
    diode_vf=.7, diode_r_ohm=.01, current_sense_tau_us=12.145,
    nonlinear_l=1., nonlinear_c=1.)
PLANT_LIMITS = dict(
    input_l_uh=(1,1000), l2_dcr_ohm=(0,.5), pv_fuse_ohm=(0,.5),
    input_shunt_ohm=(0,.1), input_protection_ohm=(0,.5),
    pv_node_c_uf=(.01,100), pv_node_esr_ohm=(0,.5),
    cin_esr_ohm=(0,.2), cout_esr_ohm=(1e-6,.5),
    out_protection_ohm=(1e-5,.5), battery_fuse_ohm=(1e-5,.5),
    bat_node_c_uf=(1,10000), bat_node_esr_ohm=(1e-6,.5),
    bat_aux_c_uf=(.1,1000), bat_aux_r_ohm=(1e-5,1),
    bat_aux_esr_ohm=(0,.5), diode_vf=(0,2), diode_r_ohm=(0,.5),
    current_sense_tau_us=(0,3000), nonlinear_l=(0,1), nonlinear_c=(0,1))
STATE_NAMES = ("v_pv_node_cap", "i_l", "v_out_cap", "v_sense",
    "energy_pv", "energy_bat", "energy_loss", "v_in_cap", "i_l2",
    "v_bat_plus_cap", "v_bat_aux_cap", "i_sense", "ipv_sense", "vout_sense")
STATE_INDEX = {name:i for i,name in enumerate(STATE_NAMES)}
N_STATE = len(STATE_NAMES)
PLANT_FIELDS = [
    dict(key=k,label=label,unit=unit,step=step,modes=modes,hint=hint)
    for k,label,unit,step,modes,hint in [
      ('input_l_uh','入力チョーク L2','µH',1,['c07'],'L2の電流を独立状態として計算'),
      ('l2_dcr_ohm','L2の直流抵抗','Ω',.001,['c07'],'入力直列損失とL2の電流変化に反映'),
      ('pv_fuse_ohm','PVヒューズ F2の抵抗','Ω',.001,['c07'],'PV_RAWとPV_FUSEDの電圧差'),
      ('input_shunt_ohm','入力シャント R27','Ω',.0001,['c07'],'入力L2電流を検出する1mΩ'),
      ('input_protection_ohm','入力保護MOS 2個のON抵抗合計','Ω',.001,['c07'],'正常ON固定抵抗の仮定'),
      ('pv_node_c_uf','PV_FUSEDの容量','µF',.01,['c07'],'ADC側100nFとは別の主回路100nF'),
      ('pv_node_esr_ohm','PV_FUSED容量のESR','Ω',.000001,['c07'],'保存モデルの未同定な極小ESR'),
      ('cin_esr_ohm','入力容量群の等価ESR','Ω',.000001,['c07'],'低周波縮約。個別高周波モードは省略'),
      ('cout_esr_ohm','出力容量群の等価ESR','Ω',.001,['c07'],'端子電圧と発熱へ反映。内部容量電圧とは別'),
      ('out_protection_ohm','出力保護MOS＋シャント抵抗','Ω',.001,['c07'],'電池側総抵抗の内訳。総抵抗から差し引いて電池内部Rを算出'),
      ('battery_fuse_ohm','電池ヒューズ F3の抵抗','Ω',.001,['c07'],'電池側総抵抗の内訳。BAT_PLUSとBAT_RAWを分離'),
      ('bat_node_c_uf','BAT_PLUSの容量','µF',10,['c07'],'保護後330µFの独立状態'),
      ('bat_node_esr_ohm','BAT_PLUS容量のESR','Ω',.001,['c07'],'330µF枝の直列抵抗'),
      ('bat_aux_c_uf','BAT_AUXの容量','µF',1,['c07'],'補助電池側11µFの独立状態'),
      ('bat_aux_r_ohm','BAT_AUX枝 F4＋F1の抵抗','Ω',.001,['c07'],'主充電経路へ直列加算しない'),
      ('bat_aux_esr_ohm','BAT_AUX容量のESR','Ω',.000001,['c07'],'保存値由来。実物の検証値ではない'),
      ('diode_vf','還流ダイオードの順方向降下','V',.01,['simple','c07'],'非同期BuckのOFF導通区間へ適用'),
      ('diode_r_ohm','還流ダイオードの導通抵抗','Ω',.001,['c07'],'平均Coreと同じ数値を置く明示仮定。物理Q2の同定値ではない'),
      ('current_sense_tau_us','電流センサの等価RC時定数','µs',.1,['c07'],'INA0.145µs＋出力RC12µsを1極へ縮約'),
      ('nonlinear_l','L1の電流依存曲線','0 / 1',1,['c07'],'1:保存Ldiff曲線を使用、0:指定Lへ固定'),
      ('nonlinear_c','Coutの電圧依存曲線','0 / 1',1,['c07'],'1:C13/C14＋MLCCのCdiff曲線、0:指定Coutへ固定')]]


def prepare(c, panel):
    """Pack coefficients once. Existing Rbattery is total normal-ON path R."""
    q = {**PLANT_DEFAULTS, **c}
    extended = q["plant_mode"] == "c07"
    rb = q["r_battery_ohm"] - q["out_protection_ohm"] - q["battery_fuse_ohm"] if extended else q["r_battery_ohm"]
    if rb <= 0:
        raise ValueError("c07では電池側総抵抗を出力保護抵抗＋F3抵抗より大きくしてください。")
    experiment = str(q.get("experiment", "voltage_step")).lower()
    changes_irradiance = "irr" in experiment or "sun" in experiment
    # Public experiment='irradiance' selects ramp/step through ramp_ms.
    # Retain explicit '*ramp*' names for direct callers of this plant API.
    is_ramp = changes_irradiance and (float(q.get("ramp_ms", 0.)) > 0. or "ramp" in experiment)
    is_step = changes_irradiance and not is_ramp
    g0 = max(float(q.get("irradiance",700.)),1e-12)
    iph_after = panel.iph * float(q.get("irradiance_after",g0))/g0
    # Passive divider loads are DC equivalents. Their separate ADC energy is
    # deliberately omitted; sensor RC states below are non-loading instruments.
    gp = 1/153300. + 1/830000. + 1/340200.
    gi = 1/15000. + 1/153300.
    go = 1/153300. + 1/(243000.+2740.+4990.)
    gbp = 1/153300. + 1/(236000.+4990.)
    p = np.array([q['cin_uf']*1e-6, q['l_uh']/214., q['cout_uf']/944.8731485952888,
        q['r_l_ohm'],q['r_switch_ohm'],rb,q['v_battery'],q['sense_tau_us']*1e-6,
        panel.iph,panel.saturation,panel.scale,q['input_l_uh']*1e-6,
        q['l2_dcr_ohm']+q['input_shunt_ohm']+q['input_protection_ohm'],
        q['pv_fuse_ohm'],q['pv_node_c_uf']*1e-6,q['pv_node_esr_ohm'],
        q['cin_esr_ohm'],q['cout_esr_ohm'],q['out_protection_ohm'],
        q['battery_fuse_ohm'],q['bat_node_c_uf']*1e-6,q['bat_node_esr_ohm'],
        q['bat_aux_c_uf']*1e-6,q['bat_aux_r_ohm'],q['bat_aux_esr_ohm'],
        q['diode_vf'],q['diode_r_ohm'],q['current_sense_tau_us']*1e-6,
        q['nonlinear_l'],q['nonlinear_c'],gp,gi,go,gbp,float(extended),
        iph_after,float(q.get('step_ms',10.))*.001,float(q.get('ramp_ms',10.))*.001,
        2. if is_ramp else (1. if is_step else 0.),q['l_uh']*1e-6,q['cout_uf']*1e-6,
        q['pwm_khz']*1000,q['rtol']], dtype=np.float64)
    return p


@njit(cache=True, fastmath=False)
def _iph(t,p):
    if p[38] == 0 or t < p[36]: return p[8]
    if p[38] == 1 or p[37] <= 0: return p[35]
    a = min(1.,max(0.,(t-p[36])/p[37]))
    return p[8]+a*(p[35]-p[8])


@njit(cache=True, fastmath=False)
def _ipv(v,t,p):
    return _iph(t,p)-p[9]*math.expm1(min(100.,v/p[10]))


@njit(cache=True, fastmath=False)
def _l_value(i,p):
    return np.interp(abs(i),L_I,L_DIFF)*p[1] if p[28] >= .5 else p[39]


@njit(cache=True, fastmath=False)
def _c_value(v,p):
    return (.00094+2*np.interp(abs(v),C_V,C_DIFF))*p[2] if p[29] >= .5 else p[40]


@njit(cache=True, fastmath=False)
def _nodes(t,y,p,on,conducting):
    """Eliminate passive resistor/ESR nodes without inserting artificial states.
    Result: PV_RAW,Ipv,PV_FUSED,VIN,VOUT,BAT_PLUS,BAT_RAW,Iprot,Ibat,
    Icpv,Icin,Icout,Icplus,Icaux,IL_effective.
    """
    il = y[1] if on or conducting else 0.
    if p[34] == 0:
        ip=_ipv(y[0],t,p); ib=(y[2]-p[6])/p[5]
        return np.array([y[0],ip,y[0],y[0],y[2],y[2],y[2],ib,ib,
            0.,ip-(il if on else 0.),il-ib,0.,0.,il])
    # vc=(1+Resr*Gp)*Vpv-[Rf*(1+Resr*Gp)+Resr]*Ipv+Resr*IL2.
    a=1+p[15]*p[30]; b=p[13]*a+p[15]; target=y[0]-p[15]*y[8]
    vp=(target+b*_iph(t,p))/a
    for _ in range(12):
        ex=math.exp(min(100.,vp/p[10])); ip=_iph(t,p)-p[9]*(ex-1)
        delta=(a*vp-b*ip-target)/(a+b*p[9]*ex/p[10])
        vp-=delta
        if abs(delta)<1e-12: break
    ip=_ipv(vp,t,p); vf=vp-p[13]*ip
    icpv=ip-y[8]-p[30]*vf
    vi=(y[7]+p[16]*(y[8]-(il if on else 0.)))/(1+p[16]*p[31])
    icin=y[8]-(il if on else 0.)-p[31]*vi
    gc=1/p[17]; gpr=1/p[18]; gf=1/p[19]; gcp=1/p[21]
    gb=1/p[5]; ga=1/(p[23]+p[24]); graw=gb+gf+ga
    av=gc+gpr+p[32]; bv=il+gc*y[2]
    ap=gcp+gpr+gf+p[33]-gf*gf/graw
    bp=gcp*y[9]+gf*(gb*p[6]+ga*y[10])/graw
    vplus=(bp+gpr*bv/av)/(ap-gpr*gpr/av)
    vo=(bv+gpr*vplus)/av
    vraw=(gb*p[6]+gf*vplus+ga*y[10])/graw
    iout=(vo-vplus)*gpr; ib=(vraw-p[6])*gb
    ico=(vo-y[2])*gc; icp=(vplus-y[9])*gcp; ica=(vraw-y[10])*ga
    return np.array([vp,ip,vf,vi,vo,vplus,vraw,iout,ib,icpv,icin,ico,icp,ica,il])


@njit(cache=True, fastmath=False)
def _rhs(t,y,p,on,conducting,out):
    a=_nodes(t,y,p,on,conducting)
    vp,ip,vf,vi,vo,vplus,vraw,iout,ib,icpv,icin,ico,icp,ica,il=a
    out[:] = 0.
    if p[34] == 0:
        out[0]=icin/p[0]; out[2]=ico/p[40]
        ind=p[39]
        loss=p[5]*ib*ib
    else:
        out[0]=icpv/p[14]; out[7]=icin/p[0]
        out[8]=(vf-vi-p[12]*y[8])/p[11]
        out[2]=ico/_c_value(y[2],p)
        out[9]=icp/p[20]; out[10]=ica/p[22]
        ind=_l_value(il,p)
        if3=(vplus-vraw)/p[19]
        loss=(p[13]*ip*ip+p[12]*y[8]*y[8]+p[15]*icpv*icpv+
            p[16]*icin*icin+p[17]*ico*ico+p[18]*iout*iout+
            p[19]*if3*if3+p[21]*icp*icp+(p[23]+p[24])*ica*ica+
            p[5]*ib*ib+p[30]*vf*vf+p[31]*vi*vi+p[32]*vo*vo+p[33]*vplus*vplus)
    if on:
        out[1]=(vi-vo-(p[3]+p[4])*il)/ind
        loss+=(p[3]+p[4])*il*il
    elif conducting:
        rd=p[26] if p[34] else 0.
        out[1]=(-vo-p[25]-(p[3]+rd)*il)/ind
        loss+=(p[3]+rd)*il*il+p[25]*il
    out[3]=(vf-y[3])/p[7] if p[7]>0 else 0.
    out[4]=vp*ip; out[5]=p[6]*ib; out[6]=loss
    if len(y)>7:
        out[11]=(il-y[11])/p[27] if p[27]>0 else 0.
        out[12]=(y[8]-y[12])/p[27] if p[27]>0 else 0.
        out[13]=(vo-y[13])/p[7] if p[7]>0 else 0.


def rhs(t,y,c,panel,on,conducting=True,*,prepared=None):
    p=prepare(c,panel) if prepared is None else prepared
    out=np.empty_like(np.asarray(y,dtype=float))
    _rhs(float(t),np.asarray(y,dtype=float),p,bool(on),bool(conducting),out)
    return out


def make_rhs(c,panel,on,conducting=True,*,prepared=None):
    p=prepare(c,panel) if prepared is None else prepared
    return lambda t,y: rhs(t,y,c,panel,on,conducting,prepared=p)


def observe(c,panel,y,on,t=0.,conducting=True,*,prepared=None):
    p=prepare(c,panel) if prepared is None else prepared
    a=_nodes(float(t),np.asarray(y),p,bool(on),bool(conducting))
    # Observation only: positive voltage/current is from switch node toward
    # VOUT. In a nonconducting OFF interval the ideal L has di/dt=0; the
    # unmodelled floating switch node follows VOUT and its L branch drop is0.
    il_effective=float(a[14])
    if on:
        vl_terminal=float(a[3]-p[4]*il_effective-a[4])
    elif conducting:
        rd=p[26] if p[34] else 0.
        vl_terminal=float(-p[25]-rd*il_effective-a[4])
    else:
        vl_terminal=0.
    vl=vl_terminal-p[3]*il_effective if on or conducting else 0.
    return dict(v_pv=float(a[0]),i_pv=float(a[1]),v_pv_fused=float(a[2]),
        v_fused=float(a[2]),i_l2=float(y[8]) if p[34] else None,
        v_l=float(vl),v_l_terminal=float(vl_terminal),
        v_in=float(a[3]),v_out=float(a[4]),v_bat_plus=float(a[5]),v_bat_raw=float(a[6]),
        i_protection=float(a[7]),i_battery=float(a[8]),i_l=float(y[1]),
        i_input=float(y[8]) if p[34] else float(a[1]),i_out=float(y[1]),
        v_sense=float(y[3] if p[7]>0 else a[2]),
        i_sense=float(y[11] if p[27]>0 and len(y)>7 else y[1]),
        ipv_sense=float(y[12] if p[27]>0 and len(y)>7 else (y[8] if p[34] else a[1])),
        i_l_sense=float(y[11] if p[27]>0 and len(y)>7 else y[1]),
        i_pv_sense=float(y[12] if p[27]>0 and len(y)>7 else (y[8] if p[34] else a[1])),
        vout_sense=float(y[13] if p[7]>0 and len(y)>7 else a[4]),
        p_pv=float(a[0]*a[1]),p_battery=float(p[6]*a[8]),
        l_diff_h=float(_l_value(y[1],p) if p[34] else p[39]),
        c_diff_f=float(_c_value(y[2],p) if p[34] else p[40]))


# Observation-only record path. This order is consumed by experiments.record;
# it shares _nodes with observe and does not change any differential equation.
RECORD_OBSERVATION_FIELDS = ('v_pv','i_pv','v_fused','i_l2','v_l','v_l_terminal',
    'v_in','v_out','v_bat_plus','i_l','v_sense','i_l_sense','i_pv_sense','vout_sense','p_pv')


@njit(cache=True, fastmath=False)
def record_observation(t,y,p,on,conducting):
    """Numeric equivalent of the fields of observe needed by the recorder.

    NaN represents the absent L2 channel in the simple model, converted back to
    None by the caller. No missing physical state is invented for that column.
    """
    a=_nodes(t,y,p,on,conducting)
    il_effective=a[14]
    if on:
        vl_terminal=a[3]-p[4]*il_effective-a[4]
    elif conducting:
        rd=p[26] if p[34] else 0.
        vl_terminal=-p[25]-rd*il_effective-a[4]
    else:
        vl_terminal=0.
    vl=vl_terminal-p[3]*il_effective if on or conducting else 0.
    values=np.empty(15)
    values[0]=a[0];values[1]=a[1];values[2]=a[2]
    values[3]=y[8] if p[34] else np.nan
    values[4]=vl;values[5]=vl_terminal;values[6]=a[3];values[7]=a[4];values[8]=a[5]
    values[9]=y[1];values[10]=y[3] if p[7]>0 else a[2]
    values[11]=y[11] if p[27]>0 and len(y)>7 else y[1]
    values[12]=y[12] if p[27]>0 and len(y)>7 else (y[8] if p[34] else a[1])
    values[13]=y[13] if p[7]>0 and len(y)>7 else a[4]
    values[14]=a[0]*a[1]
    return values


@njit(cache=True, fastmath=False)
def record_observations(times,states,p,on,conducting):
    """Observe every accepted point of one constant-switch segment in a batch."""
    result=np.empty((len(times),15))
    for j in range(len(times)):
        result[j]=record_observation(times[j],states[:,j],p,on,conducting)
    return result


def initial_state(c,panel):
    p=prepare(c,panel); vp=float(c['v_start']); ip=_ipv(vp,0.,p)
    if ip<=0 or vp<=p[6]+.8:
        raise ValueError("初期PV電圧を電池電圧+0.8Vより高く、現在日射のVoc未満にしてください。")
    if p[34] == 0:
        a=vp+p[25]; b=p[6]+p[25]+p[4]*ip
        duty=(b+math.sqrt(b*b+4*a*(p[3]+p[5])*ip))/(2*a)
        il=ip/duty
        return np.array([vp,il,p[6]+p[5]*il,vp,0.,0.,0.]),duty
    vf=vp-p[13]*ip; i2=ip-p[30]*vf; vi=vf-p[12]*i2
    def operating(d):
        il=(i2-p[31]*vi)/d
        # DC capacitors carry no current. Solve the two DC output-bus nodes.
        gr=1/p[18]; gb=1/(p[19]+p[5])
        vp1=(gr*il/(gr+p[32])+gb*p[6])/(gr+gb+p[33]-gr*gr/(gr+p[32]))
        vo=(il+gr*vp1)/(gr+p[32]); ib=(vp1-p[6])*gb
        vr=p[6]+p[5]*ib
        balance=d*vi-vo-p[3]*il-d*p[4]*il-(1-d)*(p[25]+p[26]*il)
        return balance,il,vo,vp1,vr
    try: duty=brentq(lambda d:operating(d)[0],.0200001,.9799999,xtol=1e-13)
    except ValueError as exc:
        raise ValueError("初期正常ON動作点がDuty2～98%内にありません。") from exc
    _,il,vo,vplus,vraw=operating(duty)
    if p[28]>=.5 and abs(il)>=30 or p[29]>=.5 and abs(vo)>=60:
        raise ValueError("c07代表L/C曲線の範囲（|IL|<30A、|VCout|<60V）外の初期点です。")
    y=np.zeros(N_STATE)
    y[:4]=vf,il,vo,vf
    y[7:]=vi,i2,vplus,vraw,il,i2,vo
    return y,duty


def _energy_integral(x,grid,values):
    """Integral_0^abs(x) u*value(u)du, exact for each linear table segment."""
    z=abs(float(x)); total=0.
    for j in range(len(grid)-1):
        a=float(grid[j]); b=min(z,float(grid[j+1]))
        if b<=a: break
        slope=(values[j+1]-values[j])/(grid[j+1]-grid[j])
        intercept=values[j]-slope*a
        total+=intercept*(b*b-a*a)/2+slope*(b**3-a**3)/3
        if b>=z:return float(total)
    if z>grid[-1]: total+=values[-1]*(z*z-grid[-1]**2)/2
    return float(total)


def stored_energy(c,y):
    q={**PLANT_DEFAULTS,**c}
    if q['plant_mode']!='c07':
        return .5*(q['cin_uf']*1e-6*y[0]**2+q['l_uh']*1e-6*y[1]**2+q['cout_uf']*1e-6*y[2]**2)
    el=(_energy_integral(y[1],L_I,L_DIFF)*q['l_uh']/214. if q['nonlinear_l']>=.5
        else .5*q['l_uh']*1e-6*y[1]**2)
    ec=((.5*.00094*y[2]**2+2*_energy_integral(y[2],C_V,C_DIFF))*q['cout_uf']/944.8731485952888
        if q['nonlinear_c']>=.5 else .5*q['cout_uf']*1e-6*y[2]**2)
    return float(el+ec+.5*(q['pv_node_c_uf']*1e-6*y[0]**2+q['cin_uf']*1e-6*y[7]**2+
        q['input_l_uh']*1e-6*y[8]**2+q['bat_node_c_uf']*1e-6*y[9]**2+
        q['bat_aux_c_uf']*1e-6*y[10]**2))


# Dormand-Prince5(4): independent switch intervals only; no cycle skipping.
_A=np.array([[0,0,0,0,0,0,0],[1/5,0,0,0,0,0,0],[3/40,9/40,0,0,0,0,0],
 [44/45,-56/15,32/9,0,0,0,0],[19372/6561,-25360/2187,64448/6561,-212/729,0,0,0],
 [9017/3168,-355/33,46732/5247,49/176,-5103/18656,0,0],
 [35/384,0,500/1113,125/192,-2187/6784,11/84,0]],dtype=float)
_B=np.array([35/384,0,500/1113,125/192,-2187/6784,11/84,0])
_E=_B-np.array([5179/57600,0,7571/16695,393/640,-92097/339200,187/2100,1/40])
_T=np.array([0,1/5,3/10,4/5,8/9,1,1])


@njit(cache=True,fastmath=False)
def _rkstep(t,y,h,p,on,conducting):
    n=len(y); k=np.empty((7,n)); stage=np.empty(n)
    for r in range(7):
        for j in range(n):
            s=0.
            for a in range(r):s+=_A[r,a]*k[a,j]
            stage[j]=y[j]+h*s
        _rhs(t+_T[r]*h,stage,p,on,conducting,k[r])
    trial=y.copy(); err=np.zeros(n)
    for j in range(n):
        for r in range(7):
            trial[j]+=h*_B[r]*k[r,j]; err[j]+=h*_E[r]*k[r,j]
    return trial,err


@njit(cache=True,fastmath=False)
def _event(y,p,on,conducting):
    if y[0]<=.1:return 3,0,.1,False
    imax=30. if p[34] and p[28]>=.5 else 60.
    if y[1]>=imax:return 4,1,imax,True
    if p[34] and p[29]>=.5 and y[2]>=60:return 5,2,60.,True
    if on and y[1]<=-.01:return 2,1,-.01,False
    if not on and conducting and y[1]<=0:return 1,1,0.,False
    return 0,0,0.,False


@njit(cache=True,fastmath=False)
def _integrate(t,end,initial,p,on,conducting,max_step,rtol):
    nstate=len(initial); capacity=128
    times=np.empty(capacity); states=np.empty((capacity,nstate)); times[0]=t;states[0]=initial
    y=initial.copy(); count=1; nfev=0; steps=0; h=min(max_step,end-t)
    code,_,_,_=_event(y,p,on,conducting)
    if code:return times[:count],states[:count].T.copy(),nfev,steps,code
    for attempt in range(200000):
        if t>=end:return times[:count],states[:count].T.copy(),nfev,steps,0
        # Addition of accepted steps can leave a few timestamp ULPs before the
        # requested endpoint. Snap only that representation-sized remainder;
        # do not drop an arbitrary physical-time interval such as 1 ps.
        if end-t<=8*np.spacing(max(abs(t),abs(end))):
            times[count-1]=end
            return times[:count],states[:count].T.copy(),nfev,steps,0
        h=min(h,max_step,end-t)
        if h<=1e-16 or t+h==t:break
        trial,err=_rkstep(t,y,h,p,on,conducting);nfev+=7
        norm=0.
        for j in range(nstate):
            atol=1e-10 if 4<=j<=6 else 1e-8
            e=err[j]/(atol+rtol*max(abs(y[j]),abs(trial[j])))
            norm+=e*e
            if not math.isfinite(trial[j]):norm=math.inf
        norm=math.sqrt(norm/nstate)
        if norm>1 or not math.isfinite(norm):
            h*=max(.1,.9*norm**(-.2)) if math.isfinite(norm) else .1
            continue
        code,idx,threshold,increasing=_event(trial,p,on,conducting)
        if code:
            lo=0.;hi=h
            for _ in range(50):
                mid=(lo+hi)/2; z,_=_rkstep(t,y,mid,p,on,conducting);nfev+=7
                beyond=z[idx]>=threshold if increasing else z[idx]<=threshold
                if beyond:hi=mid
                else:lo=mid
                if hi-lo<5e-14:break
            h=(lo+hi)/2;trial,_=_rkstep(t,y,h,p,on,conducting);nfev+=7
            trial[idx]=threshold
        t=end if not code and end-t<=h else t+h
        y=trial
        if count==capacity:
            capacity*=2;nt=np.empty(capacity);ns=np.empty((capacity,nstate))
            nt[:count]=times;ns[:count]=states;times=nt;states=ns
        times[count]=t;states[count]=y;count+=1;steps+=1
        if code:return times[:count],states[:count].T.copy(),nfev,steps,code
        h*=5. if norm==0 else min(5.,max(.2,.9*norm**(-.2)))
    return times[:count],states[:count].T.copy(),nfev,steps,-1


def integrate_interval(t,end,y,c,panel,on,conducting=True,max_step_fraction=.25,*,prepared=None,method="FAST"):
    p=prepare(c,panel) if prepared is None else prepared
    # A segment ending at an irradiance step uses its left limit at every
    # RK stage. The caller restarts at the boundary with the new irradiance.
    # Otherwise the endpoint stage could apply the new source too early.
    if p[38] == 1. and t < p[36] and end <= p[36]:
        p=p.copy();p[38]=0.
    max_step=max_step_fraction/p[41]
    if method=="FAST":
        times,states,nfev,steps,code=_integrate(float(t),float(end),np.asarray(y,dtype=float),
            p,bool(on),bool(conducting),max_step,c['rtol'])
        status={0:'end',1:'zero',2:'reverse',3:'collapse',4:'overcurrent',5:'curve_range',-1:'failed'}[code]
        return dict(t=times,y=states,nfev=int(nfev),steps=int(steps),status=status)
    events=[]; statuses=[]
    def add(index,level,direction,status):
        def event(tt,yy):return yy[index]-level
        event.direction=direction;event.terminal=True;events.append(event);statuses.append(status)
    add(0,.1,-1,'collapse');add(1,30 if p[34] and p[28]>=.5 else 60,1,'overcurrent')
    if p[34] and p[29]>=.5:add(2,60,1,'curve_range')
    if on:add(1,-.01,-1,'reverse')
    elif conducting:add(1,0,-1,'zero')
    sol=solve_ivp(make_rhs(c,panel,on,conducting,prepared=p),(t,end),y,method=method,
        rtol=c['rtol'],atol=1e-10,max_step=max_step,events=events)
    status='end' if sol.success else 'failed'
    if sol.status==1:status=next(statuses[i] for i,x in enumerate(sol.t_events) if len(x))
    return dict(t=sol.t,y=sol.y,nfev=sol.nfev,steps=len(sol.t)-1,status=status)


def warmup():
    """Compile the14-state and7-state paths without claiming a physical test."""
    class P:iph=9.611;saturation=1e-7;scale=4.
    c={**PLANT_DEFAULTS,'plant_mode':'c07','cin_uf':1419.9,'l_uh':214.,'cout_uf':945.,
       'r_l_ohm':.017,'r_switch_ohm':.01,'r_battery_ohm':.0623,'v_battery':51.2,
       'sense_tau_us':322.9,'pwm_khz':20.,'rtol':1e-5,'v_start':64.}
    y,d=initial_state(c,P());p=prepare(c,P())
    segment=integrate_interval(0.,1e-7,y,c,P(),True,prepared=p)
    record_observation(0.,y,p,True,True)
    record_observations(segment['t'],segment['y'],p,True,True)


# Exact digitized saved tables follow; generated once from the received snapshot.

L_I = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], dtype=float)
L_DIFF = np.array([0.000227, 0.000225, 0.000224, 0.000223, 0.000222, 0.00022099999999999998, 0.00021999999999999998, 0.00021899999999999998, 0.000217, 0.000216, 0.000215, 0.000213, 0.000212, 0.00021099999999999998, 0.00020899999999999998, 0.000208, 0.000207, 0.000205, 0.000204, 0.000202, 0.00019999999999999998, 0.00019899999999999999, 0.000197, 0.000195, 0.000193, 0.00019099999999999998, 0.00018899999999999999, 0.000186, 0.000184, 0.00017999999999999998, 0.000173], dtype=float)
C_V = np.array([0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 14.5, 15, 15.5, 16, 16.5, 17, 17.5, 18, 18.5, 19, 19.5, 20, 20.5, 21, 21.5, 22, 22.5, 23, 23.5, 24, 24.5, 25, 25.5, 26, 26.5, 27, 27.5, 28, 28.5, 29, 29.5, 30, 30.5, 31, 31.5, 32, 32.5, 33, 33.5, 34, 34.5, 35, 35.5, 36, 36.5, 37, 37.5, 38, 38.5, 39, 39.5, 40, 40.5, 41, 41.5, 42, 42.5, 43, 43.5, 44, 44.5, 45, 45.5, 46, 46.5, 47, 47.5, 48, 48.5, 49, 49.5, 50, 50.5, 51, 51.5, 52, 52.5, 53, 53.5, 54, 54.5, 55, 55.5, 56, 56.5, 57, 57.5, 58, 58.5, 59, 59.5, 60], dtype=float)
C_DIFF = np.array([1.000377e-05, 1.0004556644207483e-05, 9.994589144736188e-06, 9.974387559203447e-06, 9.944485577946502e-06, 9.905425940002714e-06, 9.857756202019259e-06, 9.802024868363762e-06, 9.738777884842261e-06, 9.668555493325224e-06, 9.591889440217146e-06, 9.509300528049927e-06, 9.421296496493124e-06, 9.328370216708087e-06, 9.230998181174325e-06, 9.129639269830485e-06, 9.024733772542146e-06, 8.916702647478391e-06, 8.80594699489459e-06, 8.692847726027809e-06, 8.577765407265313e-06, 8.461040260400473e-06, 8.342992300602766e-06, 8.223921594662601e-06, 8.104108623093978e-06, 7.983814730759701e-06, 7.863282651799843e-06, 7.742737095772564e-06, 7.62238538303957e-06, 7.5024181185310365e-06, 7.3830098940949075e-06, 7.2643200106633475e-06, 7.146493212447726e-06, 7.0296604262972146e-06, 6.91393950022178e-06, 6.7994359358855375e-06, 6.6862436106206135e-06, 6.574445485194863e-06, 6.464114294190154e-06, 6.355313216413189e-06, 6.248096523270287e-06, 6.142510203493768e-06, 6.038592563013674e-06, 5.936374799127485e-06, 5.835881548435745e-06, 5.737131408285965e-06, 5.640137431704657e-06, 5.544907596000408e-06, 5.451445245393304e-06, 5.359749508170069e-06, 5.269815688983388e-06, 5.181635637010317e-06, 5.095198090761034e-06, 5.010489000387999e-06, 4.927491828388534e-06, 4.8461878296234155e-06, 4.766556311591709e-06, 4.688574875909576e-06, 4.612219641939564e-06, 4.537465453508437e-06, 4.464286069636823e-06, 4.392654340184292e-06, 4.3225423672895546e-06, 4.253921653458317e-06, 4.186763237121659e-06, 4.121037816456165e-06, 4.056715862224157e-06, 3.993767720358572e-06, 3.93216370498278e-06, 3.87187418252144e-06, 3.812869647524365e-06, 3.755120790791708e-06, 3.6985985603560007e-06, 3.6432742158443543e-06, 3.589119376713094e-06, 3.536106064817069e-06, 3.4842067417469427e-06, 3.4333943413402224e-06, 3.3836422977452303e-06, 3.3349245693921764e-06, 3.2872156592015797e-06, 3.240490631337647e-06, 3.194725124792902e-06, 3.1498953640701752e-06, 3.1059781672091656e-06, 3.0629509513869088e-06, 3.020791736304962e-06, 2.979479145560378e-06, 2.9389924061829713e-06, 2.899311346507956e-06, 2.8604163925401037e-06, 2.8222885629540647e-06, 2.7849094628642557e-06, 2.7482612764878738e-06, 2.7123267588148556e-06, 2.6770892263900763e-06, 2.6425325473048723e-06, 2.608641130487564e-06, 2.5753999143755992e-06, 2.5427943550456542e-06, 2.5108104138720057e-06, 2.47943454477796e-06, 2.448653681140159e-06, 2.4184552224007506e-06, 2.388827020438053e-06, 2.359757365742335e-06, 2.3312349734395334e-06, 2.3032489692021477e-06, 2.275788875083377e-06, 2.248844595307404e-06, 2.2224064020459196e-06, 2.1964649212081844e-06, 2.171011118269523e-06, 2.1460362841605553e-06, 2.1215320212373182e-06, 2.0974902293502264e-06, 2.073903092027702e-06, 2.0507630627883547e-06, 2.0280628515937165e-06, 2.0057954114516103e-06, 1.9839539251786134e-06], dtype=float)
