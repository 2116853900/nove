"""China-friendly download of embedding weights.

``huggingface_hub`` often fails in mainland China even with HF_ENDPOINT set
(metadata HEAD checks still hit huggingface.co). We download files ourselves
via direct HTTPS from hf-mirror.com (or a configured base), then hand the local
directory to fastembed through ``specific_model_path``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import httpx

# Community mirror widely used in CN.
DEFAULT_HF_MIRROR = "https://hf-mirror.com"

# modelId -> files needed by fastembed for that supported model
# (repo is the ONNX/source repo on the Hub, not always the BAAI id)
MODEL_FILE_MANIFEST: dict[str, dict[str, Any]] = {
    "BAAI/bge-small-zh-v1.5": {
        "repo": "Qdrant/bge-small-zh-v1.5",
        "files": [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "vocab.txt",
            "model_optimized.onnx",
        ],
        "required": ["model_optimized.onnx", "tokenizer.json"],
    },
    "jinaai/jina-embeddings-v2-base-zh": {
        "repo": "jinaai/jina-embeddings-v2-base-zh",
        "files": [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "onnx/model.onnx",
        ],
        "required": ["onnx/model.onnx", "tokenizer.json"],
    },
    "intfloat/multilingual-e5-large": {
        "repo": "qdrant/multilingual-e5-large-onnx",
        "files": [
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "model.onnx",
            "model.onnx_data",
        ],
        "required": ["model.onnx", "tokenizer.json"],
    },
}

_configured = False


def resolve_hf_endpoint() -> str:
    """Return the HF mirror base URL (no trailing slash)."""
    for key in ("EMBEDDING_HF_ENDPOINT", "HF_ENDPOINT"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value.rstrip("/")
    try:
        from ..config import settings

        configured = (getattr(settings, "embedding_hf_endpoint", None) or "").strip()
        if configured:
            return configured.rstrip("/")
    except Exception:
        pass
    return DEFAULT_HF_MIRROR


def ensure_cn_download_endpoint() -> str:
    """Set HF_ENDPOINT for any code still using huggingface_hub."""
    global _configured
    endpoint = resolve_hf_endpoint()
    embed = (os.environ.get("EMBEDDING_HF_ENDPOINT") or "").strip().rstrip("/")
    if embed:
        endpoint = embed
    os.environ["HF_ENDPOINT"] = endpoint
    # Prefer mirror for all hub clients spawned later.
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.environ.get("HUGGINGFACE_HUB_CACHE", ""))
    _configured = True
    return endpoint


def download_source_meta() -> dict[str, Any]:
    endpoint = resolve_hf_endpoint()
    is_mirror = "hf-mirror" in endpoint or endpoint not in {
        "https://huggingface.co",
        "http://huggingface.co",
    }
    return {
        "hfEndpoint": endpoint,
        "label": "国内 HF 镜像直链" if is_mirror else "Hugging Face 官方",
        "hint": (
            f"权重通过 {endpoint}/<repo>/resolve/main/<file> 直链下载"
            "（绕过 huggingface_hub，避免国内元数据失败）。"
            "可用 HF_ENDPOINT / EMBEDDING_HF_ENDPOINT 覆盖。"
        ),
        "mode": "direct",
    }


def manifest_for(model_id: str) -> dict[str, Any] | None:
    return MODEL_FILE_MANIFEST.get(model_id)


def model_ready_dir(cache_dir: Path, model_id: str) -> Path | None:
    """Return prepared model dir if all required files exist."""
    manifest = manifest_for(model_id)
    if manifest is None:
        return None
    root = cache_dir / "prepared"
    required = manifest.get("required") or []
    if not root.exists():
        return None
    for rel in required:
        path = root / rel
        if not path.is_file() or path.stat().st_size <= 0:
            return None
    return root


def _resolve_url(endpoint: str, repo: str, rel: str) -> str:
    # hf-mirror and official both support /{repo}/resolve/main/{path}
    return f"{endpoint.rstrip('/')}/{repo}/resolve/main/{rel}"


def download_file(
    url: str,
    dest: Path,
    *,
    progress: Callable[[int], None] | None = None,
    timeout: float = 600.0,
) -> int:
    """Stream download url -> dest. Returns final size. Resumes if partial exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers: dict[str, str] = {}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"

    with httpx.stream(
        "GET",
        url,
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
    ) as response:
        # If server ignores Range, restart
        if existing and response.status_code == 200:
            existing = 0
            mode = "wb"
        elif response.status_code in {200, 206}:
            mode = "ab" if existing and response.status_code == 206 else "wb"
            if mode == "wb":
                existing = 0
        else:
            response.raise_for_status()
            mode = "wb"
            existing = 0

        total_header = response.headers.get("content-length")
        # content-range: bytes start-end/total
        content_range = response.headers.get("content-range")
        total: int | None = None
        if content_range and "/" in content_range:
            try:
                total = int(content_range.rsplit("/", 1)[-1])
            except ValueError:
                total = None
        elif total_header:
            try:
                total = existing + int(total_header) if response.status_code == 206 else int(total_header)
            except ValueError:
                total = None

        written = existing
        with partial.open(mode) as fh:
            for chunk in response.iter_bytes(chunk_size=1024 * 256):
                if not chunk:
                    continue
                fh.write(chunk)
                written += len(chunk)
                if progress:
                    progress(written)
        # basic sanity
        if written <= 0:
            raise RuntimeError(f"空文件：{url}")
        if total is not None and written < total * 0.98:
            raise RuntimeError(f"下载不完整：{url} ({written}/{total})")

    partial.replace(dest)
    return dest.stat().st_size


