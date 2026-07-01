"""Entry: python -m flashcli_bundle.infer run|serve …"""

from flashcli_bundle.infer.app import main
from flashcli_bundle.entry_env import apply_offline_hub_env
from flashcli_bundle.runtime.mirror import apply_mirror_env

apply_mirror_env()
apply_offline_hub_env()

if __name__ == "__main__":
    main()
