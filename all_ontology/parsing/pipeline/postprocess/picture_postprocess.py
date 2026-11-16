"""Picture blocks: write the crop somewhere the answer can point at.

OXR emitted a bare filesystem path (``outputs/<doc>/imgs/0_3.png``) unless its
own demo server had installed an :class:`ImageAssets` context. A path like that
is not what a caller can use: the browser cannot resolve it, and a downloaded
``.md`` refers to a directory the reader does not have.

So the link is built from ``pipeline.image_url_prefix`` — by default
``/api/parsing/assets``, which this service serves — and the three formats the
API advertises are actually honoured:

* ``url``    → ``![](/api/parsing/assets/<doc>/imgs/<page>_<idx>.png)``
* ``base64`` → ``![](data:image/png;base64,…)``; a self-contained Markdown file
* ``none``   → the picture is dropped
"""

import base64
import os
import re

import cv2
import numpy as np

from all_ontology.parsing.config.settings import settings
from all_ontology.parsing.pipeline.image_assets import image_assets
from all_ontology.parsing.pipeline.models import Block, ContentFormat


def document_slug(file_name: str) -> str:
    """A directory-safe name for one document's assets.

    Built from the whole name rather than its basename so a path like
    ``Quarter 3 / 报表.pdf`` keeps a readable prefix, then collapsed to
    ``[A-Za-z0-9._-]``. Separators and dots can only ever become ``-``, so the
    result cannot walk out of the asset directory.
    """
    stem = os.path.splitext(file_name)[0]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")
    return slug[:60] or "document"


def _encode(image: np.ndarray, extension: str = ".png") -> bytes:
    ok, encoded = cv2.imencode(extension, image)
    if not ok:
        raise ValueError("Unable to encode an output image.")
    return encoded.tobytes()


def postprocess_picture(
    block: Block,
    image: np.ndarray,
    file_name: str,
    page_num: int,
    element_formats: dict[str, str] | None = None,
) -> Block:
    """Write the crop and set the block's Markdown image reference."""
    requested = (element_formats or {}).get("image", "url")

    if requested == "none":
        block.content = ""
        block.format = ContentFormat.MARKDOWN
        return block

    if requested == "base64":
        payload = base64.b64encode(_encode(image)).decode("ascii")
        block.content = f"![](data:image/png;base64,{payload})"
        block.format = ContentFormat.MARKDOWN
        return block

    # OXR's demo server injects its own asset store; keep that path intact so the
    # port still matches upstream when it is installed.
    assets = image_assets.get()
    if assets is not None:
        block.content = f"![]({assets.save(image)})"
        block.format = ContentFormat.MARKDOWN
        return block

    slug = document_slug(file_name)
    out_dir = os.path.join(settings.pipeline.image_output_dir, slug, "imgs")
    os.makedirs(out_dir, exist_ok=True)

    img_name = f"{page_num}_{block.idx}.png"
    with open(os.path.join(out_dir, img_name), "wb") as handle:
        handle.write(_encode(image))

    prefix = settings.pipeline.image_url_prefix.rstrip("/")
    block.content = f"![]({prefix}/{slug}/imgs/{img_name})"
    block.format = ContentFormat.MARKDOWN
    return block