def download_model_direct(
    model_id: str,
    cache_dir: Path,
    *,
    on_progress: Callable[[float, str, int], None] | None = None,
) -> Path:
    """Download model files via mirror direct links into cache_dir/prepared.

    Returns the prepared directory path for ``specific_model_path``.
    """
    manifest = manifest_for(model_id)
    if manifest is None:
        raise ValueError(f"未配置直链清单：{model_id}")

    endpoint = ensure_cn_download_endpoint()
    repo = manifest["repo"]
    files: list[str] = list(manifest["files"])
    prepared = cache_dir / "prepared"
    prepared.mkdir(parents=True, exist_ok=True)

    # Skip files already present
    pending: list[str] = []
    already = 0
    for rel in files:
        path = prepared / rel
        if path.is_file() and path.stat().st_size > 0:
            already += path.stat().st_size
        else:
            pending.append(rel)

    def report(
        value: float,
        message: str,
        nbytes: int,
        total: int | None = None,
    ) -> None:
        if on_progress:
            # 4th arg is optional for callers that only accept 3
            try:
                on_progress(value, message, nbytes, total)  # type: ignore[misc]
            except TypeError:
                on_progress(value, message, nbytes)

    if not pending:
        report(0.95, f"本地已有完整权重（{prepared}）", already, already)
        return prepared

    # Estimate remaining: use content-length when known; else equal share.
    sizes: dict[str, int] = {}
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for rel in pending:
            url = _resolve_url(endpoint, repo, rel)
            try:
                head = client.head(url)
                cl = head.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > 100:
                    sizes[rel] = int(cl)
                    continue
            except Exception:
                pass
            try:
                # Some mirrors only answer GET; probe first bytes.
                r = client.get(url, headers={"Range": "bytes=0-0"})
                cr = r.headers.get("content-range")
                if cr and "/" in cr:
                    total = cr.rsplit("/", 1)[-1]
                    if total.isdigit():
                        sizes[rel] = int(total)
            except Exception:
                sizes[rel] = 0

    # Also count sizes of files already on disk for accurate total.
    for rel in files:
        if rel in sizes:
            continue
        path = prepared / rel
        if path.is_file() and path.stat().st_size > 0:
            sizes[rel] = path.stat().st_size

    expected_remaining = sum(sizes[r] for r in pending if sizes.get(r)) or max(
        len(pending) * 10 * 1024 * 1024, 1
    )
    expected_total = already + expected_remaining
    downloaded = already
    report(
        0.1,
        f"经 {endpoint} 直链下载 {len(pending)} 个文件…",
        downloaded,
        expected_total,
    )

    for index, rel in enumerate(pending):
        url = _resolve_url(endpoint, repo, rel)
        dest = prepared / rel
        file_start = downloaded

        def file_progress(n: int, _start: int = file_start, _rel: str = rel) -> None:
            nonlocal downloaded
            downloaded = _start + n
            # Grow total if a file turns out larger than HEAD claimed.
            total_now = max(expected_total, downloaded)
            ratio = min(0.99, downloaded / float(total_now or 1))
            value = 0.1 + ratio * 0.8
            report(
                min(value, 0.9),
                f"下载 {_rel}（{index + 1}/{len(pending)}）",
                downloaded,
                total_now,
            )

        try:
            size = download_file(url, dest, progress=file_progress)
        except Exception as exc:
            # Clean partial
            part = dest.with_suffix(dest.suffix + ".part")
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
            raise RuntimeError(f"下载失败 {rel} from {url}: {exc}") from exc
        downloaded = file_start + size
        sizes[rel] = size
        expected_total = max(expected_total, sum(sizes.get(r, 0) for r in files) or downloaded)
        report(
            min(0.1 + min(0.99, downloaded / float(expected_total or 1)) * 0.8, 0.9),
            f"已完成 {rel}",
            downloaded,
            expected_total,
        )

    # Verify required
    for rel in manifest.get("required") or []:
        path = prepared / rel
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"缺少必要文件：{rel}")

    final_total = max(expected_total, downloaded)
    report(0.95, f"直链下载完成 → {prepared}", downloaded, final_total)
    return prepared
