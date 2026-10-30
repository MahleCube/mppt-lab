"""Use the same c07 C control cores compiled to WebAssembly in Pyodide."""
import hashlib
import importlib
import math
from pathlib import Path
import weakref


class _LibraryPaths:
    """Map the desktop metadata lookup to the binary actually being executed."""
    def __init__(self, source, library):
        self.source = source
        self.library = library

    def __truediv__(self, name):
        return self.library if name == 'c07_lab.dll' else self.source / name


def _install_module(module, version, runtime):
    if getattr(module, '_browser_native_installed', False):
        return
    library = Path(__file__).resolve().parent / ('c07_' + version + '.wasm')
    library_hash = hashlib.sha256(library.read_bytes()).hexdigest()
    if library_hash != str(runtime.sha256):
        raise RuntimeError('Loaded c07 WebAssembly differs from the recorded binary')
    for name, expected in (('c07_control.c', module.CORE_HASH), ('c07_control.h', module.HEADER_HASH)):
        if hashlib.sha256((module.NATIVE / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('c07 unchanged source hash mismatch: ' + version + '/' + name)
    module.NATIVE = _LibraryPaths(module.NATIVE, library)

    class Native:
        def __init__(self, c, duty, target):
            self.runtime = runtime
            self.handle = int(runtime.create())
            self._close = weakref.finalize(self, runtime.free, self.handle)
            try:
                for key, name in module.REAL_MAP.items():
                    if runtime.config(self.handle, name, c[key]):
                        raise ValueError('c07 configuration: ' + key)
                for key, (name, scale) in module.TIME_MAP.items():
                    if runtime.config(self.handle, name, round(c[key] * scale)):
                        raise ValueError('c07 configuration: ' + key)
                rc = runtime.start(self.handle, c.get('pv_voc', 80.), c.get('v_battery', 51.2), duty, target)
                if rc:
                    raise ValueError('c07 core rejected configuration: ' + str(rc))
            except Exception:
                self._close()
                raise

        def settings(self):
            return {key: float(runtime.get(self.handle, name)) for key, name in module.REAL_MAP.items()} | {
                key: float(runtime.get(self.handle, name)) / scale for key, (name, scale) in module.TIME_MAP.items()}

        def step(self, measurement, dt, mppt, target):
            values = [float(measurement[key]) for key in ('v_in', 'i_pv', 'v_out', 'i_l', 'tbat', 'tsink', 'v_bat', 'v_pv')]
            if not all(map(math.isfinite, values)):
                raise ValueError('c07 measurement is not finite')
            result = runtime.step(self.handle, round(measurement.get('pv_pair_span_us', 51)),
                                  round(dt * 1e6), int(mppt), target, *values)
            return result.to_py()

        def begin(self):
            return bool(runtime.begin(self.handle))

        def finish(self):
            return int(runtime.finish(self.handle))

    original_make_class = module.make_class

    def make_class(base):
        original = original_make_class(base)

        class BrowserController(original):
            def __init__(self, *args):
                super().__init__(*args)
                self.metadata.update(core_execution_format='WebAssembly',
                                     core_library_sha256=library_hash,
                                     numeric_type='double / WebAssembly; not ARM instruction execution')
        return BrowserController

    module.Native = Native
    module.make_class = make_class
    module._browser_native_installed = True


def install():
    from js import mpptNative
    for version in ('r03', 'r04'):
        _install_module(importlib.import_module('c07_' + version), version, mpptNative.getRuntime(version))
