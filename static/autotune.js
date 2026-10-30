(() => {
  'use strict';
  const profiles={
    balanced:{label:'バランス',description:'追従の速さと揺れの両方を評価します。'},
    speed:{label:'速度重視',description:'変化後に目標へ近づく速さを優先します。'},
    gentle:{label:'行き過ぎを抑える',description:'目標を通り越す量を重く評価します。'}
  };
  const signature=config=>JSON.stringify(Object.keys(config).sort().map(key=>[key,config[key]]));
  const cache=new Map();
  // A server capability chooses the active subset; circuit and safety limits are never patches.
  const tunable=new Set(['kp','ti_ms','td_ms','derivative_filter_ms','voltage_kp','voltage_ki','voltage_kd','current_kp','current_ki','current_kd','loop_derivative_filter_ms','voltage_period_us','current_period_us','mppt_period_ms','algorithm_filter_ms','mppt_step_v','mppt_step_duty','libre_step_counts','voltage_deadband_v','fugu_voltage_kp','fugu_fast_speed','fugu_slow_speed','fugu_slow_period_ms','model_voltage_gain','model_current_gain','model_delay_us','model_filter_ms','opensec_min_delta_v','opensec_max_step_v',...['vin','vout','iin','iout','power'].flatMap(name=>['fugu_'+name+'_kp','fugu_'+name+'_kd'])]);
  function normalizeCapability(data){
    const source=data.capability||data,keys=source.tunable_keys||source.gain_keys||source.keys||[];
    return {...source,keys:keys.filter(key=>tunable.has(key)),parameter_specs:data.parameter_specs||source.parameter_specs||{}};
  }
  function capability(config){
    if(config.algorithm==='c07_r03')return {supported:false,keys:[],reason:'c07 r03は今回の自動調整の対象外です。ゲインは手動で変更できます。'};
    return cache.get(signature(config))||{supported:false,keys:[],pending:true,reason:'調整できる項目を確認しています…'};
  }
  const isMPP=c=>c.experiment==='irradiance';
  function profileFor(name,config){
    if(!isMPP(config))return profiles[name]||profiles.balanced;
    return ({balanced:{label:'バランス',description:'回収できる電力と、MPP付近の揺れを一緒に評価します。'},speed:{label:'回収電力を重視',description:'日射が変わった後の回収電力の損失を小さくする候補を探します。'},gentle:{label:'揺れを抑える',description:'MPP付近の電圧・電力の揺れを重く評価します。'}})[name]||profiles.balanced;
  }
  function scopeText(result){
    if(!result)return '';
    const scope=result.validation_scope;
    if(typeof scope==='string')return scope;
    if(scope&&typeof scope==='object')return scope.summary||scope.description||scope.label||'評価範囲の詳細は説明タブに表示します。';
    return 'この結果は指定したモデル・試験条件内の比較です。実機や全条件での安定性を確認した結果ではありません。';
  }
  function attach({getConfig,onApply,getGainSpec,onStart=()=>{},onEnd=()=>{}}){
    const $=id=>document.getElementById(id),host=$('gain-autotune');
    if(!host)return null;
    const profile=$('autotune-profile'),start=$('autotune-start'),cancel=$('autotune-cancel'),undoButton=$('autotune-undo');
    const profileButtons=[...profile.querySelectorAll('[data-autotune-profile]')];
    let selectedProfile='balanced',active=null,undo=null,lastResult=null,lastResultSignature=null,lastResultConfig=null,sequence=0;
    let parameterChanges=[],resultApplied=false,statusDetail='',capSequence=0,capTimer=null;
    const notify=()=>window.dispatchEvent(new CustomEvent('lab:autotune'));
    const release=request=>{if(!request.ended){request.ended=true;onEnd();}};
    const setStatus=(message,kind='idle',detail=message)=>{host.dataset.state=kind;statusDetail=detail;$('autotune-status').textContent=message+(kind==='error'&&detail&&detail!==message?' '+detail:'');$('autotune-status').hidden=!message;};
    const setProgress=progress=>{
      const bar=$('autotune-progress'),completed=Number(progress?.completed),total=Number(progress?.total);
      bar.hidden=!active;
      // `total` can be an exploration budget, not a planned workload. Only an
      // explicitly exact total may produce a percentage/progress fraction.
      const exactTotal=progress?.total_is_exact===true;
      if(exactTotal&&Number.isFinite(total)&&total>0&&Number.isFinite(completed)){bar.max=total;bar.value=Math.max(0,Math.min(total,completed));}
      else bar.removeAttribute('value');
      const stage=progress?.stage||'',label=stage==='queued'?'順番を待っています…':stage==='history'?'長い制御履歴を確認中…':/prepar|calcul|model|linear|seed/.test(stage)?(getConfig().algorithm==='c07_r04'?'r04のゲイン候補を準備中…':'回路から候補を計算中…'):/pwm|detail|valid/.test(stage)?'スイッチ動作を含めて確認中…':/optim|search|candidate|refin|cheap|averag/.test(stage)?'候補の追従を比較中…':'自動調整中…';
      const count=Number.isFinite(completed)&&completed>0?' '+Math.floor(completed)+'件を確認':'';
      setStatus(label+count,'running',progress?.message||label);notify();
    };
    function renderChanges(){
      const details=$('autotune-changes'),list=$('autotune-change-list');if(!details||!list)return;
      details.hidden=!parameterChanges.length;
      list.replaceChildren();
      for(const change of parameterChanges){
        const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=change.label;
        const fmt=value=>(value*change.scale).toLocaleString('ja-JP',{maximumSignificantDigits:6});
        dd.textContent=fmt(change.before)+' → '+fmt(change.after)+(change.unit?' '+change.unit:'');list.appendChild(dt);list.appendChild(dd);
      }
    }
    function render(){
      const current=getConfig(),available=capability(current),busy=Boolean(active);
      start.disabled=busy||!available.supported;start.textContent=busy?'調整中…':'自動調整';
      for(const button of profileButtons){
        const name=button.dataset.autotuneProfile,checked=name===selectedProfile;
        button.textContent=profileFor(name,current).label;button.disabled=busy||!available.supported;
        button.setAttribute('aria-checked',String(checked));button.tabIndex=checked?0:-1;
      }
      const description=$('autotune-description');if(description)description.textContent=profileFor(selectedProfile,current).description+(current.algorithm==='c07_r04'?' PV電圧'+(current.voltage_mode==='PI'?'PI':'PID')+'とL1電流PIのゲインを調整します。':'');
      cancel.hidden=!busy;undoButton.hidden=!undo;undoButton.disabled=busy||Boolean(undo&&undo.signature!==signature(current));
      $('autotune-availability').hidden=available.supported;
      $('autotune-availability').textContent=available.supported?'':available.reason||available.shortReason||'この条件では自動調整できません。';
      $('autotune-progress').hidden=!busy;
      const scope=$('autotune-scope');if(scope){scope.hidden=!lastResult;scope.textContent=(lastResult&&lastResultSignature!==signature(current)?'調整時点の条件の結果です。 ':'')+scopeText(lastResult);}
      renderChanges();notify();
    }
    async function refreshCapability(){
      const config={...getConfig()},sig=signature(config),id=++capSequence;
      clearTimeout(capTimer);capTimer=null;
      if(config.algorithm==='c07_r03'||cache.has(sig)){render();return capability(config);}
      render();
      try{
        const response=await fetch('/api/autotune/capability',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config})});
        const data=await response.json();
        const value=response.ok?normalizeCapability(data):{supported:false,keys:[],reason:data.error||'この設定では自動調整できません。'};
        cache.set(sig,value);if(cache.size>40)cache.delete(cache.keys().next().value);
      }catch(error){cache.set(sig,{supported:false,keys:[],reason:'調整項目を取得できませんでした。設定を変更するか、画面を再読み込みしてください。'});}
      if(id===capSequence&&sig===signature(getConfig()))render();return capability(config);
    }
    function postCancel(jobId){if(jobId)fetch('/api/autotune/'+encodeURIComponent(jobId)+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});}
    function cancelActive(message='中止しました'){
      const request=active;if(!request)return;active=null;request.cancelled=true;clearTimeout(request.timer);postCancel(request.jobId);
      setStatus(message,'cancelled');render();release(request);
    }
    function update(){
      if(active&&signature(getConfig())!==active.signature)cancelActive('設定変更のため中止しました');
      render();clearTimeout(capTimer);if(capability(getConfig()).pending)capTimer=setTimeout(refreshCapability,120);
    }
    function parameterSpec(key,request){
      const display=getGainSpec(key)||{},source=request.available.parameter_specs;
      const raw=Array.isArray(source)?source.find(item=>item.key===key):source?.[key];
      const spec=Array.isArray(raw)?{min:raw[0],max:raw[1]}:raw||{};
      return {display,min:Number.isFinite(spec.min)?spec.min:Number.isFinite(spec.minimum)?spec.minimum:Number.isFinite(display.min)?display.min/(display.scale||1):-Infinity,
        max:Number.isFinite(spec.max)?spec.max:Number.isFinite(spec.maximum)?spec.maximum:Number.isFinite(display.max)?display.max/(display.scale||1):Infinity};
    }
    function finish(request,result){
      if(active!==request||request.cancelled)return;
      if(signature(getConfig())!==request.signature){cancelActive('設定変更のため適用しませんでした');return;}
      if(!result||!['ok','no_improvement','unsupported','candidate_only','validation_failed'].includes(result.status))throw new Error('自動調整の結果を読み取れませんでした。');
      let applied=false,beforePatch={};
      if(result.status==='ok'){
        const allowed=new Set(request.available.keys),patch=result.patch;
        if(!patch||!Object.keys(patch).length)throw new Error('適用できるパラメータがありませんでした。');
        if(result.detailed_validated!==true&&result.pwm_validated!==true)throw new Error('詳細確認が完了していない候補のため、変更していません。');
        for(const [key,value] of Object.entries(patch)){
          const spec=parameterSpec(key,request);
          if(!allowed.has(key)||!tunable.has(key)||typeof value!=='number'||!Number.isFinite(value)||value<spec.min||value>spec.max||(key==='libre_step_counts'&&!Number.isInteger(value))||!Number.isFinite(request.config[key]))throw new Error('調整結果に適用できない設定値が含まれていたため、変更していません。');
          beforePatch[key]=request.config[key];
        }
        active=null;clearTimeout(request.timer);onApply({...patch});
        undo={patch:beforePatch,signature:signature(getConfig())};applied=true;setStatus('確認した候補へ変更しました','completed');
      }else{
        active=null;clearTimeout(request.timer);
        setStatus(result.status==='unsupported'?'この条件は対象外':result.status==='candidate_only'?'候補のみ・変更していません':result.status==='validation_failed'?'詳細確認で見送りました':'改善なし・変更していません','unchanged',result.reason||'');
      }
      parameterChanges=applied?Object.entries(result.patch).map(([key,after])=>{const spec=getGainSpec(key)||{};return {key,label:spec.label||key,unit:spec.unit||'',scale:spec.scale||1,before:beforePatch[key],after};}):[];
      resultApplied=applied;lastResult=result;lastResultConfig={...request.config};lastResultSignature=signature(getConfig());render();release(request);
    }
    function fail(request,error){
      if(active!==request&&request.cancelled)return;
      active=null;clearTimeout(request.timer);postCancel(request.jobId);
      setStatus('調整できませんでした','error',error.message+' パラメータは変更していません。');render();release(request);
    }
    async function poll(request){
      if(active!==request)return;
      try{
        const response=await fetch('/api/autotune/'+encodeURIComponent(request.jobId)),data=await response.json();
        if(active!==request)return;if(!response.ok)throw new Error(data.error||'自動調整の状態を取得できませんでした。');
        if(data.status==='completed'){finish(request,data.result);return;}
        if(data.status==='failed')throw new Error(data.error||'自動調整を完了できませんでした。');
        if(data.status==='cancelled'){cancelActive();return;}setProgress(data.progress||{});request.timer=setTimeout(()=>poll(request),600);
      }catch(error){fail(request,error);}
    }
    async function begin(){
      const snapshot={...getConfig()},available=capability(snapshot);if(active||!available.supported)return;
      const request={id:++sequence,config:snapshot,available,signature:signature(snapshot),profile:selectedProfile,cancelled:false,jobId:null,timer:null};
      active=request;setProgress({stage:'preparing'});render();
      try{
        await onStart();if(active!==request||request.cancelled)return;
        const response=await fetch('/api/autotune',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:snapshot,profile:request.profile})}),data=await response.json();
        request.jobId=data.job_id;if(active!==request||request.cancelled){postCancel(request.jobId);return;}
        if(!response.ok)throw new Error(data.error||'自動調整を開始できませんでした。');
        if(!request.jobId)throw new Error('自動調整の受付結果を読み取れませんでした。');
        if(data.status==='completed'){finish(request,data.result);return;}await poll(request);
      }catch(error){fail(request,error);}
    }
    start.addEventListener('click',begin);cancel.addEventListener('click',()=>cancelActive());
    for(const [index,button] of profileButtons.entries()){
      button.addEventListener('click',()=>{if(active||button.disabled)return;selectedProfile=button.dataset.autotuneProfile;render();});
      button.addEventListener('keydown',event=>{
        const offsets={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1};
        if(active||button.disabled||(!(event.key in offsets)&&!['Home','End'].includes(event.key)))return;
        event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?profileButtons.length-1:(index+offsets[event.key]+profileButtons.length)%profileButtons.length;
        selectedProfile=profileButtons[next].dataset.autotuneProfile;render();profileButtons[next].focus();
      });
    }
    undoButton.addEventListener('click',()=>{
      if(active||!undo||undo.signature!==signature(getConfig()))return;
      const patch=undo.patch;undo=null;onApply({...patch});resultApplied=false;setStatus('調整前の値に戻しました','idle');render();
    });
    window.addEventListener('pagehide',()=>{if(active)postCancel(active.jobId);});
    render();refreshCapability();
    return {update,refreshCapability,cancel:()=>cancelActive(),getState:()=>({running:Boolean(active),profile:selectedProfile,profileInfo:profileFor(selectedProfile,getConfig()),capability:capability(getConfig()),canUndo:Boolean(undo&&undo.signature===signature(getConfig())),result:lastResult,resultConfig:lastResultConfig?{...lastResultConfig}:null,resultStale:Boolean(lastResult&&lastResultSignature!==signature(getConfig())),parameterChanges:parameterChanges.map(change=>({...change})),gainChanges:parameterChanges.map(change=>({...change})),resultApplied,status:host.dataset.state,statusDetail})};
  }
  window.PVGainAutotune={attach,capability,profiles,profileFor,scopeText};
})();
