"""Shared flashcli-bundle errors."""


class BundleNotReadyError(RuntimeError):
    exit_code = 2


class NativeHostAbiError(BundleNotReadyError):
    """Host glibc/libstdc++ cannot satisfy selected native ``.so`` ABI needs."""


class CudaUserlandError(BundleNotReadyError):
    """CUDA userland libs missing or unloadable for the selected native CUDA tag."""
