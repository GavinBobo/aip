# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from auto_ontology.parsing.pipeline.models import Block, ContentFormat
from auto_ontology.parsing.utils.table import (
    html_table_to_markdown,
    strip_table_code_fence,
)


def postprocess_table(
    block: Block, raw_text: str, output_format: str = "html"
) -> Block:
    """Clean up table block output to the requested table format."""
    text = strip_table_code_fence(raw_text)
    if output_format == "markdown":
        block.content = html_table_to_markdown(text)
        block.format = ContentFormat.MARKDOWN
        return block

    block.content = text.strip()
    block.format = ContentFormat.HTML
    return block
