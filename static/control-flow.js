/* Signal paths for this Lab's selected configuration, not firmware execution order. */
(() => {
  'use strict';
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function nodes(c) {
    const id=c.algorithm||'baseline',irr=c.experiment==='irradiance',custom=id==='custom';
    const direct=id==='libresolar'||id==='fugu'||(custom&&c.custom_topology==='direct_duty');
    const model=id==='opensec'||(custom&&c.custom_law==='model'&&!direct);
    const cascade=['ti','plexim'].includes(id)||(custom&&c.custom_topology==='voltage_current');
    const result=[];
    const add=(title,detail='',signal='',kind='process')=>result.push({title,detail,signal,kind});
    if(['c07_r03','c07_r04'].includes(id)){
      const mode=id==='c07_r04'?'PID':'PI';
      if(irr)add('IncCondで電圧目標を探す','整定後のPV電圧・入力L2電流を平均。裏側で計算','PV電圧目標','search');
      else add('指定したPV電圧目標','この実験ではMPPT判断を停止','PV電圧目標','reference');
      add('PV電圧'+mode+'で補正',id==='c07_r04'?'PV_FUSEDを使用。Pは目標の重み付き、Iは目標誤差'+(mode==='PID'?'、Dは測定の変化':''):'平滑化したPV_FUSED電圧と目標を比較','L1電流の要求');
      add('充電電圧・電流の制限を確認','CV PI・入力電流・入力余裕'+(Number(c.c07_current_rise_a_s)>0?'・目標の上昇速度':'（目標の上昇速度制限なし）'),'制限後のL1電流目標');
      add('L1電流PIで補正','測定L1電流と目標を比較','Duty補正');
      add('VIN・VOUTの先回り値へ加算','Duty上限。最小Duty未満・電流要求ゼロはOFF','Duty');
      add('PWM → 回路',Number(c.c07_pwm_packet_cycles)>0?c.c07_pwm_packet_cycles+'パルスの有限パケット模型':'連続PWMの診断模型','','plant');
      return result;
    }
    if (direct) {
      if (irr) {
        if (id==='libresolar') add('P&Oで方向を決める','出力電力を比較','増減方向','search');
        else if (id==='fugu') add('P&Oで方向・速度を決める','出力電力を区間平均','操作速度','search');
        else {
          add(c.mppt_method==='po'?'P&Oで方向を決める':'IncCondで方向を決める','PV電圧・入力電流を使う','電圧の上下','search');
          add('BuckのDuty方向へ変換','','増減方向');
        }
      } else add('指定電圧と測定電圧を比較','PV電圧のずれを使う',id==='fugu'?'操作速度':'増減方向','target');
      if (id==='fugu') {
        add('制限と速度を比較','通常速度 × 倍率とPD制限を比較','選ばれた速度');
        add('速度 × 経過時間を積算','整数カウント分を反映','Duty');
      } else {
        add('制限を優先してDutyを変更','通常は一歩分 × Duty反映倍率','Duty');
        add('次の判断まで保持','','Duty');
      }
    } else {
      if (model) add('測定を補正・推定','時刻差をそろえ、電圧・電流を平滑化','推定した電圧・電流');
      if (irr) {
        const method=id==='ti'?'IncCond':id==='opensec'?'可変幅P&O':
          id==='plexim'?'可変幅'+(c.mppt_method==='po'?'P&O':'IncCond'):
          custom?(c.mppt_method==='po'?'P&O':'IncCond'):'P&O';
        add(method+'で目標を探す',model?'推定PV電圧・入力電流を使う':'PV電圧・入力電流を使う','PV電圧目標','search');
      } else if (!model) add('指定したPV電圧目標','','PV電圧目標','reference');
      if (model) {
        add('Cの式で電流目標を計算',irr?'目標と推定PV電圧を比較':'指定目標と推定PV電圧を比較','L1電流目標');
        add('Lの式でDutyを計算','測定・予測したL1電流と比較','Duty補正');
      } else {
        const vm=custom?(c.voltage_mode||'PI'):id==='baseline'?(c.mode||'PI'):'PI';
        add('電圧'+vm+'で補正','測定PV電圧と目標を比較',cascade?'L1電流目標':'Duty補正');
        if (cascade) add('電流'+(custom?(c.current_mode||'PI'):'PI')+'で補正','測定L1電流と目標を比較','Duty補正');
      }
      add('Dutyへ反映','基準成分 ＋ 補正 × 倍率・上下限','Duty');
    }
    add('PWM → 回路','','','plant');
    return result;
  }
  function render(c) {
    const path=nodes(c),reference=path[0]?.kind==='reference'?path.shift():null;
    const block=n=>`<div class="flow-node flow-${n.kind}"><strong>${escape(n.title)}</strong>${n.detail?`<span>${escape(n.detail)}</span>`:''}</div>${n.signal?`<div class="flow-signal">${escape(n.signal)}<span aria-hidden="true">↓</span></div>`:''}`;
    // A specified setpoint is external: measurement feeds the comparison, not the setpoint.
    const caption=['c07_r03','c07_r04'].includes(c.algorithm)?'図は信号の流れです。MPPTの裏側計算より高速制御を優先します。高速制御の中では、必要な回にPV電圧補正・制限を更新してからL1電流PIを計算します。MPPTは空き時間に別計算し、完成した目標を次の有効な高速制御回で受け取ります。':'回路の電圧・電流を再測定して各段へ帰還します。図は信号の流れで、各段はそれぞれの設定周期で動きます。';
    return `<figure class="control-flow" aria-label="制御の信号の流れ">${reference?`<div class="flow-setpoint">${block(reference)}</div>`:''}<div class="flow-cycle"><div class="flow-loop" aria-hidden="true"><span>再測定</span></div><ol>${path.map(n=>`<li>${block(n)}</li>`).join('')}</ol></div><figcaption class="flow-accessible">${escape(caption)}</figcaption></figure>`;
  }
  window.PVControlFlow={render};
})();
