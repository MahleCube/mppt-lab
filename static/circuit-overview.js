/* Compact overview of the current Lab plant, not the source board's full schematic. */
(() => {
  'use strict';
  const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=value=>Number.isFinite(Number(value))?Number(value).toLocaleString('ja-JP',{maximumSignificantDigits:5}):'—';
  const value=(c,key,unit)=>`<span data-circuit-value="${key}">${esc(number(c[key]))} ${unit}</span>`;
  const arrow='<div class="circuit-power-arrow" aria-hidden="true">↓</div>';
  const capacitorSymbol='<svg class="circuit-cap-symbol" viewBox="0 0 24 36" aria-hidden="true"><path d="M12 1v9M3 10h18M3 15h18M12 15v11M3 26h18M6 30h12M9 34h6"/></svg>';
  function render(c) {
    const extended=c.plant_mode==='c07';
    const block=(key,title,detail,kind='')=>`<div class="circuit-stage ${kind}" data-circuit-stage="${key}"><strong>${title}</strong>${detail?`<span class="circuit-stage-value">${detail}</span>`:''}</div>`;
    const capacitor=(key,name,node,variable=false)=>`<div class="circuit-cap-branch" data-circuit-branch="${key}" aria-label="${node}からGNDへの並列コンデンサ"><div class="circuit-cap-card">${capacitorSymbol}<div><strong>${name}${variable?' 基準':''}</strong>${value(c,key,'µF')}<span class="circuit-ground">GND</span></div></div></div>`;
    return `<figure class="circuit-overview" data-plant-mode="${extended?'c07':'simple'}" aria-label="選択中の回路モデルの概念図">
      ${block('pv','太陽光パネル',`Vmp ${value(c,'pv_vmp','V')} · Imp ${value(c,'pv_imp','A')}`,'circuit-pv')}
      ${arrow}
      ${extended?block('input','入力保護・L2',`L2 ${value(c,'input_l_uh','µH')}`):''}
      ${capacitor('cin_uf','Cin','Buck入力')}
      ${block('buck','降圧回路（Buck）',`PWM ${value(c,'pwm_khz','kHz')}<br>L1${extended&&c.nonlinear_l>=.5?' 基準':''} ${value(c,'l_uh','µH')}`,'circuit-buck')}
      ${capacitor('cout_uf','Cout','Buck出力',extended&&c.nonlinear_c>=.5)}
      ${extended?block('output','出力保護','MOS・ヒューズ')+arrow:''}
      ${block('battery','バッテリー',`開放電圧 ${value(c,'v_battery','V')}`,'circuit-battery')}
      <figcaption>${extended?'正常ON時の回路構成':'シミュレーションの回路構成'}</figcaption>
    </figure>`;
  }
  window.PVCircuitOverview={render};
})();
