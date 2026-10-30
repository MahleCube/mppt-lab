"""Build browser numerical kernels with Zig (wasm32-wasi, IEEE doubles)."""
import argparse
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
EXPORTS = ('k_curves k_l k_c k_iph k_ipv k_nodes k_rhs k_record k_records '
           'k_integrate k_legacy_integrate k_result_count k_result_steps '
           'k_result_nfev k_result_code k_result_times k_result_states '
           'k_average_rhs k_jacobian k_sdirk k_average_integrate k_waveform malloc free').split()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zig', nargs='?', default=shutil.which('zig'))
    parser.add_argument('--output', type=Path, default=HERE / 'kernels.wasm')
    args = parser.parse_args()
    if not args.zig:
        parser.error('Pass the Zig compiler path or add zig to PATH.')
    subprocess.run([args.zig, 'cc', '-target', 'wasm32-wasi', '-mexec-model=reactor',
                    '-O2', '-g0', '-fno-fast-math', '-ffp-contract=off', '-Wall', '-Wextra',
                    '-Wl,--strip-all',
                    '-Wl,--export-memory', '-Wl,--max-memory=536870912',
                    '-Wl,-z,stack-size=1048576',
                    *['-Wl,--export=' + name for name in EXPORTS],
                    str(HERE / 'kernels.c'), '-o', str(args.output)], check=True)
    print('Built', args.output.name)


if __name__ == '__main__':
    main()
