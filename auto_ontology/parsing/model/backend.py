"""Runtime model backend selection and local gateway lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

from auto_ontology.parsing.config.model_settings import (
    LayoutServiceSettings,
    LocalModelSettings,
    ModelBackendSettings,
    VLLMModelSettings,
)
from auto_ontology.parsing.config.settings import settings
from auto_ontology.parsing.model.client import model_client
from auto_ontology.parsing.model.layout_client import layout_client
from auto_ontology.parsing.pipeline.errors import PipelineError


LOGGER = logging.getLogger(__name__)
# Ported from OXR: the original package sat at ``<root>/oxr/model/backend.py``.
# Here it is ``<root>/auto_ontology/parsing/model/backend.py``, one level deeper,
# so the repository root (where ``deploy/`` and ``logs/`` live) is parents[3].
# Ported from OXR: the original package sat at ``<root>/oxr/model/backend.py``.
# Here it is ``<root>/auto_ontology/parsing/model/backend.py``, one level deeper,
# so the repository root (where ``logs/`` lives) is parents[3].
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# The CPU gateway moved with the package rather than staying at the repo root:
# it is parsing code, and a top-level ``deploy/`` in this repo would read as
# deployment assets for the whole product. It needs torch + transformers; the
# vLLM mode does not.
LOCAL_GATEWAY = (
    Path(__file__).resolve().parents[1] / "deploy" / "oxr_openai_cpu_server.py"
)
LOG_DIR = PROJECT_ROOT / "logs"


class ModelBackendManager:
    """Owns the selected backend without loading a model at startup.

    ``local`` starts the bundled CPU gateway on demand. ``vllm`` only points
    the existing OpenAI-compatible client at a user-provided endpoint. ``none``
    keeps the server running so the Settings page can configure it.
    """

    def __init__(self) -> None:
        self._config = ModelBackendSettings()
        self._path: Optional[Path] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._state = "unconfigured"
        self._detail = "No model backend selected."
        self._error: Optional[str] = None
        self._lock: Optional[asyncio.Lock] = None
        self._lock_loop: Optional[asyncio.AbstractEventLoop] = None
        self._start_epoch = 0

    @property
    def config(self) -> ModelBackendSettings:
        return self._config

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    def _resolve_path(self) -> Path:
        path = Path(settings.model_settings_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    async def initialize(self) -> None:
        """Load persisted settings and apply them without starting a model."""
        self._path = self._resolve_path()
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._config = ModelBackendSettings.model_validate(data)
            except Exception as error:
                LOGGER.warning(
                    "Ignoring invalid model settings %s: %s", self._path, error
                )
                self._config = ModelBackendSettings()
        else:
            # Mirror config.yaml / environment values into the Settings form,
            # even when no URL is configured yet.
            cpu_profile = (
                settings.oxr_model.url is None
                and settings.oxr_model.max_concurrency == 1
                and settings.oxr_model.timeout >= 3600
            )
            vllm_defaults = VLLMModelSettings()
            self._config = ModelBackendSettings(
                mode="vllm" if settings.oxr_model.url else "none",
                vllm=VLLMModelSettings(
                    url=settings.oxr_model.url or vllm_defaults.url,
                    model_name=settings.oxr_model.model_name,
                    api_key=settings.oxr_model.api_key,
                    max_concurrency=(
                        vllm_defaults.max_concurrency
                        if cpu_profile
                        else settings.oxr_model.max_concurrency
                    ),
                    timeout=(
                        vllm_defaults.timeout
                        if cpu_profile
                        else settings.oxr_model.timeout
                    ),
                    connect_timeout=settings.oxr_model.connect_timeout,
                    retry_times=(
                        vllm_defaults.retry_times
                        if cpu_profile
                        else settings.oxr_model.retry_times
                    ),
                ),
                layout=LayoutServiceSettings(
                    url=settings.layout_analyze_model.url
                    or LayoutServiceSettings().url,
                    batch_size=settings.layout_analyze_model.batch_size,
                    max_concurrency=settings.layout_analyze_model.max_concurrency,
                    timeout=settings.layout_analyze_model.timeout,
                    retry_times=settings.layout_analyze_model.retry_times,
                    score_threshold=settings.layout_analyze_model.score_threshold,
                    nms_iou_threshold=settings.layout_analyze_model.nms_iou_threshold,
                    provides_reading_order=settings.layout_analyze_model.provides_reading_order,
                ),
            )
        self._apply(self._config, persist=False)

    def _apply(self, config: ModelBackendSettings, *, persist: bool) -> None:
        self._config = config
        self._apply_layout(config.layout)
        if config.mode == "vllm":
            self._apply_vllm(config.vllm)
            self._state = "configured"
            self._detail = "vLLM API configured. Use Test connection to verify it."
            self._error = None
        elif config.mode == "local":
            self._apply_local(config.local)
            self._state = "stopped"
            self._detail = "Local model selected but not started."
            self._error = None
        else:
            settings.oxr_model.url = None
            self._state = "unconfigured"
            self._detail = "Select a local model or a vLLM API in Settings."
            self._error = None
        if persist:
            self._save()

    def _apply_vllm(self, config: VLLMModelSettings) -> None:
        settings.oxr_model.url = config.url.rstrip("/")
        settings.oxr_model.model_name = config.model_name
        settings.oxr_model.api_key = config.api_key
        settings.oxr_model.max_concurrency = config.max_concurrency
        settings.oxr_model.timeout = config.timeout
        settings.oxr_model.connect_timeout = config.connect_timeout
        settings.oxr_model.retry_times = config.retry_times

    def _apply_local(self, config: LocalModelSettings) -> None:
        settings.oxr_model.url = f"http://{config.host}:{config.port}/v1"
        settings.oxr_model.model_name = "oxr"
        settings.oxr_model.api_key = None
        settings.oxr_model.max_concurrency = 1
        settings.oxr_model.timeout = 7200
        settings.oxr_model.connect_timeout = 10
        settings.oxr_model.retry_times = 1

    def _apply_layout(self, config: LayoutServiceSettings) -> None:
        settings.layout_analyze_model.url = config.url.rstrip("/")
        settings.layout_analyze_model.batch_size = config.batch_size
        settings.layout_analyze_model.max_concurrency = config.max_concurrency
        settings.layout_analyze_model.timeout = config.timeout
        settings.layout_analyze_model.retry_times = config.retry_times
        settings.layout_analyze_model.score_threshold = config.score_threshold
        settings.layout_analyze_model.nms_iou_threshold = config.nms_iou_threshold
        settings.layout_analyze_model.provides_reading_order = (
            config.provides_reading_order
        )

    async def activate(self, config: ModelBackendSettings) -> dict:
        """Persist and apply a backend choice, starting a local model if needed."""
        async with self._get_lock():
            await self._stop_local_locked()
            self._apply(config, persist=True)
            await model_client.reconfigure()
            await layout_client.reconfigure()
            if config.mode == "local":
                await self._start_local_locked(config.local)
        return self.describe()

    async def update_layout(self, config: LayoutServiceSettings) -> dict:
        """Persist and apply D-FINE connection settings without touching OXR."""
        async with self._get_lock():
            self._config.layout = config
            self._apply_layout(config)
            self._save()
            await layout_client.reconfigure()
        return self.describe()

    async def start_local(self) -> dict:
        async with self._get_lock():
            if self._config.mode != "local":
                raise ValueError("Select the local model backend first.")
            await self._start_local_locked(self._config.local)
        return self.describe()

    async def stop_local(self) -> dict:
        # Cancel an in-flight startup before waiting for its lock.
        self._start_epoch += 1
        async with self._get_lock():
            await self._stop_local_locked()
            if self._config.mode == "local":
                if await self._local_ready(self._config.local):
                    self._state = "running"
                    self._detail = (
                        "An external local model is still running on this port."
                    )
                else:
                    self._state = "stopped"
                    self._detail = "Local model stopped."
        return self.describe()

    async def status(self) -> dict:
        """Return current status, probing local health without starting anything."""
        if self._config.mode == "local" and self._state != "starting":
            if await self._local_ready(self._config.local):
                self._state = "running"
                self._detail = "Local model is running."
            elif self._state == "running":
                self._state = "stopped"
                self._detail = "Local model is no longer responding."
        return self.describe()

    async def ensure_ready(self) -> None:
        """Fail parse requests early when the selected backend is unavailable."""
        if not settings.oxr_model.url:
            raise PipelineError(
                "Model backend is not configured.",
                status_code=503,
                public_message=(
                    "Model backend is not configured. Open Settings to choose "
                    "a local model or a vLLM API."
                ),
            )
        if not settings.layout_analyze_model.url:
            raise PipelineError(
                "Layout analysis service is not configured.",
                status_code=503,
                public_message=(
                    "Layout analysis service is not configured. Set "
                    "layout_analyze_model.url in config.yaml."
                ),
            )
        if self._config.mode == "local" and self._state != "running":
            if await self._local_ready(self._config.local):
                self._state = "running"
                self._detail = "Local model is running."
                return
            raise PipelineError(
                "Local model is not running.",
                status_code=503,
                public_message="Local model is not running. Open Settings and start it.",
            )

    async def test(self, config: Optional[ModelBackendSettings] = None) -> dict:
        """Check reachability without changing the active backend."""
        candidate = config or self._config
        if candidate.mode == "local":
            reachable = await self._local_ready(candidate.local)
            return {
                "mode": "local",
                "reachable": reachable,
                "detail": (
                    "Local model is running."
                    if reachable
                    else "Local model is not running."
                ),
            }
        if candidate.mode == "vllm":
            headers = (
                {"Authorization": f"Bearer {candidate.vllm.api_key}"}
                if candidate.vllm.api_key
                else None
            )
            try:
                async with httpx.AsyncClient(
                    trust_env=False,
                    timeout=candidate.vllm.connect_timeout,
                    headers=headers,
                ) as client:
                    started = time.perf_counter()
                    response = await client.get(
                        f"{candidate.vllm.url.rstrip('/')}/models"
                    )
                    response.raise_for_status()
                    payload = response.json()
                    ids = [
                        item.get("id")
                        for item in payload.get("data", [])
                        if isinstance(item, dict)
                    ]
                    return {
                        "mode": "vllm",
                        "reachable": True,
                        "model_ids": ids,
                        "model_found": candidate.vllm.model_name in ids,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
            except Exception as error:
                return {
                    "mode": "vllm",
                    "reachable": False,
                    "error": str(error),
                }
        return {
            "mode": "none",
            "reachable": False,
            "detail": "No backend selected.",
        }

    async def test_layout(self, config: Optional[LayoutServiceSettings] = None) -> dict:
        candidate = config or self._config.layout
        base = candidate.url.rstrip("/")
        if base.endswith("/inference"):
            base = base[: -len("/inference")]
        try:
            async with httpx.AsyncClient(
                trust_env=False,
                timeout=min(candidate.timeout, 10),
            ) as client:
                started = time.perf_counter()
                health = await client.get(f"{base}/health")
                health.raise_for_status()
                health_payload = health.json()
                model_info = None
                try:
                    info_response = await client.get(f"{base}/model/info")
                    if info_response.status_code == 200:
                        model_info = info_response.json()
                except Exception:
                    pass
                return {
                    "mode": "layout",
                    "reachable": True,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    "health": health_payload,
                    "model_info": model_info,
                }
        except Exception as error:
            return {
                "mode": "layout",
                "reachable": False,
                "error": str(error),
            }

    def describe(self) -> dict:
        data = self._config.model_dump(mode="json")
        running = self._state == "running"
        data["status"] = {
            "state": self._state,
            "detail": self._detail,
            "error": self._error,
            "ready": bool(settings.oxr_model.url)
            and (self._config.mode != "local" or running),
            "active_url": settings.oxr_model.url,
            "model_name": settings.oxr_model.model_name,
            "pid": (
                self._process.pid
                if self._process is not None and self._process.returncode is None
                else None
            ),
            "log_path": str(LOG_DIR / "model.err.log"),
        }
        return data

    async def shutdown(self) -> None:
        # Do not wait for an in-flight startup to finish: server shutdown must
        # not block for the full startup timeout.
        self._start_epoch += 1
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=15)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _start_local_locked(self, config: LocalModelSettings) -> None:
        if await self._local_ready(config):
            self._state = "running"
            self._detail = "Local model is already running."
            self._error = None
            return
        if self._process is not None and self._process.returncode is None:
            self._state = "running"
            self._detail = "Local model is running."
            return

        model_dir = Path(config.model_dir)
        if not model_dir.is_absolute():
            model_dir = PROJECT_ROOT / model_dir
        if not (model_dir / "model.safetensors").exists():
            raise ValueError(
                f"Local model weights not found under {model_dir}. "
                "Set the model directory in Settings."
            )
        if not LOCAL_GATEWAY.exists():
            raise ValueError(f"Local model gateway not found at {LOCAL_GATEWAY}.")

        python = config.python or os.environ.get("OXR_LOCAL_PYTHON") or sys.executable
        threads = config.threads or max(4, (os.cpu_count() or 4) - 4)
        command = [
            python,
            str(LOCAL_GATEWAY),
            "--model-dir",
            str(model_dir),
            "--host",
            config.host,
            "--port",
            str(config.port),
            "--threads",
            str(threads),
            "--dtype",
            config.dtype,
            "--default-max-tokens",
            str(config.max_tokens),
        ]
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        out_path = LOG_DIR / "model.out.log"
        err_path = LOG_DIR / "model.err.log"
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        self._state = "starting"
        self._detail = f"Starting local model on {config.host}:{config.port}..."
        self._error = None
        try:
            with out_path.open("ab") as stdout, err_path.open("ab") as stderr:
                self._process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=str(PROJECT_ROOT),
                    stdout=stdout,
                    stderr=stderr,
                    **kwargs,
                )
        except Exception as error:
            self._state = "error"
            self._detail = "Failed to start local model."
            self._error = str(error)
            raise

        deadline = time.monotonic() + config.startup_timeout
        epoch = self._start_epoch
        while time.monotonic() < deadline:
            if epoch != self._start_epoch:
                self._state = "stopped"
                self._detail = "Local model startup cancelled."
                self._error = None
                raise RuntimeError(self._detail)
            process = self._process
            if process is not None and process.returncode is not None:
                code = process.returncode
                self._process = None
                self._state = "error"
                self._detail = f"Local model exited with code {code}."
                self._error = f"See {err_path}"
                raise RuntimeError(f"{self._detail} {self._error}")
            if await self._local_ready(config):
                self._state = "running"
                self._detail = "Local model is running."
                self._error = None
                return
            await asyncio.sleep(2)

        self._state = "error"
        self._detail = "Local model did not become ready in time."
        self._error = f"See {err_path}"
        await self._stop_local_locked()
        raise TimeoutError(self._detail)

    async def _stop_local_locked(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=15)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _local_ready(self, config: LocalModelSettings) -> bool:
        base = f"http://{config.host}:{config.port}"
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=3.0) as client:
                health = await client.get(f"{base}/health")
                if health.status_code != 200:
                    return False
                try:
                    health_payload = health.json()
                except Exception:
                    health_payload = None
                if isinstance(health_payload, dict) and health_payload.get(
                    "status"
                ) not in (None, "ok"):
                    return False
                models = await client.get(f"{base}/v1/models")
                if models.status_code != 200:
                    return False
                payload = models.json()
                return any(
                    item.get("id") == "oxr"
                    for item in payload.get("data", [])
                    if isinstance(item, dict)
                )
        except Exception:
            return False

    def _save(self) -> None:
        if self._path is None:
            self._path = self._resolve_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        temporary.write_text(
            json.dumps(
                self._config.model_dump(mode="json"), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)
        try:
            os.chmod(self._path.parent, 0o700)
            os.chmod(self._path, 0o600)
        except OSError:
            pass


model_backend = ModelBackendManager()
