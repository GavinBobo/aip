# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Server-side folder browsing for folder-based parsing tasks.

Unlike the connection import wizard, the parsing picker is allowed to browse
the deployment host's filesystem: the operator is choosing a directory that
already exists on the machine running the API. An optional
``PARSING_SOURCE_ROOTS`` allowlist can narrow that access for shared
deployments; empty means "anything this process can read".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

#: Directories with this many characters or more are still valid; the limit is
#: for error messages, not path validation.
_MAX_DISPLAY_PATH = 500


def _allowed_roots() -> list[Path] | None:
    raw = os.environ.get("PARSING_SOURCE_ROOTS", "").strip()
    if not raw:
        return None
    roots: list[Path] = []
    for chunk in raw.replace(",", os.pathsep).split(os.pathsep):
        part = chunk.strip()
        if not part:
            continue
        try:
            root = Path(part).expanduser().resolve(strict=True)
        except OSError:
            continue
        if root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def _ensure_allowed(path: Path) -> None:
    roots = _allowed_roots()
    if roots is None:
        return
    if not any(path == root or root in path.parents for root in roots):
        raise ValueError(
            "该目录不在 PARSING_SOURCE_ROOTS 允许范围内；"
            "如需浏览整台服务器，请留空该配置。"
        )


def _root_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if os.name == "nt":
        drives = []
        listdrives = getattr(os, "listdrives", None)
        if callable(listdrives):
            try:
                drives = list(listdrives())
            except OSError:
                drives = []
        if not drives:
            drives = [
                f"{letter}:\\"
                for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ"
                if Path(f"{letter}:\\").exists()
            ]
        for drive in drives:
            path = Path(drive)
            entries.append(
                {
                    "name": drive,
                    "path": str(path),
                    "kind": "directory",
                    "is_root": True,
                }
            )
    else:
        entries.append(
            {
                "name": "/",
                "path": "/",
                "kind": "directory",
                "is_root": True,
            }
        )
    return entries


def _resolve_directory(raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValueError("请输入服务器文件夹路径。")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        directory = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"无法打开 {raw!r}：{error}") from error
    if not directory.is_dir():
        raise ValueError(f"{raw!r} 不是文件夹。")
    _ensure_allowed(directory)
    return directory


def browse_server_path(raw_path: str | None = None) -> dict[str, Any]:
    """List a server directory, or the filesystem roots when none is given."""
    roots = _root_entries()
    if raw_path is None or str(raw_path).strip() == "":
        if len(roots) == 1:
            directory = Path(roots[0]["path"])
        else:
            return {
                "roots": [entry["path"] for entry in roots],
                "path": None,
                "parent": None,
                "entries": roots,
            }
    else:
        directory = _resolve_directory(str(raw_path))

    try:
        children = list(directory.iterdir())
    except OSError as error:
        raise ValueError(f"无法读取 {str(directory)!r}：{error}") from error

    entries: list[dict[str, Any]] = []
    for child in children:
        try:
            resolved = child.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_dir():
            continue
        entries.append(
            {
                "name": child.name or str(resolved),
                "path": str(resolved),
                "kind": "directory",
            }
        )
    entries.sort(key=lambda entry: entry["name"].lower())

    parent = str(directory.parent) if directory.parent != directory else None
    return {
        "roots": [entry["path"] for entry in roots],
        "path": str(directory),
        "parent": parent,
        "entries": entries,
    }


def scan_server_files(
    raw_path: str,
    *,
    suffixes: set[str],
    max_files: int,
) -> list[dict[str, Any]]:
    """Recursively list matching files below any readable server directory."""
    directory = _resolve_directory(raw_path)
    found: list[dict[str, Any]] = []
    for current, dirnames, filenames in os.walk(directory, followlinks=False):
        dirnames[:] = [
            name for name in dirnames if not (Path(current) / name).is_symlink()
        ]
        for filename in filenames:
            if Path(filename).suffix.lower() not in suffixes:
                continue
            candidate = Path(current) / filename
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not resolved.is_file():
                continue
            try:
                _ensure_allowed(resolved)
                size = resolved.stat().st_size
            except (OSError, ValueError):
                continue
            found.append(
                {
                    "name": resolved.name,
                    "path": str(resolved),
                    "relative": resolved.relative_to(directory).as_posix(),
                    "size": size,
                }
            )
            if len(found) > max_files:
                raise ValueError(
                    f"该目录下找到超过 {max_files} 个文件，请选择更小的目录或分批处理"
                )
    found.sort(key=lambda item: item["relative"].lower())
    return found


def read_server_bytes(raw_path: str, *, max_bytes: int) -> tuple[Path, bytes]:
    """Read one file the deployment host can access."""
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValueError("文件路径为空。")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        source = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError(f"无法打开 {raw!r}：{error}") from error
    if not source.is_file():
        raise ValueError(f"{raw!r} 不是文件。")
    _ensure_allowed(source)
    try:
        size = source.stat().st_size
    except OSError as error:
        raise ValueError(f"无法读取 {str(source)!r}：{error}") from error
    if size > max_bytes:
        raise ValueError(f"{source.name} 超过 {max_bytes // (1024 * 1024)} MB 上限")
    try:
        return source, source.read_bytes()
    except OSError as error:
        raise ValueError(f"无法读取 {str(source)!r}：{error}") from error
