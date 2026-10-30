"""Inspectable teaching ports of six control structures, NOT vendor firmware.

All physical values are SI. ADC transport, CPU queues and PWM latching belong to
engine.py. See ALGORITHMS.md for the source/port boundary and Buck derivation.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import math
import statistics
import c07_r03
import c07_r04

# Normalized-error PD limiter coefficients. Kd multiplies a sample difference,
# not a time derivative; exposing them must preserve the reference defaults.
FUGU_PD_DEFAULTS = dict(fugu_vin_kp=-100., fugu_vin_kd=-200.,
    fugu_vout_kp=1500., fugu_vout_kd=12000., fugu_iin_kp=100., fugu_iin_kd=200.,
    fugu_iout_kp=200., fugu_iout_kd=400., fugu_power_kp=20., fugu_power_kd=5.)
FUGU_PD_FIELDS = list(FUGU_PD_DEFAULTS)

CONTROL_DEFAULTS = dict(
    algorithm="baseline", experiment="voltage", mppt_method="inccond",
    voltage_period_us=100.0, current_period_us=100.0, mppt_period_ms=10.0,
    algorithm_filter_ms=0.0, mppt_step_v=0.2,
    voltage_kp=0.2, voltage_ki=8.0, current_kp=0.005, current_ki=2.0,
    current_limit_a=20.0, output_voltage_limit_v=58.0,
    input_current_limit_a=15.0, input_voltage_limit_v=53.0,
    power_limit_w=1000.0, duty_min=0.0, duty_max=0.98,
    voltage_deadband_v=0.05, libre_arr=2142.0, libre_step_counts=3.0,
    fugu_voltage_kp=8.0, fugu_fast_speed=0.5, fugu_slow_speed=0.02,
    fugu_slow_period_ms=500.0, model_voltage_gain=0.002,
    model_current_gain=0.1, model_delay_us=0.0, model_filter_ms=0.3,
    opensec_min_delta_v=0.05, opensec_max_step_v=0.5,
    custom_topology="voltage_duty", custom_law="pid", voltage_mode="PI", current_mode="PI",
    mppt_step_duty=.001, voltage_kd=0., current_kd=0., loop_derivative_filter_ms=.15,
    duty_response_gain=1.)

LIMITS = dict(
    voltage_period_us=(1, 1e6), current_period_us=(1, 1e6),
    mppt_period_ms=(0.02, 10000), algorithm_filter_ms=(0, 10000),
    mppt_step_v=(0.0001, 10), voltage_kp=(0, 100), voltage_ki=(0, 10000),
    current_kp=(0, 1), current_ki=(0, 1000), current_limit_a=(0.1, 60),
    output_voltage_limit_v=(1, 200), input_current_limit_a=(0.1, 60),
    input_voltage_limit_v=(1, 200), power_limit_w=(1, 10000),
    duty_min=(0, 0.97), duty_max=(0.01, 0.98),
    voltage_deadband_v=(0, 5), libre_arr=(100, 65535),
    libre_step_counts=(1, 100), fugu_voltage_kp=(0, 100),
    fugu_fast_speed=(0.001, 20), fugu_slow_speed=(0.0001, 5),
    fugu_slow_period_ms=(1, 10000), model_voltage_gain=(0, 1),
    model_current_gain=(0, 1), model_delay_us=(0, 5000), model_filter_ms=(0, 100),
    opensec_min_delta_v=(0.000001, 5), opensec_max_step_v=(0.0001, 10),
    mppt_step_duty=(.000001, .1), voltage_kd=(0, 10), current_kd=(0, 10),
    loop_derivative_filter_ms=(0, 1000), duty_response_gain=(0, 5))

CONTROL_DEFAULTS.update(FUGU_PD_DEFAULTS)
LIMITS.update({key: (-200000., 0.) if key.startswith('fugu_vin_') else (0., 200000.)
               for key in FUGU_PD_FIELDS})
CONTROL_DEFAULTS.update(c07_r03.EXTRA_DEFAULTS)
LIMITS.update(c07_r03.EXTRA_LIMITS)
CONTROL_DEFAULTS.update({k:v for k,v in c07_r04.EXTRA_DEFAULTS.items() if k not in CONTROL_DEFAULTS})
LIMITS.update(c07_r04.EXTRA_LIMITS)
# Both names are exported: the engine uses the more explicit CONTROL_LIMITS.
CONTROL_LIMITS = LIMITS

_LIMIT_FIELDS = ["duty_min", "duty_max", "current_limit_a", "output_voltage_limit_v", "duty_response_gain"]
_TWO_PI_FIELDS = ["voltage_period_us", "current_period_us", "mppt_period_ms",
                  "voltage_kp", "voltage_ki", "current_kp", "current_ki",
                  "algorithm_filter_ms", "mppt_step_v"] + _LIMIT_FIELDS
_BASE_PRESET = dict(CONTROL_DEFAULTS, control_us=100.0)


def _meta(ident, label, description, preset, fields, source, adaptation):
    return dict(id=ident, label=label, description=description,
                preset={**_BASE_PRESET, **preset, "algorithm": ident}, fields=fields,
                source=source, adaptation=adaptation,
                mppt_methods=["inccond", "po"] if ident in ("plexim", "custom") else [],
                source_firmware_executed=False)


ALGORITHMS = [
    _meta("baseline", "基準：直接 P / PI / PID",
          "PV電圧誤差からDutyを計算。日射実験だけ、比較用に追加したP&Oが目標を動かします。",
          {}, ["kp", "ti_ms", "td_ms", "derivative_filter_ms", "mppt_period_ms", "mppt_step_v", "duty_response_gain"],
          "このlabの従来engine.py", "メーカーのMPPT実装ではありません。日射実験のP&Oは追加機能です。"),
    _meta("ti", "TI型：IncCond → 電圧PI → 電流PI",
          "MPPTの目標電圧、電圧PIの電流目標、電流PIのDutyを順に計算します。",
          dict(control_us=20., voltage_period_us=20., current_period_us=20.,
               mppt_period_ms=10.1, algorithm_filter_ms=-.02/math.log(.999)),
          _TWO_PI_FIELDS,
          "TI C2000Ware DigitalPower SDK 26.01 LAB3 / mppt_incc.h / DCLF32.h",
          "Boostの構造をBuckへ移植。SIゲイン・Duty上限はlab用。IncCondの原典の外側 != Cond 比較を保持。MPPTにはPV入力電流を使います（原典はIL）。"),
    _meta("plexim", "Plexim型：可変幅MPPT → 低速電圧PI → 電流PI",
          "IncCondとP&Oを選択。電圧PIと電流PIは別の周期で動きます。",
          dict(control_us=50., voltage_period_us=500., current_period_us=50., mppt_period_ms=10.),
          ["mppt_method"] + _TWO_PI_FIELDS,
          "Plexim PLECS 4.7 Single-Phase PV Inverter with Partial Shading",
          "BoostモデルをBuckへ移植。公開可変stepの形を残し、step倍率・PI係数・制限をlab用に変更。ライブラリPIの内部実装の再現ではありません。"),
    _meta("libresolar", "Libre Solar型：直接P&O + CC/CV",
          "低速の判断ごとにPWM比較値を±3カウント。電流・出力電圧制限が方向判断に優先します。",
          dict(control_us=1000., mppt_period_ms=100., algorithm_filter_ms=-1/math.log(31/32)),
          ["mppt_period_ms", "algorithm_filter_ms", "libre_arr", "libre_step_counts", "voltage_deadband_v",
           "input_current_limit_a", "input_voltage_limit_v"] + _LIMIT_FIELDS,
          "Libre Solar MPPT2420HC rev.2 / b65f274541b1589d84c9ef30a567589d5f521539",
          "原典の通常P&OにPV電圧目標はありません。目標追従実験は追加した±3カウント追従枝。1秒充電状態機械・温度・再起動は対象外。"),
    _meta("fugu", "FUGU型：P&O速度 + 5つのPD制限 → 積分",
          "判断間もDutyを動かす速度を保持し、5つの制限器の最小出力と経過時間からDutyを更新します。",
          dict(control_us=2200., mppt_period_ms=1000/30, algorithm_filter_ms=-2.2/math.log(19/21)),
          ["mppt_period_ms", "fugu_slow_period_ms", "algorithm_filter_ms", "fugu_voltage_kp",
           "fugu_fast_speed", "fugu_slow_speed", "input_current_limit_a", "input_voltage_limit_v", "power_limit_w"] + FUGU_PD_FIELDS + _LIMIT_FIELDS,
          "FUGU fmetal / 51c1b9511de7ba2c0440f3f09f4233437c03934e",
          "原典に通常のPV電圧追従なし。追従実験は追加P速度枝。固定100 Hz notch→median5→EWMA2段。周波数自動追尾・初期sweep・同期整流は対象外。"),
    _meta("opensec", "Open-SEC型：P&O → Buckモデル制御",
          "入力コンデンサとコイルの電流収支から電流目標とDutyを計算。PI積分器は使いません。",
          dict(control_us=1e6/18800, current_period_us=1e6/18800, model_voltage_gain=.05,
               mppt_period_ms=20., mppt_step_v=.1, algorithm_filter_ms=-(1000/18800)/math.log(.93)),
          ["current_period_us", "mppt_period_ms", "mppt_step_v", "algorithm_filter_ms",
           "model_voltage_gain", "model_current_gain", "model_delay_us", "model_filter_ms",
           "opensec_min_delta_v", "opensec_max_step_v"] + _LIMIT_FIELDS,
          "OpenSmartEnergyConverter / 11bb2abe40cfa05160a197a04c03e1566eb88c51 / control.c Buck branch",
          "公開Buck枝を参考に再導出したLab適応版。逐次ADCを過去の共通時刻へ補間・平滑化し、c07の入力経路からVIN/PV端子電圧を推定。係数はLab用で、元ファームの実行ではありません。"),
    _meta("custom", "組み合わせ：MPPT・構造・追従器を選ぶ",
          "P&O/IncCond、直接Duty/電圧追従/電圧と電流の追従を選択するLab独自の学習用制御です。",
          dict(control_us=100., voltage_period_us=100., current_period_us=100.,
               voltage_kp=.003, voltage_ki=1.5, current_kp=.005, current_ki=2.,
               mppt_method="po", mppt_period_ms=20., mppt_step_v=.1,
               model_voltage_gain=.05, model_current_gain=.1),
          ["mppt_method", "mppt_period_ms", "mppt_step_v", "mppt_step_duty",
           "algorithm_filter_ms", "voltage_period_us", "current_period_us",
           "voltage_kp", "voltage_ki", "voltage_kd", "current_kp", "current_ki", "current_kd",
           "loop_derivative_filter_ms", "voltage_deadband_v", "model_voltage_gain",
           "model_current_gain", "model_delay_us", "model_filter_ms"] + _LIMIT_FIELDS,
          "Lab独自の離散PID・固定刻みP&O/IncCond。モデル枝はLab適応Open-SECの内側制御。",
          "構造に応じて電圧ゲインの単位が変わります。モデル式は電圧→電流→Duty構造でのみ選択できます。電圧実験ではMPPTを停止し、直接Dutyには追加の一歩追従を使います。"),
]
_c07 = _meta('c07_r03', 'c07 r03：IncCond → PV電圧PI → L1電流PI',
    'c07ファームウェアr03の変更していないC制御本体を実行。MPPTは背景処理で計算し、次の高速処理で受理します。',
    c07_r03.PRESET, c07_r03.FIELDS,
    'c07-firmware-c-r03 / firmware/core/c07_control.c (frozen source)',
    '正常ONの制御本体のみ。Labの初期動作点と連続PWMを使用し、ARM実行・起動・FAULT・watchdog・50発PIOは再現しません。')
_c07.update(preset_override_fields=c07_r03.TIMING_FIELDS, source_control_core_executed=True,
            source_control_core_sha256=c07_r03.CORE_HASH)
ALGORITHMS.append(_c07)
_c07 = _meta('c07_r04', 'c07 r04：IncCond → PV電圧PID → L1電流PI',
    'c07ファームウェアr04の改訂したC制御本体を実行。MPPTは背景処理で計算し、次の高速処理で受理します。',
    c07_r04.PRESET, c07_r04.FIELDS,
    'c07-firmware-c-r04 / firmware/core/c07_control.c (same C source)',
    '正常ONの制御本体のみ。Labの初期動作点と連続PWMを使用し、ARM実行・起動・FAULT・watchdog・50発PIOは再現しません。')
_c07.update(preset_override_fields=c07_r04.TIMING_FIELDS, source_control_core_executed=True,
            source_control_core_sha256=c07_r04.CORE_HASH)
ALGORITHMS.append(_c07)


def clip(x, lo, hi):
    return min(hi, max(lo, x))


class EMA:
    def __init__(self):
        self.value = None

    def update(self, x, alpha):
        self.value = x if self.value is None else self.value + alpha*(x-self.value)
        return self.value


class FixedNotch:
    """Fixed 100 Hz ESP-DSP-shaped notch, nominal sample clock, DC preloaded.

    Coefficient equations: Espressif dsps_biquad_gen_notch_f32 (Apache-2.0).
    Original Copyright 2018-2019 Espressif Systems (Shanghai) PTE LTD.
    This implementation changes state form/initialization; no binary equivalence.
    """
    def __init__(self, period):
        f = 100*period
        self.enabled = 0 < f < .45
        self.history = None
        w = 2*math.pi*f
        a = math.sin(w)/40
        gain = 10**(-30/40)
        self.coefs = ((1+a*gain)/(1+a), -2*math.cos(w)/(1+a),
                      (1-a*gain)/(1+a), -2*math.cos(w)/(1+a), (1-a)/(1+a))

    def update(self, x):
        if not self.enabled:
            return x
        if self.history is None:
            self.history = [x, x, x, x]
        x1, x2, y1, y2 = self.history
        b0, b1, b2, a1, a2 = self.coefs
        y = b0*x+b1*x1+b2*x2-a1*y1-a2*y2
        self.history = [x, x1, y, y1]
        return y


class PI:
    def __init__(self, kp, ki, initial=0., ti_previous_gate=False):
        self.kp, self.ki, self.integral = kp, ki, initial
        self.previous_gate = 1.
        self.ti_previous_gate = ti_previous_gate

    def update(self, error, dt, lo, hi):
        p = self.kp*error
        trial = self.integral + self.ki*dt*error*(self.previous_gate if self.ti_previous_gate else 1.)
        raw = p+trial
        if self.ti_previous_gate:
            self.integral = trial
        elif not ((raw > hi and error > 0) or (raw < lo and error < 0)):
            self.integral = trial
        raw = p+self.integral
        value = clip(raw, lo, hi)
        self.previous_gate = float(raw == value)
        return value, p, self.integral


class Controller:
    def __init__(self, config, duty, voltage):
        self.c = {**CONTROL_DEFAULTS, **config}
        self.duty_gain = self.c["duty_response_gain"]
        self.sample_period_s = float(self.c.get("control_us", 100))*1e-6
        self.metadata = deepcopy(next(m for m in ALGORITHMS if m["id"] == self.c["algorithm"]))
        self.metadata.update(clock_policy="sample-call quantized, no catch-up iterations",
                             gain_policy="explicit fixed SI teaching-port values; no automatic tuning",
                             initial_policy="warm operating point; filter histories preloaded; no firmware startup",
                             diagnostics="p/i/d are final-stage terms, not necessarily PID; see stages",
                             applied_configuration=deepcopy(self.c))
        self.metadata["duty_conversion"] = dict(
            gain=self.duty_gain, setting="duty_response_gain", range=[0.,5.],
            policy="Scale only final Duty correction; operating bias/feedforward and hard bounds are not multiplied",
            diagnostics="p/i/d are effective final-stage terms after scaling; raw conversion is recorded in stages",
            zero_policy="Normal correction disabled; bias/feedforward remains. Explicit direct limit/stop actions bypass multiplier.",
            limit_boundary="Current-reference limits still need feedback authority. At gain zero, PI/model loops cannot reduce Duty through that correction; these are not independent hardware protections.",
            domain="Educational adjustment range, not a stability range")
        self.metadata["diagnostic_terms"] = {
            "baseline": "Duty = initial bias + p + i + d (then clamp)",
            "ti": "Current PI p and integral i; d=0. Voltage PI terms are in stages.",
            "plexim": "Current PI p and integral i; d=0. Voltage PI terms are in stages.",
            "libresolar": "p = this decision's Duty increment; i=d=0; not PID terms",
            "fugu": "p = pre-quantization Duty increment; i = resulting Duty; d=0; do not sum p+i",
            "opensec": "p = model current-correction Duty; i=d=0; separate feedforward in stages",
            "custom": "Final-stage p/i/d plus explicit warm-start bias; direct/model terms are not PID. See control_chain and stages.",
            "c07_r03": "Unchanged C core: VOUT/VIN feedforward + current PI p + integral i, then limits/OFF handling; d=0. PV PI and CV limiter are separate states.",
            "c07_r04": "Same r04 C core: VOUT/VIN feedforward + L1 current PI p + integral i, then limits/OFF handling; displayed inner d=0. Outer PV reference-weighted PID derivative is a separate current-demand term, recorded in voltage-loop events.",
        }[self.c["algorithm"]]
        self.duty = float(clip(float(duty), self.c["duty_min"], self.c["duty_max"]))
        self.d0 = self.duty
        self.v_ref = float(voltage)
        self.i_ref = None
        self.p = self.i = self.d = 0.
        self.mode = "INITIAL"
        self.events = []
        self.stages = {}
        self.filters = {}
        self.clocks = {}
        self.last_t = self.last_measurement_t = self.started = None
        self.previous_mppt = None
        self.direction = 1
        self.mppt_updated = False
        self.duty_updated = False

    @property
    def mppt_enabled(self):
        return self.c.get("experiment", "voltage") == "irradiance"

    def emit(self, t, stage, **values):
        event = dict(t_s=t, stage=stage, **values)
        self.events.append(event)
        self.stages[stage] = event

    def conversion(self, base, correction, scaled, *, gain=None):
        """Expose the actual conversion without changing the scheduled events."""
        return dict(duty_base=base, duty_gain=self.duty_gain if gain is None else gain,
                    unscaled_correction=correction, scaled_correction=scaled,
                    unclamped_duty=base+scaled)

    def due(self, name, t, period, immediate=False, strict=False):
        if name not in self.clocks:
            self.clocks[name] = t-period if immediate else self.started
        elapsed = t-self.clocks[name]
        ready = elapsed > period+1e-12 if strict else elapsed >= period-1e-12
        if ready:
            self.clocks[name] = t
            return max(elapsed, 1e-12)
        return None

    def ema(self, name, x, tau_ms=None, alpha=None):
        if alpha is None:
            tau = self.c["algorithm_filter_ms"] if tau_ms is None else tau_ms
            alpha = 1. if tau <= 0 else -math.expm1(-self.sample_period_s/(tau*.001))
        return self.filters.setdefault(name, EMA()).update(x, alpha)

    def measurements(self, m):
        return {k:self.ema(k, v) for k,v in m.items()}

    def ref_clip(self, value):
        # Teaching-port feasibility guard, not a claim about the vendor limits.
        return clip(value, self.c.get("v_battery", 51.2)+.8,
                    self.c.get("pv_voc", 74.2)*.99)

    def simple_po(self, t, v, current):
        power = v*current
        if self.previous_mppt is not None and power < self.previous_mppt[2]:
            self.direction *= -1
        self.v_ref = self.ref_clip(self.v_ref+self.direction*self.c["mppt_step_v"])
        self.previous_mppt = (v, current, power)
        self.mppt_updated = True
        self.emit(t, "mppt", method="added_po", voltage=v, current=current, power=power,
                  direction=self.direction, v_ref=self.v_ref)

    def update(self, t_s, measurement, external_vref):
        t = float(t_s)
        if not math.isfinite(t) or (self.last_t is not None and t < self.last_t-1e-12):
            raise ValueError("Controller time must be finite and nondecreasing")
        raw = {k:float(measurement[k]) for k in ("v_pv", "i_pv", "i_l", "v_out", "i_out")}
        if not all(math.isfinite(x) for x in raw.values()):
            raise ValueError("Non-finite controller measurement")
        stamp = float(measurement.get("measurement_timestamp_s", t))
        if not math.isfinite(stamp):
            raise ValueError("Non-finite measurement timestamp")
        first = self.started is None
        if first:
            self.started = t
        dt = self.sample_period_s if self.last_t is None else max(t-self.last_t, 1e-12)
        measurement_dt = self.sample_period_s if self.last_measurement_t is None else max(stamp-self.last_measurement_t, 1e-12)
        before = len(self.events)
        self.mppt_updated = self.duty_updated = False
        if not self.mppt_enabled:
            if external_vref is None or not math.isfinite(float(external_vref)):
                raise ValueError("Voltage experiment needs a finite external reference")
            self.v_ref = float(external_vref)
        filtered = self.measurements(raw)
        self.run(t, raw, filtered, dt, measurement_dt, first)
        self.duty = clip(self.duty, self.c["duty_min"], self.c["duty_max"])
        self.last_t, self.last_measurement_t = t, stamp
        result = dict(duty=self.duty, v_ref=self.v_ref, i_ref=self.i_ref,
                      p=self.p, i=self.i, d=self.d, mppt_updated=self.mppt_updated,
                      mode=self.mode, duty_updated=self.duty_updated,
                      events=self.events[before:], measurements=dict(raw=raw, filtered=filtered),
                      stages=deepcopy(self.stages))
        return result


class Baseline(Controller):
    def __init__(self, *args):
        super().__init__(*args)
        self.integral = self.filtered_rate = 0.
        self.previous_voltage = self.v_ref

    def run(self, t, raw, m, dt, measurement_dt, first):
        if self.mppt_enabled and self.due("mppt", t, self.c["mppt_period_ms"]*.001):
            self.simple_po(t, m["v_pv"], m["i_pv"])
        e = m["v_pv"]-self.v_ref
        kp = self.c.get("kp", .003)*self.duty_gain
        mode = self.c.get("mode", "PI")
        rate = (m["v_pv"]-self.previous_voltage)/measurement_dt
        a = math.exp(-measurement_dt/(max(self.c.get("derivative_filter_ms", .15), 1e-9)*.001))
        self.filtered_rate = a*self.filtered_rate+(1-a)*rate
        self.p = kp*e
        self.d = kp*self.c.get("td_ms", 0.)*.001*self.filtered_rate if mode == "PID" else 0.
        ki = kp/(self.c.get("ti_ms", 2.)*.001) if mode != "P" else 0.
        trial = self.integral+ki*e*measurement_dt
        candidate = self.d0+self.p+trial+self.d
        if not ((candidate > self.c["duty_max"] and e > 0) or (candidate < self.c["duty_min"] and e < 0)):
            self.integral = trial
        self.i = self.integral
        self.duty = self.d0+self.p+self.i+self.d
        self.previous_voltage = m["v_pv"]
        self.mode = "ADDED_PO_TO_"+mode if self.mppt_enabled else mode
        self.duty_updated = True
        self.emit(t, "direct_voltage", error=e, p=self.p, i=self.i, d=self.d, bias=self.d0,
                  duty=clip(self.duty, self.c["duty_min"], self.c["duty_max"]),
                  **self.conversion(self.d0,(self.p+self.i+self.d)/self.duty_gain if self.duty_gain else self.c.get("kp",.003)*(e+(self.c.get("td_ms",0.)*.001*self.filtered_rate if mode=="PID" else 0.)),
                                    self.p+self.i+self.d))


class Cascade(Controller):
    def __init__(self, *args):
        super().__init__(*args)
        ti = self.c["algorithm"] == "ti"
        self.vpi = PI(self.c["voltage_kp"], self.c["voltage_ki"], ti_previous_gate=ti)
        self.ipi = PI(self.c["current_kp"]*self.duty_gain, self.c["current_ki"]*self.duty_gain, self.duty, ti_previous_gate=ti)

    def mppt(self, t, m):
        v, cur = m["v_pv"], m["i_pv"]
        step = self.c["mppt_step_v"]
        prev = self.previous_mppt
        dv = 0. if prev is None else v-prev[0]
        di = 0. if prev is None else cur-prev[1]
        dp = 0. if prev is None else v*cur-prev[2]
        change = 0.
        if self.c["algorithm"] == "ti":
            method = "ti_source_inccond"
            if prev is None:
                self.v_ref = v-10*step
            elif dv == 0:
                if di != 0:
                    self.v_ref = v+math.copysign(step, di)
            elif abs(v) > 1e-12:
                cond, inc = cur/v, di/dv
                if inc != cond:  # Retain source's documented outer-comparison issue.
                    self.v_ref = v+(step if inc > -cond else -step)
        elif self.c["mppt_method"] == "po":
            method = "plexim_variable_po"
            slope = clip(dp/(dv if dv != 0 else 1e-5), -10., 15.)
            change = step*((1 if slope >= 0 else -1)+.25*slope)
            self.v_ref = v+change
        else:
            method = "plexim_variable_inccond"
            if abs(dv) < .0001:
                change = 0. if abs(di) < .001 else .1*di
            elif abs(v) > 1e-12:
                cond = cur/v+di/dv
                if abs(cond) >= .001:
                    # Original maximum 14.805 V scaled to explicit lab max step.
                    change = step*clip(v*cond, -80., 80.)/80.
            self.v_ref = v+change
        self.v_ref = self.ref_clip(self.v_ref)
        self.previous_mppt = (v, cur, v*cur)
        self.mppt_updated = True
        self.emit(t, "mppt", method=method, voltage=v, current=cur, power=v*cur,
                  delta_v=dv, delta_i=di, delta_p=dp, v_ref=self.v_ref)

    def run(self, t, raw, m, dt, measurement_dt, first):
        if first:
            # Explicit warm start of the port; source firmware normally starts at zero.
            self.i_ref = raw["i_l"]
            self.vpi.integral = self.i_ref
        if self.mppt_enabled and self.due("mppt", t, self.c["mppt_period_ms"]*.001):
            self.mppt(t, m)
        vdt = self.due("voltage", t, self.c["voltage_period_us"]*1e-6, immediate=True)
        if vdt is not None:
            e = raw["v_pv"]-self.v_ref
            cap = self.c["current_limit_a"]
            if raw["v_out"] > self.c["output_voltage_limit_v"]:
                cap = 0.  # Explicit common-lab output limiter, not original TI policy.
            self.i_ref, vp, vi = self.vpi.update(e, vdt, 0., cap)
            self.emit(t, "voltage_pi", error=e, p=vp, i=vi, i_ref=self.i_ref)
        idt = self.due("current", t, self.c["current_period_us"]*1e-6, immediate=True)
        if idt is not None:
            e = self.i_ref-raw["i_l"]
            self.duty, self.p, self.i = self.ipi.update(e, idt, self.c["duty_min"], self.c["duty_max"])
            self.d = 0.
            self.duty_updated = True
            correction=self.p+(self.i-self.d0)
            self.emit(t, "current_pi", error=e, i_ref=self.i_ref, p=self.p, i=self.i, duty=self.duty,
                      **self.conversion(self.d0,correction/self.duty_gain if self.duty_gain else self.c["current_kp"]*e,correction))
        self.mode = ("INCCOND" if self.c["algorithm"] == "ti" else self.c["mppt_method"].upper())+"_TWO_PI" if self.mppt_enabled else "VOLTAGE_PI_TO_CURRENT_PI"


class LibreSolar(Controller):
    def __init__(self, *args):
        super().__init__(*args)
        self.count = int(round(self.duty*self.c["libre_arr"]))
        self.fraction = 0.
        self.previous_power = None
        self.power_good = None

    def run(self, t, raw, m, dt, measurement_dt, first):
        if self.mppt_enabled:
            self.v_ref = None
        if self.power_good is None:
            self.power_good = t
        if self.due("direct", t, self.c["mppt_period_ms"]*.001) is None:
            self.mode = self.mode if self.mode != "INITIAL" else "HOLD_BETWEEN_DECISIONS"
            return
        power = m["v_out"]*m["i_l"]
        if power >= 1:
            self.power_good = t
        vin = max(m["v_pv"], 1e-9)
        iin_est = power/vin
        direction = self.direction
        if t-self.power_good > 10 or power < -10:
            direction, self.mode = 0, "LOW_POWER_STOP"
            self.count = 0
            self.fraction = 0.
        elif m["v_out"] > self.c["output_voltage_limit_v"]:
            direction, self.mode = -1, "CV_OUTPUT"
        elif m["i_l"] > self.c["current_limit_a"]:
            direction, self.mode = -1, "CC_OUTPUT"
        elif iin_est > self.c["input_current_limit_a"]:
            direction, self.mode = -1, "CC_INPUT"
        elif m["v_pv"] < self.c["input_voltage_limit_v"] and power > 1:
            direction, self.mode = -1, "CV_INPUT_MIN"
        elif not self.mppt_enabled:
            e = m["v_pv"]-self.v_ref
            direction = 0 if abs(e) <= self.c["voltage_deadband_v"] else (1 if e > 0 else -1)
            self.mode = "ADDED_VOLTAGE_STEP"
        else:
            if self.previous_power is not None and power < self.previous_power:
                direction *= -1
            self.mode = "DIRECT_PO"
            self.mppt_updated = True
        self.previous_power = power  # Also updated under CC/CV.
        before_count=self.count
        applied_gain=self.duty_gain if self.mode in ("ADDED_VOLTAGE_STEP","DIRECT_PO") else 1.
        if self.mode not in ("ADDED_VOLTAGE_STEP","DIRECT_PO"):
            # A remainder from scaled tracking must not attenuate a full
            # integer CC/CV/stop step on its first limiting decision.
            self.fraction=0.
        requested_step=direction*int(self.c["libre_step_counts"])
        if direction:
            self.direction = direction
            total=requested_step*applied_gain+self.fraction
            integer=math.trunc(total)
            self.fraction=total-integer
            self.count += integer
        arr = int(self.c["libre_arr"])
        lo,hi=math.ceil(self.c["duty_min"]*arr),math.floor(self.c["duty_max"]*arr)
        self.count = int(clip(self.count,lo,hi))
        if self.count in (lo,hi):self.fraction=0.
        previous = self.duty
        self.duty = self.count/arr
        self.p, self.i, self.d = self.duty-previous, 0., 0.
        self.duty_updated = self.duty != previous
        self.emit(t, "direct_decision", power=power, iin_estimate=iin_est, direction=direction,
                  ccr=self.count, duty=self.duty, mode=self.mode, mppt=self.mppt_updated,
                  fractional_counts=self.fraction, requested_step_counts=requested_step,
                  scaled_step_counts=requested_step*applied_gain,
                  limit_bypasses_multiplier=applied_gain!=self.duty_gain,
                  **self.conversion(before_count/arr,requested_step/arr,requested_step*applied_gain/arr,gain=applied_gain))


class Fugu(Controller):
    def __init__(self, *args):
        super().__init__(*args)
        self.notches = {k:FixedNotch(self.sample_period_s) for k in ("v_pv", "v_out", "i_out")}
        self.medians = {k:deque(maxlen=5) for k in ("v_pv", "v_out", "i_out", "i_pv")}
        self.med = {}
        self.pd_previous = {}
        self.last_power = 0.
        self.last_reverse_v = 0.
        self.last_reverse_ms = 0
        self.eval_ms = None
        self.buf_p, self.buf_v = [], []
        self.best_power = 0.
        self.best_ms = 0
        self.best_count = 0
        self.slow = self.was_limited = False
        self.direction = -1
        self.period_counts = 4103
        self.max_counts = 3782
        self.count = int(round(self.duty*self.period_counts))
        self.fraction = 0.

    def measurements(self, raw):
        # Converter-output sensing is represented by IL in the common Buck.
        values = dict(v_pv=raw["v_pv"], v_out=raw["v_out"], i_out=raw["i_l"])
        values["i_pv"] = values["i_out"]*values["v_out"]/max(values["v_pv"]*.97, 1e-9)
        result = {}
        for key, value in values.items():
            x = self.notches[key].update(value) if key in self.notches else value
            window = self.medians[key]
            if not window:
                window.extend([x]*5)
            else:
                window.append(x)
            self.med[key] = statistics.median(window)
            y = self.ema(key+"_one", self.med[key])
            result[key] = self.ema(key+"_two", y)
        result["i_l"] = result["i_out"]
        return result

    def pd_limits(self, t, m):
        i_cap = self.ema("i_cap", self.c["current_limit_a"], alpha=2/201)
        p_cap = self.ema("p_cap", self.c["power_limit_w"], alpha=2/201)
        rows = [("VIN_MIN", self.med["v_pv"], self.c["input_voltage_limit_v"], self.c['fugu_vin_kp'], self.c['fugu_vin_kd']),
                ("VOUT_MAX", self.med["v_out"], self.c["output_voltage_limit_v"], self.c['fugu_vout_kp'], self.c['fugu_vout_kd']),
                ("IIN_MAX", self.med["i_pv"], self.c["input_current_limit_a"], self.c['fugu_iin_kp'], self.c['fugu_iin_kd']),
                ("IOUT_MAX", self.med["i_out"], i_cap, self.c['fugu_iout_kp'], self.c['fugu_iout_kd']),
                ("POWER_MAX", m["v_out"]*m["i_out"], p_cap, self.c['fugu_power_kp'], self.c['fugu_power_kd'])]
        outputs = {}
        for name, value, target, kp, kd in rows:
            e = 1-value/max(target, 1e-9)
            derivative = 0. if name not in self.pd_previous else kd*(e-self.pd_previous[name])
            self.pd_previous[name] = e
            outputs[name] = kp*e+derivative
        which = min(outputs, key=outputs.get)
        self.emit(t, "parallel_pd", outputs=outputs, selected=which, output=outputs[which])
        return outputs[which], which

    def tracker(self, t, m):
        now = math.floor(t*1000+1e-9)
        power, vin = m["v_out"]*m["i_out"], m["v_pv"]
        self.buf_p.append(power)
        self.buf_v.append(vin)
        period = self.c["fugu_slow_period_ms"] if self.slow else self.c["mppt_period_ms"]
        if now-self.eval_ms > period:
            self.eval_ms = now
            p = sum(self.buf_p)/len(self.buf_p)
            v = sum(self.buf_v)/len(self.buf_v)
            self.buf_p.clear(); self.buf_v.clear()
            dp = p-self.last_power
            absolute, relative = (.5, .0015) if self.slow else (1., .015)
            reverse = False
            if p < 1:
                self.direction = 1
            else:
                if abs(dp) >= absolute or (abs(self.last_power) > absolute and abs(dp)/(abs(self.last_power)+5) > relative):
                    self.last_power = p
                    reverse = dp < 0
                if abs(v-self.last_reverse_v)/(self.last_reverse_v+.1) > .05:
                    reverse = True
                if reverse:
                    self.direction *= -1
                    self.last_reverse_ms, self.last_reverse_v = now, v
            if now-self.best_ms > 300000 or (now-self.best_ms > 30000 and p < self.best_power*.85):
                self.best_power = 0.
            if p > self.best_power*1.005:
                self.best_power, self.best_ms, self.best_count = p, now, self.count
            self.mppt_updated = True
            self.emit(t, "mppt", method="fugu_po_speed", mean_power=p, mean_voltage=v,
                      delta_p=dp, direction=self.direction, slow=self.slow, period_ms=period)
        slow = power > (.5 if self.slow else 2.) and now-self.best_ms > 30000 and now-self.last_reverse_ms < 15000
        if slow and not self.slow:
            self.slow = True
            return self.best_count-self.count
        self.slow = slow
        return self.direction*(self.c["fugu_slow_speed"] if slow else self.c["fugu_fast_speed"])

    def run(self, t, raw, m, dt, measurement_dt, first):
        if self.mppt_enabled:
            self.v_ref = None
        now = math.floor(t*1000+1e-9)
        if self.eval_ms is None:
            self.eval_ms = now
        limit, which = self.pd_limits(t, m)
        limited = limit < 0
        if limited or self.was_limited:
            u = limit
            self.direction = -1 if limited else 1
            self.eval_ms = now  # Source resets P&O time without clearing interval buffers.
            self.mode = "LIMIT_"+which if limited else "LIMIT_RELEASE"
        elif self.mppt_enabled:
            u = self.tracker(t, m)
            self.mode = "PO_SLOW_SPEED" if self.slow else "PO_FAST_SPEED"
        else:
            # Added experiment branch, not a purported original FUGU Vref loop.
            u = self.c["fugu_voltage_kp"]*(self.med["v_pv"]-self.v_ref)
            self.mode = "ADDED_VOLTAGE_SPEED"
        self.was_limited = limited
        requested_speed=u
        applied_gain=1. if limited or self.mode=="LIMIT_RELEASE" else self.duty_gain
        # Constraint speed remains the ceiling after scaling normal tracking.
        u = min(u*applied_gain, limit)
        increment = 0. if first else clip(u*.025*self.max_counts*dt, -self.count, .008*self.max_counts)
        total = increment+self.fraction
        integer = math.trunc(total)
        self.fraction = total-integer
        previous = self.count
        lo = math.ceil(self.c["duty_min"]*self.period_counts)
        hi = min(self.max_counts, math.floor(self.c["duty_max"]*self.period_counts))
        self.count = int(clip(self.count+integer, lo, hi))
        if self.count >= hi:
            self.direction = -1
        elif self.count <= lo:
            self.direction = 1
        self.duty = self.count/self.period_counts
        self.p, self.i, self.d = increment/self.period_counts, self.duty, 0.
        self.duty_updated = previous != self.count
        self.emit(t, "speed_integrator", speed=u, elapsed_s=0. if first else dt,
                  delta_counts=increment, fractional_counts=self.fraction,
                  count=self.count, duty=self.duty, mode=self.mode,
                  requested_speed=requested_speed, duty_gain=applied_gain,
                  scaled_speed_before_limit=requested_speed*applied_gain,
                  limit_speed=limit,limit_bypasses_multiplier=applied_gain!=self.duty_gain,
                  duty_base=previous/self.period_counts,scaled_correction=increment/self.period_counts)


class OpenSEC(Controller):
    def __init__(self, *args):
        super().__init__(*args)
        self.previous_meter = None
        self.direction = -1
        self.channel_history = {}
        self.previous_aligned = None
        self.previous_model_stamp = None
        self.metadata['input_model'] = 'c07 PV_FUSED to VIN/PV_RAW estimates from four ADC channels and configured R/L/C; no plant-state access'
        self.metadata['alignment'] = 'Causal interpolation to earliest current channel timestamp, then equal EMA; analog sensor RC delays remain'

    def update(self, t_s, measurement, external_vref):
        stamp = float(measurement.get('measurement_timestamp_s', t_s))
        supplied = measurement.get('channel_times_s', {})
        self.channel_times = {k:float(supplied.get(k, stamp)) for k in ('v_pv','v_out','i_l','i_pv')}
        if any(not math.isfinite(v) or v > t_s+1e-12 for v in self.channel_times.values()):
            raise ValueError('ADC timestamps must be finite and no later than calculation time')
        self.applied_duty = float(measurement.get('applied_duty', self.duty))
        if not math.isfinite(self.applied_duty) or not 0 <= self.applied_duty <= 1:
            raise ValueError('Applied PWM Duty must be within 0..1')
        return super().update(t_s, measurement, external_vref)

    def measurements(self, raw):
        stamp = min(self.channel_times.values())
        values = {}; self.alignment_ready = True
        for key, now in self.channel_times.items():
            previous = self.channel_history.get(key)
            if previous is not None and now <= previous[0]:
                raise ValueError('ADC channel timestamps must increase')
            if abs(now-stamp) < 1e-12:
                values[key] = raw[key]
            elif previous is not None and previous[0] <= stamp <= now:
                f = (stamp-previous[0])/(now-previous[0])
                values[key] = previous[1]+f*(raw[key]-previous[1])
            else:
                self.alignment_ready = False
                values[key] = raw[key]
            self.channel_history[key] = (now, raw[key])
        if not self.alignment_ready:
            # A sequential first frame has no earlier samples to interpolate.
            # Hold the warm-start Duty instead of inventing simultaneous data.
            return dict(raw)
        previous = self.previous_aligned
        elapsed = self.sample_period_s if previous is None else stamp-previous[0]
        if elapsed <= 0: raise ValueError('Aligned measurement clock must advance')
        tau = self.c['model_filter_ms']*.001
        alpha = 1. if tau <= 0 else -math.expm1(-elapsed/tau)
        self.fast = {k:self.ema('model_'+k,v,alpha=alpha) for k,v in values.items()}
        self.fast['i_out'] = self.fast['i_l']
        rates = {k:0. if previous is None else (self.fast[k]-previous[1][k])/elapsed for k in values}
        self.previous_aligned = (stamp,dict(self.fast))
        self.aligned_stamp, self.aligned_dt = stamp, elapsed
        self.input_estimate = self.estimate_input(self.fast, rates)
        meter = {**self.fast, 'v_pv':self.input_estimate['pv_terminal_v'],
                 'i_pv':self.input_estimate['panel_current_a']}
        meter_tau = self.c['algorithm_filter_ms']*.001
        meter_alpha = 1. if meter_tau <= 0 else -math.expm1(-elapsed/meter_tau)
        return {k:self.ema('meter_'+k,v,alpha=meter_alpha) for k,v in meter.items()}

    def estimate_input(self, values, rates):
        """Low-bandwidth circuit reconstruction, using only acquired values.

        Applying identical linear filtering to the linear L2/R/C relations
        gives estimates of filtered nodes, not instantaneous switching nodes.
        Unequal analog RCs and interpolation error remain model limitations.
        """
        vf, i2 = values['v_pv'], values['i_pv']
        if self.c.get('plant_mode', 'simple') != 'c07':
            return dict(vin_v=vf, pv_terminal_v=vf, panel_current_a=i2,
                        input_load_a=0., r_drop_v=0., l_drop_v=0.)
        r2 = sum(self.c.get(k,d) for k,d in (('l2_dcr_ohm',.00522),
                 ('input_shunt_ohm',.001),('input_protection_ohm',.0096)))
        resistive = r2*i2
        inductive = self.c.get('input_l_uh',62.)*1e-6*rates['i_pv']
        vin = vf-resistive-inductive
        # Same configured passive-divider network as the public c07 plant.
        gp, gi = 1/153300.+1/830000.+1/340200., 1/15000.+1/153300.
        ipanel = i2+gp*vf+self.c.get('pv_node_c_uf',.1)*1e-6*rates['v_pv']
        vp = vf+self.c.get('pv_fuse_ohm',.01)*ipanel
        return dict(vin_v=vin,pv_terminal_v=vp,panel_current_a=ipanel,
                    input_load_a=gi*vin,r_drop_v=resistive,l_drop_v=inductive)

    def mppt(self, t, m):
        v, power = m["v_pv"], m["v_pv"]*m["i_pv"]
        dv = 0. if self.previous_meter is None else v-self.previous_meter[0]
        dp = 0. if self.previous_meter is None else power-self.previous_meter[1]
        maximum = self.c['opensec_max_step_v']
        base = min(self.c['mppt_step_v'], maximum)
        bits = int(self.c.get('adc_bits',0))
        two_codes = 2*self.c.get('adc_voltage_range_v',116.13636363636364)/(2**bits-1) if bits else 0.
        threshold = max(self.c['opensec_min_delta_v'],two_codes)
        probe = self.previous_meter is None or abs(dv) <= threshold
        slope = None if probe else dp/dv
        if not probe:
            self.direction = 1 if slope > 0 else -1
        step = base if probe else min(maximum,base*(1+abs(slope)))
        old_ref = self.v_ref
        self.v_ref = self.ref_clip(old_ref+self.direction*step)
        actual_step = self.v_ref-old_ref
        if actual_step:
            self.direction = 1 if actual_step > 0 else -1
        else:
            self.direction *= -1  # At a feasibility endpoint, probe inward next time.
        self.previous_meter = (v, power)
        self.mppt_updated = True
        self.emit(t, "mppt", method="opensec_variable_po", voltage=v, power=power,
                  delta_v=dv, delta_p=dp, step_v=abs(actual_step), requested_step_v=step,
                  delta_v_threshold=threshold, probe=probe, slope_w_per_v=slope,
                  zero_dv_double_step=False, direction=self.direction, v_ref=self.v_ref)

    def run(self, t, raw, m, dt, measurement_dt, first):
        if not self.alignment_ready:
            self.mode = 'BUCK_MODEL_WAIT_FOR_HISTORY'
            self.emit(t,'measurement_alignment',ready=False,reason='first sequential ADC frame; Duty held')
            return
        if self.mppt_enabled and self.due("mppt", t, self.c["mppt_period_ms"]*.001):
            self.mppt(t, m)
        scheduled_dt = self.due("model", t, self.c["current_period_us"]*1e-6, immediate=True)
        if scheduled_dt is None:
            return
        model_dt = self.aligned_dt if self.previous_model_stamp is None else self.aligned_stamp-self.previous_model_stamp
        self.previous_model_stamp = self.aligned_stamp
        v, vin = self.input_estimate['pv_terminal_v'], self.input_estimate['vin_v']
        vo, il, ipv = (self.fast[k] for k in ('v_out','i_l','i_pv'))
        operating_duty = self.applied_duty
        capacitance = self.c.get("cin_uf", 1420.)*1e-6
        inductance = self.c.get("l_uh", 214.)*1e-6
        resistance = self.c.get("r_l_ohm", .017)
        ron = self.c.get("r_switch_ohm", .01)
        diode = self.c.get("diode_vf", .7)
        diode_r = self.c.get("diode_r_ohm", .01) if self.c.get("plant_mode", "simple") == "c07" else 0.
        kv, ki = self.c["model_voltage_gain"], self.c["model_current_gain"]
        delay = self.c["model_delay_us"]*1e-6
        il_pred = il+delay/inductance*(operating_duty*vin-vo-resistance*il
                   -(1-operating_duty)*(diode+diode_r*il)-operating_duty*ron*il)
        input_current_request = ipv-self.input_estimate['input_load_a']+kv*capacitance*(v-self.v_ref)/model_dt
        free_iref = input_current_request/max(operating_duty, .05)
        cap = self.c["current_limit_a"]
        if vo > self.c["output_voltage_limit_v"]:
            cap = 0.
        self.i_ref = clip(free_iref, 0., cap)
        denominator = max(vin+diode+(diode_r-ron)*il_pred, 1.)
        feedforward = (vo+diode+(resistance+diode_r)*il_pred)/denominator
        correction = inductance*ki*(self.i_ref-il_pred)/(model_dt*denominator)
        scaled=correction*self.duty_gain
        self.duty = clip(feedforward+scaled, self.c["duty_min"], self.c["duty_max"])
        self.p, self.i, self.d = scaled, 0., 0.
        self.mode = "BUCK_MODEL_CURRENT_LIMIT" if self.i_ref != free_iref else "BUCK_MODEL_VOLTAGE"
        self.duty_updated = True
        self.emit(t, "buck_model", v_ref=self.v_ref, input_current_request=input_current_request,
                  i_ref=self.i_ref, predicted_i_l=il_pred, elapsed_s=model_dt,
                  schedule_elapsed_s=scheduled_dt,measurement_time_s=self.aligned_stamp,
                  measurement_age_s=t-self.aligned_stamp,operating_duty=operating_duty,
                  measured_pv_fused_v=self.fast['v_pv'],**self.input_estimate,
                  feedforward=feedforward, correction=scaled, duty=self.duty,
                  **self.conversion(feedforward,correction,scaled),
                  mode=self.mode)


def validate_custom_configuration(c):
    """Validate architecture, without treating a tuning recommendation as law."""
    choices = {"custom_topology":("direct_duty", "voltage_duty", "voltage_current"),
               "custom_law":("pid", "model"), "voltage_mode":("P", "PI", "PID"),
               "current_mode":("P", "PI", "PID")}
    for key, allowed in choices.items():
        if c[key] not in allowed:
            raise ValueError(f"{key} must be one of {', '.join(allowed)}")
    if c["algorithm"] == "custom" and c["custom_law"] == "model" and c["custom_topology"] != "voltage_current":
        raise ValueError("モデル制御は voltage_current（電圧→電流→Duty）構造でのみ使用できます。")


class LoopPID:
    """Independent SI PID, derivative on measurement, conditional integration.

    Voltage control uses e=measured-reference and +d(measured)/dt for a Buck.
    Current control uses e=reference-measured and -d(measured)/dt.
    The constant operating-point bias is deliberately separate from integral.
    """
    def __init__(self, mode, kp, ki, kd, filter_s, bias, derivative_sign, output_gain=1.):
        self.mode, self.kp, self.ki, self.kd = mode, kp, ki, kd
        self.filter_s, self.bias, self.derivative_sign = filter_s, bias, derivative_sign
        self.output_gain=output_gain
        self.integral = self.rate = 0.
        self.previous_time = self.previous_measurement = None

    def update(self, error, measured, stamp, lo, hi):
        dt = 0. if self.previous_time is None else stamp-self.previous_time
        if dt < 0:
            raise ValueError("PID measurement clock must be nondecreasing")
        if self.previous_measurement is not None and dt > 0:
            rate = (measured-self.previous_measurement)/dt
            a = 0. if self.filter_s <= 0 else math.exp(-dt/self.filter_s)
            self.rate = a*self.rate+(1-a)*rate
        p = (self.kp*self.output_gain)*error
        d = self.derivative_sign*(self.kd*self.output_gain)*self.rate if self.mode == "PID" else 0.
        change = (self.ki*self.output_gain)*error*dt if self.mode != "P" else 0.
        trial = self.integral+change
        candidate = self.bias+p+trial+d
        blocked = (candidate > hi and change > 0) or (candidate < lo and change < 0)
        if not blocked:
            self.integral = trial
        integral = self.integral if self.mode != "P" else 0.
        raw = self.bias+p+integral+d
        self.previous_time, self.previous_measurement = stamp, measured
        return dict(output=clip(raw, lo, hi), p=p, i=integral, d=d, bias=self.bias,
                    output_gain=self.output_gain,unscaled_correction=(p+integral+d)/self.output_gain if self.output_gain else self.kp*error+(self.derivative_sign*self.kd*self.rate if self.mode=="PID" else 0.),
                    scaled_correction=p+integral+d,
                    error=error, measured=measured, measurement_time_s=stamp,
                    elapsed_s=dt, raw_output=raw, saturated=raw < lo or raw > hi,
                    integral_held=blocked)


class LocalMPPT:
    """Fixed-step local tracker: returns desired PV-voltage direction only.

    P&O compares power after its preceding perturbation. IncCond uses the
    standard local conductance sign. Tiny numerical zero tolerances are not
    advertised as sensor-noise rejection or global-MPP detection.
    """
    def __init__(self, method):
        self.method, self.previous, self.direction = method, None, 1

    def decide(self, voltage, current):
        power = voltage*current
        dv = di = dp = 0.
        reason, direction, slope = "initial_probe", self.direction, None
        if self.previous is not None:
            dv, di, dp = voltage-self.previous[0], current-self.previous[1], power-self.previous[2]
            if self.method == "po":
                direction = -self.direction if dp < 0 else self.direction
                reason = "power_decreased_reverse" if dp < 0 else "continue_previous_perturbation"
            elif abs(dv) <= 1e-9:
                direction = 0 if abs(di) <= 1e-9 else (1 if di > 0 else -1)
                reason = "unchanged_voltage_current_branch"
            else:
                slope = current+voltage*di/dv
                direction = 0 if abs(slope) <= 1e-6 else (1 if slope > 0 else -1)
                reason = "incremental_conductance"
        if direction:
            self.direction = direction
        self.previous = (voltage, current, power)
        return dict(method="custom_fixed_"+self.method, voltage=voltage, current=current,
                    power=power, delta_v=dv, delta_i=di, delta_p=dp,
                    voltage_direction=direction, slope_w_per_v=slope, reason=reason)

    def remember_motion(self, actual_voltage_direction, requested_direction):
        if actual_voltage_direction:
            self.direction = 1 if actual_voltage_direction > 0 else -1
        elif requested_direction:
            self.direction = -requested_direction

    def reset_observation(self):
        self.previous = None


def custom_metadata(controller, model=False):
    c, meta = controller.c, controller.metadata
    direct = c["custom_topology"] == "direct_duty"
    cascade = c["custom_topology"] == "voltage_current"
    node = "PV_RAW" if model or c.get("plant_mode", "simple") == "simple" else "PV_FUSED"
    first = ("P&O" if c["mppt_method"] == "po" else "IncCond") if controller.mppt_enabled else "指定電圧"
    chain = ([first, "電圧の上下判断", "Buckの逆符号", "Duty"] if direct else
             [first, "Vref", "C電流収支 → IL1目標", "L電圧収支 → Duty"] if model else
             [first, "Vref", "電圧"+c["voltage_mode"], "IL1目標", "電流"+c["current_mode"], "Duty"] if cascade else
             [first, "Vref", "電圧"+c["voltage_mode"], "Duty"])
    meta.update(control_chain=chain, custom_topology=c["custom_topology"], custom_law=c["custom_law"],
                feedback_voltage_node=node, target_voltage_node=None if direct and controller.mppt_enabled else node,
                evaluation_voltage_node="PV_RAW",
                feedback_current_node="L1", target_current_node="L1" if cascade else None,
                measurement_channels={"v_pv":"PV_FUSED ADC" if c.get("plant_mode") == "c07" else "PV_RAW ADC",
                                      "i_pv":"L2 current ADC" if c.get("plant_mode") == "c07" else "PV input current ADC",
                                      "i_l":"L1 current ADC", "v_out":"Buck output voltage ADC",
                                      "i_out":"L1 current alias; not measured battery current"},
                target_voltage_estimated=model, mppt_variant="common fixed-step local P&O/IncCond",
                mppt_numerical_zero_guards={"voltage_v":1e-9, "current_a":1e-9, "slope_a":1e-6},
                voltage_gain_units=None if direct or model else "A/V, A/(V*s), A*s/V" if cascade else "Duty/V, Duty/(V*s), Duty*s/V",
                current_gain_units="Duty/A, Duty/(A*s), Duty*s/A" if cascade and not model else None,
                inactive_settings=(["voltage_mode", "current_mode", "voltage_kp/ki/kd", "current_kp/ki/kd"] if direct or model else
                                   ["current_mode", "current_kp/ki/kd"] if not cascade else []),
                configuration_warnings=(["電流ループの要求周期が電圧ループより長い設定です。計算は可能ですが追従・安定性を確認してください。"]
                    if cascade and not model and c["current_period_us"] > c["voltage_period_us"] else []))
    if direct:
        meta["diagnostic_terms"] = "p = actual Duty step; i=d=0. No PID. Voltage experiment adds a fixed-step tracking branch."
    elif model:
        meta["diagnostic_terms"] = "p = model current-correction Duty; i=d=0. OpenSEC inner model with custom fixed-step MPPT."
    else:
        meta["diagnostic_terms"] = "Duty = warm-start bias + final-stage p + i + d, then clamp. The bias is recorded in stages."
    meta["signal_mapping"] = dict(measured_voltage=node, voltage_feedback="estimated panel terminal" if model else "latest sensed channel",
        measured_current="L1", input_current="L2" if c.get("plant_mode") == "c07" else "PV",
        target_current="L1" if cascade else None, pv_oracle_used=False,
        duty_sign="positive Duty change lowers PV voltage in the assumed normal Buck operating range")


class CustomController(Controller):
    def __init__(self, *args):
        super().__init__(*args)
        self.tracker = LocalMPPT(self.c["mppt_method"])
        self.vloop = self.iloop = None
        self.channel_stamps = {}; self.previous_channel_stamps = {}; self.filter_stamps = {}
        self.applied_duty = self.duty
        custom_metadata(self)

    def update(self, t_s, measurement, external_vref):
        stamp = float(measurement.get("measurement_timestamp_s", t_s))
        times = measurement.get("channel_times_s", {})
        self.channel_stamps = {k:float(times.get(k, stamp)) for k in ("v_pv", "i_l", "v_out", "i_pv")}
        for key, value in self.channel_stamps.items():
            if not math.isfinite(value) or value > t_s+1e-12:
                raise ValueError("ADC timestamps must be finite and no later than calculation time")
            if key in self.previous_channel_stamps and value <= self.previous_channel_stamps[key]:
                raise ValueError("ADC channel timestamps must increase")
        self.applied_duty = float(measurement.get("applied_duty", self.duty))
        if not math.isfinite(self.applied_duty) or not 0 <= self.applied_duty <= 1:
            raise ValueError("Applied PWM Duty must be within 0..1")
        result = super().update(t_s, measurement, external_vref)
        self.previous_channel_stamps = dict(self.channel_stamps)
        return result

    def measurements(self, raw):
        filtered = {}
        tau = self.c["algorithm_filter_ms"]*.001
        for key, value in raw.items():
            stamp = self.channel_stamps["i_l" if key == "i_out" else key]
            old = self.filter_stamps.get(key)
            elapsed = 0. if old is None else stamp-old
            alpha = 1. if tau <= 0 or old is None else -math.expm1(-elapsed/tau)
            filtered[key] = self.ema("custom_mppt_"+key, value, alpha=alpha)
            self.filter_stamps[key] = stamp
        return filtered

    def mppt(self, t, m):
        decision = self.tracker.decide(m["v_pv"], m["i_pv"])
        direction = decision["voltage_direction"]
        old = self.v_ref
        self.v_ref = self.ref_clip(old+direction*self.c["mppt_step_v"])
        self.tracker.remember_motion(self.v_ref-old, direction)
        self.mppt_updated = True
        self.emit(t, "mppt", **decision, step_v=self.v_ref-old, v_ref=self.v_ref)

    def _init_loops(self, raw):
        cascade = self.c["custom_topology"] == "voltage_current"
        tau = self.c["loop_derivative_filter_ms"]*.001
        self.vloop = LoopPID(self.c["voltage_mode"], self.c["voltage_kp"], self.c["voltage_ki"],
                            self.c["voltage_kd"], tau, raw["i_l"] if cascade else self.d0, 1., 1. if cascade else self.duty_gain)
        self.iloop = LoopPID(self.c["current_mode"], self.c["current_kp"], self.c["current_ki"],
                            self.c["current_kd"], tau, self.d0, -1., self.duty_gain)
        if cascade:
            self.i_ref = clip(raw["i_l"], 0., self.c["current_limit_a"])

    def run(self, t, raw, m, dt, measurement_dt, first):
        direct = self.c["custom_topology"] == "direct_duty"
        cascade = self.c["custom_topology"] == "voltage_current"
        limit = "OUTPUT_VOLTAGE" if raw["v_out"] > self.c["output_voltage_limit_v"] else "L1_CURRENT" if raw["i_l"] > self.c["current_limit_a"] else None
        if limit:
            self.tracker.reset_observation()
        if direct:
            if self.mppt_enabled:
                self.v_ref = None
            if self.due("direct", t, self.c["mppt_period_ms"]*.001) is None:
                self.mode = "CUSTOM_DIRECT_HOLD"
                return
            previous = self.duty
            if limit:
                self.duty = self.c["duty_min"]
                self.mode = "CUSTOM_DIRECT_LIMIT_"+limit
                self.emit(t, "custom_limit", limit=limit, action="command minimum Duty; not hardware protection")
            else:
                if self.mppt_enabled:
                    decision = self.tracker.decide(m["v_pv"], m["i_pv"])
                    direction = decision["voltage_direction"]
                    self.mppt_updated = True
                    self.mode = "CUSTOM_DIRECT_"+self.c["mppt_method"].upper()
                else:
                    error = m["v_pv"]-self.v_ref
                    direction = 0 if abs(error) <= self.c["voltage_deadband_v"] else (-1 if error > 0 else 1)
                    decision = dict(method="custom_added_voltage_step", voltage_direction=direction, error=error)
                    self.mode = "CUSTOM_DIRECT_ADDED_VOLTAGE_STEP"
                correction=-direction*self.c["mppt_step_duty"]
                self.duty = clip(previous+correction*self.duty_gain, self.c["duty_min"], self.c["duty_max"])
                self.tracker.remember_motion(-(self.duty-previous), direction)
                self.emit(t, "mppt" if self.mppt_enabled else "direct_voltage_step", **decision,
                          duty_step=self.duty-previous, duty=self.duty,
                          **self.conversion(previous,correction,correction*self.duty_gain))
            self.p, self.i, self.d = self.duty-previous, 0., 0.
            self.duty_updated = self.duty != previous
            return
        if self.vloop is None:
            self._init_loops(raw)
        if self.mppt_enabled and not limit and self.due("mppt", t, self.c["mppt_period_ms"]*.001):
            self.mppt(t, m)
        vdt = self.due("voltage", t, self.c["voltage_period_us"]*1e-6, immediate=True)
        if vdt is not None:
            high = (0. if raw["v_out"] > self.c["output_voltage_limit_v"] else self.c["current_limit_a"]) if cascade else self.c["duty_min"] if limit else self.c["duty_max"]
            terms = self.vloop.update(raw["v_pv"]-self.v_ref, raw["v_pv"], self.channel_stamps["v_pv"],
                                     0. if cascade else self.c["duty_min"], high)
            if cascade:
                self.i_ref = terms["output"]
                self.emit(t, "voltage_pid", **terms, i_ref=self.i_ref, loop_mode=self.c["voltage_mode"])
            else:
                self.duty = terms["output"]
                self.p, self.i, self.d = terms["p"], terms["i"], terms["d"]
                self.duty_updated = True
                self.emit(t, "voltage_pid", **terms, duty=self.duty, loop_mode=self.c["voltage_mode"],duty_base=terms["bias"],duty_gain=self.duty_gain)
        if cascade and self.due("current", t, self.c["current_period_us"]*1e-6, immediate=True) is not None:
            # An output-overvoltage limit overrides a held outer reference too.
            if raw["v_out"] > self.c["output_voltage_limit_v"]:
                self.i_ref = 0.
            self.i_ref = clip(self.i_ref, 0., self.c["current_limit_a"])
            terms = self.iloop.update(self.i_ref-raw["i_l"], raw["i_l"], self.channel_stamps["i_l"],
                                     self.c["duty_min"], self.c["duty_max"])
            self.duty = terms["output"]
            self.p, self.i, self.d = terms["p"], terms["i"], terms["d"]
            self.duty_updated = True
            self.emit(t, "current_pid", **terms, i_ref=self.i_ref, duty=self.duty, loop_mode=self.c["current_mode"],duty_base=terms["bias"],duty_gain=self.duty_gain)
        self.mode = "CUSTOM_"+("VOLTAGE_CURRENT" if cascade else "VOLTAGE_DUTY")+("_LIMIT_"+limit if limit else "")


class CustomModel(OpenSEC):
    """Keep the corrected OpenSEC inner model; replace only its MPPT module."""
    def __init__(self, *args):
        super().__init__(*args)
        self.tracker = LocalMPPT(self.c["mppt_method"])
        custom_metadata(self, model=True)

    def mppt(self, t, m):
        return CustomController.mppt(self, t, m)


def make_controller(config, initial_duty, initial_voltage):
    c = {**CONTROL_DEFAULTS, **config}
    classes = dict(baseline=Baseline, ti=Cascade, plexim=Cascade,
                   libresolar=LibreSolar, fugu=Fugu, opensec=OpenSEC,
                   custom=CustomModel if c["custom_law"] == "model" else CustomController,
                   c07_r03=c07_r03.make_class(Controller), c07_r04=c07_r04.make_class(Controller))
    if c["algorithm"] not in classes:
        raise ValueError("Unknown control algorithm: "+str(c["algorithm"]))
    if c["experiment"] not in ("voltage", "irradiance"):
        raise ValueError("Unknown experiment")
    if c["mppt_method"] not in ("inccond", "po"):
        raise ValueError("Unknown MPPT method")
    validate_custom_configuration(c)
    c07_r03.validate(c)
    c07_r04.validate(c)
    for key, (lo, hi) in LIMITS.items():
        value = float(c[key])
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"{key} must be in [{lo}, {hi}]")
        c[key] = value
    if c["duty_min"] >= c["duty_max"]:
        raise ValueError("duty_min must be below duty_max")
    for key in ("libre_arr", "libre_step_counts"):
        if c[key] != int(c[key]):
            raise ValueError(key+" must be an integer count")
    if not math.isfinite(float(c.get("control_us", 100.))) or float(c.get("control_us", 100.)) <= 0:
        raise ValueError("control_us must be positive")
    return classes[c["algorithm"]](c, initial_duty, initial_voltage)
