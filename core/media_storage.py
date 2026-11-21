"""Keep media processing scratch files and model caches on the chosen media drive."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def media_cache_dir(media_root: str | Path) -> Path:
    return Path(media_root).expanduser().resolve() / ".streamcarnia" / "cache"


def configure_media_storage(media_root: str | Path, *, configure_tempfile: bool = False) -> Path:
    """Point model/tool caches and child-process temp files at a media folder.

    Call before importing model runtimes. Preferences and OS-managed credentials
    intentionally remain in their normal per-user/secure locations.
    """
    cache = media_cache_dir(media_root)
    huggingface = cache / "huggingface"
    tmp = cache / "tmp"
    torch = cache / "torch"
    for directory in (huggingface / "hub", huggingface / "xet", huggingface / "assets",
                      tmp, torch, cache / "xdg"):
        directory.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(huggingface)
    os.environ["HF_HUB_CACHE"] = str(huggingface / "hub")
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(huggingface / "hub")
    os.environ["TRANSFORMERS_CACHE"] = str(huggingface / "hub")
    os.environ["HF_XET_CACHE"] = str(huggingface / "xet")
    os.environ["HF_ASSETS_CACHE"] = str(huggingface / "assets")
    os.environ["TORCH_HOME"] = str(torch)
    os.environ["XDG_CACHE_HOME"] = str(cache / "xdg")
    os.environ["TEMP"] = str(tmp)
    os.environ["TMP"] = str(tmp)
    os.environ["TMPDIR"] = str(tmp)
    os.environ["STREAMCARNIA_MEDIA_ROOT"] = str(Path(media_root).expanduser().resolve())
    os.environ["STREAMCARNIA_CACHE_DIR"] = str(cache)
    if configure_tempfile:
        tempfile.tempdir = str(tmp)
    return cache
