"""Download, cache, and lazy-load in-process embedding models (fastembed)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import API_ROOT
from .local_catalog import CatalogEntry, get_catalog_entry, list_catalog

EMBEDDING_CACHE_DIR = API_ROOT / "data" / "embeddings"

# novel_id -> job state
_download_jobs: dict[str, "DownloadJob"] = {}
_jobs_lock = threading.Lock()

# modelId -> TextEmbedding-like instance
_model_cache: dict[str, Any] = {}
_model_lock = threading.Lock()

# Optional override for tests: (model_id, cache_dir) -> encoder
_encoder_factory: Callable[[str, Path], Any] | None = None


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def _format_bytes(n: int) -> str:
    if n >= 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024 * 1024):.2f} GB"
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


@dataclass
class DownloadJob:
    novel_id: str
    catalog_key: str
    state: str = "idle"  # idle | downloading | ready | error
    progress: float = 0.0
    message: str = ""
    model_id: str = ""
    error: str | None = None
    cache_path: str = ""
    bytes_downloaded: int = 0
    bytes_total_approx: int = 0
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "novelId": self.novel_id,
            "catalogKey": self.catalog_key,
            "state": self.state,
            "progress": round(self.progress, 3),
            "message": self.message,
            "modelId": self.model_id,
            "error": self.error,
            "cachePath": self.cache_path,
            "bytesDownloaded": self.bytes_downloaded,
            "bytesTotalApprox": self.bytes_total_approx,
        }


def set_encoder_factory(factory: Callable[[str, Path], Any] | None) -> None:
    """Test hook to avoid real ONNX downloads."""
    global _encoder_factory
    _encoder_factory = factory


def clear_runtime_state() -> None:
    """Reset caches (tests)."""
    with _jobs_lock:
        _download_jobs.clear()
    with _model_lock:
        _model_cache.clear()


def cache_dir_for(entry: CatalogEntry) -> Path:
    # One folder per catalog key keeps sizes predictable.
    path = EMBEDDING_CACHE_DIR / entry["key"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_model_downloaded(key: str) -> bool:
    entry = get_catalog_entry(key)
    if entry is None:
        return False
    from .download_source import model_ready_dir

    root = cache_dir_for(entry)
    if model_ready_dir(root, entry["modelId"]) is not None:
        return True
    # Legacy: any non-empty tree under cache (older fastembed pulls)
    if not root.exists():
        return False
    for item in root.rglob("*"):
        if item.is_file() and item.stat().st_size > 0 and item.name != ".nove-ready":
            # Ignore tiny marker-only dirs
            if item.stat().st_size > 1024:
                return True
    return False


def mark_model_downloaded_for_tests(key: str, *, content: bytes = b"ok") -> Path:
    """Create prepared files so is_model_downloaded returns True in tests."""
    from .download_source import manifest_for

    entry = get_catalog_entry(key)
    if entry is None:
        raise KeyError(key)
    root = cache_dir_for(entry)
    prepared = root / "prepared"
    prepared.mkdir(parents=True, exist_ok=True)
    manifest = manifest_for(entry["modelId"]) or {}
    required = list(manifest.get("required") or ["model_optimized.onnx", "tokenizer.json"])
    for rel in required:
        path = prepared / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content if len(content) > 0 else b"ok")
    (root / ".nove-ready").write_bytes(content)
    return root


def _prepared_bytes(cache_root: Path) -> int:
    """Count only prepared/ payload (+ .part). Ignore HF hub leftover blobs."""
    prepared = cache_root / "prepared"
    if prepared.is_dir():
        return _dir_size_bytes(prepared)
    return 0


def get_download_status(novel_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _download_jobs.get(novel_id)
        if job is None:
            return {
                "novelId": novel_id,
                "catalogKey": "",
                "state": "idle",
                "progress": 0.0,
                "message": "",
                "modelId": "",
                "error": None,
                "cachePath": str(EMBEDDING_CACHE_DIR.resolve()),
                "bytesDownloaded": 0,
                "bytesTotalApprox": 0,
            }
        # Optional soft refresh: only prepared/ size, never whole cache tree
        # (models--* hub leftovers would inflate past catalog estimate).
        if job.state == "downloading" and job.cache_path:
            try:
                prepared_size = _prepared_bytes(Path(job.cache_path))
                # Prefer the larger of reporter value vs prepared dir (resume/partial).
                if prepared_size > job.bytes_downloaded:
                    job.bytes_downloaded = prepared_size
                # Never let total stay below actual downloaded (fixes 1.6G / 655MB).
                if job.bytes_downloaded > job.bytes_total_approx > 0:
                    job.bytes_total_approx = job.bytes_downloaded
                job.touch()
            except OSError:
                pass
        return job.to_dict()


def _set_job(job: DownloadJob) -> None:
    job.touch()
    with _jobs_lock:
        _download_jobs[job.novel_id] = job


def _default_encoder_factory(model_id: str, cache_dir: Path) -> Any:
    from .download_source import ensure_cn_download_endpoint, model_ready_dir

    # Still set HF_ENDPOINT for any residual hub calls.
    ensure_cn_download_endpoint()
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "未安装 fastembed。请在 apps/api 执行: pip install fastembed"
        ) from exc

    prepared = model_ready_dir(cache_dir, model_id)
    if prepared is not None:
        # Skip hub/GCS entirely — load from our mirror-fetched directory.
        return TextEmbedding(
            model_name=model_id,
            cache_dir=str(cache_dir),
            specific_model_path=str(prepared),
        )
    # Fallback: let fastembed try (may fail offline / without mirror-friendly hub).
    return TextEmbedding(model_name=model_id, cache_dir=str(cache_dir))


def load_encoder(model_id: str, *, catalog_key: str | None = None) -> Any:
    """Lazy-load and cache a TextEmbedding-compatible encoder."""
    with _model_lock:
        cached = _model_cache.get(model_id)
        if cached is not None:
            return cached

    entry = get_catalog_entry(catalog_key) if catalog_key else None
    if entry is None:
        from .local_catalog import get_catalog_entry_by_model_id

        entry = get_catalog_entry_by_model_id(model_id)
    if entry is None:
        # Allow raw model_id with a generic cache folder.
        cache_dir = EMBEDDING_CACHE_DIR / model_id.replace("/", "__")
        cache_dir.mkdir(parents=True, exist_ok=True)
    else:
        cache_dir = cache_dir_for(entry)

    factory = _encoder_factory or _default_encoder_factory
    encoder = factory(model_id, cache_dir)
    with _model_lock:
        _model_cache[model_id] = encoder
    return encoder


def ensure_model_files(
    entry: CatalogEntry,
    progress: Callable[[float, str, int], None],
    *,
    stop_event: threading.Event | None = None,
) -> Path:
    """Download weights into cache if missing (direct CN mirror), then warm encoder.

    progress(value 0..1, message, bytes_downloaded).
    Returns the cache directory path.
    """
    from .download_source import download_model_direct, manifest_for, model_ready_dir

    cache_dir = cache_dir_for(entry)
    progress(0.05, f"准备下载 {entry['name']}…", _dir_size_bytes(cache_dir))

    # Test hook: skip real network
    if _encoder_factory is not None:
        progress(0.5, "测试模式：跳过真实下载", 0)
        load_encoder(entry["modelId"], catalog_key=entry["key"])
        if not is_model_downloaded(entry["key"]):
            mark_model_downloaded_for_tests(entry["key"])
        progress(1.0, "下载完成", _prepared_bytes(cache_dir) or 0)
        return cache_dir

    prepared = model_ready_dir(cache_dir, entry["modelId"])
    if prepared is None and manifest_for(entry["modelId"]) is not None:
        # Direct HTTPS from hf-mirror (does not use huggingface_hub).
        def dl_progress(
            value: float,
            message: str,
            nbytes: int,
            total: int | None = None,
        ) -> None:
            try:
                progress(value, message, nbytes, total)  # type: ignore[misc]
            except TypeError:
                progress(value, message, nbytes)

        prepared = download_model_direct(
            entry["modelId"],
            cache_dir,
            on_progress=dl_progress,
        )
    elif prepared is not None:
        size = _dir_size_bytes(prepared)
        progress(0.7, f"本地已有缓存：{prepared}", size, size)
    else:
        progress(0.2, "无直链清单，回退 fastembed 下载…", _prepared_bytes(cache_dir))

    ready_size = _prepared_bytes(cache_dir)
    progress(0.92, "正在加载本地模型…", ready_size, ready_size or None)
    load_encoder(entry["modelId"], catalog_key=entry["key"])

    size = _prepared_bytes(cache_dir)
    progress(1.0, f"下载完成（{_format_bytes(size)}）", size, size or None)
    return cache_dir


def start_download_job(
    *,
    novel_id: str,
    catalog_key: str,
    on_complete: Callable[[CatalogEntry], None],
    on_error: Callable[[str], None] | None = None,
) -> DownloadJob:
    entry = get_catalog_entry(catalog_key)
    if entry is None:
        raise KeyError(f"unknown catalog key: {catalog_key}")

    with _jobs_lock:
        existing = _download_jobs.get(novel_id)
        if existing and existing.state == "downloading":
            return existing

    cache_dir = cache_dir_for(entry)
    job = DownloadJob(
        novel_id=novel_id,
        catalog_key=catalog_key,
        state="downloading",
        progress=0.0,
        message="排队下载…",
        model_id=entry["modelId"],
        cache_path=str(cache_dir.resolve()),
        bytes_downloaded=0,
        bytes_total_approx=int(entry.get("sizeBytesApprox") or 0),
    )
    _set_job(job)

    def runner() -> None:
        try:

            def progress(
                value: float,
                message: str,
                bytes_downloaded: int = 0,
                bytes_total: int | None = None,
            ) -> None:
                job.progress = max(job.progress, max(0.0, min(1.0, value)))
                job.message = message
                job.state = "downloading"
                if bytes_downloaded:
                    job.bytes_downloaded = bytes_downloaded
                if bytes_total and bytes_total > 0:
                    job.bytes_total_approx = bytes_total
                elif job.bytes_downloaded > job.bytes_total_approx:
                    job.bytes_total_approx = job.bytes_downloaded
                _set_job(job)

            ensure_model_files(entry, progress)
            on_complete(entry)
            job.state = "ready"
            job.progress = 1.0
            if job.cache_path:
                job.bytes_downloaded = _prepared_bytes(Path(job.cache_path)) or job.bytes_downloaded
            if job.bytes_downloaded > job.bytes_total_approx:
                job.bytes_total_approx = job.bytes_downloaded
            job.message = f"已启用本地 Embedding（{job.cache_path}）"
            job.error = None
            _set_job(job)
        except Exception as exc:  # noqa: BLE001 — surface to UI
            job.state = "error"
            job.error = str(exc)
            job.message = f"下载失败：{exc}"
            _set_job(job)
            if on_error:
                on_error(str(exc))

    thread = threading.Thread(target=runner, name=f"embed-dl-{novel_id[:8]}", daemon=True)
    thread.start()
    return job


def catalog_with_download_flags() -> dict[str, Any]:
    from .download_source import download_source_meta, ensure_cn_download_endpoint
    from .local_catalog import catalog_public_row

    ensure_cn_download_endpoint()
    source = download_source_meta()
    rows: list[dict[str, Any]] = []
    for entry in list_catalog():
        row = catalog_public_row(entry, downloaded=is_model_downloaded(entry["key"]))
        row["cachePath"] = str(cache_dir_for(entry).resolve())
        row["cacheRoot"] = str(EMBEDDING_CACHE_DIR.resolve())
        row["downloadSource"] = source["label"]
        row["hfEndpoint"] = source["hfEndpoint"]
        rows.append(row)
    return {"items": rows, "downloadSource": source}
