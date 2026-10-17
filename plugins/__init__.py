"""Public watcher classes, loaded on first access to keep optional imports lazy."""

from importlib import import_module

__all__ = ["BaseWatcher", "AldiTalkWatcher", "LidlConnectWatcher"]

_EXPORTS = {
    "BaseWatcher": ".base_watcher",
    "AldiTalkWatcher": ".aldi_talk",
    "LidlConnectWatcher": ".lidl_connect",
}
_OPTIONAL_DEPS = {
    "AldiTalkWatcher": {"aiohttp"},
    "LidlConnectWatcher": {"aiohttp", "playwright"},
}


def __getattr__(name: str):
    """Resolve and cache public classes without masking unrelated code errors."""
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        module = import_module(_EXPORTS[name], __name__)
    except ModuleNotFoundError as exc:
        if exc.name not in _OPTIONAL_DEPS.get(name, ()):
            raise
        hint = ""
        if exc.name == "playwright":
            hint = " Then run `python -m playwright install chromium` for the browser fallback."
        raise ImportError(
            f"{name} requires the optional dependency {exc.name!r}. "
            "Install runtime dependencies with "
            "`python -m pip install -r requirements.txt`." + hint
        ) from exc
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    """Include lazy exports in introspection without loading their modules."""
    return sorted(set(globals()) | set(__all__))
