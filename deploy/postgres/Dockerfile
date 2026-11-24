# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Local PostgreSQL 16 + pgvector image for machines that cannot reach Docker
# Hub. It is built from the Ubuntu 24.04 base rootfs plus the Tsinghua apt
# mirror, so `docker compose up` needs no registry pull.
#
#   docker import ubuntu-base.tar.gz allontology/ubuntu-base:24.04
#   docker build -t allontology/postgres-pgvector:16 deploy/postgres

FROM allontology/ubuntu-base:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PGDATA=/var/lib/postgresql/data \
    LANG=C.UTF-8

RUN printf '%s\n' \
      'deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble main restricted universe multiverse' \
      'deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble-updates main restricted universe multiverse' \
      'deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ noble-security main restricted universe multiverse' \
      > /etc/apt/sources.list \
    && rm -f /etc/apt/sources.list.d/*.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
         postgresql-16 postgresql-16-pgvector \
         ca-certificates locales util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p "$PGDATA" \
    && chown -R postgres:postgres /var/lib/postgresql

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 5432
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["postgres"]
