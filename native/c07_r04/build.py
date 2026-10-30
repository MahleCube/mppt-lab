"""Build the Windows x64 Lab bridge against the unchanged r04 core."""
import argparse
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE_HASHES = {
    "c07_control.c": "c01e9e996b52147758e683dfc6917f3ae77a6c333a683b92e115fe27c64dac1c",
    "c07_control.h": "4c17803faae480717b1f5d7d0b3a4510c950de96ab4ac06691f5ed0e33cf541d",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler", nargs="?", help="Path to zig, clang, or gcc; otherwise search PATH")
    parser.add_argument("--output", type=Path, default=HERE / "c07_lab.dll")
    args = parser.parse_args()
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        parser.error("Build with 64-bit Python on Windows.")
    for name, expected in SOURCE_HASHES.items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
            parser.error(f"{name} differs from the unchanged r04 source; build stopped.")
    compiler = args.compiler or next(
        (path for name in ("zig", "clang", "gcc") if (path := shutil.which(name))), None
    )
    if not compiler:
        parser.error("Pass a compiler path or add zig, clang, or gcc to PATH.")
    compiler = str(Path(shutil.which(compiler) or compiler).expanduser().resolve())
    if not Path(compiler).is_file():
        parser.error("The selected compiler was not found.")
    command = [compiler]
    if Path(compiler).stem.lower() == "zig":
        command += ["cc", "-target", "x86_64-windows-gnu"]
    else:
        command += ["-m64"]
    with tempfile.TemporaryDirectory(prefix="mppt-lab-r04-") as directory:
        dll = Path(directory) / "c07_lab.dll"
        subprocess.run(command + [
            "-std=c11", "-shared", "-O2", "-g0", "-Wall", "-Wextra", "-Werror",
            "-DC07_REAL_TYPE=double", "-DC07_SELECTION_DIAGNOSTICS=0",
            str(HERE / "c07_control.c"), str(HERE / "lab_bridge.c"),
            "-lm", "-o", str(dll),
        ], cwd=directory, check=True)
        # Test in a child process so Windows releases the DLL before copying it.
        subprocess.run([sys.executable, "-c", """
import ctypes, sys
library = ctypes.CDLL(sys.argv[1])
library.c07_lab_new.restype = ctypes.c_void_p
library.c07_lab_get.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
library.c07_lab_get.restype = ctypes.c_double
library.c07_lab_free.argtypes = [ctypes.c_void_p]
handle = library.c07_lab_new()
if not handle:
    raise RuntimeError("Controller allocation failed")
try:
    if library.c07_lab_get(handle, b"CONTROL_PERIOD_US") != 1001:
        raise RuntimeError("Controller initialization failed")
finally:
    library.c07_lab_free(handle)
""", str(dll)], check=True)
        shutil.copy2(dll, args.output.resolve())
    print(f"Built {args.output.name} (Windows x64).")


if __name__ == "__main__":
    main()
