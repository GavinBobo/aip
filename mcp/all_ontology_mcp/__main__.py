# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""All Ontology MCP server entrypoint.

Exposes the All Ontology semantic layer to any MCP-capable agent harness. It holds no
database connections, no model configuration, and no credentials: it is an HTTP
client of the public All Ontology API and needs only the URL of an All Ontology deployment, so it
runs equally well beside one or on a laptop far away from it.

Usage::

    export ALL_ONTOLOGY_API_URL=https://all-ontology.example.com
    all-ontology-mcp

Without installing anything::

    uvx --from all-ontology-mcp all-ontology-mcp

Callers sign in against All Ontology itself in a browser, so there is nothing to give the
server up front and nothing for a user to mint by hand.
"""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

# Load before importing config so a `.env` beside the working directory can
# supply the URL, matching how the rest of All Ontology is configured locally.
load_dotenv()

from all_ontology_mcp import get_version  # noqa: E402
from all_ontology_mcp.config import ConfigError, load_settings  # noqa: E402
from all_ontology_mcp.server import build_server  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("%s", exc)
        return 2

    logger.info(
        "Starting All Ontology MCP server — version %s, listening on %s",
        get_version(),
        settings.public_url,
    )

    mcp, _client = build_server(settings)

    # FastMCP owns the event loop and closes the client's connections when the
    # transport shuts down, so there is no separate teardown to run here.
    mcp.run(transport="http", host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
