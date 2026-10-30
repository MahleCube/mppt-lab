"""Build the unchanged c07 C cores for the browser with Zig's WASI target."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HASHES = {
    'r03': ('950d667a89a8865da36b372d256b26d5e7676344ad3e6281ec69d1afcea0a323',
            '98a3c86c2b43e16f10b5b4cd9e52faada522a3c6cdacfe5f69fb891d2a30e9af'),
    'r04': ('c01e9e996b52147758e683dfc6917f3ae77a6c333a683b92e115fe27c64dac1c',
            '4c17803faae480717b1f5d7d0b3a4510c950de96ab4ac06691f5ed0e33cf541d'),
}
EXPORTS = ['c07_lab_new', 'c07_lab_free', 'c07_lab_config', 'c07_lab_get',
           'c07_lab_start', 'c07_lab_step', 'c07_lab_begin', 'c07_lab_finish',
           'malloc', 'free']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zig', nargs='?', default=shutil.which('zig'), help='Path to Zig')
    args = parser.parse_args()
    if not args.zig:
        parser.error('Pass a Zig compiler path or add zig to PATH.')
    for version, hashes in HASHES.items():
        source = ROOT / 'native' / ('c07_' + version)
        for name, expected in zip(('c07_control.c', 'c07_control.h'), hashes):
            if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
                parser.error(f'{version}/{name}: unchanged source hash mismatch')
        output = HERE / ('c07_' + version + '.wasm')
        subprocess.run([args.zig, 'cc', '-target', 'wasm32-wasi', '-mexec-model=reactor',
                        '-std=c11', '-O2', '-g0', '-ffp-contract=off', '-Wall', '-Wextra', '-Werror',
                        '-DC07_REAL_TYPE=double', '-DC07_SELECTION_DIAGNOSTICS=0',
                        str(source / 'c07_control.c'), str(source / 'lab_bridge.c'),
                        '-lm', '-Wl,--strip-all',
                        *('-Wl,--export=' + name for name in EXPORTS), '-o', str(output)], check=True)
        print(output.name, hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
