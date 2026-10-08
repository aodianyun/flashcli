# Bundle execution ABI (language-agnostic)

<p align="right"><strong>English</strong> · <a href="bundle_execution_abi.zh-CN.md">简体中文</a></p>

Authoritative contract for **how flashcli invokes a bundle's inference entry**, independent of the implementation language. Today every bundle is Python (`python -m flashcli_bundle.infer`); this document adds a language-agnostic layer so a bundle may ship a native process or a native library instead — **without changing what end users type**.

Related: [bundle_publish_standard.md](bundle_publish_standard.md) (manifest fields), [architecture.md](architecture.md) (runtime flow), [module_layers.md](module_layers.md) (module placement).

---

## 1. Scope and non-goals

**In scope.** The `entry` contract, its new `kind` selector, the manifest version axes, and the lifecycle/env/IO rules each kind must obey. The host reads the manifest and drives whichever kind the bundle declares.

**Non-goals.**

- The host stays the same for users: `flashcli run|serve|pull|doctor|venv <ref>` is unchanged. `kind` is a manifest detail, never a user argument.
- This document does **not** define model math. Native producers own their forward passes (FlashRT / FlashRT-Nexus); flashcli only orchestrates.
- The Python backend's existing behavior (engine/script mode, `RunEngine`/`ServeEngine`) is unchanged and remains the compatibility baseline.

---

## 2. Version axes

Three independent, additive-only versions. A host must accept a bundle when all axes it understands match; unknown **new** values are a hard error with an upgrade hint.

| Field | Location | Meaning | Current |
|-------|----------|---------|---------|
| `protocol_version` | manifest top level (existing) | `flashcli_bundle` Python protocol (manifest/preset types) | `1` |
| `runtime_abi_version` | manifest top level (new) | Native **model-runtime** face (`frt_model_runtime_v1`) | `1` |
| `exec_protocol_version` | manifest top level (new) | Native **process** framing (`native-exec`) | `1` |

Rules:

- `protocol_version` is required on every bundle (already enforced).
- `runtime_abi_version` is **required** when any `entry.*.kind == "native-abi"`; otherwise it must be absent.
- `exec_protocol_version` is **required** when any `entry.*.kind == "native-exec"`; otherwise it must be absent.
- Values must equal the host's supported constant. `runtime_abi_version` mirrors `FRT_MODEL_RUNTIME_ABI_VERSION` (`/app/FlashRT/runtime/include/flashrt/model_runtime.h`, currently `1u`).

---

## 3. `entry.kind`

`entry` keeps its existing shape. One new optional field per capability block selects the backend.

```jsonc
"entry": {
  "kind": "python",              // optional; default for both capabilities
  "native": { /* shared native spec, see §6/§7 */ },
  "run":   { "module": "run",   "attr": "RunEngine" },
  "serve": { "module": "serve", "attr": "ServeEngine" }
}
```

| `kind` | Meaning | Selects | Introduced |
|--------|---------|---------|------------|
| `python` | In-process Python entry via bundle venv re-exec (default) | §5 | v0 (unchanged) |
| `native-exec` | Host spawns a separate executable; talks over stdio or HTTP | §6 | this spec |
| `native-abi` | Host `dlopen`s a model-runtime `.so` and drives it in-process | §7 | this spec |

**Resolution (per capability):**

1. `kind = block.kind` if present, else `entry.kind`, else `"python"`.
2. A capability may override the entry-level kind (e.g. `run` native, `serve` python).
3. Native config = `block.native` deep-merged over `entry.native` (objects merge; scalars/lists replace). `block` wins.
4. When `kind == "python"`, `module`/`attr` (and optional `mode`) are required exactly as today.
5. When `kind != "python"`, the native spec must be resolvable; Python-only fields (`module`/`attr`/`mode`) are ignored if present.
6. An unknown `kind` is a **hard error** (never silently fall back to Python).

Capabilities are still inferred: a `run` block enables `flashcli run`, a `serve` block enables `flashcli serve`.

---

## 4. Common lifecycle (all kinds)

At invocation time the host has already: resolved the ref, synced the bundle tree, selected the matching `runtime/<env-key>/`, created the bundle venv (Python is still required to build the infer venv for the Python kind and as the general runtime), downloaded/validated weights, and applied manifest `env`. The kind only changes **how the entry is started and driven**.

Shared guarantees:

- **Weight paths** follow §4.4.1 of [bundle_publish_standard.md](bundle_publish_standard.md). Native script-like starts (i.e. `native-exec`) receive the same `FLASHCLI_CHECKPOINT` / `FLASHCLI_BUNDLE_ROOT` / `FLASHCLI_PRESET` / `FLASHCLI_VARIANT` / `FLASHCLI_EXTRA_WEIGHT_<KEY>` variables. `native-abi` receives the checkpoint path through `open_symbol`'s `config_json`.
- **`run_options` / `serve_options`** remain the single source of defaults and `--help`, regardless of kind. The host maps them to the native call (payload fields or CLI args).
- **Weights stay offline at inference**: `HF_HUB_OFFLINE=1` semantics apply to Python and to any hub access; missing assets are fixed by `flashcli pull`, not at inference time.
- **Exit/readiness**: the host surfaces a non-zero exit or failed readiness as a CLI error; it never reports success on a crashed backend.

