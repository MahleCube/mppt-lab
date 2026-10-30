"""Install WASM numerical kernels while retaining the Python event scheduler."""
import numpy as np


def install():
    from js import mpptKernels as wasm
    import plant
    import fast_integrator
    import tuning_simulator
    import waveform_summary

    def array(value):
        return np.ascontiguousarray(value, dtype=np.float64)

    def returned(value):
        # JS typed arrays convert to Python memoryviews with a retained owner.
        return np.asarray(value.to_py(), dtype=np.float64)

    wasm.curves(array(plant.L_DIFF), array(plant.C_DIFF))

    def nodes(t, y, p, on, conducting):
        return returned(wasm.nodes(float(t), array(y), array(p), bool(on), bool(conducting)))

    def rhs(t, y, p, on, conducting, out):
        out[:] = returned(wasm.rhs(float(t), array(y), array(p), bool(on), bool(conducting)))

    def records(times, states, p, on, conducting):
        ts = array(times)
        ys = array(np.asarray(states).T)
        return returned(wasm.records(ts, ys, len(states), array(p), bool(on), bool(conducting), 0., False)).reshape(len(ts), 15)

    def record(t, y, p, on, conducting):
        return records([t], np.asarray(y)[:, None], p, on, conducting)[0]

    def unpack(result, n):
        data = result.to_py()
        return (np.asarray(data['times']), np.asarray(data['states']).reshape(data['count'], n).T.copy(),
                int(data['nfev']), int(data['steps']), int(data['code']))

    def integrate(t, end, y, p, on, conducting, max_step, rtol):
        return unpack(wasm.integrate(float(t), float(end), array(y), array(p), bool(on), bool(conducting), float(max_step), float(rtol), False), len(y))

    def legacy_integrate(t, end, y, p, on, conducting, max_step, rtol):
        return unpack(wasm.integrate(float(t), float(end), array(y), array(p), bool(on), bool(conducting), float(max_step), float(rtol), True), len(y))

    def average_rhs(t, y, p, duty):
        return returned(wasm.averageRhs(float(t), array(y), array(p), float(duty)))

    def jacobian(t, y, p, duty):
        return returned(wasm.jacobian(float(t), array(y), array(p), float(duty))).reshape(len(y), len(y))

    def sdirk(t, y, h, p, duty, inverse):
        data = wasm.sdirk(float(t), array(y), float(h), array(p), float(duty), array(inverse)).to_py()
        return np.asarray(data['state']), bool(data['ok'])

    def average_integrate(t, end, y, p, duty, rtol, max_step, jac, cache):
        data = wasm.averageIntegrate(float(t), float(end), array(y), array(p), float(duty), float(rtol), float(max_step), array(jac)).to_py()
        return (np.asarray(data['times']), np.asarray(data['states']).reshape(data['count'], len(y)).T.copy(),
                int(data['nfev']), int(data['code']), np.asarray(data['jac']).reshape(len(y), len(y)))

    def average_records(times, states, p, duty):
        ts = array(times)
        return returned(wasm.records(ts, array(np.asarray(states).T), len(states), array(p), True, True, float(duty), True)).reshape(len(ts), 15)

    def average_record(t, y, p, duty):
        return average_records([t], np.asarray(y)[:, None], p, duty)[0]

    def append_points(times, values, period, *state):
        # Called in batches of up to 4096 accepted points, never per PWM edge.
        channels = len(state[2])
        capacity = len(state[-3])
        packed = np.concatenate([np.asarray(a, dtype=np.float64).ravel() for a in state])
        result = returned(wasm.waveform(array(times), array(values), float(period), channels, capacity, packed))
        offset = 0
        for target in state:
            size = target.size
            target[:] = result[offset:offset + size].reshape(target.shape)
            offset += size

    plant._nodes = nodes
    plant._rhs = rhs
    plant._integrate = integrate
    plant.record_observation = record
    plant.record_observations = records
    fast_integrator._integrate = legacy_integrate
    tuning_simulator._rhs = average_rhs
    tuning_simulator._jacobian = jacobian
    tuning_simulator._sdirk = sdirk
    tuning_simulator._integrate = average_integrate
    tuning_simulator._observe = average_record
    tuning_simulator._observations = average_records
    waveform_summary._append_points = append_points
