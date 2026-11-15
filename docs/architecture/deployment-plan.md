<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Auto-Ontology 部署方案（使用公司现有 PostgreSQL）

> 适用场景：数据库用公司已经有的 PostgreSQL 实例，不自建、不用仓库里 `docker-compose.yml`
> 那个 `postgres` 容器。本文只讲这一条路径；想在本机跑开发环境看文末附录。
>
> 配套：[项目结构分析与重构规划](./project-review.md)

## 0. 要部署什么

四个东西，其中只有前三个是本项目的代码：

| 组件 | 说明 | 端口 |
| --- | --- | --- |
| 后端 API | FastAPI，读写 `public` 与 `frontend` 两个 schema | 3001 |
| 摄取服务 | FastAPI + 调度器，独立进程，同上数据库 | 3002 |
| 前端 | Next.js，通过 BFF 转发到后端 | 3000 |
| PostgreSQL | **公司现有实例**，本项目只往里建库/建 schema | 5432 |

三者可以在一台机器上跑（推荐起步），也可以拆开；它们之间只通过 HTTP 与数据库通信。

## 1. 先和 DBA 对齐四件事

这四项任何一项不满足，后面都会卡住，而报错信息通常不会直接指向原因。

### 1.1 版本

- **PostgreSQL 15 及以上**（本仓库在 17 上验证）。低于 15 要先确认 `public` schema 的写权限模型
  与 `gen_random_uuid()`（13+）是否可用，不建议。
- 字符集 UTF8，时区建议 UTC。所有时间列都是 `timestamptz`。
- ID 用 `(gen_random_uuid())::text`，这是 Postgres 13+ 内置函数，**不需要 pgcrypto**。

### 1.2 扩展

| 扩展 | 谁需要 | 谁创建 | 说明 |
| --- | --- | --- | --- |
| `pg_trgm` | 全局搜索的 GIN 索引 | 第一个迁移里 `CREATE EXTENSION IF NOT EXISTS pg_trgm` | 应用角色要么有 `CREATE` 权限，要么由 DBA 预先建好 |
| `vector`（pgvector **≥ 0.7**） | 向量检索 | 首次建向量表时 `langchain_postgres` 会执行 `CREATE EXTENSION IF NOT EXISTS vector`，但 **pgvector 不是 trusted 扩展，普通角色建不了** | **必须由 DBA 用超级用户预建**；预建之后应用那句 `IF NOT EXISTS` 只是空操作。0.7 才有 `halfvec`，HNSW 索引用的是 `(embedding::halfvec(2048))` 表达式 |

`pg_trgm` 属于 trusted 扩展，有库级 `CREATE` 权限的角色可以自建；`vector` 不行 ——
这是两者在权限上唯一的区别，也是最容易在上线当天才发现的坑。

```sql
-- 用超级用户执行一次
\c auto_ontology
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### 1.3 库与角色

一个库、一个应用角色即可跑通全部功能：

```sql
CREATE ROLE svc_auto_ontology LOGIN PASSWORD '<强密码>';
CREATE DATABASE auto_ontology
  OWNER svc_auto_ontology
  ENCODING 'UTF8'
  TEMPLATE template0;

\c auto_ontology
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 应用要在 public 里建表（Alembic），也要在库里建 frontend schema（Prisma）
ALTER SCHEMA public OWNER TO svc_auto_ontology;
GRANT CREATE ON DATABASE auto_ontology TO svc_auto_ontology;

