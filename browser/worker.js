import {loadPyodide} from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

const browserRoot = new URL('./', import.meta.url);
const appRoot = new URL('../', browserRoot);
const version = new URL(import.meta.url).search;
const versioned = path => new URL(path + version, appRoot);
const sourceFiles = [
  'engine.py', 'engine_v3.py', 'engine_legacy_v2.py', 'fast_integrator.py',
  'controllers.py', 'plant.py', 'experiments.py', 'waveform_summary.py',
  'parameter_sets.py', 'circuit_references.py', 'pv_operating_point.py',
  'autotune.py', 'tuning_design.py', 'tuning_search.py', 'tuning_metrics.py',
  'tuning_simulator.py', 'c07_r03.py', 'c07_r04.py', 'c07_preset.json',
  'browser/runtime.py', 'browser/numba.py', 'browser/native.py', 'browser/kernels.py',
  'browser/c07_r03.wasm', 'browser/c07_r04.wasm', 'browser/kernels.wasm',
  'native/c07_r03/c07_control.c', 'native/c07_r03/c07_control.h',
  'native/c07_r04/c07_control.c', 'native/c07_r04/c07_control.h'
];

const reportLoading = message => self.postMessage({type:'loading', message});
let dispatch, runtimeModule;
async function initialize() {
  reportLoading('計算の準備中… 初回は少し時間がかかります');
  await Promise.all([import(new URL('native.js' + version, browserRoot)),
                     import(new URL('kernels.js' + version, browserRoot))]);
  const sourcePromise = Promise.all(sourceFiles.map(async path => {
    const response = await fetch(versioned(path));
    if (!response.ok) throw new Error('計算ファイルを読み込めませんでした: ' + path);
    return [path, new Uint8Array(await response.arrayBuffer())];
  }));
  sourcePromise.catch(() => {});
  const nativePromise = globalThis.loadMpptNative(browserRoot.href).then(value => {globalThis.mpptNative=value;});
  const kernelsPromise = globalThis.loadMpptKernels(browserRoot.href).then(value => {globalThis.mpptKernels=value;});
  await Promise.all([nativePromise, kernelsPromise]);
  const pyodide = await loadPyodide({
    indexURL:'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/',
    jsglobals:globalThis,
    stdout:message => console.log(message), stderr:message => console.warn(message)
  });
  reportLoading('計算に必要なライブラリを読み込んでいます…');
  await pyodide.loadPackage(['numpy', 'scipy']);
  const files = await sourcePromise;
  pyodide.FS.mkdirTree('/lab/browser');
  for (const [path, bytes] of files) {
    const target = '/lab/' + path;
    pyodide.FS.mkdirTree(target.slice(0, target.lastIndexOf('/')));
    pyodide.FS.writeFile(target, bytes);
  }
  // This import shim lives only in the browser filesystem. Desktop Numba is untouched.
  pyodide.FS.writeFile('/lab/numba.py', pyodide.FS.readFile('/lab/browser/numba.py'));
  pyodide.FS.writeFile('/lab/browser/__init__.py', '');
  reportLoading('回路と制御の計算を準備しています…');
  pyodide.runPython(`
import sys
sys.path.insert(0, '/lab')
from browser import runtime as lab_browser_runtime
lab_browser_runtime.install()
`);
  runtimeModule = pyodide.globals.get('lab_browser_runtime');
  dispatch = runtimeModule.handle;
  self.postMessage({type:'ready'});
}

let initializationError = null;
const ready = initialize().catch(error => {
  initializationError = error;
  self.postMessage({type:'startup-error', error:String(error.message || error)});
});

self.onmessage = async ({data}) => {
  if (!data || typeof data.id !== 'number' || typeof data.operation !== 'string') return;
  await ready;
  if (initializationError) return;
  const started = performance.now();
  try {
    const progress = json => self.postMessage({type:'progress', id:data.id, json});
    const envelope = dispatch(data.operation, JSON.stringify(data.data), progress);
    let status, json;
    try {[status, json] = envelope.toJs();} finally {envelope.destroy();}
    self.postMessage({type:'result', id:data.id, status, json, computeMs:performance.now()-started});
  } catch (error) {
    console.error(error);
    self.postMessage({type:'result', id:data.id, status:400,
      json:JSON.stringify({error:String(error.message || error)}), computeMs:performance.now()-started});
  }
};
