"""Browser entry points over the shared controllers, event scheduler and metrics."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import sys
import time


def install():
    # ctypes is not available in every Pyodide release. No host DLL is invoked:
    # the browser adapter replaces Native before a controller is instantiated.
    try:
        import ctypes
    except ImportError:
        import types
        sys.modules['ctypes'] = types.ModuleType('ctypes')
    import engine
    import tuning_simulator
    import waveform_summary
    import autotune
    from browser.kernels import install as install_kernels
    from browser.native import install as install_native
    install_kernels()
    install_native()
    original_identity = autotune.source_identity

    def browser_identity():
        base = Path(__file__).resolve().parent
        names = ('runtime.py', 'numba.py', 'native.py', 'kernels.py',
                 'c07_r03.wasm', 'c07_r04.wasm', 'kernels.wasm')
        digest = hashlib.sha256(original_identity().encode('ascii'))
        for name in names:
            digest.update((base / name).read_bytes())
        return digest.hexdigest()

    autotune.source_identity = browser_identity


_CACHE = OrderedDict()


def _label_backend(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'solver' and isinstance(child, str):
                child = child.replace('Numba', 'WebAssembly')
                if 'SDIRK2' in child and 'WebAssembly' not in child:
                    child += ' / WebAssembly'
                value[key] = child
            else:
                _label_backend(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _label_backend(child)


def dispatch(operation, body, progress=None):
    """Return the same JSON contract used by the local HTTP application."""
    from engine import configuration, simulate, LIMITS
    from autotune import capability, tune_gains
    from pv_operating_point import calculate_start_mpp
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError('設定はJSONオブジェクトで指定してください。')
    if operation == 'capability':
        if not isinstance(data.get('config'), dict):
            raise ValueError('自動調整の対象設定を指定してください。')
        result = capability(configuration(data['config']))
        keys = result.get('tunable_keys', result.get('gain_keys', []))
        result = {**result, 'parameter_specs': {
            key: {'min': LIMITS[key][0], 'max': LIMITS[key][1],
                  **result.get('parameter_specs', {}).get(key, {})}
            for key in keys if key in LIMITS}}
    elif operation == 'start-mpp':
        result = calculate_start_mpp(data)
    elif operation == 'tune':
        if not isinstance(data.get('config'), dict):
            raise ValueError('自動調整する設定を指定してください。')
        def report(value):
            if progress is not None:
                progress(json.dumps(value, ensure_ascii=False, allow_nan=False))
        result = tune_gains(configuration(data['config']),
                            profile=data.get('profile', 'balanced'), progress=report)
        result['execution_environment'] = 'browser / Pyodide + WebAssembly'
    elif operation == 'simulate':
        config = configuration(data)
        key = json.dumps(config, sort_keys=True)
        if key in _CACHE:
            result = _CACHE.pop(key)
            _CACHE[key] = result
            result = {**result, 'diagnostics': {**result['diagnostics'], 'cache_hit': True}}
        else:
            result = {key: value for key, value in simulate(config).items() if key != 'events'}
            diagnostics = result['diagnostics']
            diagnostics['cache_hit'] = False
            diagnostics['solver'] = diagnostics.get('solver', '').replace('Numba', 'WebAssembly')
            diagnostics['execution_environment'] = 'browser / Pyodide + WebAssembly'
            if result['metrics']['completed']:
                _CACHE[key] = result
                while len(_CACHE) > 5:
                    _CACHE.popitem(last=False)
    else:
        raise ValueError('未対応の操作です。')
    _label_backend(result)
    return json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def handle(operation, body, progress=None):
    from engine import SimulationCancelled
    try:
        return 200, dispatch(operation, body, progress)
    except SimulationCancelled:
        return 409, json.dumps({'cancelled': True})
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        return 400, json.dumps({'error': str(error)}, ensure_ascii=False)
    except Exception as error:
        import traceback
        traceback.print_exc()
        return 500, json.dumps({'error': '計算を完了できませんでした: ' + str(error)}, ensure_ascii=False)