-- 这一条很重要，见 1.4
ALTER ROLE svc_auto_ontology SET search_path TO public;
```

如果公司规定"数据库对象只能由 DBA 创建、应用只读写"，也可以把迁移拆出来单独执行
（见 3.2），但那样每次升级都要 DBA 配合，长期维护成本更高。

### 1.4 两个容易被忽略的坑

**PG 15 之后 `public` 不再默认对所有人可写。** 用非超级用户跑 `alembic upgrade head` 会得到
`permission denied for schema public`。上面那条 `ALTER SCHEMA public OWNER TO ...` 就是为了这个，
或者显式 `GRANT CREATE, USAGE ON SCHEMA public TO svc_auto_ontology`。

**不要建与角色同名的 schema。** 默认 `search_path` 是 `"$user", public`；如果角色叫
`svc_auto_ontology`，库里又恰好有个同名 schema，所有未限定 schema 的建表都会落到那里，
Prisma 和 Alembic 随后互相看不见对方的表。项目里两处（`alembic/env.py`、`dal/session.py`）
会把 `search_path` 钉到 `public` 兜底，但那是保险，不是设计目标。

## 2. 两个 schema 的分工

同一个库里有两套表，由两个迁移工具各管各的：

| schema | 归属 | 迁移命令 | 内容 |
| --- | --- | --- | --- |
| `public` | 后端 | `alembic upgrade head` | 目录元数据、语义层、ER 画布、分区、规则等 41 张表；向量表也在这里 |
| `frontend` | 前端 | `prisma db push` | 用户、会话、对话、邀请、API token |

两边**互不越界**：Prisma 的 datasource 只声明 `frontend`，Alembic 的 autogenerate 也过滤掉对方的表。
两条迁移命令的先后**无所谓**，但都必须成功。

`frontend` schema 本身要存在：`prisma db push` **不会**自己建它（第一次会报
`schema "frontend" does not exist`）。要么先执行一次
`CREATE SCHEMA IF NOT EXISTS frontend;`，要么用前端镜像里的 `prisma/migrate.sh` —— 它会先建
schema、清理一处历史脏数据，再 `db push`（见 3.3）。

## 3. 初始化数据库（一次性）

### 3.1 先验证连通性

在要跑服务的那台机器上：

```bash
psql "host=<公司库地址> port=5432 dbname=auto_ontology user=svc_auto_ontology sslmode=require" -c "select version()"
```

### 3.2 建 `public`（Alembic）

三种执行方式，任选其一：

```bash
# A. 本机（仓库根目录，已 uv sync）
python -m uv run alembic upgrade head

# B. 用镜像的 migrate 模式（镜像里带 alembic 与迁移文件）
docker run --rm --env-file .env auto-ontology:1.2.0 migrate

# C. Kubernetes Job（见第 7 节）
```

### 3.3 建 `frontend`（Prisma）

```bash
cd frontend
pnpm install
psql "host=<公司库地址> dbname=auto_ontology user=svc_auto_ontology" \
  -c "CREATE SCHEMA IF NOT EXISTS frontend"      # db push 不会自己建 schema
pnpm db:push                                     # 等价于 prisma db push
```

容器里对应 `prisma/migrate.sh`，它把上面两步（建 schema + 一次性的历史数据清理）和 `db push`
合在一起，生产环境直接用这个脚本更稳：

```bash
docker run --rm -w /app/migrate --env-file .env \
  auto-ontology-frontend:1.2.0 sh prisma/migrate.sh
```

### 3.4 校验（必须做，否则出问题很难定位）

```sql
-- 1) Alembic 版本 == 代码期望的 head
select version_num from public.alembic_version;

-- 2) 表数量：41 张业务表 + alembic_version（首次摄取后还会多出向量表）
select count(*) from pg_tables where schemaname = 'public';

-- 3) 中文表注释在不在（应有 41 条）
select count(*) from pg_class c
  join pg_description d on d.objoid = c.oid and d.objsubid = 0
 where c.relkind = 'r' and c.relnamespace = 'public'::regnamespace;

-- 4) 前端库表在不在
select 1 from information_schema.tables
 where table_schema = 'frontend' and table_name = 'user';
