# atlas/src/atlas/__init__.py

# Standard Modules
from functools import wraps
from typing import Optional

# Internal Modules
from atlas.core.atlas import Atlas
from atlas.utils.config import load_config

__all__ = ["Atlas", "track", "locate", "survey", "erect", "transit"]

_atlas: Optional[Atlas] = None


# Lazily build the module-level default Atlas instance from config
def _get_atlas() -> Atlas:
    global _atlas
    if _atlas is None:
        ephe_path = load_config().get("ephemeris", {}).get("path", "")
        _atlas = Atlas(ephe_path=ephe_path)
    return _atlas


# Build a module-level function that forwards straight to a method on the default Atlas instance
def _facade(method_name: str):
    @wraps(getattr(Atlas, method_name))
    def call(*args, **kwargs):
        return getattr(_get_atlas(), method_name)(*args, **kwargs)

    return call


track   = _facade("track")
locate  = _facade("locate")
survey  = _facade("survey")
erect   = _facade("erect")
transit = _facade("transit")
