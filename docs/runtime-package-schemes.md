# flashcli runtime packaging (implemented)

<p align="right"><a href="runtime-package-schemes.zh-CN.md">简体中文</a></p>

**Current implementation (`format_version: 3`):**

| Capability | Implementation |
|------------|----------------|
| Manifest-first | FlashHub repo API → fetch `flashcli-bundle.json` → preflight |
| Split download | Bundle source tree + **only** this host’s `runtime/<env-key>/` |
| Fixed Python ABI | `python_abi` in manifest; dedicated bundle venv |
| Dependency isolation | `~/.flashcli/runtimes/<id>/venv/` per bundle (torch, etc.) |
| Host flashcli | **One** install in host venv; bundle infer loads it via `PYTHONPATH` — not pip-installed into bundle venv |
| Inference process | Host CLI prepares runtime → **re-exec** `bundle_venv/python -m flashcli.runtime.infer` |

Catalog uses semantic FlashHub URLs, e.g.  
`https://flashhub.aodianyun.com/api/v1/repos/flashcli-bundle/pi05_libero/1.0.2`

See [model_bundle_standard.md](model_bundle_standard.md).