---

## 5. `python` backend (baseline, unchanged)

The host re-execs into the bundle venv and runs `python -m flashcli_bundle.infer run|serve` with `entry.<cap>.module` / `.attr` / `.mode`. Engine vs script env rules (§4.4) are unchanged. Bundles without `entry.kind` behave exactly as before — **this is the compatibility guarantee for all existing bundles.**

---

## 6. `native-exec` backend

The host starts an external process and communicates over a framed channel. This is the **process** lane: strong fault isolation, language freedom, at the cost of serialization.

### 6.1 Native spec

```jsonc
"entry": {
  "kind": "native-exec",
  "native": {
    "command": ["bin/pi05_server", "--checkpoint", "{checkpoint}"],
    "cwd": "bundle",                       // "bundle" (default) | absolute
    "transport": "stdio",                  // "stdio" (default) | "http"
    "ready_timeout_sec": 120,              // optional
    "shutdown_timeout_sec": 10,            // optional
    "env": { "MY_FLAG": "1" }              // optional literal env (no placeholders)
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `command` | yes | argv array. `argv[0]` is resolved relative to the bundle root unless absolute (or contains `/`). |
| `cwd` | no | `bundle` (default) = bundle root. Only `bundle` or an absolute path is allowed. |
| `transport` | no | `stdio` (default) or `http`. |
| `ready_timeout_sec` | no | Seconds to wait for readiness before failing (default 120). |
| `shutdown_timeout_sec` | no | Grace after SIGTERM before SIGKILL (default 10). |
| `env` | no | Literal extra env vars; placeholders are **not** expanded here. |

**Placeholders** are allowed inside `command` args: `{checkpoint}`, `{bundle_root}`, `{models_dir}`, `{variant}`, `{preset}`, `{extra:<key>}`.

### 6.2 stdio transport

NDJSON over stdin/stdout, UTF-8, one JSON object per line, no embedded newlines. stderr is logs (never protocol).

Request: `{"v":1,"id":<int>,"op":"run"|"health"|"shutdown","payload":{...}}`
Response: `{"v":1,"id":<int>,"ok":true,"payload":{...}}` or `{"v":1,"id":<int>,"ok":false,"error":{"code":<int>,"message":<str>}}`
Readiness: the process emits `{"v":1,"op":"ready","payload":{...}}` before serving. `health` must be answered within `ready_timeout_sec`.

### 6.3 http transport

The process binds an endpoint (host/port chosen by the host, passed via env or `command` placeholders) and prints a readiness line `{"v":1,"op":"ready","endpoint":"<url>"}` to stdout. The host:
- **run**: `POST /run` with the run payload, read the response, then `shutdown`.
- **serve**: supervise the process and forward traffic (or hand the endpoint to the user) until SIGINT; then graceful shutdown.

### 6.4 Lifecycle

1. Spawn with the shared env (§4) + literal `env`, `cwd`.
2. Wait for readiness; on timeout, terminate and fail.
3. Drive `run` (one or more requests) or `serve` (until interrupted).
4. On stop: send `shutdown` (stdio) or SIGTERM (http); wait `shutdown_timeout_sec`; SIGKILL if needed.
5. Non-zero exit before readiness is a bundle error.

---

## 7. `native-abi` backend

The host `dlopen`s a model-runtime shared library and drives it **in-process**. This is the **library** lane: microsecond call latency and live-state snapshot/restore, at the cost of shared address space and stricter ABI coupling. It reuses the FlashRT `frt_model_runtime_v1` face adopted by FlashRT-Nexus.

### 7.1 Native spec

```jsonc
"entry": {
  "kind": "native-abi",
  "native": {
    "library": "{runtime_dir}/substrate/libflashrt_cpp_pi05_c-*.so",
    "open_symbol": "frt_model_runtime_open_v1",   // default
    "preload": [
      "{runtime_dir}/substrate/libflashrt_exec-*.so",
      "{runtime_dir}/substrate/libcapsule_nexus_flashrt-*.so"
    ],
    "config": { "precision": "{option:precision}" }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `library` | yes | Model-runtime `.so`; a single glob match. Placeholders allowed; `{runtime_dir}` = the selected `runtime/<env-key>/`. |
| `open_symbol` | no | Factory symbol; default `frt_model_runtime_open_v1`. |
| `preload` | no | Ordered list of shared libraries loaded `RTLD_GLOBAL` **before** `library`. Each entry is one glob match. |
| `config` | no | Object serialized to JSON and passed as `config_json` to `open_symbol`. Placeholders allowed, notably `{option:<name>}` from `run_options`/`serve_options`. |

### 7.2 Factory contract

`library` must export exactly `FRT_MODEL_RUNTIME_OPEN_V1_SYMBOL` (`"frt_model_runtime_open_v1"`):

```c
typedef int (*frt_model_runtime_open_v1_fn)(const char* config_json,
                                            frt_model_runtime_v1** out);
```

Returns `0` and a **retained** object on success. The host releases it exactly once via the object's `release(owner)`.

### 7.3 ABI prefix rules (additive-only)

The host reads the returned `frt_model_runtime_v1`:

1. `abi_version` must equal the host's `FRT_MODEL_RUNTIME_ABI_VERSION` (`runtime_abi_version` in the manifest).
2. `struct_size` must be `>= FRT_MODEL_RUNTIME_V1_BASE_SIZE` (anchored to the last v1 baseline field, `release`).
3. The additive tail (`query_extension`) may be read only after probing `struct_size >= FRT_MODEL_RUNTIME_V1_QUERY_EXTENSION_SIZE`; never assume `sizeof`.
4. Verbatim "hot contract": updating SWAP/STAGED ports between replays must not recapture, allocate, or rebind (see `capsule/model_runtime.h`).

### 7.4 Drive face

The host drives the adopted runtime through the **capsule** face (`FlashRT-Nexus/host/include/capsule/model_runtime.h`), not the raw producer structs:

- ports: `cap_model_n_ports`, `cap_model_port_*`, `cap_model_set_input`, `cap_model_get_output`, `cap_model_find_port`
- execution: `cap_model_tick`, `cap_model_fire`, `cap_model_execute_stage`
- state: `cap_model_state_status`, `cap_model_snapshot`, `cap_model_restore`, `cap_model_restore_into`
- identity: `cap_model_fingerprint`, `cap_model_identity`

`snapshot`/`restore` map to `flashcli serve` session endpoints; OPAQUE/step-only runtimes fail closed rather than fabricate snapshot semantics.

### 7.5 Single-SONAME constraint

A process may load **only one** `libflashrt_exec` (`libflashrt_exec.so.1`). The host must:

1. Load `preload` entries in order, `RTLD_GLOBAL`.
2. Load `library` last.
3. Refuse to load a second bundle's `libflashrt_exec` in the same process (hard error, not a stale handle).

This is why `native-abi` serves **one** bundle per process. Multi-bundle scheduling is a separate process concern.

---

## 8. Manifest validation rules

A bundle is invalid when any of these hold:

- `kind` is present but not one of `python` / `native-exec` / `native-abi`.
- `kind == "native-exec"` and (`command` missing, `transport` not in {stdio, http}, or `exec_protocol_version` absent).
- `kind == "native-abi"` and (`library` missing, `runtime_abi_version` absent/wrong, or `open_symbol` not a valid C identifier).
- `runtime_abi_version` / `exec_protocol_version` present without a matching native kind.
- A `command`/`library`/`preload` glob matches zero or more than one file at invoke time.
- Mixed kinds where a native capability lacks its own or an inherited native spec.
- A native-only bundle that also declares native Python entry fields is allowed (ignored), but a `python` capability without `module`/`attr` is invalid.

Validation is forward-compatible: an **old** host that does not know a `kind` must fail with an "upgrade flashcli" message, never execute it as Python.

---

## 9. Conformance suite

`tests/conformance/` holds one fixture bundle per kind plus a shared, language-neutral runner. Every host implementation (Python today, Go in the migration) must pass the same matrix, so the two hosts cannot drift.

| Fixture | Kind | What it proves |
|---------|------|----------------|
| `python_echo/` | `python` | Baseline engine/script entry, options plumbing, weight env |
| `exec_echo/` | `native-exec` | Spawn, readiness, NDJSON run, graceful shutdown, env/placeholders |
| `abi_echo/` | `native-abi` | `dlopen` ordering, `frt_model_runtime_open_v1`, ABI prefix probe, tick/snapshot |

The `abi_echo` fixture ships a tiny C source compiled by the test when a C compiler is available (skipped otherwise); `exec_echo` uses a stdlib-only stub so it stays portable. Fixtures declare the same logical request/response shape so a single runner can assert semantic equivalence across kinds.

---

## 10. Rollout rules

- **Additive only.** No existing field changes meaning. Bundles without `entry.kind`, `runtime_abi_version`, or `exec_protocol_version` are untouched.
- **Default is Python.** Absent `kind` behaves exactly as today.
- **Fail closed.** Unknown kinds and version mismatches abort with an upgrade hint.
- **Publish standard** gains this section's fields in a later revision; until then this document is authoritative for the native kinds.
