"""Protocol version shared by flashcli host and bundle entry modules."""

from __future__ import annotations

PROTOCOL_VERSION = 1

# On-disk cache schema (bundle tree + weights paths + resolver behavior).
#
# Bump when it changes so the host can upgrade an already-created bundle venv's
# ``flashcli-bundle`` in place (the venv fingerprint does not track the
# protocol's git ref).
#   v2: variant-independent keys ``<name>/<version>`` with per-variant weights
#       under ``weights_dir`` (docs/bundle_publish_standard.md §4.4.1).
#   v3: resolve the variant ``weights_dir`` from the raw block (scalar), not the
#       dict-only ``variant_section`` helper.
CACHE_SCHEMA_VERSION = 5

# Native model-runtime face (`frt_model_runtime_v1`). Mirrors
# FRT_MODEL_RUNTIME_ABI_VERSION in FlashRT's runtime/include/flashrt/model_runtime.h.
RUNTIME_ABI_VERSION = 1

# Process framing used by `entry.kind == "native-exec"` (see docs/bundle_execution_abi.md).
EXEC_PROTOCOL_VERSION = 1

__version__ = "0.3.3"
