# flashcli-bundle

Minimal Python package for **Model Bundle** authors and runtime entry modules (`run.py`, `serve.py`).

**Not published on PyPI.** Install from this git repo (subdirectory) or editable checkout only.

## Install

The **host** is a static Go binary (`flashcli`); this package is only for bundle
venvs and bundle authors.

**End users** — install the host with `install.sh`; bundle venvs receive
`flashcli-bundle[infer]` on demand:

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
# mirror: curl -fsSL https://gitee.com/aodiansoft/flashcli/raw/main/install.sh | sh -s -- --mirror
```

**Bundle authors / monorepo dev:**

```bash
./install.sh --from-source          # build+install the Go host (or: bash scripts/build_go.sh)
pip install -e "./flashcli-bundle"   # protocol (build, validate, tests)
# optional: infer subprocess tests
pip install -e "./flashcli-bundle[infer]"
```

**From git (protocol + infer runtime):**

```bash
pip install "flashcli-bundle[infer] @ git+https://github.com/aodianyun/flashcli.git@main#subdirectory=flashcli-bundle"
```

Bundle venvs resolve `flashcli-bundle[infer]` from `FLASHCLI_BUNDLE_PIP_SPEC`, a local
`flashcli-bundle/` checkout, or `~/.flashcli/install.env` (`FLASHCLI_INSTALL_REPO` + `FLASHCLI_INSTALL_REF`).

## Usage in bundle entry code

```python
from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults
from flashcli_bundle.protocol import ChatRequest, RunEngine
```

Manifest field:

```json
"protocol_version": 1
```

Must match `flashcli_bundle.version.PROTOCOL_VERSION` in the installed package.

See [docs/bundle_publish_standard.md](../docs/bundle_publish_standard.md) (publish spec) and [docs/model_bundle_standard.md](../docs/model_bundle_standard.md) (preset ref + runtime flow).
