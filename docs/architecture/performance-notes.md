# 性能与结构优化记录

> 记录已经落地并有验证证据的优化，不写未执行的计划。
> 基准数据来自本机 Windows + Python 3.12 环境。

## 1. 算法复杂度

| 位置 | 之前 | 现在 | 证据 |
| --- | --- | --- | --- |
| `knowledge/extractor.py: merge_chunks` | 每新增一个概念都重建全部 key 的集合，O(C²) | 直接用 `concepts` 字典判重，O(C) | 4000 个概念：0.55s → 0.26s；新增 slug 冲突测试 |
| `frontend/lib/erd/layout.ts: layeredLayout` | `queue.shift()` 每次 O(n)，BFS 整体 O(n²) | 索引游标遍历，O(n) | 2000 节点链 + 500 节点星形图测试 |
| `retrieval/interactive/kb_coverage.py` | 子/孙/曾孙三层手写展开，重复去重与追加逻辑 | 单栈深度优先遍历，最多 3 层、每父 5 个 | 新增深度、上限、去重测试 |
| `knowledge/context.py: _tokens` | 先生成全文所有 2/3/4-gram，再截到 14 个 | 边生成边去重，满 14 个立即返回 | 2500 字中文问题：0.45ms → 0.048ms/次 |
| `catalog/normalize.py: normalize_tables` | `apply` 逐行做时区转换 | pandas `.dt.tz_convert().dt.floor()` 向量化 | 20 万行：1.59s → 0.77s |
| `catalog/store/db.py` + `catalog/diff.py` | 每条表/列边单独事务写入 | 整个批次共享一个事务，新增表/列走一次 batch | N 次事务提交降为 1 次 |

## 2. 启动时间

`python -X importtime -c "import all_ontology.server.__main__"` 的累计导入时间：

| 阶段 | 耗时 |
| --- | --- |
| 优化前 | 约 7.6–8.6s |
| 优化后 | 约 3.6–4.0s |

做法：

- `all_ontology/utils/__init__.py` 改为 PEP 562 按需加载，导入 JSON 工具不再连带 embedding/openai/pandas。
- `all_ontology/connectors/__init__.py` 改为按需加载，导入包本身不再加载 Snowflake/Databricks 驱动。
- `CONNECTOR_REGISTRY` 改为懒映射，只导入连接串实际使用的 scheme 对应驱动。
- 图表分析、数据源/术语/SQL 属性重嵌入、实体覆盖率、模型导入改为函数内导入；
  路由启动只加载 HTTP 面，真正用到大模型或向量库时再加载。
- 解析模型客户端的 `openai` 与图表 LLM 客户端都延迟到首次实际使用；仅导入
  `all_ontology.server.__main__` 不再加载 openai。
- ERD 助手的 LangChain 依赖也改为接口首次调用时加载。
- 文件连接器（Excel/CSV 预览与建帧）的 pandas 依赖改为首次操作时加载。
- 数据源/探索/API 连接器与 SQL 查询存储模块的 pandas 依赖也改为按需加载；
  pandas 仍会由核心 catalog 模型带入，继续拆分的收益已经很小。

回归保护：`all_ontology/tests/test_lazy_imports.py` 用子进程断言
`import all_ontology.utils` / `import all_ontology.connectors` 不会加载重依赖。

## 2.1 知识上下文索引

`retrieve_knowledge_context` 每次提问都会对 concept/fact/action/risk/metric 的
自由文本做 `ILIKE '%词%'`。这些列原先只有 btree 索引，无法服务无锚点子串匹配。
迁移 `b8f1c3d5e7a9` 为 11 个文本列补了 `pg_trgm` GIN 索引。

临时 5 万行表上的 `EXPLAIN ANALYZE`（同一查询形状）：

| 状态 | 计划 | 执行时间 |
| --- | --- | --- |
| 无 trigram 索引 | Seq Scan + Filter | 39.744 ms |
| 有 trigram 索引 | BitmapOr → Bitmap Heap Scan | 0.102 ms |

Helm 的 `backend.alembicRevision` 已同步 bump 到 `b8f1c3d5e7a9`。

## 3. 结构清理

| 改动 | 说明 |
| --- | --- |
| 删除 `auto_ontology/` | 529 个文件的旧副本；独有测试已迁入 `all_ontology` |
| 删除 `mcp/auto_ontology_mcp/` | 与 `mcp/all_ontology_mcp/` 重复的旧包；旧测试同步移除 |
| 删除 `docs/openapi/auto-ontology-api.json` | 改名前的旧生成物，已无引用 |
| 修正 `Makefile` / `frontend/README.md` | schema 归属与端口说明改为当前事实（public / frontend，3010 / 3001） |
| 修复 `lib/erd/svgExport.ts` | 负坐标时背景不再跑进平移组；表注释以灰色标记 + `<title>` 导出 |

### 3.1 分层归位

原先 `dal/`、`semantic/`、`knowledge/`、`ingestion_service/` 都会反向 import
`all_ontology.server.*`，把 HTTP 层当成库使用。本轮把它们归位：

| 移动 | 新位置 | 理由 |
| --- | --- | --- |
| 模型导入 schema / embed 支持 | `all_ontology/model_interchange/` | DAL 与 server 共用，不属于 HTTP |
| SQL 解析与校验 | `all_ontology/sql/validation.py` | DAL 只需要 `SqlParseError`，不该 import server |
| Zone 常量与响应格式化 | `all_ontology/zones/` | DAL 的 zone 读写需要同一份标签映射 |
| SQL Attribute 编排 | `all_ontology/domain/sql_attributes.py` | semantic 建表达式与 API 建表达式是同一用例 |
| 规则重放 | `all_ontology/domain/rules.py` | 摄取进程与 API 共用 |
| 全局搜索编排 | `all_ontology/domain/search.py` | 规则与搜索路由共用 |
| 健康检查与响应契约 | `all_ontology/infra/health.py` | API 与摄取服务共用 |
| 解析 HTTP 路由 | `all_ontology/server/parsing/router.py` | `parsing/` 保持纯解析逻辑 |
| 术语链路遍历 | `all_ontology/dal/term_links.py` | 从 75KB 的 `dal/terms.py` 拆出 361 行自包含 BFS/路径补全 |
| ColumnAttribute / 关系 / 链路 | `dal/term_attributes.py`、`term_related.py`、`term_links.py`、`term_scope.py` | `dal/terms.py` 从约 1960 行降到 1176 行；DAL 现为 33 个模块、432 个函数 |
| Kumo PQL 语法 / 错误 / 执行 / 结果 | `retrieval/kumo/pql_syntax.py`、`pql_errors.py`、`pql_execution.py`、`pql_results.py` | 83KB 的 `pql_gen.py` 从约 1700 行降到 1050 行；公共导出保持不变 |

回归保护：`all_ontology/tests/test_layering.py` 用 AST 断言
`all_ontology/server/` 之外的包不再 import `all_ontology.server.*`，
并且 `dal/` 不 import FastAPI。当前违规数为 0。

## 4. 验证基线

- `pytest all_ontology -q`：2846 passed，138 skipped，3 failed（仅 `vdb/tests/test_vector_index.py`，本机 pgvector 不支持 `halfvec`，与改动无关）。
- `pytest mcp/tests -q`：88 passed。
- `pnpm test`（frontend）：30 passed。
- `tsc --noEmit`、ESLint、Prettier、Ruff：通过。
