# Auto-Ontology 项目结构分析与重构规划

> 目标读者：要长期维护这个仓库的人。
> 本文只描述**已经核实过的事实**和**可执行的分阶段计划**，不包含未落地的改动。
> 配套文档：[部署方案（公司现有 PostgreSQL）](./deployment-plan.md)

## 1. 现状全景

### 1.1 仓库形态

一个仓库里装了五个可独立运行/发布的产物，共享一份 Postgres：

| 产物 | 目录 | 技术栈 | 端口 | 发布方式 |
| --- | --- | --- | --- | --- |
| 后端 API | `auto_ontology/` | Python 3.12 + FastAPI + SQLAlchemy + Alembic，uv 管理 | 3001 | `Dockerfile` / Helm |
| 摄取服务 | `auto_ontology/ingestion_service/` | FastAPI（独立进程、独立调度器） | 3002 | 同一个镜像，不同命令 |
| 前端 | `frontend/` | Next.js 16 App Router + React 19 + Prisma + better-auth | 3000 | `frontend/Dockerfile`（standalone） |
| MCP 服务 | `mcp/auto_ontology_mcp/` | Python MCP server（只读） | — | `ci-mcp.yml` / staging |
| 部署资产 | `helm/auto-ontology/`、`docker-compose.yml` | Helm 3 / Compose | — | `release-*` workflows |

辅助目录：`alembic/`（迁移）、`dev_tools/`（本地开发脚本）、`skills/`（对外发布的 agent skills）、`docs/`（OpenAPI 与本文档）、`vendor/`（vendored engine wheel，Dockerfile 会 COPY 它）。

### 1.2 一个数据库、两套 schema

这是理解整个项目最关键的一条约束：

| Schema | 归属 | 迁移工具 | 内容 |
| --- | --- | --- | --- |
| `public` | 后端 | Alembic（`alembic/versions/`，当前 head `f5c5755297f7`） | 目录元数据、语义层、ER 画布、zone、规则等 |
| `frontend` | 前端 | Prisma `db push`（`frontend/prisma/schema.prisma`，`schemas = ["frontend"]`） | 用户、会话、对话、邀请、API token |

两边**互不越界**，Prisma 只声明 `frontend`，Alembic 的 autogenerate 也过滤掉对方的表。任何结构调整都不能打破这条线，否则一方的 `db push` 会尝试删除另一方的表（历史上 `alembic_version` 就差点被 Prisma 删掉）。

### 1.3 后端分层

```
auto_ontology/
  server/            FastAPI 应用装配（__main__.py 里 include_router）+ 各领域 router
    erd/             画布：router / dbml / ddl / import_export / schemas
    exploration/     探索页
    zones/ datasources/ connections/ chat/ metadata/ terms/ rules/ search/ ...
  dal/               数据访问层：schema.py（表定义）+ 每个聚合一个模块 + tests/
  catalog/           元数据采集
  connectors/        外部数据源连接器（postgres、duckdb 等）
  retrieval/         检索与生成：text_to_sql、kumo、interactive、entity_coverage
  semantic/          语义层编译
  ingestion_service/ 独立摄取进程（调度 + 路由）
  vdb/               向量库
  pii_detection/     PII 识别
  infra/ utils/      模型设置、通用工具
```

请求路径是**两层**：`server/<domain>/router.py` 只做入参校验与 HTTP 语义，真正的读写都在 `dal/<aggregate>.py`。这条规矩目前守得比较一致，是这套代码最值得保留的部分。

数据访问层有两种写法，边界已经定下来（`auto_ontology/dal/models.py` 的模块文档写着同样的话）：

| 场景 | 用哪一层 | 例子 |
| --- | --- | --- |
| 实体读写、按外键遍历 | **ORM**（`select(Zone)`、`db.get(Zone, id)`、`zone.targets`） | `zones.create_zone` / `update_zone` / `delete_zone` |
| 集合运算、批量 upsert、聚合 | **Core**（`select(...).join(...)`、`INSERT ... ON CONFLICT`） | `zones._databases_for_items`、`uploads.upsert_dataset` |

`dal/models.py` 把 `schema.py` 的同一批 `Table` 对象映射成 41 个实体类
（`__table__ = schema.zone` 这种写法），所以 DDL 只有一份、迁移不会漂移；
`dal/session.py: orm_session()` 在 `write_transaction()` 内部借用同一个连接，
两种写法能落在同一个事务里。`dal/tests/test_models.py` 用真实数据库验证了
“每张表都有实体、ORM 与 Core 读到同一行、级联删除、事务共享”这四件事。

### 1.4 前端分层

