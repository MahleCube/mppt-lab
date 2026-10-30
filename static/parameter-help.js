/* Parameter explanations and connected equivalent circuit. Display only. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const help = Object.create(null);
  const add = (key, title, parts, meaning, effect, equation = '', limit = '') => {
    help[key] = {title, parts:parts.split(' ').filter(Boolean), meaning, effect, equation, limit};
  };
  // Each key is explicit: missing explanations are reported, never filled with generic prose.
  add('preset','回路の設定セット（出発点）','pv cin l1 battery','c07代表値・小容量100W級・中容量400W級・大容量1200W級から、回路とパネル等の条件をまとめて選びます。','現在選んでいる制御方式・組み合わせ・ゲインを保ちながら、回路側の出発点を変えます。実験目標などはセットの対象値も確認してください。','','定格を保証する製品設計ではなく、比較用の条件セットです。');
  add('algorithm','制御方式','controller','測定からDutyを決める計算の構造を選びます。','各制御方式とr04、判断・構造・補正を自分で組み合わせるカスタムから選びます。方式に合わせて開始設定も切り替わります。','','r04はC制御本体の通常ON状態を実行します。他の方式は公開プログラムを参考にした独自実装です。いずれも基板全体・実機の検証ではありません。');
  add('mode','電圧PIDの構成','controller','電圧PID → Dutyで、比例Pだけ／Pと積分I／PとIと微分Dを選びます。','他の公開方式の構造をPI/PIDへ切り替える設定ではありません。','Duty = 初期Duty + P + I + D（上下限あり）');
  add('autotune','制御パラメータの自動調整','controller','選択した方式に合う係数・MPPT周期・刻みの候補を計算し、電圧追従またはMPP追従を比較します。','方針を選び「自動調整」を押すと計算を開始します。候補探索の後、スイッチ動作を含むモデルで改善を確認した値だけへ変更します。回路・測定条件・物理的な上限・選択した制御方式は保持します。','','指定したモデルと試験条件の中での比較です。全条件の最適値や実機の安定性を保証するものではありません。');
  add('plant_mode','回路の設定','pv l2 cin switch l1 cout battery','「簡単設定」は主な部品を使うBuck回路、「詳しく設定」は入力L2や追加の抵抗・容量を含めた回路で計算します。','設定欄の表示だけでなく、計算する回路構造も切り替わります。部品の数値は保持されます。詳しく設定ではパネル端子、電圧測定点、Buck入力が別の節点になります。','','回路セットを選ぶと、この選択もセットに合わせて切り替わります。詳しく設定はc07由来の正常ON等価回路で、保護ICの全動作・ゲート内部・起動は再現しません。');
  add('experiment','変化させる条件','controller pv','電圧目標を変える実験と、日射を変えてMPPを探す実験を選びます。','電圧実験は目標に追従する能力、日射実験は局所MPPT判断も含めた追従を比較します。');
  add('mppt_method','局所MPPTの判断','controller','「可変幅MPPT＋電圧・電流PI」の外側でIncCondまたはP&Oを選びます。','IncCondはI/VとΔI/ΔV、P&Oは電圧操作と電力変化から、次の電圧目標を判断します。内側の電圧PI・電流PIは共通です。','MPPの局所条件：dP/dV = I + V·dI/dV = 0');
  add('custom_topology','何を目標にして動かす？','controller','MPPTの判断をどの経路でDutyへつなぐかを選びます。','直接Dutyは一歩ずつ操作します。電圧目標→Dutyは電圧誤差を補正します。電圧目標→L1電流目標→Dutyは、外側の電圧制御がIrefを作り、内側で測定ILと比較します。','','P&O/IncCondという方向判断の選択と、P/PI/PIDという補正の選択は、それぞれ別の軸です。');
  add('custom_law','目標に近づける計算法','controller cin l1','電圧や電流の目標を追う際に、誤差に対するP/PI/PIDか、C・Lの回路式を用いる計算法かを選びます。','回路式は電圧目標→電流目標→Dutyの構成で使います。回路式の枝へさらにPIDを重ねる設定ではありません。','','この組み合わせ実験は原ファームウェアにはない学習用構成も含みます。');
  add('voltage_mode','電圧追従の補正','controller','カスタム構成の電圧ループをP・PI・PIDから選びます。','Pは現在の誤差、Iは誤差の累積、Dは測定電圧の変化速度を使います。出力先は構成によりDutyまたはL1電流目標です。','','直接Duty探索の構成と回路式の構成では使いません。');
  add('current_mode','L1電流追従の補正','controller isense','カスタム構成の内側の電流ループをP・PI・PIDから選びます。','電流目標と測定L1電流の差からDutyを作ります。Dは目標値のジャンプではなく測定電流の変化を使います。','','電圧→L1電流→DutyかつP/PI/PIDの計算法でのみ使います。');
  add('mppt_step_duty','直接MPPTのDuty刻み','controller pwm','カスタム構成の「Dutyを直接一歩ずつ動かす」で、一度に増減するDutyです。','P&O/IncCondが電圧を上げる判断ならBuckのDutyを下げ、電圧を下げる判断ならDutyを上げます。電圧刻みVとは別単位です。','ΔDuty = ± 指定刻み（数値欄は%）');
  add('voltage_kd','電圧追従 Kd','controller vsense','カスタムPIDで測定PV電圧の変化速度に掛ける係数です。','電圧→Duty構成ではDutyを、電圧→電流構成ではIrefを補正します。構成によって単位が変わるので、数値欄の単位を確認してください。','D成分 = Kd_v × 平滑化した測定電圧の変化速度','「電圧・電流PI」そのものにDを追加する設定ではありません。');
  add('current_kd','L1電流追従 Kd','controller isense','カスタムPIDで測定L1電流の変化速度に掛ける係数です。','目標との差を打ち消す内側の補正で、急な電流変化へ反応します。量子化やPWMリップルも差分へ現れます。','電流D成分 = −Kd_i × 平滑化した測定ILの変化速度');
  add('loop_derivative_filter_ms','カスタムPIDのDフィルタ','controller','カスタムPIDの測定電圧・電流の時間差分を平滑化する時定数です。','大きくするとD項の細かな変動を抑え、応答も遅くします。MPPTが使うΔI/ΔVやアナログRCとは別の処理です。','α = 1 − exp(−Δt/τ)');
  add('kp','比例ゲイン Kp','controller','電圧PIDでPV電圧誤差から直接Duty補正を作る係数です。','大きいほど同じ電圧誤差に強く反応します。大き過ぎると測定遅れやLCの振動を増幅します。','e = 測定V − 目標V、P = Kp·e','数値欄は %/V 表示、内部計算ではDuty/Vです。');
  add('ti_ms','積分時間 Ti','controller','基準PI/PIDの積分の強さをKpと一緒に決めます。','小さくすると残り続ける誤差を速く打ち消します。Duty制限時には積分が増え続けない処理があります。','Ki = Kp / Ti、I[k] = I[k−1] + Ki·e·Δt','Pモードでは使いません。');
  add('td_ms','微分時間 Td','controller','電圧PIDで、測定PV電圧の変化速度に掛ける係数です。','電圧の変化へ先に反応しますが、リップルや量子化の影響も受けます。目標値の差分ではなく測定値の差分を使います。','D = Kp·Td·filtered(ΔV/Δt)','PIDモードでのみ使います。「電圧・電流PI」の2つのPIにはD項はありません。');
  add('derivative_filter_ms','Dのフィルタ時定数','controller','電圧PIDの測定電圧差分を平滑化する一次フィルタです。','大きくすると細かな揺れへの反応が減り、D項の応答も遅くなります。PとIにはこのフィルタを掛けません。','a = exp(−Δt/τ)、rate[k] = a·rate[k−1] + (1−a)·ΔV/Δt');
  add('v_start','開始時のPV電圧','pv','計算開始時のパネル端子電圧です。実際の動作電圧は日射量に加え、接続した回路の負荷でも変わります。','「日射量からMPP電圧を計算」は、現在のパネル設定と変化前の日射量から最大電力点の電圧を計算し、この欄だけに入力します。手動設定も可能です。日射量を変えただけでは値を上書きしません。','I(V) = Iph − I0(exp(V/a) − 1)、MPPは I + V·dI/dV = 0 を満たす点です。','温度固定の近似PV曲線を使います。参照値Vmpそのものとは限りません。c07ではPV_RAWの開始値で、センサ位置PV_FUSEDやVINとは異なります。開始点が回路の条件を満たさない場合は適用しません。電源OFFからの起動試験ではありません。');
  add('v_target','変更後の目標','pv controller','電圧ステップ実験で追従させる電圧目標です。','指定時刻に開始目標からこの値へ変えます。電圧PID → Dutyや電圧・電流PI系等は測定PV電圧を比較し、「回路式からDutyを計算」のc07適応は推定PV端子電圧を比較します。','','「Dutyを一歩ずつ調整」と「Dutyの変化速度を調整」の電圧実験には、この比較のための目標追従処理を追加しています。');
  add('step_ms','条件を変える時刻','','実験開始 t = 0 から、電圧目標または日射を変え始めるまでの時間です。','部品の時定数ではなく、外から与えるイベントの時刻です。日射ランプならここから変化を開始します。');
  add('duration_ms','実験の長さ','','数値計算を何msまで続けるかを決めます。','全PWMのON/OFFを解くため、時間を延ばすほど計算量が増えます。終了時までに整定しない結果を、到達したと扱いません。','PWM周期数 = duration_ms × pwm_khz');
  add('irradiance','変化前の日射量','pv','パネルへ与える日射の強さです。電圧実験ではこの値が一定です。','このモデルでは光電流を日射に比例させるため、日射を下げると取り出せる電流とMPP電力も変わります。','Iph(G) = Iph(STC) × G / 1000','温度変化や部分影による複数ピークのモデルではありません。');
  add('irradiance_after','変化後の日射量','pv','日射実験で、変化が完了した後の日射の強さです。','制御器へ新しいMPPの正解を渡す設定ではありません。制御器は変化後の測定値から動作点を探します。');
  add('ramp_ms','日射のランプ時間','pv','日射が開始値から終了値まで直線的に変わる時間です。','0なら瞬時のステップです。c07の小さなPV_FUSED容量とL2では急な日射低下で電圧が崩れ、モデルの範囲外で停止する場合があります。','G(t) = G0 + (G1−G0)·(t−t開始)/Tランプ（変化区間）');
  add('mppt_tolerance_pct','MPP到達の許容不足率','','真のモデルMPPと比較する結果の合否判定の幅です。','2%ならMPP電力の98%以上を到達の条件にします。これを変えても制御計算そのものは変えません。','Ppv / Pmpp ≥ 1 − 許容不足率/100');
  add('mppt_hold_ms','MPP到達の最低確認時間','','MPP到達条件を維持していることを確認する時間です。','指定時間とMPPT判断2周期分の長い方を使います。瞬間的にMPP付近を通過しただけでは到達としません。','確認時間 = max(指定時間, 2 × MPPT判断周期)');
  add('voltage_kp','電圧PI Kp','controller','電圧・電流PI系で、PV電圧誤差からコイル電流目標を作る比例係数です。','Dutyを直接作る電圧PIDのKpとは単位も役割も異なります。','Irefの比例成分 = Kp_v · (測定Vpv − Vref)');
  add('voltage_ki','電圧PI Ki','controller','電圧・電流PI系の電圧誤差を積み上げ、電流目標の残り誤差を補う係数です。','積分値は判断の間も保持され、電圧ループが動く際に経過時間に応じて更新されます。','積分増分 = Ki_v · 電圧誤差 · Δt');
  add('current_kp','電流PI Kp','controller isense','電圧・電流PI系で、目標コイル電流と測定コイル電流の差をDutyへ変換する係数です。','内側のループが過渡中の電流を繰り返し補正します。大きくすれば必ず速く安定するわけではありません。','Dutyの比例成分 = Kp_i · (Iref − 測定IL)');
  add('current_ki','電流PI Ki','controller isense','電圧・電流PI系の電流誤差を積み上げる係数です。','電流目標とのずれが残るとDutyの積分成分を変えます。上下限と積分抑制の処理も通ります。','Duty積分増分 = Ki_i · (Iref − 測定IL) · Δt');
  add('mppt_step_v','MPPTの電圧刻み','controller','次の電圧目標を試す際の基準幅です。','大きくすると探索は大きく動きますが、MPP周辺の往復も大きくなります。可変幅の方式では実際の刻みがこの値と一致しません。','','「電圧・電流PI」は初回に10倍の刻みを用います。「Dutyを一歩ずつ調整」・Dの直接Duty操作量とは別です。');
  add('algorithm_filter_ms','測定フィルタの公称等価時定数','controller','制御方式内で使うデジタル平滑化の強さです。アナログセンサRCとは別です。','方式により対象・段数が異なります。多くの方式は指定測定周期から係数を固定するため、ADC待ちで更新が遅れると実効時定数が伸びます。「回路式からDutyを計算」の電力計側は実測定間隔を使います。','EMA：y[k] = (1−α)·y[k−1] + α·x[k]');
  add('libre_arr','「Dutyを一歩ずつ調整」 PWMの周期カウント','controller pwm','「Dutyを一歩ずつ調整」の整数カウントをDutyへ換算する分母です。','同じ1カウントでも、この値が大きいほど小さなDuty刻みになります。ここでは実際のPWM周波数は別の設定です。','Duty = compare_count / ARR');
  add('libre_step_counts','「Dutyを一歩ずつ調整」 Duty刻み','controller pwm','「Dutyを一歩ずつ調整」で一度の判断に増減する整数カウントです。','通常MPPTも電圧実験用の追加追従も、判断時にこの刻みを直接Dutyへ加えます。','ΔDuty = ± step_counts / ARR');
  add('voltage_deadband_v','追加電圧追従の許容帯','controller','「Dutyを一歩ずつ調整」の電圧実験で、Dutyを動かさない電圧誤差の幅です。','帯の中では追加電圧追従の操作方向を0にします。MPPTの電力比較や、結果の整定判定幅とは別です。','|測定Vpv − Vref| ≤ deadband → 追加操作なし');
  add('fugu_voltage_kp','追加電圧追従の係数','controller','「Dutyの変化速度を調整」の電圧実験で、電圧誤差からDutyを動かす速度を作ります。','速度を経過時間で積算してカウントを動かすため、電圧PIDのDuty/Vとは意味が違います。','操作速度 = 係数 × (測定Vpv − Vref)','電圧実験用にLabで追加した処理で、参考元の独立Vrefループを再現するものではありません。');
  add('fugu_fast_speed','「Dutyの変化速度を調整」 高速時の操作速度','controller pwm','「Dutyの変化速度を調整」のP&Oの高速状態で用いる操作速度の大きさです。','この値そのものをDutyへ代入しません。方向・制限との選択を経て、経過時間とカウント換算係数を掛けます。','Δcount = speed × 0.025 × max_count × Δt（増分制限あり）');
  add('fugu_slow_speed','「Dutyの変化速度を調整」 低速時の操作速度','controller pwm','「Dutyの変化速度を調整」のP&Oが低速状態で使う操作速度です。','MPP近傍などで細かく動かすための値です。低速判断周期と、Dutyを積算する間隔は別です。');
  add('fugu_slow_period_ms','「Dutyの変化速度を調整」 低速判断周期','controller','「Dutyの変化速度を調整」の低速状態で、平均電力を比較し次の方向を決める間隔です。','高速状態はMPPT判断周期を使います。制限が働くとP&O判断の時計を更新するため、単純な常時等間隔ではありません。');
  for(const [key,label,part] of [['vin','入力電圧下限','pv sense'],['vout','出力電圧上限','cout sense'],['iin','入力電流上限','pv sense'],['iout','L1電流上限','l1 sense'],['power','出力電力上限','cout l1 sense']]){
    for(const term of ['kp','kd'])add('fugu_'+key+'_'+term,label+'のPD '+(term==='kp'?'Kp':'Kd'),'controller '+part,
      term==='kp'?'制限値で正規化した誤差に掛ける比例係数です。':'制限値で正規化した誤差の「今回−前回」に掛ける係数です。',
      '5つの制限器の最も小さい出力がDutyの操作速度を制限します。入力電圧下限は負の係数、他の上限制限は正の係数です。制限値そのものは変更しません。',
      'e = 1 − 測定値 / 制限値、u = Kp·e ＋ Kd·(e − 前回e)',
      'Kdは時間で割る微分係数ではありません。制御周期を変えると効果も変わります。PD出力は後段で積算されてDutyになります。');
  }
  add('model_voltage_gain','モデル制御の電圧係数','controller cin','「回路式からDutyを計算」のBuck適応で、電圧誤差をCinに必要な充放電電流へ換算する係数です。','回路節点推定をした上で電流目標を作ります。PIの積分ゲインではなく、過去の電圧誤差を累積しません。','入力電流の補正 = kv · Cin · (推定Vpv − Vref) / Δt');
  add('model_current_gain','モデル制御の電流係数','controller l1','「回路式からDutyを計算」のBuck適応で、目標電流と予測ILの差からDuty補正を作る係数です。','LとVIN/VOUT等を使う回路式に基づく補正です。名前がKiでも積分PIのKiではありません。','Duty補正 ∝ L · ki · (Iref − IL予測) / (Δt · 電圧換算分母)');
  add('model_filter_ms','モデル入力4値の平滑時定数','controller','「回路式からDutyを計算」で4チャネルを同じ過去時刻へ補間した後、同じ係数のEMAを掛けます。','電圧・電流の差分からL2等の電圧を推定するとき、リップルと量子化の影響を減らします。実際の測定時刻差から係数を求めます。','α = 1 − exp(−実測定間隔 / τ)','アナログRC遅れを逆算して消す処理ではありません。0では追加EMAを掛けません。');
  add('opensec_min_delta_v','P&O傾斜を判断する最小電圧差','controller adc','「回路式からDutyを計算」のP&Oで、ΔP/ΔVを計算するには小さ過ぎる電圧差を判定します。','閾値以下なら傾斜を割り算せず、保持した方向へ基準刻みを一回だけ試します。小さなΔVで異常に大きな操作が出るのを避けます。','閾値 = max(指定値, ADC電圧2カウント相当)');
  add('opensec_max_step_v','P&Oの1回の最大電圧刻み','controller','「回路式からDutyを計算」の可変幅P&Oで、一度に変える電圧目標の大きさを制限します。','傾斜が大きくてもこの上限を超えません。基準刻みの設定が上限より大きい場合も上限で止めます。','刻み = min(上限, 基準刻み × (1 + |ΔP/ΔV|))');
  add('model_delay_us','モデルの遅延補償','controller l1','「回路式からDutyを計算」の回路式で、今の測定ILから先の電流を予測する時間です。','実際のADC取得・輸送・CPU演算・PWM反映待ちを変える設定ではありません。遅れの見積もりが正しいかは別に確認が必要です。','IL予測 = 測定IL + 遅延 × 推定コイル電圧 / L');
  add('current_limit_a','コイル電流の上限','controller isense l1','制御器が使うコイル電流の制限値です。','電圧・電流PI系・EではIrefの上限、「Dutyを一歩ずつ調整」では超過時にDutyを下げる判断、「Dutyの変化速度を調整」では制限計算に使います。','','ソフトウェアの目標・操作制限です。瞬時の実電流が必ずこの値以下になる保証や実機保護の定格ではありません。');
  add('input_current_limit_a','入力電流の上限','controller ipsense','「Dutyを一歩ずつ調整」・Dで用いる入力電流の制限値です。','「Dutyを一歩ずつ調整」は出力電力÷入力電圧で推定した入力電流と比較します。「Dutyの変化速度を調整」は入力側測定値を制限計算へ使います。');
  add('input_voltage_limit_v','入力電圧の制限値','controller vsense','「Dutyを一歩ずつ調整」・Dで、PV電圧が低くなり過ぎないようにする制御側の下限です。','「Dutyを一歩ずつ調整」は入力電圧が下がるとDutyを下げる分岐を優先します。設定Vrefや部品の耐圧とは別です。');
  add('output_voltage_limit_v','出力電圧の上限','controller vosense','制御器がVOUTを見て動作を抑える電圧です。','電圧・電流PI系・Eは超過時に電流目標上限を0にします。「Dutyを一歩ずつ調整」・Dは出力電圧制限の経路を使います。','','完全な電池充電器の状態遷移やハード保護を再現するものではありません。');
  add('power_limit_w','電力の上限','controller','「Dutyの変化速度を調整」で他の制限とともに評価する電力の制限値です。','入力電力の誤差から許されるDuty操作速度を求め、他の制限と比較して厳しい側を選びます。');
  add('duty_min','Dutyの下限','pwm switch','制御器が要求できるDutyの下限です。','演算結果が小さ過ぎる場合に切り詰めます。PWM一周期のうちONにする割合で、単位は%です。','0% = 常時OFF、100% = 常時ON');
  add('duty_max','Dutyの上限','pwm switch','制御器が要求できるDutyの上限です。','上限に達するとそれ以上の負荷操作ができず、目標に追従しない場合があります。積分抑制などの処理は方式によって異なります。','Duty = ON時間 / PWM周期');
  add('control_us','制御の周期','adc','新しい測定を指示する予定間隔です。','これだけでDutyの実更新間隔は決まりません。4チャネルADCや演算の待ち、方式内の周期、PWM境界待ちが別にあります。','測定指示時刻 = k·control_us + adc_phase·PWM周期');
  add('voltage_period_us','電圧ループの周期','controller','電圧・電流PI系が電流目標Irefを作り直す予定間隔です。','届いた測定を処理する時に、前回からの経過時間を確認します。測定が届かなければ、この設定どおりには動きません。');
  add('current_period_us','電流ループの周期','controller','電圧・電流PI系の電流PI、または「回路式からDutyを計算」のモデル制御がDutyを作り直す予定間隔です。','測定指示周期やADC到着の間隔より細かく設定しても、新しい測定なしに実行が増えるわけではありません。');
  add('mppt_period_ms','MPPT判断の周期','controller','電力変化などから探索方向や次の操作目標を判断する予定間隔です。','電圧・電流PI系・E等では内側のDuty補正と別です。「Dutyを一歩ずつ調整」ではこの判断時にDutyを直接動かします。');
  add('pwm_khz','PWM周波数','pwm switch','Buckのスイッチを毎秒何回ON/OFFするかを決めます。','Dutyが一定でも、周波数を変えると一回のON/OFF時間と電流リップルが変わります。このモデルは各ON/OFF区間を解きます。','PWM周期 [µs] = 1000 / 周波数 [kHz]','MOSFETの切替エネルギーやゲート駆動損失を計算するモデルではありません。');
  add('adc_phase','測定指示の開始位相','adc pwm','最初の測定指示をPWM一周期のどの位置から開始するかを決めます。','0.5なら半周期後です。以後はcontrol_us間隔で指示するので、周期がPWMと整数比でなければ取得位相はずれます。','初回指示 = adc_phase × PWM周期','実際の取得は、ここから取得遅れとチャネル間隔だけ後です。');
  add('sense_tau_us','電圧センサの時定数','vsense vosense','VpvとVOUTの測定経路に置く、アナログRCの等価一次遅れです。','大きいほどリップルを落としますが電圧変化への追従も遅くなります。ADCが値を保持する時刻の設定とは別です。','τ·dVsense/dt = V節点 − Vsense','c07のVpv測定点はPV_FUSEDです。簡略モデルではVOUTセンサの独立RC状態は省略しています。');
  add('current_sense_tau_us','電流センサの等価RC時定数','isense ipsense','c07のILと入力L2電流の測定経路に入れる一次遅れです。','代表値12.145µsはINAの0.145µsと出力RCの12µsを1極に縮約した値です。値0ならこの遅れを省きます。','τ·dIsense/dt = I実電流 − Isense','入力電流センサはL2/R27を流れる電流を測ります。PV端子電流とは完全に同じではありません。');
  add('acquire_us','指示 → 実際の取得','adc','ADCバスが使用可能になり測定を開始してから、最初の値を保持するまでの時間です。','その時刻のセンサ出力を取り込みます。c07代表11µsはSPIフレームの開始から保持点までです。待ち行列は別途加算されます。');
  add('transport_us','取得 → 結果の到着','adc','最後のチャネルを保持してから、測定一式が演算へ届くまでの時間です。','c07代表13µsは保持後の変換・SPIフレーム完了までです。4チャネルでは最初の取得からの経過時間はさらに長くなります。','フレーム占有 = acquire_us + 3·adc_channel_us + transport_us');
  add('adc_channel_us','ADCチャネル間の取得差','adc','Vpv → IL → VOUT → 入力電流の順で取得する時刻の差です。','0は同時取得の仮定です。24µsなら4値は別々の時刻の値になり、11+3×24+13=96µsのフレーム占有が生じます。','取得時刻 = 先頭取得時刻 + チャネル順番 × 間隔','要求周期が占有時間より短い場合、ADCの待ち行列が生じます。');
  add('adc_bits','ADC分解能','adc','センサ出力を何段階の値へ丸めるかを決めます。','0では量子化しません。ビット数が少ないほど小さな電圧・電流変化を区別しにくくなり、MPPTのΔ値にも影響します。','量子化刻み = 測定全幅 / (2^bit − 1)','この量子化モデルは実ADCのノイズ・オフセット誤差・非線形を全て含むものではありません。');
  add('adc_voltage_range_v','ADC電圧測定の全幅','adc vsense vosense','ADCコードを回路の電圧へ換算するときの、0Vから上限までの範囲です。','分圧と基準電圧に相当します。範囲外は端でクリップし、範囲が広いほど1カウントの電圧幅も大きくなります。','c07代表：2.5V × (150kΩ + 3.3kΩ) / 3.3kΩ = 116.136…V','ADC端子に116Vを直接入れる意味ではありません。');
  add('adc_current_range_a','ADC電流測定の全幅','adc isense ipsense','双方向電流をADCコードへ換算する際の全幅です。','全幅50Aなら−25Aから+25Aに対応します。0Aは中央のオフセット電圧になります。','c07代表：2.5V / (50 × 1mΩ) = 50A（中心1.25V）','抵抗値を変えてもこの換算幅は自動更新されません。計測系の条件も合わせて設定します。');
  add('compute_us','制御の演算時間','controller','測定一式が届いてから制御計算が終わるまでのモデル上の時間です。','CPUが前の処理中なら待ち時間も生じます。Python自体が計算に使った実時間ではなく、制御系へ与える遅れです。');
  add('apply_us','演算終了 → 反映待ち','pwm','Duty計算が終わってから、PWMへ渡せる状態になるまでの追加時間です。','準備完了後、次のPWM周期境界でDutyが反映されます。設定を0にしても必ず即時反映になるわけではありません。','演算終了 → apply_us → PWM周期境界 → 新Duty');
  add('cin_uf','入力コンデンサ Cin','cin','BuckがON時に吸い込むパルス電流を受け持つ入力容量です。','簡略BuckではPV端子へ直結、c07ではL2等の後のVINに接続します。容量を大きくすると同じ電流差での電圧変化が遅くなります。','Cin·dVCin/dt = 入力電流 − スイッチへ流れる電流 − 分圧負荷');
  add('l_uh','コイル L1','l1','Buckの出力側で電流の変化を抑える主コイルです。','大きいほど同じコイル電圧での電流変化が遅くなります。c07の非線形設定がONなら、保存したLdiff曲線全体をこの値/214µHで拡大縮小します。','dIL/dt = コイル両端電圧 / Ldiff(IL)','「回路式からDutyを計算」の予測器はこの設定Lの定数を使い、Plantの非線形L曲線を直接読みません。');
  add('cout_uf','出力コンデンサ Cout','cout','コイル電流と電池側へ流れる電流との差を蓄える出力容量です。','c07の非線形設定がONなら、保存した合成Cdiff曲線全体をこの値/944.873…µFで拡大縮小します。','Cdiff(VCout)·dVCout/dt = IL − 出力電流 − 分圧負荷');
  add('r_l_ohm','コイルの直列抵抗','rl','主コイルL1の巻線・配線による電圧降下と導通損失を表します。','電流が大きいほど電圧降下と損失が増えます。コイルのインダクタンスとは別の値です。','電圧降下 = R·IL、導通損失 = R·IL²');
  add('r_switch_ohm','スイッチのON抵抗','switch','Buckの上側スイッチがONのときだけ生じる抵抗です。','ON区間のコイル電圧を減らし、導通損失を発生させます。OFF時の還流ダイオード抵抗とは別です。','ON時の降下 = Ron·IL','MOSFET容量・切替過渡・ゲート駆動損失は含みません。');
  add('r_battery_ohm','電池側の直列抵抗','rout f3 rcell','主充電経路でVOUTから電池電圧源までの総抵抗です。','c07では、この総抵抗から出力保護抵抗とF3抵抗を引き、残りを電池内部抵抗として置きます。内訳を別々に総抵抗へ加算しません。','Rcell = R総 − R出力保護 − RF3 > 0','BAT_AUX枝の抵抗は主充電経路の直列抵抗ではありません。');
  add('v_battery','電池の開放電圧','battery','電池を近似する理想電圧源の電圧です。','充電時の端子電圧には、この電圧に内部抵抗の電圧降下が加わります。設定を上げるとBuckに必要なDutyも変わります。','BAT_RAW = V電池 + Rcell·I電池','SOC・温度・電池の動的インピーダンスは固定電圧源に縮約しています。');
  add('pv_voc','パネル Voc（STC）','pv','STCでパネルから電流を取り出さないときの電圧です。','IscとVmp/Imp参照点とともに、パネルの近似I–V曲線を決めます。日射が変わるとモデルの開放電圧も変わります。','開放点：I(Voc) = 0');
  add('pv_isc','パネル Isc（STC）','pv','STCで端子電圧を0Vにしたときのパネル電流です。','この参照値が光電流の規模を決めます。実験中の電流が常にこの値になる設定ではありません。','短絡点：I(0) = Isc');
  add('pv_vmp','パネル Vmp参照値','pv','STCのI–V近似曲線を合わせる参照点の電圧です。','Impと対の点として近似曲線を求めます。曲線の真の最大電力点は別計算するため、この値と完全一致するとは限りません。');
  add('pv_imp','パネル Imp参照値','pv','STCのVmp参照点で流れる電流です。','Iscより小さい値にします。Voc/Isc/Vmp/Impから指数型のI–V曲線を求め、制御の測定値はその曲線と回路の応答から生じます。','I(V) = Iph − Is·(exp(V/a) − 1)','直列抵抗Rs=0、並列抵抗Rsh=∞の近似です。');
  add('input_l_uh','入力チョーク L2','l2','c07でPV_FUSEDとVINの間の電流変化を抑えるコイルです。','このL2があるため、PVの電圧とBuck入力電圧は過渡中に同じになりません。IL2は独立した状態として計算します。','L2·dIL2/dt = V_PV_FUSED − V_IN − R入力合計·IL2');
  add('l2_dcr_ohm','L2の直流抵抗','rl2','入力チョークL2の巻線抵抗です。','入力シャント・入力保護抵抗とともにIL2に比例する降下を生みます。「回路式からDutyを計算」のVIN推定でもこの内訳を使います。','R入力合計 = L2_DCR + R27 + R入力保護');
  add('pv_fuse_ohm','PVヒューズ F2の抵抗','f2','パネル端子PV_RAWとPV_FUSEDの間の直列抵抗です。','パネル電流が流れると、センサ側PV_FUSEDはPV_RAWより低くなります。ヒューズが切れる動作は計算しません。','V_PV_RAW − V_PV_FUSED = RF2·Iパネル');
  add('input_shunt_ohm','入力シャント R27','r27 ipsense','L2と同じ入力電流が流れる検出抵抗です。','モデルの入力経路の電圧降下・損失を変えます。測定のADC換算幅は独立設定なので、この値だけを変えても自動で再校正されません。','シャント電圧 = R27·IL2');
  add('input_protection_ohm','入力保護MOSのON抵抗合計','rin','入力側の保護MOS 2個を正常ONの抵抗へ縮約した値です。','L2/DCR/R27と直列に入るため、VINの電圧と入力損失へ影響します。','','遮断・復帰・保護ICの判定はこの抵抗値で再現しません。');
  add('pv_node_c_uf','PV_FUSEDの容量','cpv','入力チョークL2の手前、PV_FUSEDからGNDへ接続する主回路容量です。','パネル電流とL2電流の瞬間的な差を受け持ちます。代表0.1µFは小さいので、この節点は急な日射変化の影響を受けます。','Cpv·dVCpv/dt = Iパネル − IL2 − 分圧負荷','電圧センサ側のフィルタ容量100nFとは別の部品です。');
  add('pv_node_esr_ohm','PV_FUSED容量のESR','cpv','PV_FUSEDの主回路容量に直列に置く等価抵抗です。','節点の端子電圧と容量内部電圧との差、損失を生みます。','V端子 − V容量 = ESR·I容量','代表値は保存モデル由来の極小値で、実物を同定した値ではありません。');
  add('cin_esr_ohm','入力容量群の等価ESR','cin','VINの複数コンデンサを一つに縮約したときの直列抵抗です。','パルス状の容量電流によってVIN端子電圧に即時の成分が生じます。Cin内部電圧とは区別します。','V_IN − V_Cin = ESRin·I_Cin','各容量枝の高周波モードを保持するモデルではなく低周波等価です。');
  add('cout_esr_ohm','出力容量群の等価ESR','cout','Cout容量内部とVOUT端子の間の等価直列抵抗です。','コイル電流と出力電流の差が、容量の積分変化とは別にVOUTの電圧差を作ります。','V_OUT − V_Cout = ESRout·I_Cout');
  add('out_protection_ohm','出力保護MOS＋シャント抵抗','rout','VOUTからBAT_PLUSへ至る正常ONの保護抵抗です。','電池側総抵抗の内訳をこの位置へ分離します。これを増やすと、総抵抗一定では電池内部Rが減ります。','V_OUT − V_BAT_PLUS = R保護·I保護','遮断や保護シーケンスは固定ON抵抗に縮約しています。');
  add('battery_fuse_ohm','電池ヒューズ F3の抵抗','f3','BAT_PLUSとBAT_RAWの間の抵抗です。','保護後の容量と電池側容量を別の節点に分けます。電池側総抵抗の内訳なので、総抵抗一定ではRcellが差し引かれます。');
  add('bat_node_c_uf','BAT_PLUSの容量','cplus','出力保護MOSの後、F3の手前に置く容量です。','Coutとは別の状態です。保護経路を流れる電流と、F3の先へ流れる電流の差で充放電します。','Cplus·dVCplus/dt = I保護 − IF3 − 分圧負荷');
  add('bat_node_esr_ohm','BAT_PLUS容量のESR','cplus','BAT_PLUS容量に直列に置く抵抗です。','BAT_PLUS端子電圧と容量内部電圧を分け、容量の充放電時に損失を生みます。');
  add('bat_aux_c_uf','BAT_AUXの容量','caux','BAT_RAWから補助枝を通って接続する容量です。','BAT_PLUSの330µFやCoutとは独立して充放電します。補助枝の抵抗を通して電池側へ接続します。');
  add('bat_aux_r_ohm','BAT_AUX枝 F4＋F1の抵抗','raux','BAT_RAWから補助容量BAT_AUXへ向かう枝の抵抗です。','主充電経路の途中に直列接続する抵抗ではありません。補助容量の充放電電流だけがこの枝を流れます。','Iaux = (V_BAT_RAW − V_Caux) / (Raux + ESRaux)');
  add('bat_aux_esr_ohm','BAT_AUX容量のESR','caux','補助容量の直列抵抗です。','補助枝抵抗と合わせて充放電速度と損失を決めます。代表値は保存モデルにある設定値です。');
  add('diode_vf','還流ダイオードの順方向降下','diode','上側スイッチがOFFでILが正の間、電流を流し続ける還流経路の電圧降下です。','OFF中のコイル電流の減り方と損失に影響します。ILが0になるとダイオードが遮断するDCMへ移ります。','OFF：L·dIL/dt = −Vout − Vf − (RL + Rd)·IL','元c07の平均Coreを完全再現する素子ではなく、このLabの非同期Buckの仮定です。');
  add('diode_r_ohm','還流ダイオードの導通抵抗','diode','c07拡張のOFF導通時に、Vfに加える電流比例の抵抗です。','還流中の降下と導通損失を増やします。逆回復や接合容量は含みません。','ダイオード降下 = Vf + Rd·IL');
  add('nonlinear_l','L1の電流依存曲線','l1','0なら固定L、1なら保存資料の差分インダクタンスLdiff(I)を使います。','電流に応じてdIL/dtの係数が変わります。保存曲線は|IL|=0〜30Aで、その範囲外では計算を停止します。','Ldiff(I) = 保存曲線(I) × l_uh/214','実装の閾値は0.5です。UIでは0か1を指定してください。');
  add('nonlinear_c','Coutの電圧依存曲線','cout','0なら固定Cout、1なら電圧依存の差分容量Cdiff(V)を使います。','C13/C14の固定容量とMLCC 2個の曲線を合成します。容量内部電圧60Vが保存曲線の上限です。','Cdiff(V) = (940µF + 2×Cmlcc(V)) × cout_uf/944.873…','実装の閾値は0.5です。これは端子電圧をかけた定格容量の単純な比ではありません。');
  add('rtol','数値計算の相対許容誤差','','微分方程式を解く際の局所誤差見積もりに対する許容値です。','小さくすると刻みを厳しく調整し、計算時間が増える場合があります。物理部品や制御ゲインに対応する項目ではありません。','誤差の尺度 ≈ 絶対許容値 + rtol × 状態の大きさ','この値が小さくても、未モデル化の部品や実機との差が小さい保証にはなりません。');

  add('duty_response_gain','Duty反映倍率','controller pwm','制御が作った補正量を、Dutyへ反映する倍率です。','1は元の補正、2は通常の補正を2倍にします。開始時のDutyや回路式のつり合い成分は倍にしません。','','0では通常の追従補正を止めます。Dutyの上下限と直接Duty方式の優先制限は残りますが、PI・回路式で電流目標を制限しても、倍率0ではDutyを直せません。回路式のつり合い成分は更新されるため、Duty固定の意味でもありません。');
  add('c07_current_filter_ms','L1電流の平滑時定数','controller isense','c07の電流PIへ渡す測定L1電流に掛けるデジタル一次平滑です。','0なら平滑を掛けません。センサのアナログRCやMPPT平均窓とは別です。','α = Δt / (τ + Δt)、IL平滑 += α·(IL測定 − IL平滑)');
  add('c07_cv_kp','充電電圧PI Kp','controller vosense battery','充電電圧からL1電流の上限を作るPIの比例係数です。','電池電圧と平滑VOUTの高い方がCV目標へ近づくと、流してよい電流を減らします。PV電圧PIやL1電流PIのKpとは別です。','eCV = CV目標 − max(電池電圧, 平滑VOUT)');
  add('c07_cv_ki','充電電圧PI Ki','controller vosense battery','充電電圧PIの積分係数です。','充電電圧の誤差を積み重ねて許容電流を補正します。選ばれた電流目標へ積分状態を追従させ、制限解除後に過大な要求が残ることを抑えます。','積分の増分 = Ki_cv × eCV × 外側ループの経過時間');
  add('c07_current_rise_a_s','L1電流目標の上昇速度','controller l1','外側のPV電圧PIが作る電流目標を、1秒あたりどこまで増やせるかです。','大きいほど要求を早く増やせます。電流を減らす制限は、この上昇制限とは別に適用します。','新Iref ≤ 前Iref ＋ 上昇速度 × 外側ループの経過時間');
  add('c07_mppt_max_step_v','MPPTの最大電圧刻み','controller','IncCond判断後に一度で動かせるVrefの最大幅です。','傾斜が大きくてもこの幅を超えません。最小刻みとの間で選びます。','刻み = clamp(傾斜倍率 × |ΔP/ΔV| / max(|平均I|, 電流下限), 最小刻み, 最大刻み)');
  add('c07_mppt_step_gain_v','MPPTの傾斜倍率','controller','電力の傾斜を入力電流で正規化した大きさを、電圧目標の刻みに変える係数です。','大きいほど一回の操作幅が増えます。電流PIのゲインやMPPT実行周期を変える値ではありません。','正規化傾斜 = |ΔP/ΔV| / max(|平均入力I|, 電流下限)');
  add('c07_mppt_power_deadband_w','IncCond判断信号の許容帯','controller','IncCondの判断信号S=I×ΔV＋V×ΔIをゼロ付近とみなす幅です。','十分なΔVがあっても|S|がこの幅以下なら電圧目標を保持します。保持中は判断基準を残し、ゆっくりした日射変化を累積して判断できます。','|S| ≤ 許容帯 → Vrefを保持','名称の単位はWですが、有限差分のΔPそのものとはΔV×ΔI分だけ異なります。');
  add('c07_mppt_voltage_deadband_v','IncCondの最小電圧差','controller adc','前の判断基準との電圧差が小さ過ぎるかを判定する幅です。','幅以下では傾斜の割り算を避け、電流差が十分正ならVrefを上げ、十分負なら下げ、それ以外は保持します。','|ΔV| ≤ 設定幅 → ΔIによる分岐');
  add('c07_mppt_current_deadband_a','IncCondの最小電流差','controller ipsense','ΔVが小さいとき、平均入力電流の差を有意とみなす幅です。','この幅内の電流差は方向判断に使わず、Vrefを保持します。L1電流の整定許容幅とは別です。');
  add('c07_mppt_settle_v','MPPT平均開始の電圧誤差幅','controller vsense','平滑PV電圧とVrefの誤差について、MPPT平均を始めてよいか確認する幅です。','L1電流誤差も範囲内にあり、制限中でない状態が連続する必要があります。平均中に外れるとその窓を破棄します。','|平滑PV電圧 − Vref| ≤ 設定幅');
  add('c07_mppt_settle_a','MPPT平均開始の電流誤差幅','controller isense','平滑L1電流とIrefの差について、MPPT平均を始めてよいか確認する幅です。','L1電流の追従を確認する値です。IncCondが計算に使う入力L2電流の差とは別です。','|Iref − 平滑IL1| ≤ 設定幅');
  add('c07_pv_headroom_v','Buck入力と電池の最低電圧差','controller cin battery','VINと電池電圧の差が小さくなり、降圧動作に余裕がなくなったときの基準です。','基準へ近づく帯域で許容L1電流を下げます。MPPT目標の下限にも使います。','余裕 = 測定VIN − 電池電圧','PV_FUSED電圧ではなく、Buck入力VINとの比較です。');
  add('c07_vout_trip_v','過電圧で電流要求を止める値','controller vosense battery','生のVOUTまたは電池電圧がこの値以上なら、通常ON制御内で許容電流を0にする値です。','CV目標57.1 Vとは別の保存値58 Vです。','max(VOUT測定, 電池電圧) ≥ 閾値 → 許容電流0','Labは通常ON制御内の動作を比較します。実ファームウェアの異常停止ラッチ・再起動まで再現しません。');
  add('c07_mppt_settle_ms','MPPT平均前の整定確認','controller','PV電圧とL1電流が各許容幅内に連続していることを確認する最短時間です。','この確認後に平均窓へ測定値を加え始めます。不整定になったら確認時間と平均窓をやり直します。','整定確認 → 平均窓 → 方向判断');
  add('c07_mppt_window_ms','MPPT平均の最短時間','controller adc','整定確認後の生のPV電圧・入力L2電流を集める窓の最短時間です。','V・Iをそれぞれ時間加重平均し、その積を電力とします。MPPT最短間隔も満たすまで窓が伸びる場合があります。','平均V = Σ(V·Δt)/ΣΔt、平均I = Σ(I·Δt)/ΣΔt、P = 平均V×平均I');
  add('c07_background_us','MPPT裏側計算の所要時間','controller','平均窓のコピーから新しいMPPT目標を計算する処理に、Lab内で割り当てる時間です。','高速制御のCPU使用時間を避けて進めます。結果が完成して有効な場合、後続の高速制御回で目標だけを受け取ります。','','実機で測定した最悪実行時間を保証する値ではありません。0にしてもC制御本体の分離した計算・受け渡しを使います。');
  add('c07_irq_occupancy_us','高速制御がCPUを使う時間','controller adc','1回の高速制御がADC取得・計算・後処理に使うと仮定する時間です。','この間はMPPTの裏側計算を進めません。8チャネル取得＋制御演算より短い値や、制御周期以上の値は使えません。','8チャネル取得時間 ＋ 演算時間 ≤ CPU使用時間 < 制御周期','実機の割り込み遅延・watchdog・処理期限違反の再現試験ではなく、Labの予定時刻モデルです。');
  add('c07_reference_weight','PV目標のP重み','controller vsense','目標変更を外側PV電圧のP項へどの強さで反映するかです。','0は測定の変化だけ、1は通常のPです。Iは目標との全誤差を積分し、Dは測定値だけを微分します。全ゲインを弱める値や電流上昇速度の制限ではありません。','P = Kp × (測定PV電圧 − β×Vref)、0 ≤ β ≤ 1','r04の外側PIDに使用します。定常動作点の偏りは積分状態が引き受けます。');
  add('c07_pwm_packet_cycles','1回に送るPWMパルス数','controller pwm','Duty指令ごとに出力するPWMパルスの数です。','計算完了ごとに指定回数を投入します。実行中なら次を1個待機し、終了時に次がなければ停止。Duty 0は実行中も停止します。r04の初期値は50です。0では連続PWMとして計算します。','1～63：有限パケット、0：連続PWM','パルスの出力期間とADC取得の位相は追従結果へ影響します。PIO命令・ゲート駆動・デッドタイム全体を再現する値ではありません。');
  const r03Help={
    algorithm_filter_ms:{meaning:'c07 r03でPV電圧・出力電圧等へ掛けるデジタル一次平滑の時定数です。',effect:'L1電流は別の平滑設定です。MPPTの平均窓にはこの平滑値ではなく生のPV電圧・入力L2電流を使います。',equation:'α = Δt / (τ + Δt)、平滑値 += α·(測定値 − 平滑値)'},
    mppt_step_v:{meaning:'c07 r03の可変刻みMPPTで使う最小電圧刻みです。',effect:'傾斜に応じた刻みをこの値と最大刻みの間へ制限します。小さなΔVではこの最小値を使います。'},
    output_voltage_limit_v:{meaning:'c07 r03の充電電圧PIが維持するCV目標です。',effect:'電池電圧と平滑VOUTの高い方を比較し、許されるL1電流の上限を作ります。超過したら常に即OFFする閾値という意味ではありません。',equation:'eCV = CV目標 − max(電池電圧, 平滑VOUT)',limit:'緊急側の過電圧閾値と区別します。完全な充電状態遷移・保護全体のモデルではありません。'},
    input_current_limit_a:{meaning:'c07 r03が直接測定する入力L2電流の上限です。',effect:'測定入力電流が閾値以上なら、許容L1電流を減らします。パネル端子電流とL1コイル電流は別です。'},
    control_us:{meaning:'8チャネル測定とL1電流PIを呼ぶ高速制御の予定周期です。',effect:'この方式ではL1電流PIの周期を別に変更しません。ADC取得と演算が終わり、PWM境界へ到達してからDutyが反映されます。',equation:'測定指示時刻 = k·control_us ＋ 初回位相'},
    voltage_period_us:{meaning:'c07 r03のPV電圧PIと充電電圧PIを更新する最短間隔です。',effect:'高速制御回で経過時間を確認します。保存値5,000 µsと高速周期1,001 µsでは5回ごと、実際は5,005 µsです。'},
    mppt_period_ms:{meaning:'c07 r03が前のMPPT判断から空ける最短間隔です。',effect:'この時間だけでは判断しません。連続整定と平均窓の条件も必要で、不整定や制限中は判断が延期されます。'},
    acquire_us:{meaning:'測定指示から8チャネル中の先頭VINを取得するまでの遅れです。',effect:'r03保存値は11.632 µs。以後、ADCチャネル間の取得差を使って順番に測定します。'},
    adc_channel_us:{meaning:'VIN → PV_FUSED → 入力L2電流 → L1電流 → VOUT → 電池電圧 → 電池温度 → 放熱器温度の取得間隔です。',effect:'8チャネルを等間隔としたLab近似です。保存値は約25.7063 µs。電池温度25℃・放熱器35℃は固定です。',equation:'チャネルnの取得 = 指示 ＋ acquire_us ＋ n×adc_channel_us',limit:'実機SPI・PIOの全タイミングを再現するものではありません。'},
    transport_us:{meaning:'8チャネル最後の取得から、一式が高速制御へ届くまでの遅れです。',effect:'r03保存値は82.424 µs。先頭VINから最後の温度までの取得差は別に加算します。',equation:'ADC一式 = acquire_us ＋ 7×adc_channel_us ＋ transport_us'},
    adc_bits:{meaning:'c07 r03へ渡す測定値をADCコードへ切り捨て量子化するビット数です。',effect:'保存値は12 bit。測定全幅とオフセットから量子化し、設定を変えるとC制御本体へ渡る値が変わります。',equation:'量子化刻み = 測定全幅 / 2^bit',limit:'ADCノイズ・オフセット誤差・非線形の全てを含むものではありません。'},
    current_limit_a:{meaning:'c07 r03が選ぶL1電流目標の上限です。',effect:'CV PI・入力電流・VINの余裕・目標上昇速度等が、さらに小さい目標を選ぶ場合があります。'},
    duty_min:{meaning:'c07 r03で連続したPWMとして許す最小Dutyです。',effect:'計算結果が0より大きくても、この値未満なら0へ落としてOFFにします。下限へ持ち上げ続ける制限とは異なります。',equation:'0 < 計算Duty < 最小Duty → Duty = 0'}
  };
  const r04Help={
    ...Object.fromEntries(Object.entries(r03Help).map(([key,item])=>[key,Object.fromEntries(Object.entries(item).map(([part,text])=>[part,text.replaceAll('c07 r03','r04').replaceAll('r03保存値','共通ADC保存値')]))])),
    voltage_mode:{meaning:'r04の外側PV電圧補正はPIDです。',effect:'PV目標のP重みを使用し、測定PV電圧の時間微分Dを加えます。内側L1電流はPIです。'},
    voltage_kp:{meaning:'PV電圧からL1電流要求を作るP係数です。',effect:'目標に対してはP重みβを掛けます。電圧変化への比例作用と目標の変化への比例作用を分けられます。',equation:'P = Kp_v × (平滑PV電圧 − β×Vref)'},
    voltage_kd:{meaning:'平滑PV電圧の時間変化をL1電流要求へ加えるD係数です。',effect:'目標値は微分しません。Buckでは測定PV電圧の上昇に対して電流要求を増やす符号です。',equation:'D = Kd_v × 一次平滑したdV測定/dt',limit:'PID時に使用します。IncCondのΔI/ΔVとは別の計算です。'},
    loop_derivative_filter_ms:{meaning:'r04のPV測定微分Dを一次平滑する時定数です。',effect:'入力のPV電圧平滑とは別です。Dへ渡す差分値を平滑し、外側PVループで電流要求に加えます。',equation:'D用差分 = (今回の平滑PV電圧 − 前回の平滑PV電圧) / 経過時間'},
    voltage_period_us:{meaning:'r04のPV電圧PIDと充電電圧PIを更新する最短間隔です。',effect:'高速制御回で経過時間を確認するため、高速周期の整数倍へ切り上げた時刻に実行します。現在値は制御方式の説明に表示します。'},
    c07_current_rise_a_s:{meaning:'通常ON状態でL1電流目標の増加速度を制限する値です。',effect:'正の値なら1秒あたりの増加量を制限し、0ならこの制限を無効にします。電流の減少制限や起動ランプとは別です。',equation:'値 > 0：新Iref ≤ 前Iref ＋ 値×Δt。値 = 0：増加速度の制限なし。',limit:'0にしてもCV・入力電流・L1電流目標などの制限は残ります。実機で任意の速さが安全だという保証ではありません。'},
    c07_cv_ki:{meaning:'r04の充電電圧PIの積分係数です。',effect:'CVが制限していない間は積分項を選択された電流目標へ合わせ、CV比例項の電圧余裕を残します。通常の電流増加をCV積分の速さだけで制限しないための処理です。',equation:'CV非作動時：CV積分項 = 選択されたIref'},
    output_voltage_limit_v:{...r03Help.output_voltage_limit_v,meaning:'r04の充電電圧PIが維持するCV目標です。',effect:'電池電圧と平滑VOUTの高い方から許容L1電流を計算します。CV非作動時の積分追従を変更し、電圧余裕の比例成分を残します。'},
    current_limit_a:{meaning:'r04が選ぶL1電流目標の上限です。瞬時電流の故障判定閾値ではありません。',effect:'保存設定の15 Aは運転目標です。CV・入力L2電流・VINの余裕などが、さらに小さい目標を選ぶ場合があります。',limit:'測定L1電流の一度の超過を故障とする判定ではありません。Labは故障監視・ラッチ停止を再現せず、部品の短時間ピーク許容も保証しません。'},
    input_current_limit_a:{meaning:'r04が直接測定する入力L2電流の折返し開始値です。',effect:'閾値以上でL1電流要求を減らします。L1電流目標とは別で、入力保護回路との余裕を確保するための暫定値です。',limit:'センサ誤差・リップル・保護ICの条件付き閾値を全て保証した設計値ではありません。'}
  };
  let config = {}, result = null, selected = 'preset', model = '', zoom = 0; // 0 = fit available pane width
  const selectorKeys = {'plant-mode':'plant_mode','mppt-method':'mppt_method',preset:'preset',algorithm:'algorithm',experiment:'experiment',rtol:'rtol','custom-mppt':'mppt_method','custom-topology':'custom_topology','custom-law':'custom_law','custom-voltage-mode':'voltage_mode','custom-current-mode':'current_mode'};
  const names = {pv:'PVパネル / PV_RAW',f2:'F2',cpv:'PV_FUSED容量',l2:'入力L2',rl2:'L2 DCR',r27:'R27',rin:'入力保護MOS',cin:'Cin / VIN',switch:'上側スイッチ',diode:'還流ダイオード',l1:'主コイルL1',rl:'L1直列抵抗',cout:'Cout / VOUT',rout:'出力保護',cplus:'BAT_PLUS容量',f3:'F3',raux:'補助枝抵抗',caux:'BAT_AUX容量',rcell:'電池内部抵抗',battery:'電池電圧源',vsense:'PV電圧センサ',isense:'ILセンサ',vosense:'VOUTセンサ',ipsense:'入力電流センサ',adc:'ADC',controller:'制御計算',pwm:'PWM反映'};
  function boxFor(key) { return document.querySelector('.field[data-key="'+CSS.escape(key)+'"]'); }
  function meta(key) {
    const box = boxFor(key), input = box?.querySelector('input[type=number]');
    const ids=Object.keys(selectorKeys).filter(id => selectorKeys[id] === key);
    const id=ids.find(id=>$(id)&&!$(id).closest('[hidden]'))||ids[0];
    const select = id && $(id);
    return {title:box?.querySelector('.field-label')?.textContent?.replace(/\s*\?\s*$/,'').trim() || help[key]?.title || key,
      value:input?.value ?? (key === 'mode' ? config.mode : select?.selectedOptions?.[0]?.textContent ?? config[key]),
      unit:box?.querySelector('.field-value span')?.textContent || '', hint:box?.querySelector('.field-hint')?.textContent || ''};
  }
  function isC07() { return (config.plant_mode || $('plant-mode')?.value) === 'c07'; }
  function value(key, unit = '') { const n=Number(config[key]); return Number.isFinite(n) ? n.toLocaleString('ja-JP',{maximumSignificantDigits:5})+unit : ''; }
  function dutyConversion() {
    const c=config,id=c.algorithm||'baseline',mult=Number(c.duty_response_gain??1);
    const fmt=n=>Number(n).toLocaleString('ja-JP',{maximumSignificantDigits:5});
    const custom=id==='custom',direct=custom&&c.custom_topology==='direct_duty';
    const modeled=id==='opensec'||(custom&&!direct&&c.custom_law==='model');
    const cascade=['ti','plexim'].includes(id)||(custom&&c.custom_topology==='voltage_current');
    if(['c07_r03','c07_r04'].includes(id))return '<section class="duty-mapping"><h3>'+(id==='c07_r04'?'r04':id.replace('_',' '))+'のDuty反映</h3><p>このC制御本体には追加のDuty倍率がなく、1に固定します。</p><div class="ph-equation"><p>eI = L1電流目標 − 測定L1電流</p><p>Duty = VOUT / VIN ＋ Kp_i×eI ＋ 積分項</p></div><p>PV電圧の補正と充電電圧PI・各制限がL1電流目標を作り、内側のL1電流PIがDutyを決めます。上限・積分飽和対策・最小Duty未満のOFF処理を適用します。</p></section>';
    let equations=[],detail='',example='';
    if(modeled){
      equations=['Duty = つり合い成分 ＋ M × 電流補正','電流補正 = 電流係数 × L × (Iref − 予測IL) / (測定時間差 × 電圧換算分母)'];
      detail='つり合い成分は、出力電圧・損失・推定入力電圧などから求めます。倍率はコイル電流を目標へ近づける補正に掛けます。';
      example='例：つり合い成分が40%、倍率前の補正が＋1ポイントなら、制限前のDutyは '+fmt(40+mult)+'% です。';
    }else if(id==='libresolar'){
      equations=['通常のカウント増分 = 方向 × M × 刻みカウント','Duty変化量 = 整数カウント増分 / 周期カウント'];
      detail='小数カウントの残りを持ち越し、整数カウント分だけ反映します。電流・電圧制限が優先された場合の操作は、この倍率で弱めません。';
      example='現在の通常操作：'+fmt(c.libre_step_counts)+' カウント × '+fmt(mult)+' = '+fmt(c.libre_step_counts*mult)+' カウント／判断（量子化前）。';
    }else if(id==='fugu'){
      equations=['通常の操作速度 = min(M × 追従速度, 制限側の速度)','Duty増分 = 操作速度 × 経過時間 × 方式の換算係数'];
      detail='増分上限を適用し、カウントへ量子化します。制限中・解除直後の専用処理は倍率より優先します。倍率を上げても、制限に当たれば操作量は増えません。';
      example='例：通常の追従速度が1なら、制限との比較前の速度は '+fmt(mult)+' です。';
    }else if(direct){
      equations=['Dutyの増分 = 方向 × M × 設定刻み','新しいDuty = 前回Duty ＋ 増分'];
      detail='方向は電圧追従またはMPPTの判断で決まります。判断しない間は指令を保持します。明示的なDuty最小値への制限操作は優先します。';
      example='現在の通常操作：'+fmt(100*c.mppt_step_duty)+' ポイント × '+fmt(mult)+' = '+fmt(100*c.mppt_step_duty*mult)+' ポイント／判断。';
    }else{
      const kp=Number(id==='baseline'?c.kp:cascade?c.current_kp:c.voltage_kp);
      const mode=id==='baseline'?(c.mode||'PI'):custom?(cascade?c.current_mode:c.voltage_mode):'PI';
      const ki=id==='baseline'?kp/(Number(c.ti_ms)*.001):Number(cascade?c.current_ki:c.voltage_ki);
      const kd=id==='baseline'?kp*Number(c.td_ms)*.001:Number(cascade?c.current_kd:c.voltage_kd);
      equations=[cascade?'誤差 e = 目標L1電流 − 測定L1電流':'誤差 e = 測定PV電圧 − 目標PV電圧',
        'P = M × Kp × e',
        mode==='P'?'I = 0':'Iの増分 = M × Ki × e × 測定・制御の経過時間',
        mode==='PID'?'D = M × Kd × 平滑化した測定変化速度'+(cascade?'（電流は負符号）':''):'D = 0',
        'Duty = 開始時Duty ＋ P ＋ 積分補正 ＋ D'];
      detail=cascade?'電圧側は電流目標を作り、倍率は最後の電流→Dutyの補正にだけ掛けます。二重PIの実装では、開始時Dutyを積分状態に含めています。':'電圧誤差からDutyを直接補正します。コイル電流を目標にする内側ループはありません。';
      detail+=' 積分には飽和を抑える処理があります。';
      example='P項の例：誤差1 '+(cascade?'A':'V')+'、Kp='+fmt(kp)+' Duty/'+(cascade?'A':'V')+'、倍率'+fmt(mult)+'なら、補正は＋'+fmt(100*kp*mult)+' ポイントです。';
      equations.push('現在の実効係数：Kp='+fmt(mult*kp)+'、Ki='+fmt(mode==='P'?0:mult*ki)+'、Kd='+fmt(mode==='PID'?mult*kd:0));
    }
    return '<section class="duty-mapping"><h3>Dutyへの反映 · '+esc(fmt(mult))+'倍</h3><p>'+esc(detail)+'</p><div class="ph-equation">'+equations.map(e=>'<p>'+esc(e)+'</p>').join('')+'</div><p>'+esc(example)+'</p><p>内部のDutyは0〜1です。補正0.01は、表示では1ポイント（例：40% → 41%）です。最後にDutyの上下限を適用します。</p></section>';
  }
  function autotuneExplanation(host) {
    const state=window.PVPIDLab?.getAutotuneState?.()||{},r=state.result,api=window.PVGainAutotune;
    const available=state.capability||api?.capability?.(config),h=help.autotune;
    const profile=api?.profileFor?.(state.profile||'balanced',config)||{label:'バランス'};
    const fmt=(v,unit='')=>Number.isFinite(v)?esc(v.toLocaleString('ja-JP',{maximumSignificantDigits:6}))+esc(unit):'—';
    const text=value=>typeof value==='string'?value:Array.isArray(value)?value.map(text).filter(Boolean).join(' '):value&&typeof value==='object'?value.summary||value.description||value.label||'':'';
    const meaning=config.algorithm==='c07_r04'?'r04のPV電圧・L1電流の追従ゲインを調整し、電圧追従またはMPP追従を比較します。':h.meaning;
    let html='<article class="ph-card"><div class="ph-title"><h2>'+h.title+'</h2><span class="ph-value">'+esc(profile.label)+'</span></div><p class="ph-meaning">'+meaning+'</p><p>'+h.effect+'</p>';
    if(config.algorithm==='c07_r04')html+='<h3>r04で調整するところ</h3><p>外側のPV電圧'+(config.voltage_mode==='PI'?'PI（Kp・Ki）':'PID（Kp・Ki・Kd）')+'と、内側のL1電流PI（Kp・Ki）を調整します。電圧側のDは測定PV電圧の変化から電流要求を補正する項です。L1電流側にはDを追加しません。</p><p>r04のC制御本体を動かして候補を比較します。MPPTの設定、P重み、Dフィルタ、制御周期、ADC、PWMパケット、回路と制限値は保持します。日射実験でも変更するのは追従ゲインです。</p>'+(config.c07_pwm_packet_cycles===0?'<p>現在は連続PWMです。その設定を保持し、平均化した候補探索の後、実際のスイッチON/OFFを含む模型で確認します。</p>':'<p>候補探索ではパケット中のON/OFFを平均化し、パケット間の停止を残します。採用前は実際のスイッチON/OFFを含む有限PWMパケットの模型で確認します。</p>')+'<p class="ph-boundary">L1電流目標の上限（初期値15 A）とCV目標（57.1 V）は瞬時停止の閾値ではありません。出力過電圧の設定閾値を確認し、候補のL1電流・入力L2電流ピークが元の設定より増えないことも比較します。この電流比較は部品定格や実機保護の安全確認ではありません。</p>';
    html+='<dl class="ph-tuning-profiles">'+['speed','balanced','gentle'].map(name=>{const p=api?.profileFor?.(name,config)||{};return '<dt>'+esc(p.label||name)+'</dt><dd>'+esc(p.description||'')+'</dd>';}).join('')+'</dl><p>同じ候補が複数の方針で選ばれる場合もあります。速度重視が必ず最短になるわけではありません。</p>';
    if(available?.supported===false)html+='<p class="ph-boundary">'+esc(available.reason||'この条件は対象外です。')+'</p>';
    if(state.statusDetail)html+='<p class="ph-boundary">'+esc(state.statusDetail)+'</p>';
    html+='<p>改善が確認できなければ値は変更しません。「元に戻す」で、変更した係数・周期・刻みをまとめて復元できます。計算中の設定変更は自動調整を中止します。</p><p class="ph-boundary">'+h.limit+'</p>';
    if(r){
      html+='<h3>直近の調整結果</h3>';
      if(state.resultStale)html+='<p class="ph-boundary">調整時点の条件の結果です。現在の設定とは異なります。</p>';
      const scope=api?.scopeText?.(r)||text(r.validation_scope);
      if(scope)html+='<p class="ph-boundary">'+esc(scope)+'</p>';
      if(r.detailed_validated===false||r.pwm_validated===false)html+='<p class="ph-boundary">候補計算だけでは採用しません。スイッチ動作を含む確認が未完了、または不合格です。</p>';
      const mpp=r.capability?.objective==='mpp'||(state.resultConfig||config).experiment==='irradiance';
      if(r.approximation?.screening)html+='<p>候補探索：スイッチのON/OFFを平均化した回路と、選択した制御器・測定時間線を使います。リップルを含む採用判定とは別です。</p>';
      else if(text(r.approximation))html+='<p>候補探索：'+esc(text(r.approximation))+'</p>';
      if(r.approximation?.acceptance)html+='<p>詳細確認：スイッチのON/OFFを解き、描画点を減らす前の値で採点します。</p>';
      const nodeLabel=node=>Array.isArray(node)?node.map(nodeLabel).join(' / '):({'PV_RAW':'PV_RAW（パネル端子）','PV_FUSED':'PV_FUSED（入力L2の手前）','VIN':'VIN（Buck入力）'}[node]||text(node));
      const node=r.metric_node||r.measurement_node||r.after?.evaluated_node||r.before?.evaluated_node||r.after?.target_node||r.before?.target_node||r.trial?.metric_node||r.validation_scope?.metric_node;
      html+='<p>評価する場所：'+esc(mpp?'PV_RAW（パネル端子）の真の電力。制御用センサの電力とは区別します。':nodeLabel(node)||'方式が目標にしている物理電圧の節点。')+'</p>';
      const trial=r.trial;
      if(!mpp&&trial&&Number.isFinite(trial.v_target))html+='<p>最初の試験：電圧目標 '+fmt(trial.v_start)+' → '+fmt(trial.v_target,' V')+' ／ 日射 '+fmt(trial.irradiance,' W/m²')+' ／ 観測 '+fmt(trial.duration_ms,' ms')+'</p>';
      const metricRows=mpp?[['recovery_ms','MPP復帰時間',' ms',1],['energy_deficit_j','回収エネルギーの不足',' J',1],['tracking_efficiency_pct','MPP追従効率',' %',1],['hold_power_ripple_fraction','終端の電力の揺れ幅／平均電力',' %',100],['peak_current_a','最大L1電流',' A',1],['peak_output_voltage_v','最大出力電圧',' V',1],['score','比較点（小さい方が良い）','',1]]:
        [['settling_ms','整定時間',' ms',1],['overshoot_pct','行き過ぎ',' %',1],['tail_max_error_v','終端区間の最大電圧誤差',' V',1],['peak_current_a','最大L1電流',' A',1],['peak_output_voltage_v','最大出力電圧',' V',1],['final_error_v','終了時の電圧誤差',' V',1],['score','比較点（小さい方が良い）','',1]];
      const inputNode=r.after?.cases?.[0]?.limit_semantics?.peak_input_current_node||r.before?.cases?.[0]?.limit_semantics?.peak_input_current_node||((state.resultConfig||config).plant_mode==='c07'?'L2':'PV_RAW');
      metricRows.splice(metricRows.findIndex(row=>row[0]==='peak_current_a')+1,0,['peak_input_current_a',inputNode==='L2'?'最大入力L2電流':'最大パネル端子電流（PV_RAW）',' A',1]);
      const table=(before,after)=>{
        const shown=metricRows.filter(([key])=>before?.[key]!==undefined||after?.[key]!==undefined);
        if(!shown.length)return '';
        return '<table class="ph-tuning-metrics"><thead><tr><th scope="col">評価値</th><th scope="col">調整前</th><th scope="col">候補</th></tr></thead><tbody>'+shown.map(([key,label,unit,scale])=>'<tr><th scope="row">'+label+'</th>'+[before,after].map(m=>'<td>'+((/settling|recovery/.test(key)&&m?.[key]===null)?'観測内に未整定':fmt(Number.isFinite(m?.[key])?m[key]*scale:null,unit))+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
      };
      if(r.before||r.after)html+='<h3>条件をまとめた比較</h3>'+table(r.before,r.after)+'<p>効率は最も低い値、時間・誤差・ピーク等は数値を確認できた条件の最大値です。未整定の条件は下の個別結果で区別します。比較点は平均＋最も悪い点の25%です。</p>';
      const caseIds=[...new Set([...(r.before?.cases||[]),...(r.after?.cases||[])].map(row=>row.case_id))];
      const status=row=>!row?'結果なし':row.completed===false?'観測未完了':row.current_peak_comparison_passed===false?'変更前に対する電流ピークの条件を満たさず':row.physical_limits_passed===false?(row.limit_semantics?'出力過電圧・有限値・C制御実行の確認不成立':'電流・出力電圧の制限を満たさず'):row.accepted?'この試験の条件を通過':'追従の条件を満たさず';
      for(const id of caseIds){
        const before=r.before?.cases?.find(row=>row.case_id===id),after=r.after?.cases?.find(row=>row.case_id===id),spec=r.cases?.find(row=>row.id===id);
        const caseNode=after?.target_node||before?.target_node||node;
        html+='<details class="ph-tuning-case"><summary>'+esc(spec?.description||id||'試験')+'</summary><p>電圧目標の節点：'+esc(nodeLabel(caseNode)||'未取得')+(mpp?' ／ 電力の採点：PV_RAW（パネル端子）':'')+'</p>';
        if(spec)html+='<p>観測 '+fmt(spec.duration_ms,' ms')+(mpp?' ／ 日射 '+fmt(spec.irradiance)+' → '+fmt(spec.irradiance_after,' W/m²')+' ／ ランプ '+fmt(spec.ramp_ms,' ms'):' ／ 目標 '+fmt(spec.v_start)+' → '+fmt(spec.v_target,' V'))+'</p>';
        html+='<p>調整前：'+esc(status(before))+' ／ 候補：'+esc(status(after))+'</p>'+table(before,after);
        if(after?.comparison_checks)html+='<p>電流ピークは変更前との比較です。数値比較の許容差：</p><ul>'+Object.entries(after.comparison_checks).map(([key,value])=>'<li>'+esc(key==='peak_current_a'?'L1電流':inputNode==='L2'?'入力L2電流':'パネル端子電流（PV_RAW）')+' '+fmt(value.tolerance_a,' A')+' ／ '+(value.passed?'比較条件を通過':'比較条件を満たさず')+'</li>').join('')+'</ul>';
        if(after?.rejection_reasons?.length)html+='<ul>'+after.rejection_reasons.map(reason=>'<li>'+esc(reason)+'</li>').join('')+'</ul>';
        html+='</details>';
      }
      if(r.before||r.after)html+='<p>調整用試験の結果です。通常グラフは選択中の実験条件で別途計算します。</p>';
      const changes=state.parameterChanges||state.gainChanges||[];
      if(changes.length)html+='<h3>変更したパラメータ'+(state.resultApplied?'':'（現在は未適用）')+'</h3><dl class="ph-tuning-gains">'+changes.map(g=>'<dt>'+esc(g.label||g.key)+'</dt><dd>'+fmt(g.before*(g.scale||1))+' → '+fmt(g.after*(g.scale||1),g.unit?' '+g.unit:'')+'</dd>').join('')+'</dl>';
      const notes=[r.reason,...(Array.isArray(r.notes)?r.notes:[])].filter(Boolean);
      if(notes.length)html+='<ul>'+notes.map(n=>'<li>'+esc(text(n))+'</li>').join('')+'</ul>';
    }
    html+='<p><a href="/AUTOTUNE.md" target="_blank" rel="noopener">計算法・評価条件</a></p></article>';
    host.innerHTML=html;
  }
  function explanation() {
    const host=$('parameter-explanation'); if (!host) return;
    const guide=$('control-guide-content'),showGuide=selected==='algorithm';
    host.hidden=showGuide&&Boolean(guide);
    if(guide)guide.hidden=!showGuide;
    if($('duty-conversion'))$('duty-conversion').innerHTML=dutyConversion();
    if(showGuide&&guide)return;
    if(selected==='autotune'){autotuneExplanation(host);return;}
    if(selected==='duty_response_gain'){host.innerHTML='<article class="ph-card"><div class="ph-title"><h2>Duty反映倍率</h2></div>'+dutyConversion()+(['c07_r03','c07_r04'].includes(config.algorithm)?'':'<p class="ph-boundary">'+esc(help.duty_response_gain.limit)+'</p>')+'</article>';return;}
    let h=help[selected];const m=meta(selected);
    if(h&&config.algorithm==='c07_r03'&&r03Help[selected])h={...h,...r03Help[selected]};
    if(h&&config.algorithm==='c07_r04'&&r04Help[selected])h={...h,...r04Help[selected]};
    if(h&&config.algorithm==='custom'){
      h={...h};
      if(selected==='mppt_method'){h.meaning='カスタム構成で、MPPへ向かう電圧の上下方向をP&OまたはIncCondで判断します。';h.effect='方向判断の結果を、固定刻みの直接Duty操作または電圧目標の変更へつなぎます。回路式の枝でもこの共通MPPTを使い、「回路式からDutyを計算」単独方式の可変刻みP&Oは使いません。電圧ステップ実験ではMPPT判断を止めます。';}
      if(selected==='mppt_step_v'){h.meaning='カスタム構成で、MPPT判断のたびに電圧目標を動かす固定刻みです。';h.effect='P&O/IncCondの上下判断をこの幅へ変換します。回路式の枝も同じ固定刻みで、「回路式からDutyを計算」単独方式の傾斜に比例する可変刻み・最小電圧差ガードとは別です。';h.limit='直接Duty構成はこの値ではなく、直接MPPTのDuty刻みを使います。';}
      if(['voltage_kp','voltage_ki'].includes(selected)){
        const output=config.custom_topology==='voltage_current'?'L1電流目標Iref':'Duty';
        h.meaning='カスタム構成で、PV電圧誤差から'+output+'を作る'+(selected==='voltage_kp'?'比例':'積分')+'係数です。';
        h.effect='今の構成の出力は'+output+'です。電圧→Dutyと電圧→電流で単位が変わるため、構成変更時には対応する開始ゲインが読み込まれます。';
        h.equation=selected==='voltage_kp'?output+'の比例成分 = Kp_v·(測定Vpv−Vref)':output+'の積分増分 = Ki_v·(測定Vpv−Vref)·Δt';
      }
      if(selected==='voltage_period_us'){h.meaning='カスタム構成の電圧補正がDutyまたはL1電流目標を作り直す予定間隔です。';}
      if(selected==='voltage_kd'){const output=config.custom_topology==='voltage_current'?'L1電流目標Iref':'Duty';h.meaning='現在のカスタム構成で、測定PV電圧の変化速度から'+output+'を補正する係数です。';h.equation=output+'のD成分 = Kd_v × 平滑化した測定PV電圧の変化速度';}
      if(selected==='current_period_us'){h.meaning='カスタム構成のL1電流補正、または回路式の計算がDutyを作り直す予定間隔です。';}
      if(['current_kp','current_ki'].includes(selected)){h.meaning=h.meaning.replace('電圧・電流PI系','カスタム');}
      if(['model_voltage_gain','model_current_gain','model_filter_ms','model_delay_us'].includes(selected)){h.meaning=h.meaning.replace('「回路式からDutyを計算」のBuck適応で','カスタムの回路式で').replace('「回路式からDutyを計算」の回路式で','カスタムの回路式で').replace('「回路式からDutyを計算」で','カスタムの回路式で');}
      if(selected==='voltage_deadband_v'){h.meaning='直接Duty構成の電圧ステップ実験で、Dutyの一歩操作を止める電圧誤差の帯です。';h.effect='許容帯の外では電圧誤差の向きに応じた一歩操作を行います。通常の局所MPPTや、結果の整定判定幅とは別です。';}
    }
    if(!h) {host.innerHTML='<div class="ph-card"><h2>説明が未登録の項目</h2><p>'+esc(selected)+'</p><p>説明と回路対応を確認できていません。この項目を他の部品と推測で対応させません。</p></div>'; return;}
    const available = h.parts.filter(part => document.querySelector('#circuit-schematic [data-part="'+part+'"]'));
    host.innerHTML = '<article class="ph-card"><div class="ph-title"><h2>'+esc(m.title)+'</h2>'+(m.value!==undefined?'<span class="ph-value">'+esc(m.value)+' <small>'+esc(m.unit)+'</small></span>':'')+'</div><p class="ph-meaning">'+esc(h.meaning)+'</p><h3>変更の効果</h3><p>'+esc(h.effect)+'</p>'+(h.equation?'<p class="ph-equation">'+esc(h.equation)+'</p>':'')+(h.limit?'<p class="ph-boundary">'+esc(h.limit)+'</p>':'')+'<h3>対応する箇所</h3><p>'+(available.length?available.map(x=>'<span class="ph-part-tag">'+esc(names[x]||x)+'</span>').join(' '):h.parts.length?'現在の簡略回路では、この部品・機能を省略しています。':'回路部品との対応なし')+'</p>'+(m.hint?'<details class="ph-key"><summary>補足</summary><p>'+esc(m.hint)+'</p></details>':'')+'</article>';
  }
  const line=(x1,y1,x2,y2,klass='wire')=>'<path class="'+klass+'" d="M'+x1+' '+y1+'H'+x2+'V'+y2+'"/>';
  const text=(x,y,s,klass='part-label',anchor='middle')=>'<text class="'+klass+'" x="'+x+'" y="'+y+'" text-anchor="'+anchor+'">'+esc(s)+'</text>';
  function part(id, key, inner, title) {return '<g class="sc-part" data-part="'+id+'" data-help-key="'+key+'" tabindex="0" role="button" aria-label="'+esc(title||names[id])+'の説明"><title>'+esc(title||names[id])+'</title>'+inner+'</g>';}
  function resistor(id,key,x,y,w,label,val='') {return part(id,key,line(x,y,x+8,y)+'<rect class="component" x="'+(x+8)+'" y="'+(y-8)+'" width="'+(w-16)+'" height="16" rx="1"/>'+line(x+w-8,y,x+w,y)+text(x+w/2,y-18,label)+text(x+w/2,y+30,val,'part-value'));}
  function coil(id,key,x,y,w,label,val='') {const step=(w-12)/4;let path='M'+x+' '+y+'h6';for(let i=0;i<4;i++)path+='a'+step/2+' 11 0 0 1 '+step+' 0';path+='h6';return part(id,key,'<path class="component" d="'+path+'"/>'+text(x+w/2,y-25,label)+text(x+w/2,y+30,val,'part-value'));}
  function cap(id,key,x,y,bottom,label,val='') {return part(id,key,line(x,y,x,y+54)+'<rect class="component" x="'+(x-6)+'" y="'+(y+54)+'" width="12" height="20"/>'+line(x,y+74,x,y+90)+'<path class="component" d="M'+(x-14)+' '+(y+90)+'h28 M'+(x-14)+' '+(y+101)+'h28"/>'+line(x,y+101,x,bottom)+text(x+21,y+67,'ESR','part-value','start')+text(x+21,y+94,label,'part-label','start')+text(x+21,y+114,val,'part-value','start'));}
  function node(x,y,label,above=0) {return '<circle class="junction" cx="'+x+'" cy="'+y+'" r="3.5"/>'+text(x,y-18-above,label,'node-label');}
  function arrow(x1,y,x2,label) {return '<path class="current-arrow" marker-end="url(#ph-current-arrow)" d="M'+x1+' '+y+'H'+x2+'"/>'+text((x1+x2)/2,y-8,label,'current-label');}
  function sensor(id,key,x,label,caption) {return part(id,key,'<rect class="signal-box" x="'+x+'" y="438" width="270" height="64" rx="7"/>'+text(x+135,462,label,'signal-title')+text(x+135,485,caption,'signal-small'));}
  function schematic() {
    const host=$('circuit-schematic');if(!host)return;
    const c=isC07(), y=172, ground=350;
    let s='<svg class="ph-svg" viewBox="0 0 1440 675" role="img" aria-labelledby="ph-svg-title ph-svg-desc"><title id="ph-svg-title">'+(c?'c07由来':'簡略Buck')+'の正常ON等価回路</title><desc id="ph-svg-desc">左からパネル、入力経路、上側スイッチ、L1、出力経路、電池。各コンデンサは下の共通GNDへ接続します。ダイオードの正電流はGNDからスイッチ節点へ流れます。下部の点線は測定・演算の信号です。</desc><defs><marker id="ph-current-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#087f8c"/></marker><marker id="ph-signal-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#8669a4"/></marker></defs>';
    s+=text(25,32,c?'c07：正常ONの主回路を分離した等価回路':'簡略Buck：PV端子とVINを同じ節点に置く','diagram-title','start');
    s+=text(25,59,'実線：電力回路　点線：測定・演算の信号　電圧はGND基準（上側が＋）','diagram-subtitle','start');
    s+=line(65,ground,1355,ground)+text(45,ground+24,'GND / 共通戻り','node-label','start');
    s+=part('pv','pv_voc',line(65,y,65,213)+'<circle class="component source" cx="65" cy="245" r="32"/>'+text(65,228,'＋','part-value')+text(65,250,'PV')+text(65,270,'−','part-value')+line(65,277,65,ground), 'PVパネル');
    s+=line(65,y,125,y)+node(80,y,'PV_RAW',28)+arrow(75,104,192,'Iパネル →');
    if(c){
      s+=resistor('f2','pv_fuse_ohm',125,y,58,'F2',value('pv_fuse_ohm','Ω'))+line(183,y,250,y)+node(215,y,'PV_FUSED',28);
      s+=cap('cpv','pv_node_c_uf',215,y,ground,'Cpv',value('pv_node_c_uf','µF'));
      s+=coil('l2','input_l_uh',250,y,68,'L2',value('input_l_uh','µH'))+line(318,y,329,y);
      s+=resistor('rl2','l2_dcr_ohm',329,y,51,'DCR',value('l2_dcr_ohm','Ω'))+line(380,y,389,y);
      s+=resistor('r27','input_shunt_ohm',389,y,51,'R27',value('input_shunt_ohm','Ω'))+line(440,y,449,y);
      s+=resistor('rin','input_protection_ohm',449,y,69,'入力保護',value('input_protection_ohm','Ω'))+line(518,y,617,y)+node(550,y,'VIN',28);
      s+=cap('cin','cin_uf',550,y,ground,'Cin',value('cin_uf','µF'))+arrow(255,104,515,'IL2 →（R27で測定）');
    } else {
      s+=line(125,y,617,y)+node(370,y,'PV_RAW = VIN',28)+cap('cin','cin_uf',370,y,ground,'Cin',value('cin_uf','µF'));
    }
    s+=part('switch','r_switch_ohm',line(617,y,635,y)+'<circle class="component" cx="635" cy="172" r="3"/><circle class="component" cx="677" cy="172" r="3"/><path class="component" d="M635 172L671 146"/>'+line(677,y,714,y)+text(655,125,'上側スイッチ')+text(655,207,'Ron '+value('r_switch_ohm','Ω'),'part-value'));
    s+=node(714,y,'SW',28)+line(714,y,750,y);
    s+=part('diode','diode_vf',line(714,y,714,245)+'<path class="component" d="M700 245h28 M714 245L700 274H728Z"/>'+line(714,274,714,ground)+text(734,268,'還流D','part-label','start')+text(734,289,value('diode_vf','V'),'part-value','start')+arrow(688,324,688,'')+'<path class="current-arrow" marker-end="url(#ph-current-arrow)" d="M683 321V281"/>'+text(669,307,'↑','current-label'));
    s+=coil('l1','l_uh',750,y,70,'L1',value('l_uh','µH'))+line(820,y,839,y)+resistor('rl','r_l_ohm',839,y,58,'RL1',value('r_l_ohm','Ω'))+line(897,y,969,y)+node(930,y,'VOUT',28)+cap('cout','cout_uf',930,y,ground,'Cout',value('cout_uf','µF'))+arrow(755,104,906,'IL →');
    if(c){
      s+=resistor('rout','out_protection_ohm',969,y,62,'出力保護',value('out_protection_ohm','Ω'))+line(1031,y,1090,y)+node(1060,y,'BAT_PLUS',28)+cap('cplus','bat_node_c_uf',1060,y,ground,'Cplus',value('bat_node_c_uf','µF'));
      s+=resistor('f3','battery_fuse_ohm',1090,y,56,'F3',value('battery_fuse_ohm','Ω'))+line(1146,y,1230,y)+node(1180,y,'BAT_RAW',28);
      s+=part('raux','bat_aux_r_ohm',line(1180,y,1180,216)+'<rect class="component" x="1174" y="216" width="12" height="24"/>'+text(1200,226,'F4 + F1','part-value','start'));
      s+=cap('caux','bat_aux_c_uf',1180,240,ground,'Caux',value('bat_aux_c_uf','µF'));
      s+=resistor('rcell','r_battery_ohm',1230,y,64,'Rcell',Number.isFinite(Number(config.r_battery_ohm))?Number(config.r_battery_ohm-config.out_protection_ohm-config.battery_fuse_ohm).toPrecision(3)+'Ω':'')+line(1294,y,1355,y);
    }else{s+=line(969,y,1190,y)+resistor('rcell','r_battery_ohm',1190,y,104,'電池側R',value('r_battery_ohm','Ω'))+line(1294,y,1355,y);}
    s+=part('battery','v_battery',line(1355,y,1355,229)+'<path class="component" d="M1333 229h44 M1342 241h26 M1333 260h44 M1342 272h26"/>'+text(1384,235,'＋','part-label','start')+text(1384,275,'−','part-label','start')+line(1355,272,1355,ground)+text(1355,308,value('v_battery','V'),'part-label'))+arrow(1250,104,1360,'I電池 →');
    s+=text(25,405,'真値 → センサ応答 → ADCコード → 制御器が使う測定値','signal-heading','start');
    s+=sensor('vsense','sense_tau_us',25,c?'V(PV_FUSED) → 電圧RC':'V(PV_RAW) → 電圧RC',c?'取得①：PV電圧（PV_RAW真値とは区別）':'取得①：PV電圧');
    s+=sensor('isense','current_sense_tau_us',380,c?'IL → 電流RC':'IL（電流RC省略）','取得②：主コイル電流');
    s+=sensor('vosense','sense_tau_us',735,c?'V(VOUT) → 電圧RC':'V(VOUT)（独立RC省略）','取得③：出力端子電圧');
    s+=sensor('ipsense','current_sense_tau_us',1090,c?'IL2 → 電流RC':'Iパネル（電流RC省略）','取得④：入力電流');
    const taps=c?[[215,160],[800,515],[930,870],[414,1225]]:[[370,160],[800,515],[930,870],[125,1225]];
    taps.forEach(([x,end],i)=>{s+='<path class="signal-wire" d="M'+x+' '+(y+5)+'V'+(379+i*10)+'H'+end+'V438" marker-end="url(#ph-signal-arrow)"/>';});
    s+='<path class="signal-wire" d="M160 502V526H1225V502 M515 502V526 M870 502V526 M540 526V558" marker-end="url(#ph-signal-arrow)"/>';
    s+=part('adc','adc_bits','<rect class="signal-box" x="370" y="558" width="270" height="64" rx="7"/>'+text(505,583,'ADC：保持 → 量子化 → 到着','signal-title')+text(505,607,'4値は別時刻（間隔0なら同時）','signal-small'));
    s+='<path class="signal-wire" d="M640 591H726" marker-end="url(#ph-signal-arrow)"/>';
    s+=part('controller','algorithm','<rect class="signal-box" x="726" y="558" width="250" height="64" rx="7"/>'+text(851,583,'選択した制御の計算','signal-title')+text(851,607,'測定・履歴 → 目標/方向 → Duty','signal-small'));
    s+='<path class="signal-wire" d="M976 591H1061" marker-end="url(#ph-signal-arrow)"/>';
    s+=part('pwm','pwm_khz','<rect class="signal-box" x="1061" y="558" width="294" height="64" rx="7"/>'+text(1208,583,'PWM周期境界でDutyを反映','signal-title')+text(1208,607,'上側スイッチのON時間を変更','signal-small'));
    s+='</svg>';
    host.innerHTML='<div class="ph-schematic-heading"><div><p class="ph-schematic-selection" aria-live="polite"></p></div><div class="ph-zoom"><button type="button" data-ph-zoom="reset" aria-label="回路図の全体を表示">全体</button><button type="button" data-ph-zoom="out" aria-label="回路図を縮小">−</button><button type="button" data-ph-zoom="in" aria-label="回路図を拡大">＋</button></div></div><div class="ph-selection-parts" aria-label="選択パラメータに対応する箇所"></div><div class="ph-diagram-scroll">'+s+'</div><details class="ph-circuit-notes"><summary>回路の注記</summary><p class="ph-node-note">'+(c?'PV_RAWはパネル端子の真値。ADCのPV電圧はPV_FUSEDのRC出力です。VINはL2と直列抵抗の後のBuck入力で、独立したADCチャネルはありません。IL2とパネル電流はCpv・分圧負荷への分岐分だけ異なります。':'簡略BuckはPV_RAWとVINを同じ節点に置きます。L2・入力保護・出力保護後の別容量を省略しています。')+'</p><p class="ph-node-note">出力電流の制御用推定値はILです。Coutや電池側容量に分岐するため、実際の電池電流と常に一致するわけではありません。モデルMPPは評価専用で、ADCや制御器には入力しません。</p><p class="ph-node-note">簡略等価回路です。分圧の静的負荷は図では省略しています。実機の配線図・起動/保護回路ではありません。</p></details>';
    host.querySelector('.ph-svg').style.width=zoom?(1440*zoom)+'px':'100%';
    host.querySelector('[data-ph-zoom=reset]').setAttribute('aria-pressed',String(zoom===0));
  }
  function highlight() {
    const parts=help[selected]?.parts||[];
    const host=$('circuit-schematic'),present=[];
    document.querySelectorAll('#circuit-schematic [data-part]').forEach(el=>{
      const active=parts.includes(el.dataset.part);
      el.classList.toggle('ph-active',active);el.setAttribute('aria-pressed',String(active));
      if(active)present.push(el.dataset.part);
    });
    host?.classList.toggle('ph-has-selection',present.length>0);
    document.querySelectorAll('#settings-pane .field[data-key]').forEach(el=>el.classList.toggle('ph-selected-field',el.dataset.key===selected));
    document.querySelectorAll('#settings-pane [data-ph-help]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.phHelp===selected)));
    const line=host?.querySelector('.ph-schematic-selection');
    if(line){const m=meta(selected);line.textContent=m.title+(m.value!==undefined?'：'+m.value+' '+m.unit:'')+(!present.length&&parts.length?'（回路図では省略）':'');}
    const list=host?.querySelector('.ph-selection-parts');
    if(list){list.hidden=!present.length;list.innerHTML=present.map((id,i)=>'<span class="ph-selection-chip"><b aria-hidden="true">'+(i+1)+'</b><span>'+esc(names[id]||id)+'</span></span>').join('');}
    queueSelectionFrames();
  }
  let selectionFramePending=false;
  function queueSelectionFrames() {
    if(selectionFramePending)return;selectionFramePending=true;
    requestAnimationFrame(()=>{selectionFramePending=false;drawSelectionFrames();});
  }
  function drawSelectionFrames() {
    const host=$('circuit-schematic'),svg=host?.querySelector('svg');if(!svg)return;
    svg.querySelectorAll('.ph-selection-underlay,.ph-selection-overlay').forEach(el=>el.remove());
    const selectedParts=[...svg.querySelectorAll('.sc-part.ph-active')];
    const width=svg.getBoundingClientRect().width;
    if(!selectedParts.length||width<=0||host.closest('[hidden]'))return;
    const ns='http://www.w3.org/2000/svg',scale=width/1440;
    const create=(name,attrs)=>{const el=document.createElementNS(ns,name);for(const [key,v] of Object.entries(attrs))el.setAttribute(key,String(v));return el;};
    const under=create('g',{class:'ph-selection-underlay','aria-hidden':'true'}),over=create('g',{class:'ph-selection-overlay','aria-hidden':'true'});
    // Frames surround electrical symbols, not their long connecting wires.
    // Non-scaling borders and screen-sized numbers remain visible in fit view.
    selectedParts.forEach((part,index)=>{
      const bounds=[...part.querySelectorAll('.component,.signal-box')].map(el=>el.getBBox()).filter(b=>b.width>0||b.height>0);
      if(!bounds.length)return;
      const left=Math.min(...bounds.map(b=>b.x)),right=Math.max(...bounds.map(b=>b.x+b.width));
      const top=Math.min(...bounds.map(b=>b.y)),bottom=Math.max(...bounds.map(b=>b.y+b.height));
      const pad=12,w=Math.max(56,right-left+pad*2),h=Math.max(46,bottom-top+pad*2);
      const x=(left+right-w)/2,y=(top+bottom-h)/2;
      const attrs={x,y,width:w,height:h,rx:9,'vector-effect':'non-scaling-stroke'};
      under.append(create('rect',{...attrs,class:'ph-selection-fill'}));
      over.append(create('rect',{...attrs,class:'ph-selection-frame'}));
      const r=10/scale,cx=Math.max(r+5,x),cy=Math.max(r+5,y);
      over.append(create('circle',{class:'ph-selection-number-disc',cx,cy,r,'vector-effect':'non-scaling-stroke'}));
      const number=create('text',{class:'ph-selection-number',x:cx,y:cy,'font-size':12/scale,'text-anchor':'middle','dominant-baseline':'central'});number.textContent=String(index+1);over.append(number);
    });
    const defs=svg.querySelector('defs');if(defs)defs.after(under);else svg.prepend(under);
    svg.append(over);
  }
  function focusPart() {
    if(!zoom)return;
    const host=$('circuit-schematic'),scroll=host?.querySelector('.ph-diagram-scroll'),part=host?.querySelector('.ph-active');
    if(!scroll||!part||!scroll.clientWidth||host.closest('[hidden]'))return;
    const a=part.getBoundingClientRect(),b=scroll.getBoundingClientRect(),margin=28;
    let left=scroll.scrollLeft,top=scroll.scrollTop;
    if(a.left<b.left+margin||a.right>b.right-margin)left+=((a.left+a.right)-(b.left+b.right))/2;
    if(a.top<b.top+margin||a.bottom>b.bottom-margin)top+=((a.top+a.bottom)-(b.top+b.bottom))/2;
    scroll.scrollTo({left:Math.max(0,left),top:Math.max(0,top),behavior:'auto'});
  }
  function select(key) {if(!key)return;selected=String(key);explanation();highlight();focusPart();}
  function installButtons() {
    const pane=$('settings-pane');if(!pane)return;
    pane.querySelectorAll('.field[data-key]').forEach(box=>{
      box.dataset.field=box.dataset.key;
      const label=box.querySelector('.field-label');if(!label||label.parentElement.querySelector('[data-ph-help]'))return;
      const button=document.createElement('button');button.type='button';button.className='ph-help-button';button.textContent='?';button.dataset.phHelp=box.dataset.key;button.setAttribute('aria-label',label.textContent+'の説明');button.setAttribute('aria-controls','parameter-explanation circuit-schematic');label.after(button);
    });
    for(const [id,key] of Object.entries(selectorKeys)){
      const input=$(id),label=pane.querySelector('label[for="'+id+'"]');if(!input||!label||label.querySelector('[data-ph-help]'))continue;
      const b=document.createElement('button');b.type='button';b.className='ph-help-button';b.textContent='?';b.dataset.phHelp=key;b.setAttribute('aria-label',help[key].title+'の説明');b.setAttribute('aria-controls','parameter-explanation circuit-schematic');label.append(' ',b);
    }
  }
  function update(nextConfig,nextResult) {
    if(nextConfig)config={...nextConfig};if(nextResult!==undefined)result=nextResult;
    installButtons();
    const current=isC07()?'c07':'simple';
    // Rebuild also when component values change, but do not move either pane or change tabs.
    const stamp=current+'|'+Object.keys(config).filter(k=>help[k]?.parts.some(p=>!['controller','adc','pwm'].includes(p))).map(k=>k+':'+config[k]).join('|');
    if(stamp!==model||!$('circuit-schematic')?.querySelector('svg')){const sc=$('circuit-schematic')?.querySelector('.ph-diagram-scroll'),left=sc?.scrollLeft||0;schematic();model=stamp;const fresh=$('circuit-schematic')?.querySelector('.ph-diagram-scroll');if(fresh)fresh.scrollLeft=left;}
    explanation();highlight();
  }
  function keyFrom(target) {
    if(!(target instanceof Element))return null;
    const explicit=target.closest('[data-ph-help],[data-help-key]');if(explicit)return explicit.dataset.phHelp||explicit.dataset.helpKey;
    const box=target.closest('.field[data-key]');if(box)return box.dataset.key;
    if(target.closest('[data-mode]'))return 'mode';
    const label=target.closest('label');
    return selectorKeys[target.id] || selectorKeys[label?.htmlFor] || null;
  }
  function init() {
    const pane=$('settings-pane');if(pane){
      const follow=event=>{const key=keyFrom(event.target);if(key){if(event.target.closest('[data-ph-help]'))event.preventDefault();config=window.PVPIDLab?.getConfig?.()||config;select(key);}};
      pane.addEventListener('focusin',follow);pane.addEventListener('click',follow);
      pane.addEventListener('change',()=>queueMicrotask(()=>update(window.PVPIDLab?.getConfig?.()||config,result)));
      pane.addEventListener('input',event=>{const key=keyFrom(event.target);if(key){config=window.PVPIDLab?.getConfig?.()||config;selected=key;explanation();highlight();}});
    }
    $('circuit-schematic')?.addEventListener('click',event=>{
      const z=event.target.closest('[data-ph-zoom]');if(z){const fit=Math.max(.1,($('circuit-schematic').clientWidth||600)/1440);zoom=z.dataset.phZoom==='reset'?0:Math.min(2,Math.max(fit,(zoom||fit)+(z.dataset.phZoom==='in'?.2:-.2)));if(zoom<=fit)zoom=0;schematic();highlight();focusPart();return;}
      const p=event.target.closest('[data-help-key]');if(p)select(p.dataset.helpKey);
    });
    $('circuit-schematic')?.addEventListener('keydown',event=>{const p=event.target.closest('[data-help-key]');if(p&&['Enter',' '].includes(event.key)){event.preventDefault();select(p.dataset.helpKey);}});
    $('result-tab-schematic')?.addEventListener('click',()=>requestAnimationFrame(()=>{drawSelectionFrames();focusPart();}));
    window.addEventListener('lab:layout',queueSelectionFrames);
    window.addEventListener('lab:autotune',()=>{if(selected==='autotune'){config=window.PVPIDLab?.getConfig?.()||config;explanation();}});
    window.addEventListener('lab:tab',event=>{
      if(event.detail?.kind!=='setting')return;
      if(event.detail.key==='control')select('algorithm');
      else if(event.detail.key==='circuit-set')select('preset');
    });
    if($('circuit-schematic'))new ResizeObserver(queueSelectionFrames).observe($('circuit-schematic'));
    update(window.PVPIDLab?.getConfig?.()||{},window.PVPIDLab?.getResult?.());
    // Fields arrive after /api/config. Observe only insertions; do not alter values or control listeners.
    if(pane){let queued=false;const observer=new MutationObserver(records=>{if(queued||!records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&(n.matches?.('.field,select')||n.querySelector?.('.field,select')))))return;queued=true;queueMicrotask(()=>{queued=false;update(window.PVPIDLab?.getConfig?.()||config,result);});});observer.observe(pane,{subtree:true,childList:true});}
  }
  window.PVLabHelp={update,select,getSelected:()=>selected,getCoverage:()=>({documented:Object.keys(help),undocumented:[...document.querySelectorAll('#settings-pane .field[data-key]')].map(e=>e.dataset.key).filter(k=>!help[k])})};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
