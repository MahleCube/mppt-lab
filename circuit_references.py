"""Source circuit facts and explicitly assumed Buck experiments; no controller gains."""
from copy import deepcopy


def row(label, original, use):
    return dict(label=label, original=original, use=use)


COMMON_ASSUMED = dict(
    plant_mode='simple', nonlinear_l=0., nonlinear_c=0.,
    r_switch_ohm=.01, r_battery_ohm=.08, diode_vf=0.,
    sense_tau_us=1., current_sense_tau_us=0., acquire_us=.5,
    transport_us=1., adc_channel_us=2., adc_bits=12., adc_phase=.5,
    compute_us=2., apply_us=0., irradiance=700., irradiance_after=400., ramp_ms=20.)
COMMON_NOTES = [
    '実行するのは簡略Buckです。同期整流は正方向の導通をVf=0 Vで近似し、下側MOSの抵抗、deadtime、逆流・起動・保護ICは再現しません。',
    '測定はLab仮定：PV電圧RC 1 µs、出力電圧・電流は直接測定（電流RC未再現）、12 bit、取得0.5 µs、到着1 µs、チャネル差2 µs、演算2 µs、反映待ち0 µs、初回位相0.5。元のADC、DMA、平均回数、実行時間の再現ではありません。',
    'PV・電池・日射の採用元は各セットの説明を参照してください。明記のない値はLab仮定：日射700→400 W/m²、ランプ20 ms、電池側抵抗0.08 Ω、上側スイッチ抵抗0.01 Ω。STC電力と基板最大定格を混同しません。',
    'PWM周波数は回路セットで変わります。制御方式、ゲイン、MPPT/電圧/電流ループ周期、実験の種類と長さは保持します。組合せによっては振動や未整定になります。',
    'c07専用のL2・ESR・保護部品・非線形曲線はこの簡略Buckでは使いません。原基板の寄生値や安全機能が再現されたという意味ではありません。',
]

