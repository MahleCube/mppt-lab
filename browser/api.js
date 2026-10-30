(() => {
  'use strict';
  const scriptURL = new URL(document.currentScript.src);
  const browserRoot = new URL('./', scriptURL);
  const appRoot = new URL('../', browserRoot);
  const networkFetch = window.fetch.bind(window);
  const jobs = new Map();
  let worker = null, ready = false, active = null, nextId = 0, queue = [];
  let suspended = false;
  let loadingMessage = '', startupError = false;
  let banner = null;

  function showLoading(message, error=false) {
    loadingMessage = message; startupError = error;
    if (!document.body) return;
    if (!banner) {
      banner = document.createElement('div');
      banner.className = 'browser-runtime-status';
      banner.setAttribute('role', 'status');
      banner.setAttribute('aria-live', 'polite');
      document.body.appendChild(banner);
    }
    banner.hidden = !message;
    banner.dataset.error = String(error);
    banner.textContent = message;
  }
  document.addEventListener('DOMContentLoaded', () => showLoading(loadingMessage, startupError), {once:true});

  const configPromise = networkFetch(new URL('config.json', browserRoot), {cache:'no-store'})
    .then(async response => {
      if (!response.ok) throw new Error('設定を読み込めませんでした。ページを再読み込みしてください。');
      return response.json();
    });
  // Attach a handler immediately; the endpoint still receives the original rejection.
  configPromise.catch(() => {});
  const response = (data, status=200, computeMs=0) => new Response(
    typeof data === 'string' ? data : JSON.stringify(data), {
      status, headers:{'Content-Type':'application/json; charset=utf-8',
        'Server-Timing':'compute;dur='+computeMs.toFixed(3)}
    });

  function finish(record, result) {
    if (record.settled) return;
    record.settled = true;
    record.signal?.removeEventListener('abort', record.abort);
    record.resolve(result);
  }
  function cancelRecord(record, hard=false) {
    if (record.settled) return;
    const index = queue.indexOf(record);
    if (index >= 0) queue.splice(index, 1);
    if (active === record) {
      // Frequent slider changes discard stale answers without reloading Python.
      // The newest queued configuration runs as soon as this calculation ends.
      if (!hard && record.dispatched && record.operation === 'simulate') {
        finish(record, response({cancelled:true}, 409));
        return;
      }
      active = null;
      if (record.dispatched) {
        worker?.terminate(); worker = null; ready = false;
      }
    }
    finish(record, response({cancelled:true}, 409));
    pump();
  }
  function failWorker(error) {
    worker?.terminate(); worker = null; ready = false;
    showLoading('計算の準備に失敗しました。接続を確認して再読み込みしてください。', true);
    const requests = [active, ...queue].filter(Boolean);
    active = null; queue = [];
    for (const request of requests) finish(request, response({error:String(error.message || error)}, 500));
  }
  let spawning = null;
  async function ensureWorker() {
    if (suspended || worker || spawning) return spawning;
    spawning = (async () => {
      const config = await configPromise;
      if (suspended) return;
      const url = new URL('worker.js', browserRoot);
      url.searchParams.set('v', config.browser_build || '1');
      const instance = new Worker(url, {type:'module', name:'mppt-calculation'});
      worker = instance;
      instance.onmessage = ({data}) => {
        if (worker !== instance) return;
        if (data.type === 'loading') showLoading(data.message);
        else if (data.type === 'ready') {ready=true; showLoading(''); pump();}
        else if (data.type === 'startup-error') failWorker(new Error(data.error));
        else if (data.type === 'progress' && active?.id === data.id) {
          try {active.onProgress?.(JSON.parse(data.json));} catch (error) {console.error(error);}
        } else if (data.type === 'result' && active?.id === data.id) {
          const request = active; active = null;
          finish(request, response(data.json, data.status, data.computeMs || 0));
          pump();
        }
      };
      instance.onerror = event => {
        if (worker === instance) failWorker(new Error(event.message || '計算を読み込めませんでした。'));
      };
    })().catch(failWorker).finally(() => {spawning=null;});
    return spawning;
  }
  function pump() {
    if (suspended || active || !queue.length) return;
    if (!worker) {ensureWorker(); return;}
    if (!ready) return;
    active = queue.shift();
    if (active.signal?.aborted) {cancelRecord(active); return;}
    active.dispatched = true;
    active.onStart?.();
    worker.postMessage({id:active.id, operation:active.operation, data:active.data});
  }
  function request(operation, data, options={}) {
    let record;
    const promise = new Promise(resolve => {
      record = {id:++nextId, operation, data, resolve, settled:false, dispatched:false, ...options};
      record.abort = () => cancelRecord(record);
      if (record.signal?.aborted) {finish(record, response({cancelled:true}, 409)); return;}
      record.signal?.addEventListener('abort', record.abort, {once:true});
      queue.push(record); pump();
    });
    return {record, promise};
  }
  function publicJob(job) {
    return Object.fromEntries(Object.entries(job).filter(([key]) => !key.startsWith('_')));
  }
  function cancelJob(job) {
    if (job && ['queued','running'].includes(job.status)) {
      job.status = 'cancelled';
      job.finished_at = Date.now()/1000;
      job.progress = {stage:'cancelled', completed:0, total:0, message:'中止しました。設定は変更していません。'};
      if (job._request) cancelRecord(job._request, true);
    }
    return job;
  }
  function newJob(data) {
    if (!data.config || typeof data.config !== 'object' || Array.isArray(data.config))
      return response({error:'自動調整する設定を指定してください。'}, 400);
    if (!['balanced','speed','gentle'].includes(data.profile || 'balanced'))
      return response({error:'自動調整の目的を選んでください。'}, 400);
    if ([...jobs.values()].filter(job => ['queued','running'].includes(job.status)).length >= 3)
      return response({error:'別の自動調整を処理中です。終了または中止してください。'}, 400);
    while (jobs.size >= 16) {
      const first = [...jobs].find(([,job]) => !['queued','running'].includes(job.status));
      if (!first) break;
      jobs.delete(first[0]);
    }
    const id = crypto.randomUUID().replaceAll('-', '');
    const job = {job_id:id, status:'queued', profile:data.profile || 'balanced', created_at:Date.now()/1000,
      progress:{stage:'queued', completed:0, total:0, message:'計算の準備を待っています。'}};
    jobs.set(id, job);
    const operation = request('tune', data, {
      jobId:id,
      onStart:() => {job.status='running'; job.started_at=Date.now()/1000;},
      onProgress:progress => {if (job.status === 'running') job.progress=progress;}
    });
    job._request = operation.record;
    operation.promise.then(async result => {
      if (job.status === 'cancelled') return;
      const payload = await result.json();
      job.finished_at = Date.now()/1000;
      if (result.ok) {job.result=payload; job.status='completed';}
      else {job.status='failed'; job.error=payload.error || '自動調整を完了できませんでした。';}
    }).catch(error => {
      if (job.status !== 'cancelled') {job.status='failed'; job.error=String(error.message || error); job.finished_at=Date.now()/1000;}
    });
    return response(publicJob(job), 202);
  }

  async function apiFetch(path, options={}, input=null) {
    const method = (options.method || input?.method || 'GET').toUpperCase();
    if (path === '/api/config' && method === 'GET') return response(await configPromise);
    if (path === '/api/health' && method === 'GET') return response({app:'mppt-lab', version:3, engine:'browser / Pyodide + WebAssembly'});
    const match = path.match(/^\/api\/autotune\/([a-f0-9]{32})(\/cancel)?$/);
    if (match) {
      const job = jobs.get(match[1]);
      if (!job) return response({error:'自動調整の記録が見つかりません。'}, 404);
      if (match[2] && method === 'POST') cancelJob(job);
      else if (match[2] || method !== 'GET') return response({error:'not found'}, 404);
      return response(publicJob(job));
    }
    if (method !== 'POST') return response({error:'not found'}, 404);
    let data;
    try {
      data = JSON.parse(options.body === undefined && input ? await input.clone().text() : options.body || '{}');
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('設定はオブジェクトで指定してください。');
    } catch (error) {return response({error:'設定データを読み取れませんでした。'}, 400);}
    const headers = new Headers(options.headers || input?.headers || {});
    const client = headers.get('X-PV-Client') || '';
    const revision = Number(headers.get('X-PV-Revision') || 0);
    if (path === '/api/cancel') {
      for (const record of [active,...queue].filter(Boolean))
        if (record.operation === 'simulate' && record.client === client && record.revision < revision) cancelRecord(record);
      return response({cancelled:true});
    }
    if (path === '/api/autotune') return newJob(data);
    const operation = {'/api/simulate':'simulate','/api/start-mpp':'start-mpp','/api/autotune/capability':'capability'}[path];
    if (!operation) return response({error:'not found'}, 404);
    if (operation === 'simulate') {
      for (const record of [...queue])
        if (record.operation === 'simulate' && record.client === client && record.revision < revision) cancelRecord(record);
    }
    return request(operation, data, {signal:options.signal || input?.signal, client, revision}).promise;
  }
  function recognizedPath(input) {
    const url = new URL(input instanceof Request ? input.url : String(input), document.baseURI);
    if (url.origin !== location.origin) return null;
    let path = url.pathname;
    if (path.startsWith(appRoot.pathname + 'api/')) path = '/api/' + path.slice((appRoot.pathname + 'api/').length);
    return /^\/api\/(config|health|simulate|cancel|start-mpp|autotune(?:\/capability|\/[a-f0-9]{32}(?:\/cancel)?)?)$/.test(path) ? path : null;
  }
  window.fetch = function(input, options) {
    const path = recognizedPath(input);
    return path ? apiFetch(path, options, input instanceof Request ? input : null) : networkFetch(input, options);
  };
  window.MPPTBrowser = Object.freeze({
    baseURL:appRoot.href,
    get ready(){return ready;},
    get pending(){return queue.length + Number(Boolean(active));},
    get activeOperation(){return active?.operation || null;}
  });
  window.addEventListener('pagehide', () => {
    suspended = true;
    worker?.terminate(); worker=null; ready=false;
    for (const job of jobs.values()) cancelJob(job);
    for (const record of [active,...queue].filter(Boolean)) finish(record, response({cancelled:true}, 409));
    active=null; queue=[];
  });
  window.addEventListener('pageshow', () => {suspended=false; pump();});
})();
