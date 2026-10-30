/* Explicit initial-point calculation; never a live MPP input to the controller. */
(() => {
  'use strict';
  const label='日射量からMPP電圧を計算';
  function attach({field,getConfig,getRevision,onApply}) {
    const actions=document.createElement('div');actions.className='start-voltage-actions';
    const button=document.createElement('button');button.id='start-voltage-from-irradiance';
    button.type='button';button.textContent=label;button.dataset.helpKey='v_start';
    const message=document.createElement('p');message.id='start-voltage-message';
    message.className='start-voltage-message';message.setAttribute('role','status');message.hidden=true;
    actions.append(button);field.append(actions,message);
    let generation=0,request=null;
    function invalidate() {
      generation++;request?.abort();request=null;
      button.disabled=false;button.textContent=label;message.hidden=true;message.textContent='';
    }
    button.addEventListener('click',async()=>{
      invalidate();const token=++generation,revision=getRevision(),snapshot=getConfig();
      request=new AbortController();button.disabled=true;button.textContent='計算中…';
      try {
        const response=await fetch('/api/start-mpp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(snapshot),signal:request.signal});
        const result=await response.json();
        if(token!==generation||revision!==getRevision())return;
        if(!response.ok)throw new Error(result.error||'MPP電圧を計算できませんでした。');
        const v=result.v_start;
        if(!Number.isFinite(v))throw new Error('MPP電圧の計算結果が不正です。');
        const voltage=v.toLocaleString('ja-JP',{maximumFractionDigits:3})+' V';
        if(!result.within_start_voltage_range)throw new Error('MPP電圧 '+voltage+' は開始電圧の設定範囲外です。');
        if(result.initialization?.checked&&result.initialization.feasible===false)
          throw new Error('MPP電圧 '+voltage+' はこの回路の開始条件では使えません。'+(result.initialization.reason||''));
        request=null;button.disabled=false;button.textContent=label;
        if(getConfig().v_start!==v)onApply(v);
      } catch(error) {
        if(token===generation&&error.name!=='AbortError'){
          message.textContent=error.message||'MPP電圧を計算できませんでした。';message.hidden=false;
        }
      } finally {
        if(token===generation){request=null;button.disabled=false;button.textContent=label;}
      }
    });
    return {invalidate};
  }
  window.PVStartVoltage={attach};
})();
