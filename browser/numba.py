"""Import compatibility for browser builds; hot kernels are installed from WASM."""
import sys
import types as _types


def njit(*args, **kwargs):
    def decorate(function):
        function.py_func = function
        return function
    return decorate(args[0]) if args and callable(args[0]) else decorate


class _Type:
    def __getitem__(self, item):
        return self


types = _types.SimpleNamespace(int64=_Type(), float64=_Type())


class _Dict(dict):
    @classmethod
    def empty(cls, **kwargs):
        return cls()


typed = _types.ModuleType('numba.typed')
typed.Dict = _Dict
sys.modules['numba.typed'] = typed