```

再把服务起起来，`GET /api/health` 会自己复核第 1 项：

```json
{"status":"ok","postgres":{"status":"ok"},"migrations":{"status":"ok","revision":"f5c5755297f7"}}
```

`migrations.status` 不是 `ok` 时后端会**拒绝启动**并打印需要的命令 —— 这是刻意设计，
比"启动成功、每个接口悄悄 500"要好。

## 4. 配置

所有组件共用仓库根目录的 `.env`（容器用 `--env-file`，K8s 用 Secret）。

### 4.1 数据库

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `POSTGRES_HOST` | 是 | 公司库地址 |
| `POSTGRES_PORT` | 是 | 通常 5432 |
| `POSTGRES_USER` | 是 | 建议专用账号，不要用 postgres 超级用户 |
| `POSTGRES_PASSWORD` | 是 | |
| `POSTGRES_DATABASE` | 是 | 例如 `auto_ontology` |
| `POSTGRES_SSLMODE` | 视公司策略 | 留空 = 明文；强制 TLS 填 `require`，要验证书填 `verify-full` |

`POSTGRES_SSLMODE` 只填一次，三个消费方各自翻译成自己驱动的写法：psycopg/libpq 与 Prisma 用
`sslmode=`，向量库用的 asyncpg 用 `ssl=`。这一项是本轮补的 —— 之前只能拼 5 个变量，
没有表达 TLS 的入口。

### 4.2 应用

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `APP_URL` | 是 | 浏览器访问的地址，如 `https://ontology.example.com`；better-auth 的 cookie 与回调都基于它 |
| `AUTH_SECRET` | 是 | 会话签名密钥，**所有副本必须一致**，升级时不要变，否则登录态全失效 |
| `AUTO_ONTOLOGY_ADMIN_EMAIL` / `_PASSWORD` | 是 | 启动时幂等创建/重置管理员；自助注册关闭，没有它就没有入口 |
| `INGESTION_SERVICE_URL` | 是 | 后端调摄取服务的地址，如 `http://ingestion-service:3002` |
| `INGESTION_PORT` | 否 | 默认 3002 |
| `PYTHON_API_URL` | 前端必填 | 前端 BFF 的转发目标，如 `http://127.0.0.1:3001` |
| `NVIDIA_API_KEY` 或 `DEFAULT_MODELS_API_KEY/ENDPOINT/MODEL` | 功能需要 | 缺了服务能起，但语义编译 / Text-to-SQL 会失败 |
| `EMBED_ENDPOINT` / `EMBED_MODEL` | 向量检索需要 | 缺省回落到 `DEFAULT_MODELS_*` |
| `AUTO_ONTOLOGY_MCP_PUBLIC_URL` | 否 | 只有对外暴露 MCP 时才需要 |

## 5. 部署方式 A：单机原生进程（推荐起步）

适合一台 Linux 服务器，或一台常开的 Windows 机器。

### 5.1 依赖

- Python 3.12 + uv
- Node.js 20+ 与 pnpm 10
- 能访问公司库的 5432

### 5.2 首次安装

```bash
git clone <repo> /opt/auto-ontology && cd /opt/auto-ontology
cp .env.example .env && ${EDITOR:-vi} .env      # 按第 4 节填
uv sync
python -m uv run alembic upgrade head            # 建 public
psql "host=$POSTGRES_HOST dbname=$POSTGRES_DATABASE user=$POSTGRES_USER" \
  -c "CREATE SCHEMA IF NOT EXISTS frontend"      # db push 不会自己建 schema
cd frontend && pnpm install && pnpm db:push && pnpm build && cd ..
```

`pnpm build` 只做一次、或前端改动后做；日常运行用 `pnpm start` 而不是 `pnpm dev`。

### 5.3 起三个进程

```bash
# 1) 后端 API
python -m auto_ontology.server

# 2) 摄取服务
python -m auto_ontology.ingestion_service

# 3) 前端
cd frontend && pnpm start
```

Windows 上可以直接用仓库脚本按顺序拉起（带健康门控）：

