# Model catalog

The preset catalog lives in a single file (also shipped inside the pip wheel):

**[`../src/flashcli/catalog/models.yaml`](../src/flashcli/catalog/models.yaml)**

Edit that file to add presets or change each preset's `bundle.zip` / `path` / `git` source.

Override at runtime: `export FLASHCLI_MODELS_YAML=/path/to/models.yaml` (see [docs/environment.zh-CN.md](../docs/environment.zh-CN.md)).
