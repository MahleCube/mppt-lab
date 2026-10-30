(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const color = {pv:'#087f8c',ref:'#d68b39',sense:'#8b73b0',duty:'#315b88',command:'#a2b8c9',current:'#397e6d',p:'#e08a38',i:'#087f8c',d:'#8b73b0',base:'#8c93b0',pwm:'#48728b',mpp:'#c06c46',power:'#087f8c',sun:'#b58b32',energy:'#735b96'};
  // Display names only. Source IDs, presets, calculations and provenance URLs stay intact.
  const publicLabels={baseline:'電圧PID → Duty',custom:'カスタム',c07_r04:'r04',ti:'電圧・電流PI',plexim:'可変幅MPPT＋電圧・電流PI',libresolar:'Dutyを一歩ずつ調整',fugu:'Dutyの変化速度を調整',opensec:'回路式からDutyを計算'};
  const referenceLabels={ti:'2相昇圧＋絶縁変換回路',plexim:'昇圧＋インバータ回路',libresolar:'70 kHzの降圧充電回路',fugu:'入力コンデンサが大きい降圧回路',opensec:'188 kHzの降圧充電回路'};
  const c07RepositoryUrl='https://github.com/MahleCube/MPPT';
  const experimentLabels={voltage:'目標電圧の変化に対する電圧追従のシミュレーション',irradiance:'日射変化に対するMPP追従のシミュレーション'};
  const publicText=value=>String(value??'')
    .replace(/c07 r04/g,'r04').replace(/\bTI\b(?:型)?|制御手法A/g,publicLabels.ti).replace(/\bPlexim(?:型)?|制御手法B/gi,publicLabels.plexim)
    .replace(/\bLibre(?:[ -]?Solar)?|制御手法C/gi,publicLabels.libresolar).replace(/\bFugu2/gi,'参考回路D').replace(/\bFUGU|制御手法D/gi,publicLabels.fugu)
    .replace(/OpenSmartEnergyConverter|Open[- ]?SEC|制御手法E/gi,publicLabels.opensec).replace(/PLECS/g,'公開シミュレーション').replace(/組み合わせ制御/g,publicLabels.custom).replace(/基準制御/g,publicLabels.baseline);
  const publicMetadata=a=>({...a,label:publicLabels[a.id]||publicText(a.label),description:publicText(metadataText(a.description)),adaptation:publicText(metadataText(a.adaptation))});

  const fallbackAlgorithms=[
    {id:'baseline',label:publicLabels.baseline,description:'PV電圧の誤差からDutyを直接補正する学習用制御。',adaptation:'日射実験では電圧目標を探索するP&Oを追加します。'},
    {id:'ti',label:publicLabels.ti,description:'IncCond → 電圧PI → 電流目標 → 電流PI → Duty。',adaptation:'参考元の回路は2相Boost＋LLC。本実験ではBuckに合わせて符号・利得・周期を設定しています。'},
    {id:'libresolar',label:publicLabels.libresolar,description:'P&OがDutyを直接変える構造。',adaptation:'参考元の方式に独立した電圧目標追従器はなく、電圧実験用の追従処理を追加します。'},
    {id:'fugu',label:publicLabels.fugu,description:'測定を処理し、P&Oの操作速度と制限からDutyを動かす構造。',adaptation:'電圧実験用の目標追従処理を追加します。参考元の回路・保護の再現ではありません。'},
    {id:'opensec',label:publicLabels.opensec,description:'P&O → 電圧目標 → 電流推定・予測を使う制御 → Duty。',adaptation:'公開Buck枝を参考にしたLab適応版。元ファームウェアの実行ではありません。'},
    {id:'plexim',label:publicLabels.plexim,description:'IncCondまたはP&O → 電圧PI → 電流PI → PWM。',adaptation:'公開シミュレーションの制御構造をBuckへ適応。参考元のライブラリ内部の再現ではありません。'}
  ];
  const specs = {
    control: [
      ['kp','比例ゲイン Kp','% / V',0,3,.01,100,'1 Vの誤差に対するDutyの操作量'],
      ['ti_ms','積分時間 Ti','ms',.2,100,.1,1,'小さいほど積分が強くなります','integral'],
      ['td_ms','微分時間 Td','ms',0,3,.01,1,'大きいほど電圧の変化を強く抑えます','derivative'],
      ['derivative_filter_ms','Dのフィルタ時定数','ms',.01,2,.01,1,'D項だけに作用する一次フィルタ','derivative']
    ],
    target: [
      ['v_start','開始時のPV電圧','V',53,72,.1,1,'PV端子の初期動作点。ボタンで変化前の日射量におけるMPP電圧を設定できます'],
      ['v_target','変更後のPV電圧目標','V',53,72,.1,1,'制御器へ渡すVref。c07では方式によりPV_FUSED測定値またはPV_RAW推定値を比較します'],
      ['step_ms','条件を変える時刻','ms',0,1500,1,1,'電圧実験では目標変更、日射実験では日射変化の開始'],
      ['duration_ms','実験の長さ','ms',10,3000,10,1,'全PWMのON/OFFを計算するため、長い実験ほど計算量が増えます'],
      ['mppt_tolerance_pct','MPP到達の許容不足率','%',.1,20,.1,1,'2%ならモデルMPP電力の98%以上。制御器に正解を渡す設定ではなく、結果の判定条件'],
      ['mppt_hold_ms','MPP到達の最低確認時間','ms',1,2000,1,1,'指定時間とMPPT周期2回分の長い方だけ、最後まで条件を満たすか確認']
    ],
    irradiance:[
      ['irradiance','変化前の日射量','W/m²',100,1200,10,1,'電圧実験ではこの日射量が一定'],
      ['irradiance_after','変化後の日射量','W/m²',100,1200,10,1,'日射実験の変更後の値'],
      ['ramp_ms','日射のランプ時間','ms',0,1000,1,1,'0なら瞬時のステップ。正の値なら指定時間をかけて変化']
    ],
    algorithm:[
      ['duty_response_gain','Duty反映倍率','倍',0,5,.1,1,'最終段のDuty補正にかける倍率。基準Dutyや回路式の先回り値は維持します'],
      ['mppt_step_duty','直接MPPTのDuty刻み','%',.001,2,.001,100,'電圧を上げる判断ではDutyを減らす、下げる判断ではDutyを増やす（Buck）'],
      ['voltage_kd','電圧追従 Kd','A·s/V',0,.01,.000001,1,'測定電圧の変化速度へかける係数。PIでは使用しません'],
      ['current_kd','L1電流追従 Kd','Duty·s/A',0,.001,.000001,1,'L1測定電流の変化速度へかける係数。PIでは使用しません'],
      ['loop_derivative_filter_ms','測定微分Dのフィルタ','ms',.001,5,.001,1,'測定値の時間差分を一次平滑。MPPTのΔI/ΔVとは別です'],
      ['voltage_kp','電圧PI Kp','A/V',0,2,.001,1,'PV電圧誤差から電流目標への比例係数'],
      ['voltage_ki','電圧PI Ki','A/(V·s)',0,500,.1,1,'電流目標を作る積分係数'],
      ['current_kp','電流PI Kp','Duty/A',0,1,.001,1,'電流誤差からDutyへの比例係数'],
      ['current_ki','電流PI Ki','Duty/(A·s)',0,1000,.1,1,'電流ループの積分係数'],
      ['mppt_step_v','MPPTの電圧刻み','V',.001,5,.01,1,'方式ごとの基準刻み。可変ステップでは実際の操作量と異なります'],
      ['algorithm_filter_ms','測定フィルタの公称等価時定数','ms',0,100,.1,1,'指定した測定周期での等価値。実行がADC待ちで遅れると実効時定数も伸びます。方式により段数・用途は異なります。'],
      ['c07_current_filter_ms','L1電流の平滑時定数','ms',0,100,.01,1,'c07の電流PIへ渡すL1電流。0ならデジタル平滑なし'],
      ['c07_cv_kp','充電電圧PI Kp','A/V',0,20,.01,1,'出力・電池電圧から許容L1電流を作る比例係数'],
      ['c07_cv_ki','充電電圧PI Ki','A/(V·s)',0,100,.1,1,'充電電圧の誤差を積分して許容L1電流を補正'],
      ['c07_current_rise_a_s','L1電流目標の上昇速度','A/s',0,200,.1,1,'正の値なら目標の増加を制限。r04の0はこの制限を無効にします（起動ランプとは別）'],
      ['c07_reference_weight','PV目標のP重み','',0,1,.01,1,'目標の変更をP項へ反映する強さ。0は測定の変化だけ、1は通常のP。IとDの強さは変えません'],
      ['c07_mppt_max_step_v','MPPTの最大電圧刻み','V',.001,5,.01,1,'正規化した傾斜が大きい場合でも、この幅まで'],
      ['c07_mppt_step_gain_v','MPPTの傾斜倍率','V',0,5,.01,1,'|ΔP/ΔV|を入力電流で正規化した値に掛ける係数'],
      ['c07_mppt_power_deadband_w','IncCond判断信号の許容帯','W',0,5,.01,1,'I×ΔV＋V×ΔIがこの範囲なら電圧目標を保持します'],
      ['c07_mppt_voltage_deadband_v','IncCondの最小電圧差','V',0,1,.001,1,'小さいΔVでは割り算せず、ΔIの符号で分岐'],
      ['c07_mppt_current_deadband_a','IncCondの最小電流差','A',0,1,.001,1,'ΔVが小さい場合に、ΔIを有意とみなす幅'],
      ['c07_mppt_settle_v','MPPT平均開始の電圧誤差幅','V',0,5,.01,1,'PV電圧の目標との差がこの範囲にあることを確認'],
      ['c07_mppt_settle_a','MPPT平均開始の電流誤差幅','A',0,5,.01,1,'L1電流の目標との差がこの範囲にあることを確認'],
      ['c07_pv_headroom_v','Buck入力と電池の最低電圧差','V',0,20,.1,1,'VINと電池電圧が近づいたとき電流を抑える基準'],
      ['c07_vout_trip_v','過電圧で電流要求を止める値','V',1,100,.1,1,'CV目標とは別。Labでは通常ON制御内の電流制限を再現'],
      ['libre_arr','PWMの周期カウント','count',10,65535,1,1,'参考元のカウント刻みをDutyへ換算する基準'],
      ['libre_step_counts','Dutyの刻み','count',1,100,1,1,'直接Duty操作の刻み'],
      ['voltage_deadband_v','追加電圧追従の許容帯','V',0,2,.01,1,'一歩ずつDutyを調整する方式の電圧追従処理'],
      ['fugu_voltage_kp','追加電圧追従の係数','速度/V',0,5,.01,1,'Dutyの変化速度を調整する方式の電圧追従処理'],
      ['fugu_fast_speed','高速時の操作速度','',0,5,.01,1,'参考元の高速側の操作量パラメータ'],
      ['fugu_slow_speed','低速時の操作速度','',0,1,.001,1,'参考元の低速側の操作量パラメータ'],
      ['fugu_slow_period_ms','低速判断周期','ms',1,2000,1,1,'高速側の判断周期とは別'],
      ['model_voltage_gain','モデル制御の電圧係数','',0,.1,.0001,1,'Buckへの適応式の係数。原本のPIゲインではありません'],
      ['model_current_gain','モデル制御の電流係数','',0,2,.01,1,'電流推定・予測を使うBuck適応式の係数'],
      ['model_filter_ms','モデル入力4値の平滑時定数','ms',0,5,.01,1,'取得時刻をそろえた4測定値のEMA。実際の取得間隔から係数を計算。アナログRC遅れの補償ではありません'],
      ['opensec_min_delta_v','P&O傾斜を判断する最小電圧差','V',.001,1,.001,1,'この値とADC 2カウント相当の大きい方以下なら、傾斜計算を止めて基準刻み1回だけ試します'],
      ['opensec_max_step_v','P&Oの1回の最大電圧刻み','V',.01,5,.01,1,'小さなΔVで刻みが急増しないためのLab側上限。基準刻みもこの値を超えません'],
      ['model_delay_us','モデルの遅延補償','µs',0,500,1,1,'予測に使う遅延。ADC取得・到着の設定とは別'],
      ['current_limit_a','コイル電流の上限','A',.1,50,.1,1,'制御側の制限値。実機の保護定格ではありません'],
      ['input_current_limit_a','入力電流の上限','A',.1,50,.1,1,'対応方式の入力電流制限'],
      ['input_voltage_limit_v','入力電圧の制限値','V',1,100,.1,1,'対応方式の入力電圧制限。目標電圧とは別'],
      ['output_voltage_limit_v','出力電圧の上限','V',1,100,.1,1,'対応方式の出力電圧制限'],
      ['power_limit_w','電力の上限','W',1,3000,10,1,'対応方式の制御側電力制限'],
      ['duty_min','Dutyの下限','%',0,99,.1,100,'共通の操作範囲'],
      ['duty_max','Dutyの上限','%',1,100,.1,100,'共通の操作範囲']
    ],
    timing: [
      ['control_us','測定を要求する周期','µs',20,2000,10,1,'4チャネル測定の指示を出す間隔。ADC待ちにより実際の更新は遅れる場合があります'],
      ['voltage_period_us','PV電圧ループの周期','µs',20,10000,10,1,'電圧誤差からDutyまたはL1電流目標を更新する間隔'],
      ['current_period_us','L1電流 / モデル制御の周期','µs',20,10000,10,1,'L1電流の補正からDutyを更新する間隔'],
      ['mppt_period_ms','MPPT判断の周期','ms',.1,1000,.1,1,'方向・目標・Dutyを探索する間隔。測定指示周期とは別'],
      ['c07_mppt_settle_ms','MPPT平均前の整定確認','ms',0,1000,.1,1,'電圧・L1電流の誤差が範囲内に連続している時間'],
      ['c07_mppt_window_ms','MPPT平均の最短時間','ms',.001,1000,.1,1,'整定確認後の生のPV電圧・入力電流を時間加重平均'],
      ['c07_background_us','MPPT裏側計算の所要時間','µs',0,10000,1,1,'Lab内の処理時間モデル。電流制御とは別に結果を用意します'],
      ['c07_irq_occupancy_us','高速制御がCPUを使う時間','µs',0,10000,1,1,'この時間を避けてMPPTの裏側計算を進めます'],
      ['c07_pwm_packet_cycles','1回に送るPWMパルス数','回',0,63,1,1,'50は実機に合わせた有限パケット模型、0は従来の連続PWM診断。PIO命令の完全再現ではありません'],
      ['pwm_khz','PWM周波数','kHz',5,100,1,1,'MOSFETをON／OFFする周波数'],
      ['adc_phase','測定指示の開始位相','周期',0,.95,.05,1,'PWM一周期に対する初回指示の位置'],
      ['sense_tau_us','電圧センサの時定数','µs',0,1000,10,1,'0 = センサの一次遅れなし'],
      ['acquire_us','指示 → 実際の取得','µs',0,1000,1,1,'c07初期値11 µs：SPI開始から値の保持まで'],
      ['transport_us','取得 → 結果の到着','µs',0,1000,1,1,'c07初期値13 µs：保持後の変換・SPIフレーム完了まで'],
      ['adc_channel_us','ADCチャネル間の取得差','µs',0,1000,1,1,'複数の測定値を同時刻の値とみなすか、順番に取得するかの設定'],
      ['adc_bits','ADC分解能','bit',0,16,1,1,'0は量子化なし。4〜16ならそのビット数で量子化'],
      ['adc_voltage_range_v','ADC電圧測定の全幅','V',10,300,.1,1,'ADC端子そのものではなく、換算後の電圧測定範囲'],
      ['adc_current_range_a','ADC電流測定の全幅','A',1,200,.1,1,'換算後の電流測定範囲。測定回路のスケールに対応'],
      ['compute_us','制御の演算時間','µs',0,1000,5,1,'測定値の到着から演算終了まで'],
      ['apply_us','演算終了 → 反映待ち','µs',0,1000,5,1,'その後のPWM周期境界で適用します']
    ],
    plant: [
      ['cin_uf','入力コンデンサ Cin','µF',200,4000,10,1,'簡略BuckではPV端子、c07拡張では入力L2の後の容量'],
      ['l_uh','Buckコイル L1','µH',50,800,5,1,'固定Lの値。c07の非線形ON時はLdiff曲線をこの値/214µHで拡大縮小'],
      ['cout_uf','出力コンデンサ Cout','µF',200,3000,10,1,'固定Coutの設定。c07の電圧依存曲線を有効にすると、その曲線を使用'],
      ['r_l_ohm','コイルの直列抵抗','Ω',.001,.2,.001,1,'巻線・配線の抵抗を表す設定'],
      ['r_switch_ohm','スイッチのON抵抗','Ω',.001,.1,.001,1,'スイッチング損失は含みません'],
      ['r_battery_ohm','電池側の直列抵抗','Ω',.01,.3,.005,1,'主充電経路の総抵抗。c07では出力保護・F3抵抗をこの値の内訳として分離'],
      ['v_battery','電池の開放電圧','V',40,57,.1,1,'SOC・温度による変化なし'],
      ['pv_voc','パネル Voc（STC）','V',65,90,.1,1,'開放電圧'],
      ['pv_isc','パネル Isc（STC）','A',5,20,.01,1,'短絡電流'],
      ['pv_vmp','パネル Vmp参照値','V',55,75,.1,1,'I–V近似曲線の参照点'],
      ['pv_imp','パネル Imp参照値','A',4,19,.01,1,'I–V近似曲線の参照点']
    ]
  };
  for(const [name,label,negative] of [['vin','入力電圧下限',true],['vout','出力電圧上限',false],['iin','入力電流上限',false],['iout','L1電流上限',false],['power','出力電力上限',false]]){
    for(const term of ['kp','kd'])specs.algorithm.push(['fugu_'+name+'_'+term,'FUGU '+label+' '+(term==='kp'?'Kp':'Kd'),'速度',negative?-200000:0,negative?0:200000,1,1,
      term==='kp'?'1−測定値/制限値の誤差に掛ける比例係数。制限値そのものは変えません。':'正規化誤差の前回との差に掛ける係数。秒で割った微分ではなく、制御周期によって効果が変わります。']);
  }
  let defaults={}, config={}, presets=[], algorithms=fallbackAlgorithms, experiments=[], apiLimits={}, plantFieldMetadata={}, revision=0, pending=false, running=false, timer=null;
  let defaultPresetId='',selectedCircuitPresetId='';
  let current=null, baseline=null, charts=[], verification=null, verificationUrl=null, initialized=false;
  let lastDispatch=0, editStarted=0, timingIndex=0, timingSelected=false,cancelTimer=null,lastCancel=0;
  let gainAutotune=null,tuningGains=false,startVoltage=null;
  const clientId='pv-'+Math.random().toString(36).slice(2);
  const uiPerformance={render_ms:0,response_ms:0,update_ms:0,updates:0};
  const fields=new Map();
  const format=(n,d=2)=>n!==null&&n!==undefined&&n!==''&&Number.isFinite(Number(n))?Number(n).toLocaleString('ja-JP',{maximumFractionDigits:d}):'—';
  const finite=n=>typeof n==='number'&&Number.isFinite(n);
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const metadataText=value=>Array.isArray(value)?value.map(metadataText).filter(Boolean).join(' '):value&&typeof value==='object'?Object.values(value).map(metadataText).filter(Boolean).join(' '):value==null?'':String(value);
  const algorithmFor=c=>algorithms.find(a=>a.id===(c.algorithm||'baseline'))||fallbackAlgorithms[0];
  const algorithmLabel=c=>algorithmFor(c).label||c.algorithm;
  const isIrradiance=c=>c.experiment==='irradiance';
  const isC07Firmware=id=>id==='c07_r03'||id==='c07_r04';
  const firmwareVersion=id=>id==='c07_r04'?'r04':'r03';
  const firmwareVoltageMode=c=>c.algorithm==='c07_r04'?'PID':'PI';
  const voltageMetricNode=r=>r.metrics?.tracking_node||r.controller?.tracking_evaluation_voltage_node||'PV_RAW';
  const voltageNodeLabel=node=>({PV_RAW:'パネル端子 PV_RAW',PV_FUSED:'入力L2手前 PV_FUSED',VIN:'Buck入力 VIN'}[node]||node);
  const experimentLabel=c=>experimentLabels[isIrradiance(c)?'irradiance':'voltage'];
  const algorithmKeys=a=>Array.isArray(a.fields)?a.fields.map(f=>typeof f==='string'?f:f.key||f.id):a.fields&&typeof a.fields==='object'?Object.keys(a.fields):null;
  function inputLimits(key,min,max,scale=1){
    const value=apiLimits[key];
    if(Array.isArray(value)&&value.length>=2)return [value[0]*scale,value[1]*scale];
    if(value&&typeof value==='object')return [(value.min??value.minimum??min/scale)*scale,(value.max??value.maximum??max/scale)*scale];
    return [min,max];
  }
  function setupMetadata(data){
    const incoming=Array.isArray(data.algorithms)?data.algorithms:Object.entries(data.algorithms||{}).map(([id,a])=>({id,...a}));
    if(incoming.length)algorithms=incoming.filter(a=>a.id!=='c07_r03').sort((a,b)=>Number(a.id==='custom')-Number(b.id==='custom')).map(a=>publicMetadata({...fallbackAlgorithms.find(f=>f.id===a.id),...a}));
    experiments=(Array.isArray(data.experiments)?data.experiments:Array.isArray(data.experiment)?data.experiment:[]).map(e=>({...e,label:experimentLabels[e.id]||e.label,description:publicText(metadataText(e.description))}));
    apiLimits=data.limits||{};
    $('algorithm').replaceChildren(...algorithms.map(a=>{const o=document.createElement('option');o.value=a.id;o.textContent=a.label||a.id;return o;}));
    if(experiments.length)$('experiment').replaceChildren(...experiments.map(a=>{const o=document.createElement('option');o.value=a.id;o.textContent=a.label||a.id;return o;}));
    const known=new Set(Object.values(specs).flat().map(s=>s[0]));
    const extras=Array.isArray(data.plant_fields)?data.plant_fields:Object.entries(data.plant_fields||{}).map(([key,f])=>({key,...f}));
    for(const f of extras){
      const key=f.key||f.id;if(key)plantFieldMetadata[key]=f;if(!key||known.has(key)||typeof config[key]==='string')continue;
      const value=Number(config[key]);if(!finite(value))continue;
      const [min,max]=inputLimits(key,f.min??0,f.max??Math.max(1,value*5));
      specs.plant.push([key,f.label||key,f.unit||'',min,max,f.step??(Math.abs(value)<1?.001:.1),1,f.hint||f.description||'拡張主回路モデルの設定値']);known.add(key);
    }
    const method=document.createElement('details');method.id='mppt-method-field';method.className='method-details';
    method.innerHTML='<summary>MPPT判断</summary><label class="select-label" for="mppt-method">判断方式</label><select id="mppt-method"><option value="inccond">IncCond</option><option value="po">P&amp;O</option></select>';
    $('composer-options').before(method);
    $('mppt-method').addEventListener('change',()=>{config.mppt_method=$('mppt-method').value;changed();});
  }
  function renderAlgorithmSummary(){
    const a=algorithmFor(config),native=config.algorithm==='baseline'||!config.algorithm;
    const irr=isIrradiance(config),entry=experiments.find(e=>e.id===config.experiment),firmware=isC07Firmware(config.algorithm);
    $('experiment-note').textContent=metadataText(entry?.description)||(irr?'指定時刻から日射量を変更し、制御器が自分でMPPを探す応答を見ます。モデルMPPは評価用の参照値です。':'日射を一定にし、指定時刻にPV目標電圧を変更します。直接Duty型には電圧追従用の追加処理があります。');
    $('pid-mode').hidden=!native;$('control-fields').hidden=!native;$('formula-note').hidden=!native;
    $('mppt-method-field').hidden=config.algorithm!=='plexim';
    $('mppt-method').value=config.mppt_method||'inccond';
    const used=config.algorithm==='custom'?customFields():algorithmKeys(a);
    for(const [key,f] of fields){
      let visible=finite(Number(config[key]));
      if(f.group==='algorithm')visible=visible&&(key==='duty_response_gain'||(used?used.includes(key):!native));
      if(key.startsWith('c07_'))visible=visible&&firmware;
      if(firmware&&key==='current_period_us')visible=false;
      if(key==='c07_reference_weight')visible=visible&&config.algorithm==='c07_r04';
      if(config.algorithm==='c07_r04'&&['voltage_kd','loop_derivative_filter_ms'].includes(key))visible=visible&&config.voltage_mode==='PID';
      if(['voltage_period_us','current_period_us','mppt_period_ms'].includes(key))visible=visible&&(used?used.includes(key):key==='mppt_period_ms'?irr:['ti','plexim'].includes(config.algorithm));
      if(key==='v_target')visible=visible&&!irr;
      if(['irradiance_after','ramp_ms'].includes(key))visible=visible&&irr;
      if(['mppt_tolerance_pct','mppt_hold_ms'].includes(key))visible=visible&&irr;
      if(native&&['mppt_period_ms','mppt_step_v'].includes(key))visible=visible&&irr;
      if(plantFieldMetadata[key]?.modes)visible=visible&&plantFieldMetadata[key].modes.includes(config.plant_mode||'simple');
      f.box.hidden=!visible;
    }
    const profileLabels=firmware?{
      control_us:'測定・L1電流PIの周期',mppt_period_ms:'MPPT判断の最短間隔',
      algorithm_filter_ms:'PV電圧の平滑時定数',mppt_step_v:'MPPTの最小電圧刻み',
      output_voltage_limit_v:'充電電圧のCV目標',input_current_limit_a:'入力L2電流の上限',current_limit_a:'L1電流目標の上限'
    }:{};
    const profileHints=firmware?{
      control_us:'8チャネル測定とL1電流PIを呼び出します。別の電流周期は設定しません',
      mppt_period_ms:'最短間隔。連続整定と平均窓の条件も満たした後に裏側で判断します',
      algorithm_filter_ms:'PV・出力電圧の一次平滑。MPPTは生のPV電圧・入力L2電流を別に平均します',
      mppt_step_v:'正規化傾斜に応じた可変刻みの下限',
      output_voltage_limit_v:'CV PIが許容L1電流を作る目標。過電圧停止の閾値とは別',
      input_current_limit_a:'入力L2電流センサの測定値から許容L1電流を減らす閾値',
      acquire_us:'VINを先頭とする8チャネル測定の開始から最初の保持まで',
      transport_us:'8チャネル最後の保持から、測定一式が制御へ届くまで',
      duty_response_gain:'このc07制御には追加倍率がないため1に固定します',
      current_limit_a:'運転中の電流目標を制限します。瞬時ピークの故障判定値ではありません'
    }:{};
    for(const key of ['control_us','mppt_period_ms','algorithm_filter_ms','mppt_step_v','output_voltage_limit_v','input_current_limit_a','current_limit_a']){
      const f=fields.get(key),spec=Object.values(specs).flat().find(s=>s[0]===key);
      if(f&&spec)f.box.querySelector('.field-label').textContent=profileLabels[key]||spec[1];
    }
    for(const key of ['control_us','mppt_period_ms','algorithm_filter_ms','mppt_step_v','output_voltage_limit_v','input_current_limit_a','current_limit_a','acquire_us','transport_us','duty_response_gain']){
      const f=fields.get(key),spec=Object.values(specs).flat().find(s=>s[0]===key);
      if(f&&spec)f.box.querySelector('.field-hint').textContent=profileHints[key]||spec[7];
    }
    $('algorithm').value=config.algorithm||'baseline';$('experiment').value=config.experiment||'voltage';
    if($('plant-mode'))$('plant-mode').value=config.plant_mode||'simple';
    renderComposer();
    renderAlgorithmGuide(config);
  }
  function customFields(){
    const c=config,common=['mppt_period_ms','algorithm_filter_ms','duty_min','duty_max','current_limit_a','output_voltage_limit_v'];
    if(c.custom_topology==='direct_duty')return [...common,'mppt_step_duty','voltage_deadband_v'];
    if(c.custom_law==='model')return [...common,'mppt_step_v','current_period_us','model_voltage_gain','model_current_gain','model_filter_ms','model_delay_us'];
    const v=['voltage_kp',...(c.voltage_mode!=='P'?['voltage_ki']:[]),...(c.voltage_mode==='PID'?['voltage_kd']:[])];
    const i=c.custom_topology==='voltage_current'?['current_period_us','current_kp',...(c.current_mode!=='P'?['current_ki']:[]),...(c.current_mode==='PID'?['current_kd']:[])]:[];
    return [...common,'mppt_step_v','voltage_period_us',...v,...i,...(c.voltage_mode==='PID'||(i.length&&c.current_mode==='PID')?['loop_derivative_filter_ms']:[])];
  }
  function composerChain(c){
    const first=isIrradiance(c)?(c.mppt_method==='po'?'P&O':'IncCond')+' → 電圧の上下判断':'指定したPV電圧目標';
    if(c.custom_topology==='direct_duty')return [first,'Buckの向きへ変換','Dutyを一歩操作'];
    if(c.custom_law==='model')return [first,'Vref','Cの収支 → IL1目標','Lの式 → Duty'];
    return c.custom_topology==='voltage_current'?[first,'Vref','電圧'+c.voltage_mode+' → IL1目標','L1電流'+c.current_mode+' → Duty']:[first,'Vref','電圧'+c.voltage_mode+' → Duty'];
  }
  function renderComposer(){
    const c=config,custom=c.algorithm==='custom',direct=c.custom_topology==='direct_duty',cascade=c.custom_topology==='voltage_current',model=c.custom_law==='model';
    $('control-composer').hidden=!custom;
    $('composer-options').hidden=!custom;
    for(const [id,key] of [['custom-mppt','mppt_method'],['custom-topology','custom_topology'],['custom-law','custom_law'],['custom-voltage-mode','voltage_mode'],['custom-current-mode','current_mode']])if(c[key])$(id).value=c[key];
    $('custom-law-field').hidden=direct;
    $('custom-law').querySelector('[value="model"]').disabled=!cascade;
    $('custom-voltage-mode-field').hidden=direct||model;
    $('custom-current-mode-field').hidden=!cascade||model;
    $('custom-mppt').disabled=false;
    $('mppt-decision-explanation').textContent=(isIrradiance(c)?'':'電圧ステップ実験ではMPPTを停止します。日射実験で有効になります。 ')+(c.mppt_method==='po'?'P&O：前回の操作で電力が増えれば同じ方向、減れば逆方向へ動かします。':'IncCond：I + V×ΔI/ΔV の符号で判断。正なら電圧を上げ、負なら下げ、ゼロ付近なら保持します。');
    $('composer-note').textContent=direct?'内側のPIDはありません。電圧実験ではLab追加の電圧誤差による一歩操作です。':model?'電圧と電流の両方を扱う回路式の方式です。この枝ではPIDを選びません。':'P：その時の誤差、I：誤差の積み重ね、D：測定値の変化速度。構成を変えると、単位に合う開始ゲインを読み込みます。安定保証値ではありません。';
    for(const term of ['kp','ki','kd']){
      const f=fields.get('voltage_'+term);if(!f)continue;
      const directVoltage=custom&&!cascade;
      f.box.querySelector('.field-label').textContent='電圧追従 '+term.replace('k','K');
      f.box.querySelector('.field-value span').textContent=(directVoltage?'Duty':'A')+({kp:'/V',ki:'/(V·s)',kd:'·s/V'}[term]);
      f.box.querySelector('.field-hint').textContent=(term==='kd'?'測定PV電圧の変化速度':term==='ki'?'PV電圧誤差の積み重ね':'PV電圧のずれ')+(directVoltage?'をDuty補正へ変換する係数':'をL1電流目標へ変換する係数');
    }
  }
  function renderAlgorithmGuide(c){
    const a=algorithmFor(c),irr=isIrradiance(c),id=c.algorithm||'baseline';
    const guide=window.PVAlgorithmGuides?.[id];
    const chains={
      c07_r04:[...(irr?['PV電圧・入力L2電流を平均','裏側IncCond → Vref']:['指定PV電圧目標']),'PV電圧'+firmwareVoltageMode(c)+' → L1電流要求','CV・入力電流・運転目標の制限','L1電流PI → Duty'],
      c07_r03:irr?['PV電圧・入力L2電流を平均','裏側IncCond → Vref','PV電圧PI → L1電流要求','CV・電流・上昇速度制限','L1電流PI → Duty']:['指定PV電圧目標','PV電圧PI → L1電流要求','CV・電流・上昇速度制限','L1電流PI → Duty'],
      baseline:irr?['PVのV・I','追加P&O → Vref',c.mode||'PI','Duty']:['PV電圧と指定目標',c.mode||'PI','Duty'],
      ti:irr?['PVのV・Iを平滑','IncCond → Vref','電圧PI → Iref','測定ILと比較','電流PI → Duty']:['PV電圧と指定目標','電圧PI → Iref','測定ILと比較','電流PI → Duty'],
      libresolar:irr?['Vout・ILを平滑','制限を先に確認','通常時はP&Oで方向判断','カウント操作 → Duty']:['PV電圧と指定目標','制限を先に確認','通常時は追加の方向判断','カウント操作 → Duty'],
      fugu:irr?['測定を処理・電力平均','5つのPD制限を確認','通常時はP&Oとの最小選択','経過時間で積算 → Duty']:['PV電圧と指定目標','5つのPD制限を確認','通常時は追加の速度と最小選択','経過時間で積算 → Duty'],
      opensec:irr?['4測定を時刻補間・平滑','PV端子とVINを推定','P&O → Vref','容量の式 → Iref','コイルの式 → Duty']:['4測定を時刻補間・平滑','PV端子とVINを推定','容量の式 → Iref','コイルの式 → Duty'],
      plexim:irr?['PVのV・I',(c.mppt_method==='po'?'可変幅P&O':'可変幅IncCond')+' → Vref','電圧PI → Iref','測定ILと比較','電流PI → Duty']:['PV電圧と指定目標','電圧PI → Iref','測定ILと比較','電流PI → Duty']
    };
    const chain=id==='custom'?composerChain(c):isC07Firmware(id)?chains[id]:Array.isArray(a.control_chain)?a.control_chain:chains[c.algorithm||'baseline'];
    $('topology-chain').innerHTML=(chain||[]).map((s,i)=>`${i?'<i aria-hidden="true">→</i>':''}<span>${esc(metadataText(s))}</span>`).join('');
    $('topology-adaptation').textContent=metadataText(a.adaptation)||'この画面は共通Buckモデル上の比較実装です。元基板の起動・保護・全周辺回路は再現しません。';
    if(!guide)return;
    $('algorithm-guide-title').textContent=algorithmLabel(c);
    $('algorithm-guide-idea').textContent=guide.idea;
    $('algorithm-d-note').innerHTML=`<strong>${id==='ti'?'Dは使う？':id==='fugu'?'この方式のDはどこにある？':'P・I・Dとの関係'}</strong><p>${esc(guide.d)}</p>${id==='baseline'?`<p>現在は <b>${esc(c.mode||'PI')}</b>、Td = ${esc(format(c.td_ms,3))} ms です。</p>`:''}`;
    $('algorithm-steps').innerHTML=(irr?guide.irradiance:guide.voltage).map((step,i)=>`<li><span class="guide-step-number">${i+1}</span><div><strong>${esc(step[0])}</strong><p>${esc(step[1])}</p></div></li>`).join('');
    $('algorithm-experiment-note').textContent=`今の実験：${experimentLabel(c)}。${guide.experiment}`;
    $('algorithm-boundary').textContent=guide.boundary;
    const guideLink=$('algorithm-guide').querySelector('a[href="/ALGORITHMS.md"],a[href="/C07_R03.md"],a[href="/C07_R04.md"]');
    if(guideLink){guideLink.href=isC07Firmware(id)?'/'+id.toUpperCase()+'.md':'/ALGORITHMS.md';guideLink.textContent=isC07Firmware(id)?firmwareVersion(id)+'の保存設定・再現範囲':'式・参考コード・変更点';}
    $('algorithm-formulas').innerHTML=guide.formula.map(x=>`<p>${esc(x)}</p>`).join('');
    const periods=[['測定を要求する間隔',format(c.control_us,3)+' µs']];
    if(id==='custom'&&c.custom_topology!=='direct_duty'){
      if(c.custom_law!=='model')periods.push(['電圧補正',format(c.voltage_period_us,3)+' µs']);
      if(c.custom_topology==='voltage_current')periods.push(['L1電流補正 / Duty更新',format(c.current_period_us,3)+' µs']);
    }
    if(['ti','plexim'].includes(id))periods.push(['電圧PI → 電流目標',format(c.voltage_period_us,3)+' µs'],['電流PI → Duty',format(c.current_period_us,3)+' µs']);
    if(isC07Firmware(id)){
      periods.push(['L1電流PI → Duty',format(c.control_us,3)+' µs'],['PV電圧'+firmwareVoltageMode(c)+'・CV PI',format(c.voltage_period_us,3)+' µs以上経過した高速制御回（この設定では '+format(Math.ceil(c.voltage_period_us/c.control_us)*c.control_us,3)+' µs）']);
      if(irr)periods.push(['MPPT平均前の整定確認',format(c.c07_mppt_settle_ms,3)+' ms'],['MPPT平均の最短時間',format(c.c07_mppt_window_ms,3)+' ms'],['MPPT裏側計算',format(c.c07_background_us,3)+' µs（高速制御を優先）']);
    }
    if(id==='baseline')periods.push(['直接'+(c.mode||'PI')+'のDuty補正','届いた測定ごと']);
    if(id==='opensec')periods.push(['回路モデルからDutyを計算',format(c.current_period_us,3)+' µs'],['モデル入力のEMA時定数',format(c.model_filter_ms,3)+' ms'],['式に入れるΔt','整合した測定時刻の差']);
    if(id==='libresolar')periods.push([irr?'P&O判断とDutyの一歩':'追加電圧追従の一歩',format(c.mppt_period_ms,3)+' ms'],['Dutyの1回の刻み',format(100*c.libre_step_counts/c.libre_arr,4)+' ポイント（%表示）']);
    else if(irr)periods.push([id==='fugu'?'速いP&O判断のしきい値':isC07Firmware(id)?'MPPT判断の最短間隔':'MPPT判断の設定',format(c.mppt_period_ms,3)+' ms'+(id==='fugu'?'を超えてから':isC07Firmware(id)?'＋整定・平均条件':'' )]);
    if(id==='fugu'){
      if(irr)periods.push(['遅いP&O判断のしきい値',format(c.fugu_slow_period_ms,3)+' msを超えてから']);
      periods.push(['速度からDutyへ積算','届いた測定ごと・実経過時間を使用']);
    }
    if(isC07Firmware(id))periods.push(['PWMの出力方式',Number(c.c07_pwm_packet_cycles)>0?format(c.c07_pwm_packet_cycles,0)+'パルスの有限パケット':'連続PWM（診断用）']);
    periods.push(['PWMのON/OFF',format(c.pwm_khz,3)+' kHz（1周期 '+format(1000/c.pwm_khz,3)+' µs）']);
    $('algorithm-periods').innerHTML=periods.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('');
  }
  function renderTopology(){
    if(!current)return;const c=current.config,a=algorithmFor(c);
    renderAlgorithmGuide(config);
    const m=current.metrics||{};
    const scope=a.source_control_core_executed===true?firmwareVersion(c.algorithm)+'のC制御本体を実行しています。通常ON状態の比較で、起動・異常停止・実機の周辺機能全体の再現ではありません。':'公開プログラムを参考にした独自実装で、参考元の制御を再現したものではありません。';
    $('result-scope').textContent=`グラフの計算条件：${algorithmLabel(c)} / ${experimentLabel(c)} / ${c.plant_mode==='c07'?'c07主回路拡張':'簡略Buck'}。${m.completed===false?'計算途中までの結果です。 ':''}${scope}設定を変えて計算中の場合、上の説明は新しい選択、グラフは直前の結果です。`;
    $('pid-card').hidden=!((c.algorithm||'baseline')==='baseline'||(c.algorithm==='custom'&&c.custom_law==='pid'&&c.custom_topology!=='direct_duty'));
    const currentLoop=c.algorithm==='custom'&&c.custom_topology==='voltage_current';
    $('pid-card').querySelector('.chart-heading p').textContent=(currentLoop?'内側のL1電流PID':'PV電圧のPID')+'：Duty = 初期Duty ＋ P ＋ I ＋ D（上下限あり）';
    $('pid-card').querySelector('.chart-caption').textContent='1ポイント = Duty 1%。P・I・DはDuty反映倍率を適用済みの値です。Dは'+(currentLoop?'L1測定電流':'測定PV電圧')+'の変化速度を平滑化して計算します。PIではD=0、PではI=D=0です。回路式やP&Oの内部値をPID項として表示しません。';
  }
  function status(text,kind='ready'){$('status-text').textContent=text;$('status').className=kind;}
  function buildFields(){
    for(const [group,list] of Object.entries(specs)){
      const host=$(group+'-fields');
      for(const spec of list){
        const [key,label,unit,defaultMin,defaultMax,step,scale,hint,mode]=spec;
        const [min,max]=inputLimits(key,defaultMin,defaultMax,scale);
        const box=document.createElement('div');box.className='field';box.dataset.key=key;
        box.innerHTML=`<div class="field-row"><label class="field-label" for="${key}">${esc(label)}</label><div class="field-value"><input id="${key}-number" type="number" min="${min}" max="${max}" step="${step}" aria-label="${esc(label)} 数値入力"><span>${esc(unit)}</span></div></div><input id="${key}" type="range" min="${min}" max="${max}" step="${step}" aria-label="${esc(label)}"><p class="field-hint">${esc(hint)}</p>`;
        host.appendChild(box);
        const range=$(key),number=$(key+'-number');
        fields.set(key,{range,number,box,scale,min,max,mode,group});
        range.addEventListener('input',()=>{number.value=range.value;const value=Number(range.value)/scale;if(config[key]===value)return;config[key]=value;changed(false);});
        number.addEventListener('change',()=>{
          const value=Number(number.value);
          if(!Number.isFinite(value)||number.value.trim()===''){syncFields();return;}
          // Numerical entry is intentionally not rounded to a slider tick.
          range.value=String(value);if(config[key]===value/scale)return;config[key]=value/scale;changed(false);
        });
      }
    }
  }
  function syncFields(){
    for(const [key,f] of fields){
      const value=Number(config[key])*f.scale;
      f.number.value=finite(value)?Number(value.toPrecision(10)):'';if(finite(value))f.range.value=value;
      const inactive=(f.mode==='integral'&&config.mode==='P')||(f.mode==='derivative'&&config.mode!=='PID')||(isC07Firmware(config.algorithm)&&key==='duty_response_gain');
      f.box.classList.toggle('inactive',inactive);f.range.disabled=inactive;f.number.disabled=inactive;
    }
    document.querySelectorAll('[data-mode]').forEach(b=>{const active=b.dataset.mode===config.mode;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
    $('rtol').value=String(config.rtol);
    updateGainEquation();
    renderAlgorithmSummary();
    updateParameterSetState();
    window.PVLabHelp?.update(config,current);
  }
  function updateParameterSetState(){
    const matching=presets.find(p=>circuitPresetEntries(p).every(([key,value])=>sameReferenceValue(config[key],value)));
    if(matching)selectedCircuitPresetId=matching.id;
    $('preset').value=matching?.id||'';
    renderSelectionSummary(matching);
    gainAutotune?.update();
    window.PVChoices?.refresh();
  }
  function renderSelectionSummary(matching){
    const host=$('selection-summary-content'),controlHost=$('control-summary-content');if(!host||!controlHost)return;
    // Read the selected configuration, never the older simulation result.
    const c=config,id=c.algorithm||'baseline',native=id==='baseline',irr=isIrradiance(c);
    const circuit=matching||presets.find(p=>p.id===selectedCircuitPresetId);
    const changedCount=circuit?circuitPresetEntries(circuit).filter(([key,value])=>!sameReferenceValue(c[key],value)).length:0;
    const opened=new Set([...host.querySelectorAll('details[open]'),...controlHost.querySelectorAll('details[open]')].map(d=>d.dataset.selectionDetail));
    const parametersOpen=Boolean($('selection-parameters')?.open),controlParametersOpen=Boolean($('control-parameters')?.open);
    const c07AboutOpen=Boolean($('c07-about')?.open),isC07Circuit=Boolean(circuit&&circuit.id===defaultPresetId);
    const r04AboutOpen=$('r04-about-content')?.hidden===false;
    const number=value=>finite(Number(value))?String(Number(Number(value).toPrecision(7))):'—';
    const value=(key,unit='')=>number(c[key])+(unit?' '+unit:'');
    const rows=items=>'<dl class="selection-values">'+items.map(([label,text,key])=>`<div${key?` data-selection-key="${esc(key)}"`:''}><dt>${esc(label)}</dt><dd>${esc(text)}</dd></div>`).join('')+'</dl>';
    const detail=(key,title,items)=>items.length?`<details class="selection-details" data-selection-detail="${key}"${opened.has(key)?' open':''}><summary>${esc(title)}</summary>${rows(items)}</details>`:'';
    const configuredFields=(groups,exclude=[])=>[...fields].filter(([key,f])=>groups.includes(f.group)&&!exclude.includes(key)&&!f.box.hidden&&!(f.group==='control'&&(!native||f.range.disabled))).map(([key,f])=>[
      /^current_k[pdi]$/.test(key)?'L1電流追従 '+key.slice(-2).replace('k','K'):f.box.querySelector('.field-label').textContent,
      number(Number(c[key])*f.scale)+' '+f.box.querySelector('.field-value span').textContent,key
    ]);
    const mppt=['ti','c07_r03','c07_r04'].includes(id)?'IncCond':['plexim','custom'].includes(id)?(c.mppt_method==='po'?'P&O':'IncCond'):'P&O';
    const path=id==='custom'?composerChain(c).join(' → '):native?'PV電圧 → '+(c.mode||'PI')+' → Duty':
      ['ti','plexim','c07_r03','c07_r04'].includes(id)?'PV電圧目標 → 電圧'+firmwareVoltageMode(c)+' → L1電流目標 → 電流PI → Duty':
      id==='opensec'?'PV電圧目標 → C・Lの回路式 → Duty':id==='libresolar'?'制限の確認 → Dutyを一歩ずつ操作':'PD制限と操作速度 → Duty';
    const circuitKeys=['pv_vmp','pv_imp','v_battery','l_uh','cin_uf','cout_uf'];
    const circuitRows=[['パネル Vmp / Imp',value('pv_vmp','V')+' / '+value('pv_imp','A')],['電池の開放電圧',value('v_battery','V'),'v_battery'],
      ['L1 基準値',value('l_uh','µH'),'l_uh'],['Cin / Cout 基準値',value('cin_uf','µF')+' / '+value('cout_uf','µF')],
      ['L1 / Coutの扱い',(c.plant_mode==='c07'&&c.nonlinear_l>=.5?'L1は電流依存':'L1は固定')+'・'+(c.plant_mode==='c07'&&c.nonlinear_c>=.5?'Coutは電圧依存':'Coutは固定')]];
    const experimentRows=[['実験',experimentLabel(c)],...(irr?[
      ['日射量',value('irradiance','W/m²')+' → '+value('irradiance_after','W/m²')],['変化にかける時間',value('ramp_ms','ms'),'ramp_ms']
    ]:[['PV電圧',value('v_start','V')+' → '+value('v_target','V')],['日射量',value('irradiance','W/m²'),'irradiance']]),
      ['変更時刻 / 実験の長さ',value('step_ms','ms')+' / '+value('duration_ms','ms')]];
    const timingKeys=['pwm_khz','control_us','voltage_period_us','current_period_us','mppt_period_ms'];
    const timingRows=configuredFields(['timing']).filter(row=>timingKeys.includes(row[2])&&(row[2]!=='mppt_period_ms'||irr||id==='libresolar'||(id==='custom'&&c.custom_topology==='direct_duty')));
    const otherTiming=configuredFields(['timing'],timingRows.map(row=>row[2])).filter(row=>row[2]!=='mppt_period_ms');
    host.innerHTML=`${window.PVCircuitOverview.render(c)}
      ${isC07Circuit?`<details id="c07-about" class="selection-details"${c07AboutOpen?' open':''}><summary>c07回路とは</summary><div class="c07-about-content"><p>c07は、作者が自作設計している太陽光発電システムです。</p><p>現在はBOM（部品表）を掲載しています。</p><p><a href="${esc(c07RepositoryUrl)}" target="_blank" rel="noopener noreferrer">c07のリポジトリ</a></p></div></details>`:''}
      <details id="selection-parameters" class="selection-parameters"${parametersOpen?' open':''}><summary>パラメータを見る</summary>
      ${detail('main-circuit','主な回路値',[
        ['回路の設定',c.plant_mode==='c07'?'詳しく設定':'簡単設定'],
        ['回路セットの状態',matching?'セットの値を使用':circuit?`${changedCount}項目を個別に変更`:'個別設定'],...circuitRows])}
      ${detail('experiment','実験条件',experimentRows)}${detail('timing','測定・遅延の詳細',otherTiming)}
      ${detail('circuit','回路の詳細',configuredFields(['plant'],circuitKeys))}</details>`;
    const about=id==='c07_r04'?`<div class="r04-about"><button type="button" id="r04-about-button" aria-expanded="${r04AboutOpen}" aria-controls="r04-about-content">r04とは</button><div id="r04-about-content"${r04AboutOpen?'':' hidden'}><p>作者が設計中のc07を最適制御するために開発中の制御方式</p><p><a href="${esc(c07RepositoryUrl)}" target="_blank" rel="noopener noreferrer">太陽光発電のリポジトリ</a></p></div></div>`:'';
    controlHost.innerHTML=`${about}${window.PVControlFlow.render(c)}
      <details id="control-parameters" class="selection-parameters"${controlParametersOpen?' open':''}><summary>パラメータを見る</summary>
      ${detail('control-path','制御の構成',[[ '制御の経路',path],['MPPT判断',mppt+(irr?'（有効）':'（この実験では停止）')]])}
      ${detail('periods','制御・測定の周期',timingRows)}${detail('gains','ゲイン・制限',configuredFields(['control','algorithm']))}</details>`;
    $('r04-about-button')?.addEventListener('click',()=>{const content=$('r04-about-content');content.hidden=!content.hidden;$('r04-about-button').setAttribute('aria-expanded',String(!content.hidden));});
  }
  function updateGainEquation(){
    const ki=config.mode==='P'?0:config.kp/(config.ti_ms/1000);
    const kd=config.mode==='PID'?config.kp*(config.td_ms/1000):0;
    $('gain-equation').textContent=`Ki = ${format(ki*100,3)} %/(V·s)　Kd = ${format(kd*100,5)} %·s/V`;
  }
  function sameReferenceValue(actual,expected){
    if(finite(actual)&&finite(expected))return Math.abs(actual-expected)<=1e-9*Math.max(1,Math.abs(expected));
    return actual===expected;
  }
  function changed(fullSync=true){
    startVoltage?.invalidate();
    if(isC07Firmware(config.algorithm)){config.current_period_us=config.control_us;config.duty_response_gain=1;}
    if(config.algorithm==='c07_r04')config.voltage_mode='PID';
    revision++;pending=true;editStarted=performance.now();
    if(fullSync)syncFields();else{updateGainEquation();renderAlgorithmGuide(config);updateParameterSetState();window.PVLabHelp?.update(config,current);}
    $('stale').hidden=!current;$('error').hidden=true;
    status('更新待ち…','busy');
    if(running&&!cancelTimer){cancelTimer=setTimeout(()=>{
      cancelTimer=null;lastCancel=performance.now();
      if(running&&pending&&performance.now()-lastDispatch>=250)fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-PV-Client':clientId,'X-PV-Revision':String(revision)},body:'{}'}).catch(()=>{});
    },Math.max(0,250-(performance.now()-lastDispatch)));}
    // Throttle, rather than waiting for a drag to stop. At most one request
    // is in flight and intermediate configurations are never queued.
    if(!running&&!timer&&!tuningGains)timer=setTimeout(run,Math.max(0,80-(performance.now()-lastDispatch)));
  }
  async function run(){
    clearTimeout(timer);timer=null;
    if(tuningGains){pending=true;return;}
    if(running){pending=true;return;}
    if(!initialized)return;
    running=true;pending=false;const token=revision;const requested={...config};lastDispatch=performance.now();
    $('error').hidden=true;$('stale').hidden=!current;$('stale').textContent='前の設定の結果を表示中';status('計算中…','busy');
    $('calculate').textContent='計算中…';$('calculate').disabled=true;
    const start=performance.now();
    try{
      const response=await fetch('/api/simulate',{method:'POST',headers:{'Content-Type':'application/json','X-PV-Client':clientId,'X-PV-Revision':String(token)},body:JSON.stringify(requested)});
      const serverTiming=Object.fromEntries((response.headers.get('Server-Timing')||'').split(',').map(s=>s.trim().split(';dur=')).filter(p=>p.length===2).map(([k,v])=>[k,Number(v)]));
      const result=await response.json();
      if(response.status===409&&result.cancelled){pending=true;return;}
      if(!response.ok)throw new Error(result.error||`計算に失敗しました（${response.status}）`);
      // Show each finished experiment during a continuous drag. Because only
      // one request runs, this can never replace a newer completed experiment.
      // Explicitly mark an intermediate result until the latest settings finish.
      {
        if(!result.series?.t_ms?.length)throw new Error('計算結果に波形がありません。');
        result.config=result.config||requested;result.clientElapsed=performance.now()-start;current=result;
        const renderStart=performance.now();renderResult();uiPerformance.render_ms=performance.now()-renderStart;
        uiPerformance.response_ms=result.clientElapsed;uiPerformance.update_ms=performance.now()-(editStarted||start);uiPerformance.updates++;
        uiPerformance.server=serverTiming;
        $('metric-response').textContent=`通信・描画を含む応答 ${format(result.clientElapsed+uiPerformance.render_ms,0)} ms`;
        const detail=finite(serverTiming.compute)?`計算 ${format(serverTiming.compute,0)} ms · 結果の変換 ${format((serverTiming.encode||0)+(serverTiming.compress||0),0)} ms · 描画 ${format(uiPerformance.render_ms,0)} ms${serverTiming.queue>20?' · 待機 '+format(serverTiming.queue,0)+' ms':''}`:'';
        $('performance-detail').textContent=detail;
        $('stale').hidden=token===revision;
        if(token!==revision)status('更新中…','busy');
        else if(result.metrics?.completed===false)status('中断','error');
        else if(result.diagnostics?.cache_hit===true)status('完了（再利用）','ready');
        else status('完了','ready');
      }
    }catch(error){
      if(token===revision){$('error').textContent=error.message||String(error);$('error').hidden=false;$('stale').hidden=!current;$('stale').textContent='現在の設定は未計算 · 前回の結果を表示中';status('計算できませんでした','error');}
    }finally{
      running=false;$('calculate').textContent=tuningGains?'ゲイン調整中…':'再計算';$('calculate').disabled=tuningGains;
      if(pending||token!==revision){pending=true;if(!tuningGains)timer=setTimeout(run,Math.max(0,80-(performance.now()-lastDispatch)));}
    }
  }
  function setMetric(id,value,unit,digits=2,empty='—'){$(id).innerHTML=!finite(value)?esc(empty):`${format(value,digits)}<small>${esc(unit)}</small>`;}
  function latest(values){if(!Array.isArray(values))return null;for(let i=values.length-1;i>=0;i--)if(finite(values[i]))return values[i];return null;}
  function metricWindow(m){
    const start=m.evaluation_start_ms??m.metric_window_start_ms??m.integration_start_ms;
    const end=m.evaluation_end_ms??m.metric_window_end_ms??m.integration_end_ms;
    return finite(start)&&finite(end)?`評価区間 ${format(start,2)}–${format(end,2)} ms。`:'計算器が定義した評価区間。';
  }
  function renderComparison(){
    $('comparison-card').hidden=!baseline||!current;if(!baseline||!current)return;
    const c=current.config,b=baseline.config;
    const keys=[...new Set([...specs.plant.map(s=>s[0]),'plant_mode','experiment','irradiance','irradiance_after','ramp_ms','v_start','v_target','step_ms','duration_ms','mppt_tolerance_pct','mppt_hold_ms','pwm_khz','sense_tau_us','acquire_us','transport_us','adc_channel_us','adc_bits','adc_voltage_range_v','adc_current_range_a','compute_us','apply_us','adc_phase'])];
    const labels=Object.fromEntries(Object.values(specs).flat().map(s=>[s[0],s[1]]));
    const differences=keys.filter(k=>!(k==='v_target'&&isIrradiance(c)&&isIrradiance(b))&&!sameReferenceValue(c[k],b[k]));
    $('comparison-conditions').textContent=differences.length?'条件の違い：'+differences.map(k=>`${labels[k]||k}（基準 ${b[k]??'未指定'} → 今回 ${c[k]??'未指定'}）`).join('、'):'回路・測定条件は一致';
    const display=(r,key,unit)=>{
      const value=r.metrics?.[key],partial=r.metrics?.completed===false,settling=key.includes('settling');
      if((key==='settling_ms'&&isIrradiance(r.config))||(key==='mppt_settling_ms'&&!isIrradiance(r.config)))return '対象外';
      if(partial&&settling)return '未判定・途中';
      return finite(value)?format(value,unit==='J'?6:3)+' '+unit+(partial?'（途中）':''):settling?'未到達':'—';
    };
    const resultRange=r=>`${format(latest(r.series?.t_ms),3)} / ${format(r.config.duration_ms,3)} ms ${r.metrics?.completed===false?'（途中）':'（完了）'}`;
    const mppCriterion=r=>isIrradiance(r.config)?`${format(100-r.config.mppt_tolerance_pct,2)}%以上 / 最低${format(r.metrics?.mppt_hold_ms,3)} ms保持`:'対象外';
    const rows=[['実験',experimentLabel(b),experimentLabel(c)],['結果 / 指定時間',resultRange(baseline),resultRange(current)],['電圧の評価節点',isIrradiance(b)?'対象外':voltageNodeLabel(voltageMetricNode(baseline)),isIrradiance(c)?'対象外':voltageNodeLabel(voltageMetricNode(current))],['電圧整定',display(baseline,'settling_ms','ms'),display(current,'settling_ms','ms')],['MPP到達（変化終了から）',display(baseline,'mppt_settling_ms','ms'),display(current,'mppt_settling_ms','ms')],['MPP判定条件',mppCriterion(baseline),mppCriterion(current)],['追従効率',display(baseline,'tracking_efficiency_pct','%'),display(current,'tracking_efficiency_pct','%')],['積分エネルギー差',display(baseline,'energy_deficit_j','J'),display(current,'energy_deficit_j','J')]];
    $('comparison-table').innerHTML=`<table><thead><tr><th>指標</th><th>基準：${esc(algorithmLabel(b))}</th><th>今回：${esc(algorithmLabel(c))}</th></tr></thead><tbody>${rows.map(r=>'<tr>'+r.map((v,i)=>`<${i?'td':'th'}>${esc(v)}</${i?'td':'th'}>`).join('')+'</tr>').join('')}</tbody></table>`;
    $('baseline-note').firstElementChild.textContent=`比較基準：${algorithmLabel(b)} / ${experimentLabel(b)} / ${format(latest(baseline.series?.t_ms),3)} msまで${baseline.metrics?.completed===false?'（途中）':''}`;
  }
  function renderResult(){
    const m=current.metrics||{},d=current.diagnostics||{},s=current.series;
    const irr=isIrradiance(current.config),partial=m.completed===false,node=voltageMetricNode(current),nodeLabel=voltageNodeLabel(node);
    $('metric-settling-title').textContent=irr?'MPP到達時間':'整定時間 · '+node;
    setMetric('metric-settling',partial?null:irr?m.mppt_settling_ms:m.settling_ms,'ms',2,partial?'未判定（途中）':irr?'未到達':'未整定');
    $('metric-settling-note').textContent=irr?(metadataText(m.mppt_settling_definition||d.mppt_settling_definition)||'日射変化の終了からのMPP到達時間。未到達は不安定の断定ではありません。'):`目標変更から、${nodeLabel} が指定目標 ±${format(m.voltage_band_v??.2,3)} V に入り、その後も帯内に留まるまでの時間。センサの遅れた値ではなく、この節点の物理電圧で評価します。`;
    setMetric('metric-overshoot',irr?null:m.overshoot_v,'V',3,irr?'対象外':'—');
    $('metric-overshoot-note').textContent=irr?'電圧ステップ実験で評価する指標':`${nodeLabel} が目標を通り越した電圧`;
    const finalNode=irr?'PV_RAW':node,finalSeries=s[({PV_RAW:'v_pv',PV_FUSED:'v_fused',VIN:'v_in'})[finalNode]],finalVoltage=!irr&&finite(m.final_error_v)?current.config.v_target+m.final_error_v:latest(finalSeries);
    $('metric-final-title').textContent='最終電圧 · '+finalNode;
    setMetric('metric-final',finalVoltage,'V',3);
    $('metric-final-note').textContent=irr?`パネル端子 PV_RAW。${partial?'中断時':'終了時'}のモデルMPP電圧 ${format(latest(s.v_mpp),3)} V`:`${nodeLabel} の${partial?'中断時':'終了時'}の目標との差 ${format(m.final_error_v,3)} V。パネル端子PV_RAWは ${format(latest(s.v_pv),3)} Vです。`;
    setMetric('metric-efficiency',m.tracking_efficiency_pct,'%',3);
    setMetric('metric-energy',m.energy_deficit_j,'J',4);
    const pp=latest(s.p_pv),pm=latest(s.p_mpp);
    $('metric-power').innerHTML=finite(pp)&&finite(pm)?`${format(pp,1)} / ${format(pm,1)}<small>W</small>`:'—';
    $('metric-efficiency-note').textContent=metricWindow(m)+(metadataText(m.tracking_efficiency_definition||d.tracking_efficiency_definition)||'PV発電エネルギー / 同じ条件のモデルMPPエネルギー。')+(partial?' 途中までの値です。':'');
    $('metric-energy-note').textContent=metricWindow(m)+(metadataText(m.energy_deficit_definition||d.energy_deficit_definition)||'∫(モデルMPP電力 − PV電力) dt。')+(partial?' 途中までの値です。':'');
    $('energy-chart-note').textContent=Array.isArray(s.energy_deficit_j)?'計算器が返した累積積分を表示。途中で打ち切られた結果は、その時刻までです。':'この結果には積分の時系列がありません。上の指標に計算器の積分結果を表示します。';
    $('timing-at-step').textContent=irr?'日射変化の直後':'目標変更の直後';
    $('zoom-position').querySelector('[value="step"]').textContent=irr?'日射を変えた直後':'目標を変えた直後';
    const runtime=m.elapsed_ms??current.clientElapsed;
    setMetric('metric-runtime',runtime>=1000?runtime/1000:runtime,runtime>=1000?'s':'ms',runtime>=1000?2:0);
    $('metric-steps').textContent=`${format(d.accepted_steps,0)} ステップ / PWMラッチ ${format(d.pwm_cycles,0)} 回`;
    if(d.cache_hit===true){$('metric-runtime').textContent='再利用';$('metric-steps').textContent='同じ設定の計算結果を再利用';}
    $('baseline').disabled=false;
    const warnings=[...(Array.isArray(d.warnings)?d.warnings:[]),...(current.controller?.configuration_warnings||[])];
    $('warnings').hidden=!warnings.length;$('warnings').innerHTML=warnings.map(w=>`<p>${esc(publicText(w))}</p>`).join('');
    $('model-description').innerHTML=`<p><b>今回の計算：</b> ${esc(d.solver||'適応刻み・切替時刻を分けた数値積分')}。記録点 ${format(d.raw_points||s.t_ms.length,0)}、式の評価 ${format(d.nfev,0)} 回。初期Duty ${format((m.initial_duty||0)*100,3)}%。</p>${finite(m.energy_residual_pct)?`<p><b>今回のエネルギー収支残差：</b> ${format(m.energy_residual_pct,5)}%。</p>`:''}${d.model?`<p>${esc(typeof d.model==='string'?d.model:JSON.stringify(d.model))}</p>`:''}`;
    const hasCurrentTarget=s.i_ref?.some(finite),cc=current.config;
    $('model-independence-note').textContent=isC07Firmware(cc.algorithm)?firmwareVersion(cc.algorithm)+'の保存したC制御本体を、通常ON状態で実行する比較モデルです。回路・8チャネル測定時刻・PWMにはLabのモデルを使い、UF2全体・起動・異常停止ラッチ・watchdog・実機周辺機能の再現は含みません。':'複数の公開プログラムを参考に、制御手法を独自に実装した学習・比較用シミュレータです。各社・各プロジェクトの制御、ファームウェア、製品動作をシミュレーションとして再現したものではありません。';
    $('node-voltage-chart').closest('article').querySelector('.chart-heading p').textContent=cc.plant_mode==='c07'?'PV_RAW → F2 → PV_FUSED → 入力L2・抵抗 → VIN':'簡略Buck：パネル端子PV_RAWとVINは同じ節点。F2と入力L2は省略しています。';
    $('panel-current-chart').closest('article').querySelector('h2').textContent=cc.plant_mode==='c07'?'パネル端子電流と入力チョークL2電流':'パネル端子電流と入力電流センサ出力';
    $('current-tracking-note').textContent=hasCurrentTarget?'L1電流の平均と目標を比べます。パネル電流は下の別グラフです。':'この構成にはL1電流目標がありません。パネル電流は下の別グラフです。';
    updateCurrentViewNote();
    const reconstructed=cc.algorithm==='opensec'||(cc.algorithm==='custom'&&cc.custom_law==='model');
    $('feedback-node-note').textContent=(cc.plant_mode==='c07'?(reconstructed?'この制御はPV_FUSEDのADC測定からPV_RAWを推定してVrefと比較します。入力L2・抵抗を挟むVINや、L1の両端電圧をPV電圧として扱いません。':'この制御の電圧入力はPV_FUSEDのセンサを通した測定値です。Vrefはこのフィードバックへ渡されます。パネル端子PV_RAWとは別の節点で、正常な抵抗降下があります。'):'簡略Buckではパネル端子とVINは同じ節点です。制御はセンサ・ADCを経たPV電圧を使い、L1両端電圧は使いません。')+(irr?' MPPの電力評価はパネル端子PV_RAWです。':` 今回の整定・行き過ぎ・最終誤差は${nodeLabel}で評価しています。`);
    window.PVLabHelp?.update(config,current);
    renderTopology();renderComparison();resetTimingSelection();renderTiming();charts.forEach(chart=>chart.render());
  }
  const timingStages=[
    ['request_ms','acquire_ms','命令 → 取得','#c39243'],
    ['acquire_ms','arrival_ms','取得 → 到着','#6482a8'],
    ['arrival_ms','compute_start_ms','CPU待機','#a283a9'],
    ['compute_start_ms','compute_end_ms','制御演算','#087f8c'],
    ['compute_end_ms','ready_ms','反映準備まで','#5e9b89'],
    ['ready_ms','applied_ms','PWM境界待ち','#d27c4b']
  ];
  const timingEvents=[['request_ms','測定命令'],['acquire_ms','値の取得'],['arrival_ms','結果到着'],['compute_start_ms','演算開始'],['compute_end_ms','演算完了'],['ready_ms','PWMへ準備'],['applied_ms','Duty実反映']];
  function resetTimingSelection(){
    const items=current.timings||[];
    if(!timingSelected){const i=items.findIndex(e=>finite(e.request_ms)&&e.request_ms>=current.config.step_ms);timingIndex=i<0?0:i;}
    timingIndex=Math.max(0,Math.min(timingIndex,items.length-1));
    $('timing-sample').max=Math.max(0,items.length-1);$('timing-sample').value=timingIndex;
  }
  function renderTiming(){
    const items=current?.timings||[],e=items[timingIndex];
    $('timing-empty').hidden=!!e;$('timing-content').hidden=!e;
    $('timing-sample').disabled=!e;$('timing-prev').disabled=!e||timingIndex===0;$('timing-next').disabled=!e||timingIndex===items.length-1;
    if(!e)return;
    const elapsed=(a,b)=>finite(e[a])&&finite(e[b])?(e[b]-e[a])*1000:null;
    const timeLabel=(value)=>finite(value)?`${format(value,3)} µs`:'未反映';
    const applied=finite(e.applied_ms),superseded=e.status==='superseded',held=e.status==='held';
    $('timing-label').textContent=`測定 #${e.sample_id}　${timingIndex+1} / ${items.length}`;
    $('timing-selection-time').textContent=`命令時刻 ${format(e.request_ms,6)} ms`;
    $('timing-total').textContent=held?'Duty保持':timeLabel(elapsed('request_ms','applied_ms'));
    $('timing-age').textContent=held?'Duty保持':timeLabel(elapsed('acquire_ms','applied_ms'));
    $('timing-acquire').textContent=finite(e.acquire_ms)?timeLabel(elapsed('request_ms','acquire_ms')):'未取得';
    const state=applied?'この測定から計算したDutyが反映されました。':held?'この測定では制御がDutyの更新を要求していません。前のDutyを保持しています。':superseded?`PWM反映前に測定 #${e.superseded_by??'—'} の指令で上書きされ、この指令は適用されていません。`:'表示終了までにDutyへ反映されていません。未到達の工程は未完了として表示します。';
    $('timing-state').textContent=state;$('timing-state').className='timing-state '+(applied?'applied':superseded?'superseded':'pending');
    $('timing-values').textContent=`取得値 ${finite(e.measurement)?format(e.measurement,5)+' V':'未取得'}　→　計算したDuty ${finite(e.output)?format(e.output*100,5)+' %':'未計算'}`;
    const extended=current.config.plant_mode==='c07';
    const channelDefinitions=isC07Firmware(current.config.algorithm)?[
      ['v_in','Buck入力VINのADC値','V'],['v_pv',extended?'PV_FUSED電圧のADC値':'PV端子電圧のADC値','V'],
      ['i_pv',extended?'入力L2電流のADC値':'パネル電流のADC値','A'],['i_l','L1電流のADC値','A'],
      ['v_out','VOUTのADC値','V'],['v_bat','電池電圧のADC値','V'],['tbat','電池温度（モデル固定値）','℃'],['tsink','放熱器温度（モデル固定値）','℃']
    ]:[['v_pv',extended?'PV_FUSED電圧のADC値':'PV端子電圧のADC値','V'],['i_l','L1電流のADC値','A'],['v_out','VoutのADC値','V'],['i_pv',extended?'入力L2電流のADC値':'パネル電流のADC値','A']];
    const channelTable=$('timing-channel-table');
    channelTable.hidden=!e.channel_times_ms;
    channelTable.innerHTML=e.channel_times_ms?channelDefinitions.map(([key,label,unit])=>`<div><span>${esc(label)}</span><strong>${format(e.measurements?.[key],5)} ${unit}</strong><small>${finite(e.channel_times_ms[key])?'保持：命令から '+format((e.channel_times_ms[key]-e.request_ms)*1000,3)+' µs':'未取得'}</small></div>`).join(''):'';
    const displayStages=finite(e.bus_start_ms)?[['request_ms','bus_start_ms','ADCの空き待ち','#a87f58'],['bus_start_ms','acquire_ms','SPI開始 → 保持','#c39243'],...timingStages.slice(1)]:timingStages;
    const displayEvents=finite(e.bus_start_ms)?[timingEvents[0],['bus_start_ms','SPI開始'],...timingEvents.slice(1)]:timingEvents;
    const known=displayEvents.map(([k])=>e[k]).filter(finite),last=Math.max(...known,e.request_ms);
    const end=applied?e.applied_ms:last;
    const span=Math.max(1,(end-e.request_ms)*1000),width=940,left=126,right=100,plot=width-left-right,axisBottom=34+displayStages.length*33,height=axisBottom+46;
    const px=t=>left+(t-e.request_ms)*1000/span*plot;
    let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="測定命令からDuty反映までの各工程の所要時間"><defs><pattern id="pending-hatch" width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="#b8c6cf"/></pattern></defs>`;
    for(const tick of niceTicks(0,span,6)){const x=left+tick/span*plot;svg+=`<path d="M${x} 27V${axisBottom}" stroke="#e6edf1"/><text x="${x}" y="${axisBottom+20}" text-anchor="middle" class="timeline-tick">${format(tick,3)}</text>`;}
    svg+=`<text x="${left}" y="15" class="timeline-axis">測定命令を 0 µs とした経過時間</text><text x="${width-right+9}" y="${axisBottom+20}" class="timeline-tick">µs</text>`;
    const descriptions=[];
    displayStages.forEach(([a,b,label,fill],index)=>{
      const y=34+index*33,dt=elapsed(a,b),knownStart=finite(e[a]),knownEnd=finite(e[b]);
      svg+=`<text x="${left-12}" y="${y+14}" text-anchor="end" class="timeline-label">${label}</text><path d="M${left} ${y+10}H${width-right}" stroke="#eff3f6"/>`;
      if(knownStart&&knownEnd){const xa=px(e[a]),xb=px(e[b]);if(xb-xa>0.1)svg+=`<rect x="${xa}" y="${y}" width="${xb-xa}" height="20" rx="3" fill="${fill}"/>`;else svg+=`<path d="M${xa} ${y}V${y+20}" stroke="${fill}" stroke-width="3"/>`;svg+=`<circle cx="${xa}" cy="${y+10}" r="2.8" fill="${fill}"/><circle cx="${xb}" cy="${y+10}" r="2.8" fill="${fill}"/>`;}
      else if(knownStart){const xa=px(e[a]);svg+=`<circle cx="${xa}" cy="${y+10}" r="3.5" fill="${fill}"/><path d="M${xa} ${y+10}H${width-right}" stroke="${fill}" stroke-dasharray="4 4"/>`;}
      svg+=`<text x="${width-right+12}" y="${y+14}" class="timeline-duration">${dt!==null?format(dt,3)+' µs':held&&['ready_ms','applied_ms'].includes(b)?'Duty保持':superseded&&b==='applied_ms'?'上書き・未適用':'未完了'}</text>`;
      descriptions.push(`${label}: ${dt!==null?format(dt,3)+' µs':'未完了'}`);
    });
    svg+='</svg>';$('timing-diagram').innerHTML=svg;$('timing-diagram').setAttribute('aria-label',descriptions.join('。'));
    $('timing-event-table').innerHTML=displayEvents.map(([key,label])=>`<div><span>${label}</span><strong>${finite(e[key])?format(e[key],6)+' ms':'—'}</strong><small>${finite(e[key])?'命令から '+format((e[key]-e.request_ms)*1000,3)+' µs':'未到達'}</small></div>`).join('');
    const before=Math.max(0,timingIndex-2),after=Math.min(items.length,timingIndex+3);
    $('timing-neighbors').innerHTML=items.slice(before,after).map((x,j)=>`<button class="timing-neighbor${j+before===timingIndex?' selected':''}" data-timing-index="${j+before}"><span>#${esc(x.sample_id)}</span><b>${finite(x.applied_ms)?format((x.applied_ms-x.request_ms)*1000,3)+' µs':x.status==='superseded'?'上書き':'未反映'}</b><small>命令 ${format(x.request_ms,4)} ms</small></button>`).join('');
  }
  function selectTiming(index){timingSelected=true;timingIndex=Math.max(0,Math.min(index,(current?.timings?.length||1)-1));$('timing-sample').value=timingIndex;renderTiming();}
  function lowerBound(a,value){let lo=0,hi=a.length;while(lo<hi){const mid=(lo+hi)>>>1;if(a[mid]<value)lo=mid+1;else hi=mid;}return lo;}
  function getWindow(type){
    const c=current?.config||config;const duration=current?.series?.t_ms?.at(-1)||c.duration_ms||80;
    if(type==='pwm'){
      const width=Math.min(duration,4/(c.pwm_khz||20));
      const position=$('zoom-position').value;
      let start=position==='start'?0:position==='step'?Math.min(c.step_ms||0,duration-width):duration-width;
      start=Math.max(0,start);return [start,start+width];
    }
    const requested=Number($('view-width').value),width=requested>0?Math.min(duration,requested):duration;
    const start=(duration-width)*Number($('view-position').value)/1000;
    $('view-position').disabled=width>=duration;
    $('view-range').textContent=`${format(start,2)}–${format(start+width,2)} ms`;
    return [start,start+width];
  }
  function niceTicks(min,max,count=5){
    const span=max-min||1;const raw=span/count;const mag=10**Math.floor(Math.log10(raw));const n=raw/mag;
    const step=(n<=1?1:n<=2?2:n<=5?5:10)*mag;
    const ticks=[];for(let t=Math.ceil(min/step)*step;t<=max+step*1e-8;t+=step){ticks.push(Math.abs(t)<step*1e-9?0:t);if(ticks.length>20)break;}
    return ticks;
  }
  const point=(s,j)=>finite(s.y[j])?s.y[j]*s.scale:NaN;
  function updateCurrentViewNote(){
    const summary=current?.waveform_summary,mode=$('current-view').value;
    $('current-view-note').textContent=summary?.available
      ?(mode==='instant'?'PWMで上下する瞬時波形です。広い時間範囲では山と谷が重なって太い帯に見えます。':'実際のPWM波形を'+(summary.grouped?'最大'+summary.max_cycles_per_bin+'周期ずつ':'1周期ずつ')+'時間平均して表示します。'+(mode==='envelope'?'薄い帯はその区間の最小〜最大電流です。':'細かな上下は省き、追従の動きを見ます。'))+' 表示だけの処理で、制御入力・数値計算は変えません。'
      :'この結果には全計算点からの周期平均がないため、瞬時波形を表示します。';
  }
  class Chart{
    constructor(id,legend,series,options={}){
      this.canvas=$(id);this.ctx=this.canvas.getContext('2d');this.series=series;this.options=options;this.hover=null;this.geometry=null;
      this.background=document.createElement('canvas');this.cachedData=null;this.cacheKey=null;this.lastCurrent=null;this.lastBaseline=null;this.scheduled=false;this.sourceCache=null;this.legendHtml=null;
      this.tip=this.canvas.parentElement.querySelector('.chart-tooltip');
      this.legend=legend?$(legend):null;
      this.canvas.addEventListener('pointermove',event=>{const r=this.canvas.getBoundingClientRect();this.hover=[event.clientX-r.left,event.clientY-r.top];this.requestRender();});
      this.canvas.addEventListener('pointerleave',()=>{this.hover=null;this.tip.hidden=true;this.requestRender();});
      if(this.legend)this.legend.innerHTML=series.map(s=>`<span class="legend-item"><i class="legend-line${s.dash?' dashed':''}" style="--series:${s.color}"></i>${esc(s.label)}</span>`).join('');
    }
    sources(){
      if(!current)return [];
      const mode=this.options.current?$('current-view').value:'instant',adc=!this.options.current||$('show-current-adc').checked;
      if(this.sourceCache?.current===current&&this.sourceCache.baseline===baseline&&this.sourceCache.mode===mode&&this.sourceCache.adc===adc)return this.sourceCache.data;
      const makeSource=(def,result)=>{
        const summary=result.waveform_summary;
        if(def.average&&mode!=='instant'&&summary?.available&&summary.series?.[def.key]?.some(finite)){
          return {...def,label:def.label+'（周期平均）',t:summary.series.t_ms,y:summary.series[def.key],scale:def.scale||1,
            low:mode==='envelope'?summary.minimum[def.key]:null,high:mode==='envelope'?summary.maximum[def.key]:null,averaged:true};
        }
        return Array.isArray(result.series[def.key])&&result.series[def.key].some(finite)?{...def,label:def.label+(def.average?'（瞬時値）':''),t:result.series.t_ms,y:result.series[def.key],scale:def.scale||1}:null;
      };
      const result=this.series.flatMap(def=>{
        if(def.modes&&!def.modes.includes(current.config.plant_mode))return [];
        if(def.sample){if(!adc)return [];const rows=(current.timings||[]).filter(r=>finite(r.measurements?.[def.sample])&&finite(r.channel_times_ms?.[def.sample]));return rows.length?[{...def,t:rows.map(r=>r.channel_times_ms[def.sample]),y:rows.map(r=>r.measurements[def.sample]),scale:def.scale||1,scatter:true}]:[];}
        const source=makeSource(def,current);return source?[source]:[];
      });
      const key=this.options.baseline===true?'v_pv':this.options.baseline;
      if(baseline&&key){const source=makeSource({key,label:'基準：'+algorithmLabel(baseline.config),color:color.base,dash:true,average:!!this.options.current,scale:this.options.baselineScale||1,unit:this.options.baselineUnit||''},baseline);if(source)result.push(source);}
      this.sourceCache={current,baseline,mode,adc,data:result};
      return result;
    }
    requestRender(){if(this.scheduled)return;this.scheduled=true;requestAnimationFrame(()=>{this.scheduled=false;this.render();});}
    render(){
      const canvas=this.canvas,ctx=this.ctx,rect=canvas.getBoundingClientRect();
      if(rect.width<1||rect.height<1)return;
      // Offscreen charts render when scrolled into view, not during every drag.
      if(rect.bottom < -100 || rect.top > window.innerHeight+100){this.cacheKey=null;return;}
      const data=this.sources();
      const legendHtml=data.map(s=>`<span class="legend-item"><i class="legend-line${s.dash?' dashed':''}" style="--series:${s.color}"></i>${esc(s.label)}</span>`).join('');
      if(this.legend&&legendHtml!==this.legendHtml){this.legend.innerHTML=legendHtml;this.legendHtml=legendHtml;}
      const ratio=Math.min(window.devicePixelRatio||1,2),w=rect.width,h=rect.height;
      if(canvas.width!==Math.round(w*ratio)||canvas.height!==Math.round(h*ratio)){canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);}
      ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);
      const [xmin,xmax]=getWindow(this.options.window),key=`${w}:${h}:${ratio}:${xmin}:${xmax}:${this.options.current?$('current-view').value+':'+$('show-current-adc').checked:''}`;
      if(this.cacheKey===key&&this.lastCurrent===current&&this.lastBaseline===baseline&&this.cachedData){
        ctx.drawImage(this.background,0,0,w,h);this.drawHover(w,h,this.cachedData);return;
      }
      const margin={l:w<280?42:48,r:12,t:12,b:31},pw=w-margin.l-margin.r,ph=h-margin.t-margin.b;
      if(!data.length){ctx.fillStyle='#9aabb3';ctx.font='11px "Yu Gothic UI", sans-serif';ctx.textAlign='center';ctx.fillText(current?'データなし':'計算待ち',w/2,h/2);this.tip.hidden=true;return;}
      let ymin=Infinity,ymax=-Infinity;
      for(const s of data){const lo=Math.max(0,lowerBound(s.t,xmin)-1),hi=Math.min(s.t.length-1,lowerBound(s.t,xmax)+1);s.lo=lo;s.hi=hi;for(let j=lo;j<=hi;j++){const v=point(s,j);if(finite(v)){ymin=Math.min(ymin,v,finite(s.low?.[j])?s.low[j]*s.scale:v);ymax=Math.max(ymax,v,finite(s.high?.[j])?s.high[j]*s.scale:v);}}}
      if(!finite(ymin)){ymin=0;ymax=1;}
      if(this.options.zero){ymin=Math.min(0,ymin);ymax=Math.max(0,ymax);}
      if(this.options.binary){ymin=-.12;ymax=1.18;}else{const pad=Math.max((ymax-ymin)*.12,this.options.minPad||.02);ymin-=pad;ymax+=pad;}
      const px=t=>margin.l+(t-xmin)/(xmax-xmin||1)*pw,py=v=>margin.t+(ymax-v)/(ymax-ymin||1)*ph;
      this.geometry={margin,pw,ph,xmin,xmax,ymin,ymax,px,py};
      ctx.font='10px "Yu Gothic UI", sans-serif';ctx.lineWidth=1;ctx.textBaseline='middle';
      const yticks=this.options.binary?[0,1]:niceTicks(ymin,ymax,4);
      for(const t of yticks){const y=py(t);ctx.strokeStyle='#e9eff2';ctx.beginPath();ctx.moveTo(margin.l,y);ctx.lineTo(w-margin.r,y);ctx.stroke();ctx.fillStyle='#81959f';ctx.textAlign='right';ctx.fillText(this.options.binary?(t?'ON':'OFF'):format(t,Math.max(0,Math.min(5,-Math.floor(Math.log10((ymax-ymin)/4))+1))),margin.l-8,y);}
      const xticks=niceTicks(xmin,xmax,w<350?3:6);
      ctx.textAlign='center';ctx.textBaseline='top';
      for(const t of xticks){const x=px(t);ctx.strokeStyle='#f1f4f6';ctx.beginPath();ctx.moveTo(x,margin.t);ctx.lineTo(x,h-margin.b);ctx.stroke();ctx.fillStyle='#81959f';ctx.fillText(format(t,this.options.window==='pwm'?4:2),x,h-margin.b+7);}
      ctx.fillStyle='#9aabb3';ctx.textAlign='right';ctx.fillText('ms',w-margin.r,h-11);
      const step=current.config.step_ms;
      if(step>=xmin&&step<=xmax){ctx.setLineDash([3,4]);ctx.strokeStyle='#bdc8ce';ctx.beginPath();ctx.moveTo(px(step),margin.t);ctx.lineTo(px(step),h-margin.b);ctx.stroke();ctx.setLineDash([]);if(!this.options.binary&&w>300){ctx.fillStyle='#96a4ac';ctx.textAlign='left';ctx.textBaseline='top';ctx.fillText(isIrradiance(current.config)?'日射変化':'目標変更',Math.min(px(step)+5,w-65),margin.t+2);}}
      ctx.save();ctx.beginPath();ctx.rect(margin.l,margin.t,pw,ph);ctx.clip();
      for(const s of data){
        if(s.low&&s.high){ctx.fillStyle=s.color;ctx.globalAlpha=.13;ctx.beginPath();let started=false;for(let j=s.lo;j<=s.hi;j++){if(!finite(s.high[j]))continue;const x=px(s.t[j]),y=py(s.high[j]*s.scale);if(!started){ctx.moveTo(x,y);started=true;}else ctx.lineTo(x,y);}for(let j=s.hi;j>=s.lo;j--)if(finite(s.low[j]))ctx.lineTo(px(s.t[j]),py(s.low[j]*s.scale));ctx.closePath();ctx.fill();ctx.globalAlpha=1;}
        if(s.scatter){ctx.fillStyle=s.color;ctx.globalAlpha=.65;for(let j=s.lo;j<=s.hi;j++){const x=px(s.t[j]),y=py(point(s,j));if(!finite(y))continue;ctx.beginPath();ctx.arc(x,y,1.4,0,Math.PI*2);ctx.fill();}ctx.globalAlpha=1;continue;}
        ctx.strokeStyle=s.color;ctx.lineWidth=s.averaged?2:s.key==='v_ref'?1.5:1.55;ctx.setLineDash(s.dash?[5,4]:[]);ctx.beginPath();
        // Retain first/min/max/last samples in each display pixel. No averaging.
        const indices=[];let first=s.lo;
        while(first<=s.hi){
          const bucket=Math.floor(px(s.t[first]));let last=first,minIndex=first,maxIndex=first;
          while(last+1<=s.hi&&Math.floor(px(s.t[last+1]))===bucket){last++;if(finite(s.y[last])){if(!finite(s.y[minIndex])||s.y[last]<s.y[minIndex])minIndex=last;if(!finite(s.y[maxIndex])||s.y[last]>s.y[maxIndex])maxIndex=last;}}
          for(const j of [...new Set([first,minIndex,maxIndex,last])].sort((a,b)=>a-b))indices.push(j);
          first=last+1;
        }
        let started=false,lastY=0;
        for(const j of indices){const x=px(s.t[j]),y=py(point(s,j));if(!finite(y)){started=false;continue;}if(!started){ctx.moveTo(x,y);started=true;}else if(s.step){ctx.lineTo(x,lastY);ctx.lineTo(x,y);}else ctx.lineTo(x,y);lastY=y;}
        ctx.stroke();
      }
      ctx.restore();ctx.setLineDash([]);
      this.background.width=canvas.width;this.background.height=canvas.height;
      this.background.getContext('2d').drawImage(canvas,0,0);
      this.cacheKey=key;this.lastCurrent=current;this.lastBaseline=baseline;this.cachedData=data;
      this.drawHover(w,h,data);
    }
    drawHover(w,h,data){
      const ctx=this.ctx,{margin,pw,ph,xmin,xmax,ymin,ymax,px,py}=this.geometry;
      if(this.hover&&this.hover[0]>=margin.l&&this.hover[0]<=w-margin.r&&this.hover[1]>=margin.t&&this.hover[1]<=h-margin.b){
        const mouseTime=xmin+(this.hover[0]-margin.l)/pw*(xmax-xmin),a=current.series.t_ms;
        let index=Math.min(a.length-1,lowerBound(a,mouseTime));if(index>0&&Math.abs(a[index-1]-mouseTime)<Math.abs(a[index]-mouseTime))index--;
        const time=a[index],x=px(time);ctx.strokeStyle='#adc0ca';ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(x,margin.t);ctx.lineTo(x,h-margin.b);ctx.stroke();ctx.setLineDash([]);
        let html=`<b>${format(time,5)} ms</b>`;
        for(const s of data){let j=Math.min(s.t.length-1,lowerBound(s.t,time));if(j>0&&Math.abs(s.t[j-1]-time)<Math.abs(s.t[j]-time))j--;const v=point(s,j);if(!finite(v))continue;html+=`<div class="tip-row"><span><i class="tip-dot" style="background:${s.color}"></i>${esc(s.label)}${s.scatter?' ('+format(s.t[j],4)+' ms)':''}</span><span>${this.options.binary?(v>.5?'ON':'OFF'):format(v,4)}${s.unit?' '+esc(s.unit):''}</span></div>`;ctx.fillStyle=s.color;ctx.beginPath();ctx.arc(px(s.t[j]),py(v),2.5,0,Math.PI*2);ctx.fill();}
        this.tip.innerHTML=html;this.tip.hidden=false;const tw=this.tip.offsetWidth,th=this.tip.offsetHeight;this.tip.style.left=`${Math.max(0,Math.min(w-tw-3,this.hover[0]+14))}px`;this.tip.style.top=`${Math.max(0,Math.min(h-th,this.hover[1]-th-12))}px`;
      }else this.tip.hidden=true;
    }
  }
  function buildCharts(){
    charts=[
      new Chart('voltage-chart','voltage-legend',[{key:'v_pv',label:'パネル端子電圧 PV_RAW',color:color.pv,unit:'V'},{key:'v_ref',label:'制御器の電圧目標 Vref',color:color.ref,dash:true,step:true,unit:'V'},{key:'v_mpp',label:'モデルMPPの端子電圧',color:color.mpp,dash:true,unit:'V'},{key:'v_sense',label:'PV電圧センサ出力（RC後・ADC前）',color:color.sense,unit:'V'}],{baseline:'v_pv',baselineUnit:'V',minPad:.2}),
      new Chart('node-voltage-chart','node-voltage-legend',[{key:'v_pv',label:'パネル端子 PV_RAW',color:color.pv,unit:'V'},{key:'v_fused',label:'F2後 PV_FUSED',color:color.sense,unit:'V',modes:['c07']},{key:'v_in',label:'Buck入力 VIN',color:color.duty,unit:'V'},{sample:'v_pv',label:'PV電圧ADC値（測定点は説明参照）',color:color.ref,unit:'V'}],{minPad:.1}),
      new Chart('power-chart','power-legend',[{key:'p_pv',label:'PV電力',color:color.power,unit:'W'},{key:'p_mpp',label:'モデルMPP電力',color:color.mpp,dash:true,unit:'W'}],{baseline:'p_pv',baselineUnit:'W',minPad:1}),
      new Chart('irradiance-chart','irradiance-legend',[{key:'irradiance',label:'日射量',color:color.sun,unit:'W/m²'}],{minPad:5}),
      new Chart('energy-chart','energy-legend',[{key:'energy_deficit_j',label:'積分エネルギー差',color:color.energy,unit:'J'}],{baseline:'energy_deficit_j',baselineUnit:'J',minPad:.001}),
      new Chart('duty-chart','duty-legend',[{key:'duty_command',label:'指令',color:color.command,scale:100,step:true,unit:'%'},{key:'duty',label:'反映済み',color:color.duty,scale:100,step:true,unit:'%'}],{baseline:'duty',baselineScale:100,baselineUnit:'%',minPad:.05}),
      new Chart('current-chart','current-legend',[{key:'i_l',label:'BuckコイルL1の実電流 IL1',color:color.current,unit:'A',average:true},{key:'i_ref',label:'L1電流目標 IL1_ref',color:color.ref,dash:true,step:true,unit:'A'},{sample:'i_l',label:'L1電流ADC値（取得時刻の値）',color:color.sense,unit:'A'}],{current:true,baseline:'i_l',baselineUnit:'A',minPad:.1}),
      new Chart('panel-current-chart','panel-current-legend',[{key:'i_pv',label:'パネル端子電流 Ipanel',color:color.pv,unit:'A',average:true},{key:'i_l2',label:'入力チョーク電流 IL2',color:color.duty,unit:'A',average:true},{key:'i_pv_sense',label:'入力電流センサ出力（ADC前）',color:color.sense,unit:'A',average:true}],{current:true,minPad:.1}),
      new Chart('coil-voltage-chart','coil-voltage-legend',[{key:'v_l_terminal',label:'L1端子電圧 SW−Vout（DCR含む）',color:color.duty,unit:'V'},{key:'v_l',label:'L1誘導部分の電圧（DCR除く）',color:color.current,unit:'V'}],{window:'pwm',zero:true,minPad:.2}),
      new Chart('pid-chart','pid-legend',[{key:'p',label:'P（比例）',color:color.p,scale:100,step:true},{key:'i',label:'I（積分）',color:color.i,scale:100,step:true},{key:'d',label:'D（微分）',color:color.d,scale:100,step:true}],{zero:true,minPad:.01}),
      new Chart('pwm-chart','pwm-legend',[{key:'pwm',label:'スイッチ状態',color:color.pwm,step:true}],{binary:true,window:'pwm'}),
      new Chart('ripple-chart',null,[{key:'i_l',label:'コイル電流',color:color.current,unit:'A'}],{window:'pwm',minPad:.02})
    ];
    const visibility=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting)charts.find(c=>c.canvas===entry.target)?.requestRender();},{rootMargin:'100px'});
    charts.forEach(c=>visibility.observe(c.canvas));
    const chartResize=new ResizeObserver(()=>charts.forEach(c=>c.requestRender()));
    charts.forEach(c=>chartResize.observe(c.canvas.parentElement));
    window.addEventListener('resize',()=>charts.forEach(c=>c.requestRender()));
    window.addEventListener('lab:layout',()=>charts.forEach(c=>c.requestRender()));
  }
  function renderVerification(){
    const host=$('verification');
    if(!verification){host.innerHTML='<b>数値検証</b><p>検証レポートはまだありません。実験モデルとして結果を確認してください。</p>';return;}
    const passed=verification.passed??verification.all_passed;
    const title=passed===true?'数値検証：実施した確認に合格':passed===false?'数値検証：未達項目があります':'数値検証レポート';
    const checks=verification.checks||verification.tests||verification.results||[];
    const items=Array.isArray(checks)?checks:Object.entries(checks).map(([name,value])=>({name,...(typeof value==='object'?value:{passed:value})}));
    const names={
      'PV STC three-point fit':'PV近似曲線と3つの参照点の一致',
      'Tolerance and maximum-step refinement':'許容誤差・最大刻みを厳しくした結果との比較',
      'DOP853 versus Radau':'異なる数値解法（DOP853 / Radau）での比較',
      'Repeat starts from identical state':'同じ初期状態からの再計算の一致',
      'Duty latch uses only already-ready command':'Dutyの反映時刻と計算済み指令の対応',
      'OFF diode stops at zero current':'OFF区間の電流ゼロでの導通切替',
      'D term has observable effect':'D項を変えたときの応答の変化'
    };
    const featured=items.filter(item=>typeof item==='object'&&names[item.name]);
    const visible=featured.length?featured:items.slice(0,8),passedCount=items.filter(i=>i?.passed===true).length;
    const reportLink=typeof verificationUrl==='string'&&/^\/verification[-a-z0-9]*\.json$/.test(verificationUrl)?`<p><a href="${esc(verificationUrl)}" target="_blank" rel="noopener">全ての数値検証結果（JSON）</a></p>`:'';
    host.innerHTML=`<b>${esc(title)}</b><p>${format(passedCount,0)} / ${format(items.length,0)} 項目に合格。以下は主な確認です。</p><ul>${visible.map(item=>`<li>${esc(typeof item==='string'?item:(names[item.name]||item.name||item.description||item.test||JSON.stringify(item)))}${typeof item==='object'&&typeof item.passed==='boolean'?`：${item.passed?'合格':'未達'}`:''}</li>`).join('')}</ul>${reportLink}<p>この確認は実機試験やc07全体の検証を意味しません。</p>`;
  }
  // Circuit presets may contain old controller defaults. Preserve the selected
  // firmware profile and user edits when applying physical circuit values.
  function firmwareProfileKeys(c=config){
    if(!isC07Firmware(c.algorithm))return new Set();
    const profile=algorithmFor(c);
    return new Set([...(algorithmKeys(profile)||[]),...(profile.preset_override_fields||[]),'control_us','current_period_us','mppt_method','voltage_mode','current_mode','voltage_kd','current_kd','duty_response_gain']);
  }
  function circuitPresetEntries(p){
    const owned=firmwareProfileKeys();
    return Object.entries(p.config).filter(([key])=>!owned.has(key));
  }
  function applyCircuitPreset(id){
    const p=presets.find(p=>p.id===id);if(!p)return;
    selectedCircuitPresetId=p.id;
    Object.assign(config,Object.fromEntries(circuitPresetEntries(p)));
  }
  function applyAlgorithmPreset(id){
    const a=algorithms.find(x=>x.id===id);if(!a)return;
    const protectedKeys=new Set([...presets.flatMap(p=>Object.keys(p.config)),...specs.plant.map(s=>s[0]),...specs.target.map(s=>s[0]),...specs.irradiance.map(s=>s[0]),'plant_mode','experiment','rtol','duty_response_gain','sense_tau_us','acquire_us','transport_us','compute_us','apply_us','adc_phase']);
    const values=a.preset||a.defaults||{};
    const timingOverrides=new Set(a.preset_override_fields||[]);
    const timingKeys=new Set(specs.timing.map(s=>s[0]));
    const controlKeys=new Set(specs.algorithm.map(s=>s[0]));
    for(const [key,value] of Object.entries(values))if(!protectedKeys.has(key)||(isC07Firmware(id)&&(controlKeys.has(key)||(timingKeys.has(key)&&timingOverrides.has(key)))))config[key]=value;
    if(isC07Firmware(id))config.duty_response_gain=1;
    config.algorithm=id;
  }
  async function init(){
    try{
      const response=await fetch('/api/config');if(!response.ok)throw new Error('Pythonサーバーの設定を取得できません。');
      const data=await response.json();defaults={algorithm:'baseline',experiment:'voltage',...data.defaults};config={...defaults};presets=(data.presets||[]).map(p=>({...p,label:p.reference_id?(referenceLabels[p.reference_id]||publicText(p.label)):publicText(p.label),description:publicText(p.description)}));verification=data.verification||null;verificationUrl=data.verification_url||null;defaultPresetId=data.default_preset_id||'';
      selectedCircuitPresetId=defaultPresetId;
      setupMetadata(data);buildFields();syncFields();buildCharts();renderVerification();
      startVoltage=window.PVStartVoltage.attach({field:fields.get('v_start').box,
        getConfig:()=>({...config}),getRevision:()=>revision,
        onApply:value=>{config.v_start=value;changed();}});
      gainAutotune=window.PVGainAutotune?.attach({
        getConfig:()=>({...config}),
        getGainSpec:key=>{const f=fields.get(key);return f?{label:f.box.querySelector('.field-label').textContent,unit:f.box.querySelector('.field-value span').textContent,scale:f.scale,min:f.min,max:f.max}:null;},
        onApply:patch=>{Object.assign(config,patch);changed();},
        onStart:async()=>{
          tuningGains=true;revision++;pending=true;clearTimeout(timer);timer=null;clearTimeout(cancelTimer);cancelTimer=null;
          $('calculate').disabled=true;$('calculate').textContent='自動調整中…';status('自動調整中…','busy');
          if(running)await fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json','X-PV-Client':clientId,'X-PV-Revision':String(revision)},body:'{}'}).catch(()=>{});
        },
        onEnd:()=>{tuningGains=false;$('calculate').disabled=running;$('calculate').textContent=running?'計算中…':'再計算';if(pending&&!running&&!timer)timer=setTimeout(run,0);}
      })||null;
      for(const [label,items] of [['作成回路・学習用',presets.filter(p=>!p.reference_id)],['参考回路',presets.filter(p=>p.reference_id)]]){
        const group=document.createElement('optgroup');group.label=label;
        for(const p of items){const opt=document.createElement('option');opt.value=p.id;opt.textContent=p.label;group.appendChild(opt);}$('preset').appendChild(group);
      }
      $('preset').value=defaultPresetId;
      document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{config.mode=button.dataset.mode;changed();}));
      $('algorithm').addEventListener('change',()=>{applyAlgorithmPreset($('algorithm').value);changed();});
      for(const [id,key] of [['custom-mppt','mppt_method'],['custom-topology','custom_topology'],['custom-law','custom_law'],['custom-voltage-mode','voltage_mode'],['custom-current-mode','current_mode']]){
        $(id).addEventListener('change',()=>{
          config[key]=$(id).value;
          if(key==='custom_topology'){
            if(config.custom_topology!=='voltage_current')config.custom_law='pid';
            const cascade=config.custom_topology==='voltage_current';
            config.voltage_kp=cascade ? .2 : .003;config.voltage_ki=cascade ? 8 : 1.5;config.voltage_kd=0;
            config.current_kp=.005;config.current_ki=2;config.current_kd=0;
          }
          if(key==='custom_law'&&config.custom_law==='model'){
            config.model_voltage_gain=.05;config.model_current_gain=.1;config.model_filter_ms=.3;config.current_period_us=100;
          }
          changed();
        });
      }
      $('experiment').addEventListener('change',()=>{
        const previous=config.experiment;config.experiment=$('experiment').value;
        if(config.experiment!==previous){
          if(isIrradiance(config)){
            if(config.duration_ms<=200){config.duration_ms=1500;config.step_ms=300;}
            if(!finite(config.irradiance_after))config.irradiance_after=600;
            if(!finite(config.ramp_ms))config.ramp_ms=0;
          }else if(config.duration_ms>=1000){config.duration_ms=defaults.duration_ms||80;config.step_ms=defaults.step_ms??10;}
        }
        changed();
      });
      $('plant-mode')?.addEventListener('change',()=>{config.plant_mode=$('plant-mode').value;changed();});
      $('rtol').addEventListener('change',()=>{config.rtol=Number($('rtol').value);changed();});
      $('preset').addEventListener('change',()=>{applyCircuitPreset($('preset').value);changed();});
      $('calculate').addEventListener('click',()=>{revision++;pending=true;run();});
      $('baseline').addEventListener('click',()=>{if(!current)return;baseline=current;$('baseline-note').hidden=false;renderComparison();charts.forEach(c=>c.render());});
      $('clear-baseline').addEventListener('click',()=>{baseline=null;$('baseline-note').hidden=true;renderComparison();charts.forEach(c=>c.render());});
      ['view-width','view-position','zoom-position'].forEach(id=>$(id).addEventListener(id==='view-position'?'input':'change',()=>charts.forEach(c=>c.requestRender())));
      ['current-view','show-current-adc'].forEach(id=>$(id).addEventListener('change',()=>{updateCurrentViewNote();charts.filter(c=>c.options.current).forEach(c=>c.requestRender());}));
      $('timing-sample').addEventListener('input',()=>selectTiming(Number($('timing-sample').value)));
      $('timing-prev').addEventListener('click',()=>selectTiming(timingIndex-1));
      $('timing-next').addEventListener('click',()=>selectTiming(timingIndex+1));
      $('timing-at-step').addEventListener('click',()=>{timingSelected=false;resetTimingSelection();renderTiming();});
      $('timing-neighbors').addEventListener('click',event=>{const button=event.target.closest('[data-timing-index]');if(button)selectTiming(Number(button.dataset.timingIndex));});
      $('timing-focus').addEventListener('click',()=>{
        const sample=current?.timings?.[timingIndex];if(!sample)return;
        const duration=current.series.t_ms.at(-1),width=Math.min(1,duration),start=Math.max(0,Math.min(duration-width,sample.request_ms-width*.2));
        $('view-width').value='1';$('view-position').value=duration>width?start/(duration-width)*1000:0;
        window.PVChoices?.refresh();
        $('voltage-chart').scrollIntoView({block:'center',behavior:'smooth'});charts.forEach(c=>c.requestRender());
      });
      window.PVChoices?.refresh();
      initialized=true;revision++;run();
    }catch(error){$('error').textContent=`${error.message} 起動スクリプトからこのページを開いてください。`;$('error').hidden=false;status('サーバーに接続できません','error');}
  }
  window.PVPIDLab={getConfig:()=>({...config}),getResult:()=>current,isRunning:()=>running,getAutotuneState:()=>gainAutotune?.getState()||null,getPerformance:()=>({...uiPerformance}),getAlgorithms:()=>algorithms,getParameterSets:()=>presets,getBaseline:()=>baseline,setConfig:values=>{if(values.algorithm&&values.algorithm!==config.algorithm)applyAlgorithmPreset(values.algorithm);config={...config,...values};changed();},recalculate:()=>{revision++;pending=true;run();}};
  init();
})();