```powershell
.\dev_tools\start-dev.ps1 -SkipPostgres     # 用公司库，所以跳过容器
.\dev_tools\smoke-test.ps1                  # 只读自检
.\dev_tools\stop-dev.ps1
```

### 5.4 常驻（systemd）

```ini
# /etc/systemd/system/auto-ontology-api.service
[Unit]
Description=Auto-Ontology API
After=network-online.target

[Service]
Type=simple
User=auto-ontology
WorkingDirectory=/opt/auto-ontology
EnvironmentFile=/opt/auto-ontology/.env
ExecStart=/opt/auto-ontology/.venv/bin/python -m auto_ontology.server
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

摄取服务把 `ExecStart` 换成 `-m auto_ontology.ingestion_service` 即可；前端同样可以做成 unit
（`pnpm start`），或者交给反向代理转发到 `127.0.0.1:3000`。

### 5.5 反向代理

生产建议由 Nginx / Caddy 终止 TLS 并转发到 3000，`APP_URL` 写对外域名。
后端 3001 与摄取 3002 **不要**直接暴露到公网。

## 6. 部署方式 B：Docker（单机，不跑数据库容器）

镜像自带三个运行模式，正好对应部署所需：

```bash
docker build -t auto-ontology:1.2.0 .
docker build -t auto-ontology-frontend:1.2.0 ./frontend \
  --build-arg PYTHON_API_URL=http://127.0.0.1:3001
```

```bash
# 1) 后端迁移：public（跑完即退出；升级时也执行它）
docker run --rm --env-file .env auto-ontology:1.2.0 migrate

# 2) 前端迁移：frontend（建 schema + prisma db push）
docker run --rm -w /app/migrate --env-file .env \
  auto-ontology-frontend:1.2.0 sh prisma/migrate.sh

# 3) 后端
docker run -d --name ao-api --env-file .env -p 127.0.0.1:3001:3001 auto-ontology:1.2.0 server

# 4) 摄取
docker run -d --name ao-ingest --env-file .env auto-ontology:1.2.0 ingestion_service

# 5) 前端
docker run -d --name ao-web --env-file .env -p 127.0.0.1:3000:3000 auto-ontology-frontend:1.2.0
```

三个注意点：

- **不要** `docker compose up`：`docker-compose.yml` 里的 `postgres` 服务是给本地开发用的，
  接公司库时只取 `.env`，别把 `POSTGRES_HOST=postgres` 那套覆盖带进来。
- 前端镜像的 `PYTHON_API_URL` 是**构建参数**，改它要重新 build，改 `.env` 不生效。
- 容器里的 `127.0.0.1` 是容器自己。前后端都跑 Docker 时，用自定义网络，
  前端填 `PYTHON_API_URL=http://ao-api:3001`。

## 7. 部署方式 C：Kubernetes（Helm）

**现状要先说清楚**：仓库里的 chart 假定数据库是它自己起的 Pod —— `templates/secret.yaml` 把
`POSTGRES_HOST` 写死成 `"postgres"`，两个迁移 Job 的等待容器也 `nc -z postgres`。
接公司外部库需要改三个地方：

| 文件 | 现在 | 需要改成 |
| --- | --- | --- |
| `templates/secret.yaml` | `POSTGRES_HOST: "postgres"` | 从 values 读，例如 `.Values.postgres.host` |
| `templates/_helpers.tpl` | `nc -z postgres {{ .Values.postgres.service.port }}` | `nc -z "$POSTGRES_HOST" "$POSTGRES_PORT"` |
| `templates/postgres.yaml` | 无条件渲染 PVC/Deployment/Service | 用 `{{- if .Values.postgres.enabled }}` 包起来 |

同时设 `postgres.enabled=false`，并用 `bundledSecret.enabled=false` + 外部 Secret
（External Secrets Operator / Vault）提供 `POSTGRES_*`、`AUTH_SECRET`、管理员账号。

