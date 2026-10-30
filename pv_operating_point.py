"""MPP suggestion for a user-selected initial PV terminal voltage.

This uses the same fixed-temperature panel curve as the simulator. It does not
predict a unique loaded PV voltage from irradiance, tune a controller, or run
the switched circuit. Optional DC initialization information is separate from
the panel MPP and never changes/clamps that MPP.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from engine_legacy_v2 import Panel
from engine_v3 import DEFAULTS, LIMITS
from experiments import true_mpp
import plant

PANEL_KEYS = ("pv_voc", "pv_isc", "pv_vmp", "pv_imp", "irradiance")
STARTUP_KEYS = tuple(sorted(set(plant.PLANT_DEFAULTS) | {
    "v_battery", "r_l_ohm", "r_switch_ohm", "r_battery_ohm",
    "cin_uf", "l_uh", "cout_uf", "sense_tau_us",
}))


def _numeric(raw, key):
    if key not in raw:
        raise ValueError(f"{key}: 計算に必要な値がありません。")
    try:
        if isinstance(raw[key], bool):
            raise ValueError
        value = float(raw[key])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{key}: 有効な数値を入力してください。") from exc
    lo, hi = LIMITS[key]
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{key}: {lo} ～ {hi} の範囲で設定してください。")
    return value


def _initialization(raw, panel_inputs, panel, voltage):
    result = dict(checked=False, feasible=None, duty=None, reason=None)
    # Pure panel requests must not invent a battery or a circuit selection.
    if "plant_mode" not in raw or "v_battery" not in raw:
        return result
    result["checked"] = True
    result["basis"] = "normal_on_dc_initialization_with_2_to_98_percent_duty"
    try:
        mode = raw["plant_mode"]
        if mode not in ("simple", "c07"):
            raise ValueError("plant_mode: simple, c07 から選んでください。")
        c = dict(DEFAULTS)
        for key in STARTUP_KEYS:
            if key in raw and key != "plant_mode":
                c[key] = _numeric(raw, key)
        c.update(panel_inputs, plant_mode=mode, v_start=voltage,
                 experiment="voltage", irradiance_after=panel_inputs["irradiance"],
                 ramp_ms=0., step_ms=0.)
        _, duty = plant.initial_state(c, panel)
        duty = float(duty)
        if not math.isfinite(duty):
            raise ValueError("初期動作点のDutyを計算できません。")
        result["duty"] = duty
        # The legacy and c07 initializers use this normal-ON range. The simple
        # extended initializer omits the bound, so make this check explicit.
        if not .02 < duty < .98:
            raise ValueError("このMPPで必要な初期Dutyが2～98%の範囲外です。")
        result["feasible"] = True
    except (ValueError, TypeError, KeyError, OverflowError, ZeroDivisionError) as exc:
        result.update(feasible=False, reason=str(exc))
    return result


def calculate_start_mpp(rawconfig):
    """Return the exact fitted-panel MPP at pre-change irradiance.

    Five panel values are required. Other controller/experiment settings are
    ignored. If a circuit and battery are supplied, its normal-ON DC check is
    reported separately; a failed check still returns the unmodified panel MPP.
    """
    if not isinstance(rawconfig, Mapping):
        raise ValueError("設定はJSONオブジェクトで指定してください。")
    inputs = {key: _numeric(rawconfig, key) for key in PANEL_KEYS}
    if not inputs["pv_imp"] < inputs["pv_isc"] or not inputs["pv_vmp"] < inputs["pv_voc"]:
        raise ValueError("PV参照点は Imp < Isc、Vmp < Voc にしてください。")
    panel = Panel.from_config(inputs)
    voltage, current, power = true_mpp(panel, inputs["irradiance"], inputs["irradiance"])
    if not all(math.isfinite(x) and x > 0 for x in (voltage, current, power, panel.voc)):
        raise ValueError("設定したパネルのMPPを計算できません。")
    lo, hi = LIMITS["v_start"]
    return dict(v_mpp=voltage, i_mpp=current, p_mpp=power, v_oc=panel.voc,
                irradiance=inputs["irradiance"], voltage_node="PV_RAW",
                v_start=voltage, inputs=inputs,
                within_start_voltage_range=lo <= voltage <= hi,
                initialization=_initialization(rawconfig, inputs, panel, voltage))
