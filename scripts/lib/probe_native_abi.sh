# Probe whether a pybind .so matches the given Python interpreter ABI.
#   source scripts/lib/probe_native_abi.sh
#   probe_native_so_python_abi /usr/bin/python3.11 /path/to/mod-py311.so
# Exit: 0 = ABI OK, 2 = Python version mismatch, other = probe error.

probe_native_so_python_abi() {
  local py_bin="$1" so_path="$2"
  "${py_bin}" - "${so_path}" <<'PY'
import importlib.util
import sys

path = sys.argv[1]
spec = importlib.util.spec_from_file_location("flashcli_native_probe", path)
if spec is None or spec.loader is None:
    raise SystemExit("cannot create extension spec")
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except ImportError as exc:
    msg = str(exc)
    if "Python version mismatch" in msg or "interpreter version is incompatible" in msg:
        print(msg, file=sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(0) from exc
PY
}