这几处改动不大，但改完必须在目标集群 `helm install --dry-run` 验证。本文档不包含这部分改动，
需要走 Kubernetes 时单独做一轮。

chart 的其余约束仍然适用：

| 检查 | 为什么 |
| --- | --- |
| `backend.alembicRevision` == 迁移 head | 否则 `wait-for-catalog-schema` init container 永久等待，Pod 卡在 Init |
| `appUrl` == 实际访问地址 | better-auth 的 cookie/回调基于它 |
| `authSecret` 所有副本一致 | 否则多副本登录态互相失效 |
| `adminEmail` / `adminPassword` 非空 | 空值会让 install 直接失败（故意的） |

## 8. 启动顺序与健康检查

```
公司 Postgres 可连
   -> alembic upgrade head        (public)
   -> prisma db push              (frontend)
        -> 后端 /api/health == 200
             -> 前端 /login == 200
摄取服务与后端并列，挂了不影响后端起，但"触发摄取"类功能会失败。
```

| 端点 | 语义 | 用途 |
| --- | --- | --- |
| `GET /api/health` | 连接 + schema 版本 + 存储 | **readiness** |
| `GET /api/health/live` | 只证明进程活着 | **liveness** |
| `GET /health/live`（3002） | 摄取进程活着 | liveness |
| `GET /login`（3000） | 前端可渲染 | readiness |

`/api/health` 会真的查库，**不要**用它做 liveness：数据库抖一下就会触发重启风暴。

## 9. 升级

1. 确认迁移 head 是否变化：仓库里 `alembic heads`，或看新镜像带的 `alembic/versions`。
2. 拉新镜像 -> 跑 `migrate` -> 滚动更新后端/摄取/前端。迁移只加不删，旧进程短时间共存是安全的。
3. 前端 `db push` 与新后端可并行，两个 schema 独立。
4. Kubernetes 部署时把 `backend.alembicRevision` 与迁移一起改（`test_migration_revision.py` 会拦）。

## 10. 回滚

- **应用**：回滚到上一个镜像 tag。迁移都是向后兼容的加表/加列，旧代码在新 schema 上能跑。
- **数据库**：`alembic downgrade -1` 只对最近一次迁移有效，且多半会丢列。生产优先"前滚修复"；
  真要回退就用备份恢复（见 11），再校验 `alembic_version` 与镜像期望的 head 一致。

## 11. 备份与恢复

数据库归 DBA 管，这里只列本项目需要的：

```bash
# 备份：两个 schema 都要，别只 dump public
pg_dump -h <host> -U <user> -d auto_ontology -Fc -f auto_ontology_$(date +%F).dump

# 恢复
pg_restore -h <host> -U <user> -d auto_ontology --clean --if-exists auto_ontology_2026-11-15.dump
```

恢复后必须核对：

```sql
select version_num from public.alembic_version;   -- 必须等于当前镜像期望的 head
```

不一致就 `alembic upgrade head`，否则后端拒绝启动。

## 12. 连接数与容量

公司库的 `max_connections` 通常不宽裕，部署前算一遍。单个进程的峰值：

| 来源 | 默认上限 | 环境变量 |
| --- | --- | --- |
| 后端 DAL 连接池 | 5 + 5 = 10 | `AUTO_ONTOLOGY_PG_POOL_SIZE` / `AUTO_ONTOLOGY_PG_MAX_OVERFLOW` |
| 向量库连接池 | 10 + 10 = 20，**两个 store** 共 40 | `AUTO_ONTOLOGY_VDB_POOL_SIZE` / `AUTO_ONTOLOGY_VDB_MAX_OVERFLOW` |
| 摄取服务 | DAL 池 10（写向量时再加 VDB 池） | 同上 |
| 前端 Prisma | node-postgres 默认 10 | — |