```
frontend/
  app/               App Router 页面 + app/api/** 路由处理器（BFF）
  api/               给浏览器用的 typed client（requests.get/post/patch/delete）
  auth/              better-auth 配置、权限判定、proxy-backend、seed-admin
  components/<page>/ 每个页面一个目录，页面级组件
  lib/erd/           画布的纯逻辑：geometry / layout / svgExport / templates / dbml
  i18n/              以英文原文为 key 的翻译表（messages/zh.ts）
  prisma/            schema + 迁移脚本
  types/             手写 TS 类型（erd.ts、exploration.ts ...）
  common/ enums/ hooks/ contexts/ constants/ assets/
```

关键设计：`next.config.ts` **故意没有 `rewrites()`**。浏览器发的每个 `/api/*` 都由 `app/api/**/route.ts` 接住，经 `withPermission()` 判权后由 `proxyToBackend()` 转发到 3001。所以权限判定在 BFF 层，后端不再重复校验"这个用户能不能看这个 zone"。

## 2. 问题清单（按影响排序）

### 2.1 【高】仓库根部曾有一整套未被使用的前端副本（已清理）

| 目录 | 文件数 | 状态 |
| --- | --- | --- |
| `app/` | 173 | 已归档移除 |
| `components/` | 77 | 已归档移除 |
| `common/` | 97 | 已归档移除 |
| `auto-ontology-i18n-backup/` | 0（空目录壳） | 已归档移除 |
| `outputs/` | 27 张截图 | 已归档移除（本地调试产物） |

证据：根目录没有 `package.json` / `tsconfig.json`；`frontend/tsconfig.json` 的 `@/*` 映射到 `frontend/*`，`frontend/**` 里没有任何一处 import 解析到根目录的同名目录；`docker-compose.yml` 里前端镜像的 `build.context` 是 `./frontend`；用 `Compare-Object` 比对文件清单，根部的 `app/`(173) / `components/`(77) / `common/`(97) 是 `frontend/` 对应目录的**严格子集**——根目录这份是更早的快照，没有任何独有文件。

> 注意：`shared/` **不是**死代码，尽管它也只有一份 README。它是 Excel/CSV 连接向导的默认文件投放目录（`auto_ontology/server/connections/files.py` 在 `FILE_SOURCE_ROOTS` 未设时读 `./shared`），必须保留。

影响（清理前）：任何人第一次读仓库都会以为这是两套前端；全局搜索会命中重复实现；`rg` / IDE 索引变慢。

### 2.2 【高】巨型单文件

前端：`ExplorationView.tsx` 105 KB、`GraphCanvas.tsx` 74 KB、`TermsView.tsx` 57 KB、`ErdView.tsx` 46 KB。
后端：`retrieval/kumo/pql_gen.py` 79 KB、`dal/terms.py` 71 KB、`dal/schema.py` 67 KB、`dal/model_interchange.py` 64 KB。

影响：改一处要读整文件；冲突面积大；`ErdView` 已经同时承担状态、撤销栈、剪贴板、快捷键、导出、模板、版本等多个职责。

### 2.3 【低】目录约定没有写下来

后端其实是统一的，只是从没写成规则，所以只能靠读代码猜：

- `server/<domain>/router.py` —— 该领域自己的 HTTP 面（16 个领域如此）；
- `server/<domain>/service.py` —— 编排逻辑，但 HTTP 面挂在别的领域下（`custom_analyses`、`pql_analyses` 就是这样被 exploration/chat 复用）；
- `server/ingestion/proxy.py` —— 对 3002 摄取服务的客户端，不是路由；
- `server/` 根下的 `identity.py` / `models.py` / `owners.py` / `pagination.py` / `responses.py` / `sql_utils.py` 是横切工具，平铺在这里是合理的。

真正的散乱在前端：页面组件放在 `components/<page>Page/`，但 `app/<route>/page.tsx` 里也有不少逻辑；`types/` 是手写的，与后端 Pydantic 模型没有生成关系，靠人肉同步。

### 2.4 【中】接口契约靠约定维护

`docs/openapi/auto-ontology-api.json` 由 `dev_tools/generate_backend_openapi.py` 生成并被 CI 校验，但前端 `types/*.ts` 是手抄的。字段一改（例如本次新增的列别名），两端要各自改一遍。

### 2.5 【中】启动顺序是隐式知识

后端在 import 期就会 `require_current_schema()`，Postgres 没就绪直接拒绝启动；前端 `seed-admin` 又依赖 `frontend` schema 已 push；Helm 的 `waitForCatalogSchema` 靠 `values.yaml: backend.alembicRevision` 与迁移 head 对齐（这个值曾落后于 head，已修复）。这些约束分散在四个地方，没有一份可执行的编排。

