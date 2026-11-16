# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Block until the configured Postgres database accepts connections.

`docker compose ... --wait` only proves the container's healthcheck passed;
this proves the app's own credentials and target database work, which is the
failure mode `require_current_schema()` reports at startup. Used by
`dev_tools/start-dev.ps1`.

Usage: python -m dev_tools.wait_for_db [timeout-seconds]
"""

from __future__ import annotations

import os
import sys
import time

import psycopg

from all_ontology.env import load_env


def main() -> int:
    load_env()
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    target = "{user}@{host}:{port}/{db}".format(
        user=os.environ.get("POSTGRES_USER", "postgres"),
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        db=os.environ.get("POSTGRES_DATABASE", "all_ontology"),
    )
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(
                host=os.environ.get("POSTGRES_HOST", "localhost"),
                port=os.environ.get("POSTGRES_PORT", "5432"),
                user=os.environ.get("POSTGRES_USER", "postgres"),
                password=os.environ.get("POSTGRES_PASSWORD", ""),
                dbname=os.environ.get("POSTGRES_DATABASE", "all_ontology"),
                connect_timeout=3,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("select 1")
                    cur.fetchone()
            print(f"database {target} is accepting connections")
            return 0
        except Exception as exc:  # noqa: BLE001 - retried until the deadline
            last_error = exc
            time.sleep(1.0)
    print(
        f"database {target} did not accept connections within {timeout:.0f}s: {last_error}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