粗算：**一套服务（1 后端 + 1 摄取 + 1 前端）峰值约 60~70 条连接**，多副本按倍数算。
向 DBA 申请时按 `副本数 × 70 + 20 余量` 报；并发不高时把池参数调小
（`POOL_SIZE=3`、`MAX_OVERFLOW=2` 完全够用）。

需要 PgBouncer 时用 transaction 模式，并让 DBA 执行
`ALTER ROLE svc_auto_ontology SET search_path TO public;` —— 角色级设置能穿过连接池，
而连接串里的 `options=-c search_path=...` 在事务池下的行为需要单独验证。

## 13. 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `permission denied for schema public` | PG 15+ 的 public 不再对所有人可写 | `ALTER SCHEMA public OWNER TO <role>` 或 `GRANT CREATE, USAGE` |
| `extension "vector" is not available` / `type "vector" does not exist` | 公司库没装 pgvector | DBA 安装 pgvector 0.7+ 并 `CREATE EXTENSION vector` |
| `function gen_random_uuid() does not exist` | 库版本低于 13 | 升级到 15+ |
| 表建到了意料之外的 schema | 库里存在与角色同名的 schema | 删掉该 schema，或 `ALTER ROLE ... SET search_path TO public` |
| 后端启动即退出：`the database is at revision X, but this build expects Y` | 迁移没跑或跑早了 | `alembic upgrade head` |
| 后端启动即退出：`could not read the applied revision: connection timeout expired` | 网络不通 / 白名单没放行 / 库未就绪 | 先用 `psql` 验证连通，再起服务 |
| `server does not support SSL` 或要求 SSL | 公司库强制 TLS，`.env` 没配 | 设 `POSTGRES_SSLMODE=require`（或 `verify-full`） |
| 登录后立刻掉线 / 多副本互踢 | `AUTH_SECRET` 或 `APP_URL` 副本间不一致 | 统一 Secret，`APP_URL` 与浏览器地址同源 |
| 语义编译 / Text-to-SQL 报模型错误 | `NVIDIA_API_KEY` / `DEFAULT_MODELS_*` 缺失 | 补齐后重启；日志里 `nemotron ... type is unknown` 只是告警 |

排查顺序固定：`psql` 连通性 -> `alembic_version` -> `/api/health` 的 `migrations` 字段
-> 服务日志 -> 浏览器 Network 里 `/api/*` 的状态码（401/403 是前端权限层，不是后端）。

## 14. 上线检查清单

- [ ] PG 15+，`vector` 0.7+ 与 `pg_trgm` 已装
- [ ] 专用角色（非超级用户），`public` 有写权限，能建 `frontend` schema
- [ ] `ALTER ROLE ... SET search_path TO public` 已执行
- [ ] `alembic upgrade head` 成功，`alembic_version` == 镜像期望 head
- [ ] `prisma db push` 成功，`frontend.user` 存在
- [ ] 41 条中文表注释存在（`pg_description` 查得到）
- [ ] `.env` 里没有默认密码，`AUTH_SECRET` 随机且副本一致
- [ ] `POSTGRES_SSLMODE` 按公司要求设置
- [ ] `/api/health` 200 且 `migrations.status == "ok"`
- [ ] `/health/live`（3002）200，`INGESTION_SERVICE_URL` 指向正确
- [ ] `/login` 200，管理员账号能登录
- [ ] 跑一次摄取，向量表建出来，检索有结果
- [ ] 连接数已按第 12 节报给 DBA，备份策略已排期

## 附：本机开发（不用公司库时）

想在自己机器上跑一套独立的，仍然可以用仓库自带的容器化 Postgres —— 那是**开发环境**的默认路径，
与本文的生产部署无关：

```powershell
.\dev_tools\start-dev.ps1     # 会起 postgres 容器 + 三个原生进程
.\dev_tools\smoke-test.ps1
.\dev_tools\stop-dev.ps1
```
