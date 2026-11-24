#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Minimal entrypoint: initialise the cluster on first start, then run postgres
# in the foreground. Mirrors the official image's contract for the variables
# the compose file sets (POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB).
set -euo pipefail

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    chmod 700 "$PGDATA"
    exec setpriv --reuid=postgres --regid=postgres --init-groups "$0" "$@"
fi

export PATH="/usr/lib/postgresql/16/bin:$PATH"
DB_USER="${POSTGRES_USER:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD:-}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "entrypoint: initialising cluster in $PGDATA"
    if [ -n "${POSTGRES_PASSWORD:-}" ]; then
        printf '%s' "$POSTGRES_PASSWORD" > /tmp/pg-password
        initdb --username="$DB_USER" --pwfile=/tmp/pg-password \
               --auth-local=trust --auth-host=scram-sha-256 -E UTF8 >/dev/null
        rm -f /tmp/pg-password
    else
        initdb --username="$DB_USER" --auth-local=trust --auth-host=trust -E UTF8 >/dev/null
    fi
    echo "host all all all scram-sha-256" >> "$PGDATA/pg_hba.conf"
fi

postgres -c listen_addresses='*' &
pg_pid=$!

until pg_isready -U "$DB_USER" >/dev/null 2>&1; do
    if ! kill -0 "$pg_pid" 2>/dev/null; then
        echo "entrypoint: postgres exited during startup" >&2
        exit 1
    fi
    sleep 0.5
done

if [ -n "${POSTGRES_DB:-}" ]; then
    if ! psql -U "$DB_USER" -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'" | grep -q 1; then
        createdb -U "$DB_USER" "$POSTGRES_DB"
    fi
fi

wait "$pg_pid"
