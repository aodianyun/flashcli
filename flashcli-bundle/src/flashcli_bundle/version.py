"""Protocol version shared by flashcli host and bundle entry modules."""

from __future__ import annotations

PROTOCOL_VERSION = 1

# Native model-runtime face (`frt_model_runtime_v1`). Mirrors
# FRT_MODEL_RUNTIME_ABI_VERSION in FlashRT's runtime/include/flashrt/model_runtime.h.
RUNTIME_ABI_VERSION = 1

# Process framing used by `entry.kind == "native-exec"` (see docs/bundle_execution_abi.md).
EXEC_PROTOCOL_VERSION = 1

__version__ = "0.2.0"
