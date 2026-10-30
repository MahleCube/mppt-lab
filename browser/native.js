/* Browser access to the unchanged c07 C cores. No operating-system imports. */
(() => {
  'use strict';
  const encoder = new TextEncoder();
  class NativeCore {
    constructor(version, exports, sha256) {
      this.version = version;
      this.exports = exports;
      this.sha256 = sha256;
      this.outputCount = version === 'r03' ? 31 : 33;
      this.strings = new Map();
      this.instances = new Map();
      exports._initialize();
    }
    string(value) {
      if (this.strings.has(value)) return this.strings.get(value);
      const bytes = encoder.encode(value + '\0');
      const ptr = this.exports.malloc(bytes.length);
      if (!ptr) throw new Error('c07 string allocation failed');
      new Uint8Array(this.exports.memory.buffer, ptr, bytes.length).set(bytes);
      this.strings.set(value, ptr);
      return ptr;
    }
    create() {
      const e = this.exports, handle = e.c07_lab_new();
      if (!handle) throw new Error('c07 controller allocation failed');
      const input = e.malloc(8 * 8), output = e.malloc(this.outputCount * 8);
      if (!input || !output) {
        if (input) e.free(input);
        if (output) e.free(output);
        e.c07_lab_free(handle);
        throw new Error('c07 measurement allocation failed');
      }
      this.instances.set(handle, {input, output});
      return handle;
    }
    check(handle) {
      const buffers = this.instances.get(handle);
      if (!buffers) throw new Error('c07 controller handle is closed');
      return buffers;
    }
    free(handle) {
      const buffers = this.instances.get(handle);
      if (!buffers) return;
      this.exports.free(buffers.input);
      this.exports.free(buffers.output);
      this.exports.c07_lab_free(handle);
      this.instances.delete(handle);
    }
    config(handle, name, value) {
      this.check(handle);
      return this.exports.c07_lab_config(handle, this.string(name), value);
    }
    get(handle, name) {
      this.check(handle);
      return this.exports.c07_lab_get(handle, this.string(name));
    }
    start(handle, voc, battery, duty, target) {
      this.check(handle);
      return this.exports.c07_lab_start(handle, voc, battery, duty, target);
    }
    step(handle, span, dt, mppt, target, ...values) {
      const b = this.check(handle), e = this.exports;
      if (values.length !== 8 || !values.every(Number.isFinite)) throw new Error('c07 requires 8 finite measurements');
      new Float64Array(e.memory.buffer, b.input, 8).set(values);
      const rc = e.c07_lab_step(handle, b.input, span, dt, mppt, target, b.output);
      if (rc) throw new Error('c07 core rejected sample/time: ' + rc);
      // A copy prevents the next step from mutating a previous result.
      return Array.from(new Float64Array(e.memory.buffer, b.output, this.outputCount));
    }
    begin(handle) {
      this.check(handle);
      return this.exports.c07_lab_begin(handle);
    }
    finish(handle) {
      this.check(handle);
      return this.exports.c07_lab_finish(handle);
    }
  }
  async function createMpptNativeModule(version, bytes) {
    if (!['r03', 'r04'].includes(version)) throw new Error('Unknown c07 core');
    const module = await WebAssembly.compile(bytes);
    if (WebAssembly.Module.imports(module).length) throw new Error('c07 WASM must not require host imports');
    const instance = await WebAssembly.instantiate(module, {});
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    const sha256 = Array.from(digest, value => value.toString(16).padStart(2, '0')).join('');
    return new NativeCore(version, instance.exports, sha256);
  }
  globalThis.createMpptNativeModule = createMpptNativeModule;
  globalThis.loadMpptNative = async function(baseUrl) {
    const loaded = await Promise.all(['r03', 'r04'].map(async version => {
      const response = await fetch(new URL('c07_' + version + '.wasm', baseUrl), {cache:'no-store'});
      if (!response.ok) throw new Error('Cannot load c07 ' + version + ': HTTP ' + response.status);
      return [version, await createMpptNativeModule(version, await response.arrayBuffer())];
    }));
    const cores = Object.fromEntries(loaded);
    globalThis.mpptNative = {getRuntime(version) {
      if (!cores[version]) throw new Error('Unknown c07 core');
      return cores[version];
    }};
    return globalThis.mpptNative;
  };
})();
