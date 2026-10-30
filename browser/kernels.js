/* Numerical WASM adapter. Input PyProxy buffers are released after copying. */
globalThis.loadMpptKernels = async function (baseURL) {
  const response = await fetch(new URL('kernels.wasm', baseURL), { cache: 'no-store' });
  if (!response.ok) throw new Error('計算ファイルを読み込めません。');
  const bytes = await response.arrayBuffer();
  const wasi = {
    proc_exit(code) { throw new Error('Calculation WASM exit ' + code); },
    fd_close() { return 8; }, fd_seek() { return 8; }, fd_write() { return 8; },
    environ_get() { return 0; }, environ_sizes_get() { return 0; },
    random_get() { return 52; }, clock_time_get() { return 52; }
  };
  const { instance } = await WebAssembly.instantiate(bytes, { wasi_snapshot_preview1: wasi });
  const e = instance.exports;
  if (e._initialize) e._initialize();
  function alloc(length) {
    const ptr = e.malloc(Math.max(8, length * 8));
    if (!ptr) throw new Error('計算用メモリを確保できません。');
    return ptr;
  }
  const view = (ptr, length) => new Float64Array(e.memory.buffer, ptr, length);
  function copyInput(value) {
    let source = value, buffer;
    if (value && typeof value.getBuffer === 'function') {
      buffer = value.getBuffer(); source = buffer.data;
    }
    try {
      if (!ArrayBuffer.isView(source) && !Array.isArray(source)) throw new Error('Expected numeric buffer');
      const ptr = alloc(source.length);
      view(ptr, source.length).set(source);
      return { ptr, length: source.length };
    } finally { if (buffer) buffer.release(); }
  }
  function inputs(values, run) {
    const buffers = [];
    try { for (const value of values) buffers.push(copyInput(value)); return run(buffers); }
    finally { for (const item of buffers) e.free(item.ptr); }
  }
  function output(n, run) {
    const ptr = alloc(n);
    try { run(ptr); return view(ptr, n).slice(); }
    finally { e.free(ptr); }
  }
  function result(n) {
    const count = e.k_result_count();
    return { times: view(e.k_result_times(), count).slice(),
      states: view(e.k_result_states(), count * n).slice(), count,
      steps: e.k_result_steps(), nfev: e.k_result_nfev(), code: e.k_result_code() };
  }
  const api = {
    curves(l, c) { inputs([l, c], b => e.k_curves(b[0].ptr, b[1].ptr)); },
    nodes(t, y, p, on, conducting) { return inputs([y, p], b => output(15, ptr => e.k_nodes(t, b[0].ptr, b[1].ptr, +on, +conducting, ptr))); },
    rhs(t, y, p, on, conducting) { return inputs([y, p], b => output(b[0].length, ptr => e.k_rhs(t, b[0].ptr, b[0].length, b[1].ptr, +on, +conducting, ptr))); },
    records(times, states, n, p, on, conducting, duty, averaged) {
      return inputs([times, states, p], b => output(b[0].length * 15, ptr => e.k_records(b[0].ptr, b[1].ptr, b[0].length, n, b[2].ptr, +on, +conducting, duty, +averaged, ptr)));
    },
    integrate(t, end, y, p, on, conducting, maxStep, rtol, legacy) {
      return inputs([y, p], b => {
        if (legacy) e.k_legacy_integrate(t, end, b[0].ptr, b[1].ptr, +on, +conducting, maxStep, rtol);
        else e.k_integrate(t, end, b[0].ptr, b[0].length, b[1].ptr, +on, +conducting, maxStep, rtol);
        return result(b[0].length);
      });
    },
    averageRhs(t, y, p, duty) { return inputs([y, p], b => output(b[0].length, ptr => e.k_average_rhs(t, b[0].ptr, b[0].length, b[1].ptr, duty, ptr))); },
    jacobian(t, y, p, duty) { return inputs([y, p], b => output(b[0].length ** 2, ptr => e.k_jacobian(t, b[0].ptr, b[0].length, b[1].ptr, duty, ptr))); },
    sdirk(t, y, h, p, duty, inverse) {
      return inputs([y, p, inverse], b => {
        let ok;
        const state = output(b[0].length, ptr => { ok = e.k_sdirk(t, b[0].ptr, b[0].length, h, b[1].ptr, duty, b[2].ptr, ptr); });
        return { state, ok: !!ok };
      });
    },
    averageIntegrate(t, end, y, p, duty, rtol, maxStep, jac) {
      return inputs([y, p, jac], b => {
        e.k_average_integrate(t, end, b[0].ptr, b[0].length, b[1].ptr, duty, rtol, maxStep, b[2].ptr);
        return { ...result(b[0].length), jac: view(b[2].ptr, b[2].length).slice() };
      });
    },
    waveform(times, values, period, channels, capacity, state) {
      return inputs([times, values, state], b => {
        const code = e.k_waveform(b[0].ptr, b[1].ptr, b[0].length, period, channels, capacity, b[2].ptr);
        if (code) throw new Error(code === 1 ? 'Waveform timestamps must be nondecreasing' : 'Internal PWM boundary precedes interval');
        return view(b[2].ptr, b[2].length).slice();
      });
    }
  };
  globalThis.mpptKernels = api;
  return api;
};
