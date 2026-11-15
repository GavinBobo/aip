# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Document decoding, which is the only part of the pipeline that runs locally.

Everything after this point talks to the recognition and layout services, so
this is where the ported code meets the host: ``sopdf`` (PDF → page images) and
``opencv`` (image bytes → array). Both are native wheels, and a missing or
broken build of either is exactly the kind of thing that "it imports fine"
hides. A bad file has to come back as OXR's public message rather than a
traceback leaking a decoder's internals.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from auto_ontology.parsing.pipeline.errors import PipelineError
from auto_ontology.parsing.pipeline.orchestrator import _decode_document_images


def _png(width: int = 64, height: int = 48) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (250, 250, 250)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_png_decodes_to_one_colour_page() -> None:
    pages = _decode_document_images(_png(64, 48), "scan.png")
    assert len(pages) == 1
    assert isinstance(pages[0], np.ndarray)
    assert pages[0].shape[:2] == (48, 64)
    # IMREAD_COLOR: three channels even though the source is opaque.
    assert pages[0].shape[2] == 3


def test_a_file_that_is_not_an_image_reports_the_public_message() -> None:
    with pytest.raises(PipelineError) as raised:
        _decode_document_images(b"not an image at all", "notes.png")
    assert raised.value.public_message is not None
    # The message is what the panel shows; it must not name a decoder.
    assert "cv2" not in raised.value.public_message.lower()


def test_an_empty_image_is_rejected_rather_than_returned() -> None:
    with pytest.raises(PipelineError):
        _decode_document_images(b"", "empty.png")
