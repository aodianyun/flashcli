# Create/list zip archives (zip CLI or python3 zipfile fallback).
#   source "${FLASHCLI_ROOT}/scripts/lib/make_zip.sh"
#   make_zip_archive STAGE_DIR ARCHIVE_TOP_DIR_NAME OUTPUT.zip

make_zip_archive() {
  local stage_dir="$1" top_name="$2" output="$3"
  if command -v zip >/dev/null 2>&1; then
    (cd "${stage_dir}" && zip -rq "${output}" "${top_name}")
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "${stage_dir}" "${top_name}" "${output}" <<'PY'
import sys
import zipfile
from pathlib import Path

stage = Path(sys.argv[1])
top = sys.argv[2]
out = Path(sys.argv[3])
root = stage / top
if not root.is_dir():
    raise SystemExit(f"missing staged dir: {root}")
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            zf.write(path, path.relative_to(stage))
PY
    return 0
  fi
  printf '[make_zip] ERROR: need `zip` or `python3` to create %s\n' "${output}" >&2
  return 1
}

list_zip_archive() {
  local zip_path="$1"
  if command -v zipinfo >/dev/null 2>&1; then
    zipinfo -1 "${zip_path}"
    return 0
  fi
  if command -v unzip >/dev/null 2>&1; then
    unzip -Z1 "${zip_path}"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "${zip_path}" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as zf:
    for name in zf.namelist():
        print(name)
PY
    return 0
  fi
  printf '[make_zip] WARN: cannot list %s (install zip/unzip or use python3)\n' "${zip_path}" >&2
  return 1
}
