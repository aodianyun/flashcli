# flashcli-bundle

Minimal Python package for **Model Bundle** authors and runtime entry modules (`run.py`, `serve.py`).

**Not published on PyPI.** Install from this git repo (subdirectory) or editable checkout only.

## Install

**End users** — `install.sh` / `auto_install.sh` install `flashcli-bundle` from git, then `flashcli` with `--no-deps`:

```bash
curl -fsSL https://raw.githubusercontent.com/aodianyun/flashcli/main/install.sh | sh
# mirror: ... | sh -s -- --mirror
```

Manual equivalent:

```bash
pip install "flashcli-bundle @ git+https://github.com/aodianyun/flashcli.git@main#subdirectory=flashcli-bundle"
pip install --no-deps "flashcli @ git+https://github.com/aodianyun/flashcli.git@main"
pip install typer pyyaml packaging 'huggingface_hub>=0.26' tqdm fastapi 'uvicorn[standard]'
```

**Bundle authors / monorepo dev:**

```bash
# same git repo as flashcli
pip install -e ./flashcli-bundle
pip install -e .
```

**From git (protocol package only):**

```bash
pip install "flashcli-bundle @ git+https://github.com/aodianyun/flashcli.git@main#subdirectory=flashcli-bundle"
```

Bundle venvs get the same git spec via `~/.flashcli/install.env` (`FLASHCLI_INSTALL_REPO` / `FLASHCLI_INSTALL_REF`) or the host install’s `direct_url.json`.

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