### 2.6 【低】i18n 以英文原文为 key

`t('Note')` 这种写法可读性好，但英文文案一改，中文翻译就静默失效（回退成英文）。目前靠人工维护 `messages/zh.ts`。

## 3. 目标结构

不推倒重来，只在**边界**上收口。目标形态：

```
auto-ontology/
  auto_ontology/            # 后端唯一源码根（pyproject packages 已如此声明）
    server/                 # 只放 HTTP 装配与 router
      <domain>/router.py
      <domain>/schemas.py   # 请求/响应模型（与 models.py 分离）
    dal/                    # 只放读写；大文件按聚合拆分
    domain/                 # 新增：跨 dal 的用例编排（现在的 router 里的业务分支迁到这里）
    retrieval/ semantic/ catalog/ connectors/ vdb/ pii_detection/ infra/ utils/
    ingestion_service/
  frontend/                 # 前端唯一源码根
    app/                    # 路由 + app/api/**（BFF），页面只做组装
    features/<feature>/     # 新增：按功能切片的 view / hooks / state
    components/             # 只剩跨页面复用的展示组件
    api/                    # typed client，与 app/api 一一对应
    lib/                    # 纯逻辑（无 React）
    types/                  # 生成物 + 少量手写补充
  mcp/
  alembic/
  helm/ docker-compose.yml
  dev_tools/
  docs/
```

三条硬规则，落地后写进 `CLAUDE.md` 并由工具检查：

1. `dal/` 不 import `server/`；`server/` 不写 SQL。
2. `frontend/lib/` 不 import React；`frontend/components/` 不直接 `fetch`。
3. 只有 `frontend/app/api/**` 能访问 `PYTHON_API_URL`。

## 4. 分阶段重构计划

每个阶段都能独立发布、独立回滚。**不要一次做完**。

| 阶段 | 内容 | 验收标准 | 风险 |
| --- | --- | --- | --- |
| **P0 清死代码** ✅ 已完成 | 移走根部 `app/ components/ common/ auto-ontology-i18n-backup/ outputs/`（`shared/` 保留，它是文件投放目录） | `tsc` / `eslint` / `prettier` / `pytest` 全绿 | 低。已改为"移动到 archive"而非删除，可随时搬回 |
| **P1 固化边界** | 加 `import-linter` 契约（后端）、`eslint-plugin-boundaries`（前端）；把 dev 启动脚本作为唯一入口 | CI 能拦住越界 import | 低 |
| **P2 后端拆大文件** | `dal/terms.py`、`dal/model_interchange.py`、`dal/schema.py` 按聚合拆包；`pql_gen.py` 拆 prompt/parser/emitter | 拆分后 `dal_surface.json` 快照显式重新生成并 review | 中。`auto_ontology/dal/tests/test_dal_surface.py` 会冻结公开签名，改签名必须重新生成快照 |
| **P3 引入 service 层** | 把 `router.py` 里的业务分支（例如 `erd/router.py` 的导入合并、`datasources/router.py` 的树构建）下沉到 `server/<domain>/service.py` | router 只剩参数校验 + 调用 service | 中。按领域逐个搬，不做大爆炸 |
| **P4 前端切片** | `ExplorationView` / `ErdView` 拆成 `features/<x>/{use*.ts, *Panel.tsx}`；`lib/erd` 保持纯函数 | 单文件 ≤ 400 行；`tsc` + `eslint` 绿 | 中高。需要逐块搬迁并保持行为，建议先给 `lib/erd` 加单测再动 `ErdView` |
| **P5 契约生成** | 由 `docs/openapi/auto-ontology-api.json` 生成 `frontend/types/generated.ts`，手写类型只保留 UI 专用 | 后端加字段后前端 `tsc` 直接报错提示 | 中。需要一次全量对齐 |

### 建议的执行顺序理由

P0/P1 成本最低、收益立竿见影，且不改变运行时行为，先做。P2 需要动 DAL，而 DAL 有签名快照测试兜底，安全。P3 是纯搬迁，但依赖 P2 拆好的模块。P4 风险最高，放在契约稳定之后。P5 只有在接口趋于稳定时才有意义。

## 5. 本轮已经落地的结构调整

为了避免"只写计划不动手"，本轮已经完成的部分（可验证）：

