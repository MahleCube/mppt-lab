# 制御方式

制御には「電力を増やす方向を探すMPPT」と「目標へ近づける追従制御」があります。P&OとIncCondは前者、P・PI・PIDは後者です。これらは別の選択です。

## MPPTの方向判断

- **P&O**：少し操作した後の電力を前回と比較し、増えたら同じ方向、減ったら逆方向へ進みます。
- **IncCond**：$dP/dV=I+V\,dI/dV$ の符号を、測定した $\Delta I/\Delta V$ から判断します。正なら電圧を上げ、負なら下げます。電圧差が小さい場合には別の分岐を使います。

IncCondの傾き計算はPIDのD項とは異なります。どちらのMPPTも、直接Dutyを変える構造と、電圧目標を介する構造に組み合わせられます。

## 方式ごとの流れ

| 方式 | 測定からDutyまでの流れ |
|---|---|
| 電圧P/PI/PID | PV電圧誤差 → P/PI/PID → Duty。MPP実験ではLabのP&Oで電圧目標を更新 |
| TI型 | IncCond → 電圧目標 → 電圧PI → L1電流目標 → 電流PI → Duty |
| Plexim型 | 可変刻みのIncCondまたはP&O → 電圧目標 → 電圧PI → L1電流目標 → 電流PI → Duty |
| Libre Solar型 | 出力側電力の比較・CC/CV制限 → Dutyの比較カウントを増減 → 次の判断まで保持 |
| FUGU型 | 出力側電力の比較 → Dutyの変化速度 → 5つのPD制限器 → 経過時間で積分 → Duty |
| Open-SEC型 | 可変刻みP&O → 電圧目標 → コンデンサの電流収支 → L1電流目標 → コイルの式 → Duty |
| カスタム | P&O/IncCond、直接Duty/電圧追従/電圧と電流の追従、P/PI/PIDまたは回路式を組み合わせ |
| c07 r03 / r04 | IncCond → PV電圧PIまたはPID → L1電流目標 → 電流PI → Duty。C制御本体を実行 |

通常のBuckではDutyを増やすとPVから引く電流が増え、PV電圧が下がります。このため電圧ループには「測定PV電圧 − 目標電圧」の誤差を使います。電流ループは「目標L1電流 − 測定L1電流」です。TI型とPlexim型はPIで、D項を使いません。

Open-SEC型はPIの代わりに回路式を使います。入力容量について $C_{in}\dot V_{in}=I_{in}-D I_L$、コイルについてON/OFFの電圧収支を作り、目標へ向かう補正量からDutyを求めます。実装では抵抗損失、測定の時刻合わせ、c07の入力経路も扱います。

## 周期と測定

以下はLabの開始設定です。時間設定を変更すると、実際の処理間隔も変わります。

| 方式 | 測定・制御の呼出し間隔 | MPPT判断の設定間隔 | 追従側 |
|---|---:|---:|---|
| TI型 | 20 µs | 10.1 ms | 電圧PI・電流PIとも20 µs |
| Plexim型 | 50 µs | 10 ms | 電圧PI 500 µs、電流PI 50 µs |
| Libre Solar型 | 1 ms | 100 ms | 判断時にDutyを一歩変更 |
| FUGU型 | 2.2 ms | fast 約33.3 ms、slow 500 ms | 呼出しごとにDuty変化速度を積分 |
| Open-SEC型 | 約53.2 µs | 20 ms | 呼出しごとに回路式を計算 |

各判断は制御器が呼ばれた時刻で経過時間を確認します。設定間隔と呼出し間隔が割り切れない場合、判断時刻は呼出し時刻へ繰り上がります。ADC取得から実際のPWM反映までには別の遅れがあります。

TI型・Plexim型・Libre Solar型・Open-SEC型は設定した平滑化を使います。FUGU型は100 Hzノッチ、5点中央値、2段の指数移動平均を使い、出力電圧とL1電流から出力電力を求めます。入力電流は効率0.97を仮定して推定します。c07でのPV入力電流はL2の測定値であり、L1電流やパネル端子電流とは区別します。

## 参照した公開資料

5つの参照方式は、公開アルゴリズムを共通のBuck回路で比較するためのPython実装です。TI・Pleximの参照回路はBoostで、符号・ゲイン・制限はLab用に変更しています。Libre Solar・FUGUの電圧目標追従はLabで追加した比較用処理です。元のファームウェア全体の動作を再現するものではありません。

- [TI TIDM-SOLAR-DCDC](https://www.ti.com/tool/TIDM-SOLAR-DCDC)：C2000Ware DigitalPower SDKのMPPT・PI構成。
- [Plexim Single-Phase PV Inverter with Partial Shading](https://www.plexim.com/sites/default/files/demo_models_categorized/plecs/single_phase_pv_inverter_with_partial_shading.zip)：MPPTと二重PI。
- [Libre Solar charge-controller-firmware](https://github.com/LibreSolar/charge-controller-firmware/tree/b65f274541b1589d84c9ef30a567589d5f521539)：直接DutyのP&Oと制限。
- [FUGU MPPT firmware](https://github.com/fl4p/fugu-mppt-firmware/tree/51c1b9511de7ba2c0440f3f09f4233437c03934e)：探索速度・PD制限・Duty積分。
- [OpenSmartEnergyConverter](https://github.com/TjitteS/OpenSmartEnergyConverter/tree/11bb2abe40cfa05160a197a04c03e1566eb88c51)：P&OとBuckの回路式制御。
- [ESP-DSP](https://github.com/espressif/esp-dsp/blob/master/modules/iir/biquad/dsps_biquad_gen_f32.c)：ノッチの係数式。Copyright 2018–2019 Espressif Systems (Shanghai) PTE LTD、[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)。

c07の設定は [r03](C07_R03.md)・[r04](C07_R04.md)、調整方法は[自動調整](AUTOTUNE.md)を参照してください。
