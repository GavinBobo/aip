"""CPU-only OpenAI-compatible gateway for the OXR-1.0 model.

The upstream project ships OXR as a vLLM out-of-tree plugin, which only runs on
Linux/NVIDIA. This gateway loads the same weights through transformers' remote
code path and exposes the small subset of the OpenAI chat API that
``oxr serve`` uses, so the parsing pipeline can run on a plain CPU host.

Usage:
    python deploy/oxr_openai_cpu_server.py --model-dir models/OXR-1.0 \
        --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import io
import logging
import os
import sys
import types
import threading
import time
import uuid
from typing import Any, Dict, Iterable, List

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("oxr-cpu")

app = FastAPI(title="OXR CPU OpenAI-compatible gateway")

_state: Dict[str, Any] = {}
_lock = threading.Lock()


def _decode_data_url(url: str) -> Image.Image:
    if not url.startswith("data:"):
        raise HTTPException(
            status_code=400, detail="Only data: image URLs are supported"
        )
    try:
        _, payload = url.split(",", 1)
        raw = base64.b64decode(payload)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"Invalid image payload: {exc}"
        ) from exc


def _iter_content_parts(content: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(content, str):
        yield {"type": "text", "text": content}
        return
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                yield part


def _build_model_messages(raw_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for message in raw_messages:
        parts: List[Dict[str, Any]] = []
        for part in _iter_content_parts(message.get("content")):
            part_type = part.get("type")
            if part_type in {"image_url", "image"}:
                image_value = part.get("image_url") or part.get("image")
                if isinstance(image_value, dict):
                    image_value = image_value.get("url")
                if not isinstance(image_value, str):
                    raise HTTPException(
                        status_code=400, detail="image_url.url is required"
                    )
                parts.append({"type": "image", "image": _decode_data_url(image_value)})
            elif part_type == "text":
                parts.append({"type": "text", "text": part.get("text") or ""})
        messages.append({"role": message.get("role", "user"), "content": parts})
    return messages


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok" if _state.get("model") is not None else "loading",
        "device": "cpu",
        "model_dir": _state.get("model_dir"),
        "threads": torch.get_num_threads(),
        "max_pixels": _state.get("max_pixels"),
    }


@app.get("/v1/models")
def list_models() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": _state.get("model_name", "oxr"),
                "object": "model",
                "created": 0,
                "owned_by": "local",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(payload: Dict[str, Any]) -> JSONResponse:
    model = _state.get("model")
    tokenizer = _state.get("tokenizer")
    if model is None or tokenizer is None:
        raise HTTPException(status_code=503, detail="Model is still loading")

    if payload.get("stream"):
        raise HTTPException(
            status_code=400, detail="Streaming is not supported by this gateway"
        )

    messages = _build_model_messages(payload.get("messages") or [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    max_new_tokens = int(
        payload.get("max_tokens")
        or payload.get("max_completion_tokens")
        or _state.get("default_max_tokens", 4096)
    )
    temperature = float(payload.get("temperature") or 0.0)
    top_p = float(payload.get("top_p") or 1.0)
    repetition_penalty = float(payload.get("repetition_penalty") or 1.0)

    started = time.perf_counter()
    with _lock, torch.inference_mode():
        input_ids, pixel_values, grid_thws = model.preprocess_inputs(
            messages,
            min_pixels=_state["min_pixels"],
            max_pixels=_state["max_pixels"],
            add_generation_prompt=True,
            enable_thinking=False,
        )
        generate_kwargs: Dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "repetition_penalty": repetition_penalty,
            "do_sample": temperature > 0,
            # The wrapper calls the inner Qwen3 decoder directly, so the
            # checkpoint-level EOS list (<|endoftext|>, <|im_end|>) and the KV
            # cache must be forwarded explicitly.
            "use_cache": True,
        }
        eos_token_id = _state.get("eos_token_ids")
        if eos_token_id is not None:
            generate_kwargs["eos_token_id"] = eos_token_id
        if temperature > 0:
            generate_kwargs.update(temperature=temperature, top_p=top_p)
        output_ids = model.generate(
            inputs=input_ids,
            pixel_values=pixel_values,
            grid_thws=grid_thws,
            **generate_kwargs,
        )

    if isinstance(output_ids, torch.Tensor):
        text = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        completion_tokens = int(output_ids.shape[-1])
    else:  # transformers GenerateOutput-like object
        sequences = output_ids.sequences
        text = tokenizer.decode(sequences[0], skip_special_tokens=True)
        completion_tokens = int(sequences.shape[-1])

    elapsed = time.perf_counter() - started
    logger.info(
        "completion done in %.1fs: prompt_tokens=%d completion_tokens=%d max_new=%d",
        elapsed,
        int(input_ids.shape[-1]),
        completion_tokens,
        max_new_tokens,
    )

    response = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model") or _state.get("model_name", "oxr"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text.strip()},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": int(input_ids.shape[-1]),
            "completion_tokens": completion_tokens,
            "total_tokens": int(input_ids.shape[-1]) + completion_tokens,
        },
    }
    return JSONResponse(response)


def _import_model_package(model_dir: str):
    """Import the model's own modules once, so config and model classes match.

    transformers' dynamic-module loader can create two copies of the remote
    code for a local checkpoint, which breaks the class identity used by the
    model's ``AutoModel`` registration. Importing directly avoids that.
    """
    package_name = "_oxr_local_model"
    if package_name in sys.modules:
        return sys.modules[f"{package_name}.modeling_oxr"]

    package = types.ModuleType(package_name)
    package.__path__ = [model_dir]
    sys.modules[package_name] = package

    for module_name in ("configuration_oxr", "modeling_oxr"):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{module_name}",
            os.path.join(model_dir, f"{module_name}.py"),
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {module_name}.py from {model_dir}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{package_name}.modeling_oxr"]


def _load_model(
    model_dir: str, dtype: torch.dtype, attn_implementation: str, max_pixels: int
):
    from transformers import AutoTokenizer

    model_dir = os.path.abspath(model_dir)
    logger.info("Loading OXR weights from %s (dtype=%s)", model_dir, dtype)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)

    modeling = _import_model_package(model_dir)
    config_class = sys.modules["_oxr_local_model.configuration_oxr"].OXRConfig
    config = config_class.from_pretrained(model_dir)
    config.name_or_path = model_dir

    load_kwargs: Dict[str, Any] = {
        "config": config,
        "attn_implementation": attn_implementation,
    }
    try:
        model = modeling.OXR.from_pretrained(model_dir, dtype=dtype, **load_kwargs)
    except TypeError:
        model = modeling.OXR.from_pretrained(
            model_dir, torch_dtype=dtype, **load_kwargs
        )
    # Non-persistent buffers are not stored in the checkpoint; transformers
    # zero-fills them on load, so rebuild the indicator ids deterministically.
    visual_vocab_size = int(config.visual_vocab_size)
    model.register_buffer(
        "indicator_token_indices",
        torch.arange(visual_vocab_size - 4, visual_vocab_size, dtype=torch.long),
        persistent=False,
    )
    model.eval()
    return tokenizer, model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve OXR-1.0 on CPU with an OpenAI-compatible API"
    )
    parser.add_argument(
        "--model-dir", default=os.environ.get("OXR_MODEL_DIR", "models/OXR-1.0")
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--model-name", default="oxr")
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--dtype", choices=["float32", "bfloat16"], default="float32")
    # The OXR wrapper class only declares eager attention support; the inner
    # Qwen3 decoder still uses its own default implementation.
    parser.add_argument("--attn-implementation", default="eager")
    parser.add_argument("--min-pixels", type=int, default=448 * 448)
    parser.add_argument("--max-pixels", type=int, default=1344 * 1792)
    parser.add_argument("--default-max-tokens", type=int, default=4096)
    args = parser.parse_args()

    torch.set_num_threads(args.threads)
    torch.set_grad_enabled(False)
    dtype = torch.float32 if args.dtype == "float32" else torch.bfloat16

    tokenizer, model = _load_model(
        args.model_dir, dtype, args.attn_implementation, args.max_pixels
    )
    eos_token_ids = (
        [tokenizer.eos_token_id] if tokenizer.eos_token_id is not None else []
    )
    im_end_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
    if isinstance(im_end_id, int) and im_end_id >= 0 and im_end_id not in eos_token_ids:
        eos_token_ids.append(im_end_id)
    _state.update(
        tokenizer=tokenizer,
        model=model,
        eos_token_ids=eos_token_ids or None,
        model_dir=os.path.abspath(args.model_dir),
        model_name=args.model_name,
        min_pixels=args.min_pixels,
        max_pixels=args.max_pixels,
        default_max_tokens=args.default_max_tokens,
    )
    logger.info("Model ready (threads=%d)", torch.get_num_threads())

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