REFERENCES = [
    dict(id='ti', label='TI · TIDM-SOLAR-DCDC', preset_id=None,
         topology='2相Boost → LLC',
         description='入力200–300 VをBoostで400 Vへ昇圧し、LLC段へ渡す500 W設計です。現在のBuck＋電池モデルでは、この元回路の動作を計算できません。値を確認する参照資料として表示します。',
         revision='TIDU404（2014）の回路図と配布BOM Rev5（2021）を区別。監査したC2000 SDKコードと全部品の版一致は未確定。',
         values=[row('入出力','入力200–300 V / 中間400 V / 500 W','Boostモデル未実装のため読込なし'),
                 row('Boostコイル','旧回路図：150 µH ×2 / Rev5 BOM：500 µH ×2','資料の版で異なる。単一のLに合成しない'),
                 row('入力容量','旧回路図：3.9 µF ×2 = 7.8 µF','旧版の参考値。新BOMと混在させない'),
                 row('Boost出力容量','旧回路図：100 µF ×3 + 47 nF','電池側Coutではなく400 V中間バス'),
                 row('PWM','Boost 100 kHz','元回路の値。現在の設定は変更しない')],
         assumptions=['2相の位相差、Boostの電流経路、LLC、400 Vバスは現Labにありません。これらをBuckへ置換したものを元回路セットとして登録しません。',
                      'TI型の制御アルゴリズムは別の選択肢として、現在のBuckへ適応したまま使用できます。'],
         sources=[dict(label='TI設計資料 TIDU404',url='https://www.ti.com/lit/ug/tidu404/tidu404.pdf'),
                  dict(label='TI公式設計ページ・BOM',url='https://www.ti.com/tool/TIDM-SOLAR-DCDC')],
         documented_values={},assumed_values={}),
    dict(id='plexim', label='Plexim · 部分影PVインバータモデル', preset_id=None,
         topology='Boost → DCバス → 系統インバータ',
         description='公開PLECSモデルのMPPT段は昇圧回路です。400 VのDCバスと交流インバータを含むため、現在のBuck＋電池モデルへの読込は用意していません。',
         revision='Single-Phase PV Inverter with Partial Shading：取得済み公式PLECSモデルを参照。',
         values=[row('入力容量','C1 = 22 µF','PV側の容量。参照のみ'),
                 row('Boostコイル','L2 = 1 mH','BuckのL1とは電流経路が異なる'),
                 row('コイル直列抵抗','1 mΩ','元のBoostコイルの抵抗。参照のみ'),
                 row('DCバス容量 / 初期値','1000 µF / 400 V','電池の開放電圧ではない'),
                 row('Boost PWM','20 kHz','元モデルの周波数。現在の設定は変更しない'),
                 row('PV構成','3直列サブシステム、各54セル直列×3並列','単一の均一照度パネルに置換しない'),
                 row('制御周期','電流50 µs / 電圧500 µs / MPPT10 ms','制御方式セット側の情報。回路セットへは入れない')],
         assumptions=['PLECSで公開されたモデル値であり、特定実機の部品仕様や実測値ではありません。',
                      'Plexim型の2段PIは現在のBuckで使用できますが、元のBoostモデルを実行しているわけではありません。'],
         sources=[dict(label='Plexim公式モデルZIP',url='https://www.plexim.com/sites/default/files/demo_models_categorized/plecs/single_phase_pv_inverter_with_partial_shading.zip')],
         documented_values={},assumed_values={}),
    dict(id='libresolar',label='Libre Solar · MPPT 2420 HC rev0.2',preset_id='source-libresolar-2420',
         topology='同期Buck',
         description='監査対象のrev0.2基板からL・容量群・PWMを読み込み、25.6 V電池への実験例を組みます。分散した出力容量を一つへまとめた近似です。パネル、電池、抵抗、測定条件にはLab仮定を含みます。',
         revision='基板 035b794cfb363d9bb76acadeac415e7b1f6dbad5 / FW b65f274541b1589d84c9ef30a567589d5f521539。rev0.2.3の部品値は混ぜません。',
         values=[row('コイル L1','33 µH','L = 33 µH'),
                 row('入力容量','390 µF ×2 + 1 µF + 0.1 µF','Cin = 781.1 µF（公称値合算）'),
                 row('出力容量','820 µF + 0.22 µF ×2','Cout = 820.44 µF（シャント前後をまとめる近似）'),
                 row('PWM','70 kHz','PWM = 70 kHz'),
                 row('基板の範囲','PV最大80 V / 電池10–32 V / 最大20 A','基板の仕様。20 AをLabのL1制限に使用'),
                 row('パネル / 電池','接続する機器による','Lab仮定：約400 W、Vmp38 V / 電池25.6 V')],
         documented_values=dict(l_uh=33.,cin_uf=781.1,cout_uf=820.44,pwm_khz=70.,current_limit_a=20.),
         assumed_values=dict(pv_voc=46.,pv_isc=11.5,pv_vmp=38.,pv_imp=10.53,v_battery=25.6,
             v_start=39.,v_target=37.,r_l_ohm=.01,adc_voltage_range_v=80.,adc_current_range_a=40.,
             input_current_limit_a=13.,input_voltage_limit_v=27.,output_voltage_limit_v=29.2,power_limit_w=450.),
         assumptions=COMMON_NOTES+['PV Voc46 V / Isc11.5 A / Vmp38 V / Imp10.53 A、開始39 V→目標37 V。LのDCR 0.01 Ω、ADC全幅80 V/40 A、入力制限13 A・27 V、出力上限29.2 V、電力上限450 WはLab仮定です。',
             '元基板のPV上限80 Vに対しFWの定義には90 Vがあります。80 Vを基板仕様として表示し、90 Vの安全性を仮定しません。300 nsのdeadtimeや元基板のADC処理は再現しません。'],
         sources=[dict(label='rev0.2基板の回路図',url='https://github.com/LibreSolar/mppt-2420-hc/blob/035b794cfb363d9bb76acadeac415e7b1f6dbad5/kicad/dcdc.sch'),
                  dict(label='監査したFW',url='https://github.com/LibreSolar/charge-controller-firmware/tree/b65f274541b1589d84c9ef30a567589d5f521539')]),
    dict(id='fugu',label='FUGU · Fugu2 v2.3 / Lモデル40 µH',preset_id='source-fugu2',
         topology='同期Buck',
         description='Fugu2 v2.3回路図の容量群と、監査したfmetal設定の40 µH・39 kHzを使用します。40 µHはFWのリップル計算用設定で、実コイルの全電流域の値ではありません。',
         revision='基板 7f7cd61571094715581dece3516226e67785aaaf / FW 51c1b9511de7ba2c0440f3f09f4233437c03934e。基板v2.3と監査FWの出荷組合せは未確認。',
         values=[row('コイル L1','回路図は値なし。fmetalのL0 = 40 µH','L = 40 µH固定。FWモデル値を採用'),
                 row('入力容量','1000 µF ×3 + 10 µF ×2 + 1 µF ×3 + 0.22 µF ×2','Cin = 3023.44 µF（手実装する電解を含む公称値）'),
                 row('出力容量','1000 µF','Cout = 1000 µF（手実装する電解）'),
                 row('PWM','39 kHz設定','PWM = 39 kHz'),
                 row('基板 / FWの範囲','基板PV80 V。FW HV85 V / LV60 V / 32 A / 1000 W','相違を表示。実験はVoc72 V・600 W・25.6 V電池'),
                 row('実コイルの情報','出荷仕様の例：32 Aで25.6 µH','40 µH一定モデルにはバイアス依存を含めない')],
         documented_values=dict(l_uh=40.,cin_uf=3023.44,cout_uf=1000.,pwm_khz=39.),
         assumed_values=dict(pv_voc=72.,pv_isc=10.8,pv_vmp=60.,pv_imp=10.,v_battery=25.6,
             v_start=61.,v_target=59.,r_l_ohm=.01,adc_voltage_range_v=100.,adc_current_range_a=50.,
             current_limit_a=30.,input_current_limit_a=12.,input_voltage_limit_v=27.,output_voltage_limit_v=29.2,power_limit_w=750.),
         assumptions=COMMON_NOTES+['PV Voc72 V / Isc10.8 A / Vmp60 V / Imp10 A、開始61 V→目標59 V。LのDCR 0.01 Ω、ADC全幅100 V/50 A、L1制限30 A、入力制限12 A・27 V、出力上限29.2 V、電力上限750 WはLab仮定です。',
             '元の電圧RCは入力約72.3 µs・出力235 µsなどで異なり、INA226の電圧/電流変換も各1100 µsです。このセットの統一したLab測定条件には移していません。',
             '電解部品はMPN欄がDNPですが、回路図Descriptionに手実装品が指定されています。本セットはそれらを実装する前提です。MLCCのDCバイアスによる容量低下は含みません。'],
         sources=[dict(label='Fugu2 v2.3の回路図',url='https://github.com/fl4p/Fugu2/blob/7f7cd61571094715581dece3516226e67785aaaf/PowerStage.kicad_sch'),
                  dict(label='実コイルの注意点',url='https://github.com/fl4p/Fugu2/blob/7f7cd61571094715581dece3516226e67785aaaf/doc/INSTALLATION.md#L104-L116'),
                  dict(label='監査したfmetal FW',url='https://github.com/fl4p/fugu-mppt-firmware/tree/51c1b9511de7ba2c0440f3f09f4233437c03934e')]),
    dict(id='opensec',label='Open-SEC · SEC-B80-8B Buck',preset_id='source-opensec-buck',
         topology='公式対応の同期Buck接続',
         description='公式マニュアルにある端子交換とBuck用FWの構成です。PVを高圧側、電池を低圧側へ接続するため、入力224 µF・出力119 µFとなります。主要定数を使う簡略モデルです。',
         revision='OpenSmartEnergyConverter 11bb2abe40cfa05160a197a04c03e1566eb88c51 / Manual v1.13。Buck実機の追従性能を検証したものではありません。',
         values=[row('コイル','HW_L = 33 µH','L = 33 µH'),
                 row('高圧側容量','HW_CHIGH = 224 µF','Buckの入力Cin = 224 µF'),
                 row('低圧側容量','HW_CLOW = 119 µF','Buckの出力Cout = 119 µF'),
                 row('内部抵抗モデル','HW_RLINT = 0.005 Ω','L直列抵抗へ使用。実測DCRと同一かは未確認'),
                 row('PWM','188 kHz','PWM = 188 kHz'),
                 row('PVの参照点（原典SIM）','Voc63.812 V / Vmp55.814 V / Isc2 A / Imp≈1.940299 A','testing.cのBuck合成パネル参照点を採用。実製品ではない'),
                 row('電池・日射（原典SIM）','64/3 V / 抵抗0.1 Ω / 1000 W/m²','電池≈21.333 V・0.1 Ω、初期日射1000 W/m²')],
         documented_values=dict(l_uh=33.,cin_uf=224.,cout_uf=119.,r_l_ohm=.005,pwm_khz=188.,
             pv_voc=.742*86,pv_vmp=.649*86,pv_isc=2.,pv_imp=6.5/6.7*2.,v_battery=64/3,r_battery_ohm=.1,irradiance=1000.),
         assumed_values=dict(v_start=56.,v_target=54.,adc_voltage_range_v=80.,adc_current_range_a=20.,
             current_limit_a=8.,input_current_limit_a=3.,input_voltage_limit_v=23.,output_voltage_limit_v=26.,power_limit_w=130.,irradiance_after=600.),
         assumptions=COMMON_NOTES+['電池とPVの参照点は原典SIM_NOMINALのBuck計算から採用。Labでは別のPV近似曲線と全PWMの積分を使うため、原SIMや実パネルの完全再現ではありません。原SIM特有のPWM半周波数化は使わず、ハード用188 kHzを設定します。',
             '開始56 V→目標54 V、変更後日射600 W/m²、ADC全幅80 V/20 A、L1制限8 A、入力制限3 A・23 V、出力上限26 V、電力上限130 WはLabの実験設定です。',
             '原典のBoost動作の効率・仕様グラフを、このBuck例の実測性能と扱いません。元のADC倍率、保護設定、ゲインやモデル補正の再現ではありません。'],
         sources=[dict(label='固定版の回路定義・Buckビルド',url='https://github.com/TjitteS/OpenSmartEnergyConverter/tree/11bb2abe40cfa05160a197a04c03e1566eb88c51'),
                  dict(label='公式Manual v1.13（Buck対応）',url='https://www.tpee.nl/wp-content/uploads/2026/07/OpenSEC-firmware-Manual-ref-6.pdf'),
                  dict(label='原典SIMの入力条件',url='https://github.com/TjitteS/OpenSmartEnergyConverter/blob/11bb2abe40cfa05160a197a04c03e1566eb88c51/Open-SEC%20Firmware/src/testing.c#L80-L115')]),
]


def circuit_references():
    return deepcopy(REFERENCES)


def reference_parameter_sets(common):
    entries=[]
    for r in REFERENCES:
        if not r['preset_id']:
            continue
        entries.append(dict(id=r['preset_id'], reference_id=r['id'],
            label=r['label']+' · Buck参考', description=r['description'],
            config={**common,**COMMON_ASSUMED,**r['assumed_values'],**r['documented_values']}))
    return entries
