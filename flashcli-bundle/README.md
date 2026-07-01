# flashcli-bundle

Minimal Python package for **Model Bundle** authors and runtime entry modules (`run.py`, `serve.py`).

**Not published on PyPI.** Install from this git repo (subdirectory) or editable checkout only.

## Install

**End users** — `install.sh` installs `flashcli-bundle` on the host and `flashcli-bundle[infer]` in bundle venvs:

```bash
curl -fsSL https://cli.flashhub.top/flashcli/auto_install.sh | sh
# mirror: ... | sh -s -- --mirror
```

Manual equivalent (host CLI venv only — **do not** install these into bundle venvs):

```bash
pip install "flashcli-bundle @ git+https://github.com/aodianyun/flashcli.git@main#subdirectory=flashcli-bundle"
pip install --no-deps "flashcli @ git+https://github.com/aodianyun/flashcli.git@main"
# flashcli pulls host deps (typer, huggingface_hub, …) via install.sh / deps.ensure_flashcli_core_stack
```

**Bundle authors / monorepo dev:**

```bash
# host CLI + protocol (build, validate, pull, run from repo)
pip install -e "./flashcli-bundle"
pip install -e ".[dev]"
# optional: infer subprocess tests
pip install -e "./flashcli-bundle[infer]"
```

**From git (protocol + infer runtime):**

```bash
pip install "flashcli-bundle[infer] @ git+https://github.com/aodianyun/flashcli.git@main#subdirectory=flashcli-bundle"
```

Bundle venvs pip-install `flashcli-bundle[infer]` via `ensure_flashcli_bundle_in_venv()` (see `~/.flashcli/install.env` for git source).

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
