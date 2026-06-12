# flashcli-bundle

Minimal Python package for **Model Bundle** authors and runtime entry modules (`run.py`, `serve.py`).

## Install

**End users** — installed automatically with flashcli (`install.sh` or `pip install flashcli`).

**Bundle authors / monorepo dev:**

```bash
# same git repo as flashcli
pip install -e ./flashcli-bundle
pip install -e .
```

**From git (without full flashcli checkout):**

```bash
pip install "flashcli-bundle @ git+https://github.com/aodianyun/flashcli.git@main#subdirectory=flashcli-bundle"
```

PyPI publish is optional; git subdirectory install is enough for internal teams.

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

See [docs/bundle_builder_guide.md](../docs/bundle_builder_guide.md) (full build/release walkthrough) and [docs/model_bundle_standard.md](../docs/model_bundle_standard.md).
