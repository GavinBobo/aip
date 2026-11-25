<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# BKN 能力整合复盘与落地清单

> 对照对象：`aip`（承载产品）、`bkn-foundry`（BKN 后端与规范）、
> `bkn-studio`（知识网络控制台）以及现有 `auto-ontology` 数据本体。
>
> 原则：能力进入 `aip`，页面使用 `aip` 的 App Router / BFF / 组件体系，
> 图谱使用 `aip` 已有的 Sigma + d3-force 画布，不把 `bkn-studio` 的页面壳搬进来。

## 1. 已落地

| 能力 | `aip` 位置 | 状态 |
| --- | --- | --- |
| 知识网络 | `/knowledge`、`/knowledge/{id}` | 已接入 |
| 对象类（概念） | 概念页签、`knowledge_concept` | 已接入；支持别名、属性、认证、证据、数据映射 |
| 关系类 | 关系页签、`knowledge_relation` | 已接入；有向、类型、可信度、证据 |
| 行动类 | 行动页签、`knowledge_action` | 已接入；意图、绑定概念、参数、证据、认证 |
| 风险类 | 风险页签、`knowledge_risk` | 已接入；严重度、缓解措施、关联概念、证据 |
| 概念分组 | 分组页签、`knowledge_concept_group` | 已接入；创建、成员展示、删除 |
| 对象指标 | 指标页签、`knowledge_metric` | 已接入；表达式、单位、概念绑定、认证、BKN 导出/导入 |
| 能力挂载（skills / functions / MCP tools / knowledge bases） | 能力页签、`knowledge_capability` | 已接入声明、BKN capabilities 导入/导出；尚未实际执行 |
| 行动能力挂载 | 行动卡片、`knowledge_action__capability` | 已支持挂载 Function/MCP，并在 BKN action_type 输出 Action Source |
| 行动执行 | 行动卡片、`knowledge_action_execution` | 已支持 dry-run 计划、参数校验与执行记录；真实执行待独立服务 |
| 版本/回滚 | 版本页签、`knowledge_network_version` | 已接入快照、列表、字段级差异和恢复 |
| 评测（evals） | 评测页签、`knowledge_eval_case` / `run` | 已接入问题集、概念/事实命中与运行明细 |
| 事实与证据链 | 事实页签、`knowledge_evidence` | 已接入；页码、块号、原文引文 |
| OXR 文档输入 | 文档页签、`parsing_run` | 已接入；Markdown + 页级 block JSON |
| 数据本体映射 | 概念展开、`knowledge_concept__data` | 已接入；概念 → 术语 / 目录表 |
| BKN 导出 | `knowledge/bkn.py` | 已接入；object/relation/action/risk/concept_group + evidence |
| BKN 导入 | `knowledge/bkn_import.py` | 已接入；tar/zip 结构导入并按 BKN id upsert |
| 图谱画布 | `components/knowledgePage/KnowledgeGraph.tsx` | 已复用 Exploration 的 `GraphCanvas` |
| Agent 只读入口 | `mcp/all_ontology_mcp/tools.py` | 已接入知识网络、图谱、事实工具 |

### 1.1 图谱节点

`GraphCanvas` 现在支持四种知识节点：

| 节点 | 颜色语义 |
| --- | --- |
| 知识概念 | 紫色 |
| 知识行动 | 琥珀色 |
| 知识风险 | 红色 |
| 数据对象 | 绿色 |

关系边来自概念关系、行动→概念、风险→概念和概念→数据对象映射。点击概念节点会跳回概念页签。

## 2. 尚未整合的 BKN Studio 能力

这些能力在 `bkn-studio` 中已有页面或交互，但本轮没有直接搬入 `aip`：

| 能力 | 现状 | 建议落地方式 |
| --- | --- | --- |
| 对象指标（object metric） | 已接入定义、校验与数据表预览 | 增加更多 SQL 属性联动与指标版本 |
| 能力挂载（skills / functions / MCP tools / knowledge bases） | 已接入声明 | 增加工具实际挂载、授权与执行校验 |
| 执行工厂 | 已有 dry-run 计划层 | 真实执行器放到独立服务，不在 API 进程内跑工具 |
| 风险控制/权限矩阵 | 已支持 zone 回退、网络级 read/edit/manage 授权与审计 | 增加批量策略与临时授权 |
| 版本/发布/回滚 | 已支持快照、对比与恢复 | 增加发布审批与自动快照 |
| 评测（evals） | 已接入基础检索评测 | 增加答案正确性、证据覆盖率和基准集 |
| 图查询 | 已接入受控遍历（起点/深度/方向） | 完整 Cypher 需要图数据库或递归 SQL 适配层；不要假设已有 Neo4j |
| 知识网络 Agent Chat | 已接入 | Chat worker 检索已认证概念/事实/行动/风险并注入 system prompt |
| BKN 导入 | 已支持 tar/zip 结构导入 | 增加完整校验、冲突预览和版本合并策略 |
| CHECKSUM/生命周期（deprecated/replaced_by） | 未实现 | 在概念/关系/行动表上增加 lifecycle 字段并纳入导出 |

## 3. 为什么没有直接搬 `bkn-studio`

`bkn-studio` 是独立的 React Router + Ant Design 控制台，能力边界与 `aip` 不同：

- 认证、路由、权限、BFF 全部不同；
- 画布实现、节点组件、样式体系不同；
- 它依赖 `bkn-backend` 的接口与执行链，直接嵌入会把两套后端耦合在一起。

因此采用“能力迁移、页面重写、画布复用”的方式：

- 数据模型进入 `aip` Postgres / Alembic；
- 页面进入 `aip` App Router；
- 画布复用 `aip` Exploration 的 Sigma 画布；
- 对外互操作走 BKN 导出/导入，双向保持结构兼容。

## 4. 后续优先级

1. **指标 SQL 属性联动**：把指标绑定到已有 SqlAttribute，复用其目录校验和执行路径。
2. **发布审批与冲突处理**：快照/对比/恢复已打通；下一步做发布审批与冲突合并。
3. **能力挂载与执行**：行动类绑定工具/MCP，执行放在独立执行服务。
4. **细粒度权限**：知识网络 → 概念/行动/风险的授权矩阵。
5. **知识检索升级**：词面检索升级为向量召回 + rerank。

## 5. 验收命令

```powershell
uv run alembic check
uv run pytest all_ontology/knowledge/tests -q
cd frontend
pnpm exec tsc --noEmit
pnpm exec eslint components/knowledgePage components/explorationPage/graph
pnpm build
```

当前结果：迁移无漂移、知识与 Chat 测试 16 passed、MCP 工具/打包测试 20 passed、
前端类型检查/ESLint/生产构建通过；知识页、解析页与后端 API 的中英文文案已按
`zh.ts` 单一字典收口。
