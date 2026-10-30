"""Circuit/measurement examples, deliberately independent of controller choice."""
from plant import PLANT_DEFAULTS
from circuit_references import reference_parameter_sets

PARAMETER_KEYS = set(PLANT_DEFAULTS) | set('cin_uf l_uh cout_uf r_l_ohm r_switch_ohm r_battery_ohm v_battery pv_voc pv_isc pv_vmp pv_imp pwm_khz sense_tau_us acquire_us transport_us adc_channel_us adc_bits adc_voltage_range_v adc_current_range_a adc_phase compute_us apply_us v_start v_target irradiance irradiance_after ramp_ms current_limit_a input_current_limit_a input_voltage_limit_v output_voltage_limit_v power_limit_w'.split())

def parameter_sets(c07):
    common = {**PLANT_DEFAULTS, 'plant_mode':'simple', 'nonlinear_l':0., 'nonlinear_c':0.,
        'sense_tau_us':30., 'current_sense_tau_us':5., 'acquire_us':2.,
        'transport_us':2., 'adc_channel_us':4., 'adc_bits':12.,
        'adc_phase':.5, 'compute_us':2., 'apply_us':0., 'pwm_khz':40.,
        'irradiance':700., 'irradiance_after':400., 'ramp_ms':20.}
    entries = [dict(id=c07['id'], label='c07 · 約800 Wパネル / 51.2 V電池',
        description='作成したc07の正常ON等価モデルと公称測定条件。保護IC内部や実機の性能保証は含みません。',
        config={k:v for k,v in c07['config'].items() if k in PARAMETER_KEYS})]
    examples = [
        ('small100','小電力 · 約100 W / 12.8 V電池',
         dict(pv_voc=22.,pv_isc=6.,pv_vmp=18.,pv_imp=5.56,v_battery=12.8,
              v_start=18.5,v_target=17.,cin_uf=470.,l_uh=220.,cout_uf=470.,
              r_l_ohm=.04,r_switch_ohm=.02,r_battery_ohm=.08,
              adc_voltage_range_v=30.,adc_current_range_a=15.,current_limit_a=10.,
              input_current_limit_a=7.,input_voltage_limit_v=14.,output_voltage_limit_v=14.6,power_limit_w=120.)),
        ('medium400','中電力 · 約400 W / 25.6 V電池',
         dict(pv_voc=46.,pv_isc=11.5,pv_vmp=38.,pv_imp=10.53,v_battery=25.6,
              v_start=39.,v_target=36.,cin_uf=1000.,l_uh=270.,cout_uf=1000.,
              r_l_ohm=.025,r_switch_ohm=.012,r_battery_ohm=.06,
              adc_voltage_range_v=60.,adc_current_range_a=25.,current_limit_a=20.,
              input_current_limit_a=13.,input_voltage_limit_v=27.,output_voltage_limit_v=29.2,power_limit_w=450.)),
        ('large1200','大電力 · 約1200 W / 51.2 V電池',
         dict(pv_voc=96.,pv_isc=16.,pv_vmp=80.,pv_imp=15.,v_battery=51.2,
              v_start=82.,v_target=76.,cin_uf=2200.,l_uh=330.,cout_uf=2200.,
              r_l_ohm=.015,r_switch_ohm=.008,r_battery_ohm=.04,
              adc_voltage_range_v=120.,adc_current_range_a=45.,current_limit_a=35.,
              input_current_limit_a=18.,input_voltage_limit_v=53.,output_voltage_limit_v=58.4,power_limit_w=1500.))]
    for ident,label,values in examples:
        entries.append(dict(id=ident,label=label,
            description='学習用の仮定値。電力はSTCでのVmp×Impの概算です。部品選定済みの製品設計ではありません。制御方式・ゲインは変更しません。',
            config={**common,**values}))
    return entries + reference_parameter_sets(common)