| 改动 | 位置 | 说明 |
| --- | --- | --- |
| 清掉根部死前端树 | `app/ components/ common/ auto-ontology-i18n-backup/` | 348 个文件、约 1.2 MB 的死快照移出仓库（见下方回滚说明）；`tsc` 与全量测试仍然通过 |
| 清掉根部调试产物 | `outputs/`（27 张截图） | 本地 UI 截图，无任何文档引用 |
| ERD 视图瘦身 | `frontend/lib/erd/clipboard.ts` / `download.ts` / `history.ts` | 从 `ErdView.tsx` 抽出剪贴板、文件下载、撤销栈三块纯逻辑；撤销/重做规则从 ~90 行分散代码收敛成一个 40 行的类 |
| 前端测试立起来 | `frontend/vitest.config.ts` + `lib/erd/*.test.ts` | vitest 之前装了却零测试；现在 `lib/` 下的纯逻辑有了基线（10 个用例：历史栈边界、别名行高、端口锚点） |
| 文档索引 | `docs/README.md` | 把散落的说明、生成物、设计稿分门别类，并写明各自是不是权威 |
| 忽略本地产物 | `.gitignore` | 新增 `/logs/`（启动脚本日志）与 `/outputs/` |
| Windows 可移植性 | `sqlite.py`、`infra/tests/test_frontend_schema_qualified.py`、`semantic/domain.py`、`dev_tools/release_helm_chart.py` | 四处 `read_text()` 补 UTF-8（默认 cp936 会崩）；`sqlite:///C:/...` 被解析成 `\C:\...` 的真实缺陷修掉并加了 5 个用例 |
| 可选依赖的测试不再红 | `retrieval/kumo/tests/test_wiring.py` | 缺 `kumo_relational_client`（vendored wheel）时按仓库既有惯例 `importorskip` 跳过，而不是 18 个失败 |
| 约定写进 CLAUDE.md | 根 `CLAUDE.md` + `frontend/CLAUDE.md` | 记录 Windows 一键启动、`lib/` 放纯逻辑、`pnpm test` 进入门禁 |
| 原生启动编排 | `dev_tools/start-dev.ps1` / `stop-dev.ps1` / `dev-common.ps1` | 把"隐式启动顺序"变成可执行脚本：Postgres 真实可连 → 后端 health → 摄取 → 前端 |
| 数据库就绪探针 | `dev_tools/wait_for_db.py` | 用 `.env` 里的真实凭据连库，替代"容器 healthy 就算就绪" |
| 端到端自检 | `dev_tools/smoke-test.ps1` | 登录、页面、画布 API 一条命令验证 |
| 迁移版本对齐 | `helm/auto-ontology/values.yaml` | `alembicRevision` 曾落后于 head（`b7d4f2a19c31`），会让 Helm 的 schema gate 永久等待；现在跟随 head `f5c5755297f7` |
| ORM 实体层 | `auto_ontology/dal/models.py` | 41 张表各一个实体类，中文文档；与 `schema.py` 共用 `Table` 对象，对迁移零影响 |
| ORM 会话 | `auto_ontology/dal/session.py: orm_session()` | 在 `write_transaction()` 内借用同一连接，ORM 与 Core 同事务 |
| ORM 范式改造 | `auto_ontology/dal/zones.py` | 实体 CRUD 改走 ORM，集合查询保持 Core；15 个既有测试原样通过 |
| 中文表注释 | `schema.py: TABLE_COMMENTS` + 迁移 `f5c5755297f7` | 41 张表的 `COMMENT ON TABLE` 已写入数据库，Navicat / pgAdmin 直接可见 |
| 测试可移植性 | `auto_ontology/dal/tests/test_migration_revision.py` | 读文件显式 `encoding="utf-8"`，Windows 下不再因 GBK 默认编码失败 |

### 回滚本次清理

仓库不是 Git 仓库，所以删除是**移动**而不是 `rm`。被移走的目录都在：

```
C:\Users\Administrator\Documents\auto-ontology-archive\2026-11-15-structure-cleanup\
    app\  components\  common\  auto-ontology-i18n-backup\  outputs\
```

需要任何一份时直接 `Move-Item` 回仓库根目录即可。确认不再需要后，整个 archive 目录可以删掉。

## 6. 验证基线

改动前后都应满足（在 Windows + 本地 Postgres 上实测）：

```powershell
.\dev_tools\start-dev.ps1      # 冷启动约 30s
.\dev_tools\smoke-test.ps1     # 7/7 通过
python -m pytest auto_ontology dev_tools -q   # 2653 passed, 148 skipped, 0 failed
cd frontend; pnpm exec tsc --noEmit; pnpm exec eslint .; pnpm exec prettier --check .; pnpm test
```

`skipped` 是缺少 `POSTGRES_*`、catalog fixture 或 vendored 的 `kumo_relational_client` 时的正常跳过，不是失败。
`pnpm exec eslint .` 目前只剩一条既有警告（`common/UserMenu.tsx` 用 `window.location.href` 做站内跳转），与本轮改动无关。
