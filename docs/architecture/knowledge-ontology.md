<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# 知识本体（Knowledge Ontology）

> 目标：让 All-Ontology 同时拥有两条互补的本体链路：
> **数据本体**回答“这个业务词落在哪张表、哪个字段、怎么算”；
> **知识本体**回答“这个业务概念在文档里是什么、与谁相关、依据哪一段原文”。
> 两条链路通过“概念 → 术语 / 数据表”的映射连接。

## 1. 为什么不是再做一个术语表

现有数据本体由目录、术语、列属性、SQL 属性、语义外键和 ER 画布组成。它描述
的是**结构化数据里有什么**。制度、流程、合同、采购单、操作手册里的知识不在
这些表里，强行塞进术语表会丢失三样东西：

1. **关系**：概念之间的“包含、审批、依赖、流向”；
2. **事实**：带具体值的陈述，例如“采购订单 PO-001 的金额为 12,480 元”；
3. **证据**：这句话来自哪个文档、第几页、哪一段原文。

知识本体把这三样作为一等公民，并保留审核状态（草稿 / 已审阅 / 已认证），
只有被认证的概念才会成为智能体优先使用的稳定词汇。

## 2. 总体结构

```text
PDF / 图片
   │  OXR（已有）
   ▼
parsing_run（Markdown + 页级 block JSON + 源文件）
   │  知识抽取（新增）
   ▼
knowledge_document
   │
   ├── knowledge_concept      概念：对象/事件/流程/规则/指标/角色
   ├── knowledge_relation     关系：有向、带类型与可信度
   ├── knowledge_fact         事实：主语 + 谓语 + 宾语/字面值
   ├── knowledge_action       行动：可执行操作、作用对象与参数
   ├── knowledge_risk         风险：严重度与缓解措施
   ├── knowledge_metric       指标：概念的可计算表达式与单位
   ├── knowledge_concept_group 概念分组：组织相关对象类型
   ├── knowledge_capability    能力：Skill / Function / MCP / 知识库依赖
   ├── knowledge_network_version 版本：完整图定义快照
   ├── knowledge_eval_case / run 评测：问题集与检索命中结果
   └── knowledge_evidence     证据：page + block_index + 原文引文
           │
           └── knowledge_concept__data
                   ├── term（数据本体的术语）
                   └── catalog_table（数据目录中的表）
```

所有表都在现有 `public` schema、同一 Postgres 中，由 Alembic 管理；权限仍由
Next.js BFF 的 `withPermission({ catalog: [...] })` 判定，不引入第二套认证。

### 2.1 表的分工

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `knowledge_network` | 知识网络：一组可独立审核/发布的文档知识 | `status` 为 draft/published/archived |
| `knowledge_document` | 一次“解析结果 → 知识”的绑定 | 同一网络同一 `run_id` 只建一行 |
| `knowledge_concept` | 概念/类，带别名、属性、可信度 | `(network_id, key)` 唯一；`key` 兼容 BKN id |
| `knowledge_relation` | 两个概念间的有向关系 | `(network_id, key)` 唯一 |
| `knowledge_fact` | 一条可独立阅读的陈述 | 必须有主语；宾语可为概念或字面值 |
| `knowledge_action` | 从文档抽取的可执行操作 | 可绑定概念；导出为 BKN action_type |
| `knowledge_risk` | 风险、严重度与缓解措施 | 导出为 BKN risk_type |
| `knowledge_metric` | 概念的可计算指标 | 表达式可为 SQL/公式；可链接 SQL 属性并导出为 BKN object_metric |
| `knowledge_concept_group` | 相关概念的分组 | 与概念多对多；导出为 BKN concept_group |
| `knowledge_capability` | 网络依赖的 Skill/Function/MCP/知识库 | 导出为 `network.bkn` 的 capabilities |
| `knowledge_action__capability` | 行动与能力的挂载关系 | 导出为 action_type 的 Action Source |
| `knowledge_action_execution` | 行动执行计划与结果 | 当前只生成 dry-run 计划，不调用外部工具 |
| `knowledge_network_version` | 网络定义快照 | 保存完整 JSON；用于审计与回滚，不随 BKN 导出 |
| `knowledge_eval_case` / `knowledge_eval_run` | 评测问题与运行明细 | 校验概念/事实是否被检索命中 |
| `knowledge_evidence` | 概念/关系/事实/行动/风险的原文依据 | 五者恰好指向一个；删除文档级联删除 |
| `knowledge_concept__data` | 知识概念到术语或目录表的映射 | 术语/表二者取其一 |

`knowledge_evidence` 现在同时支持概念、关系、事实、行动和风险五类目标，仍然由
“恰好指向一个”约束保证不会出现孤立引文。`knowledge_document.run_id` 使用
`ON DELETE SET NULL`：删除解析结果不会删除已经
审核过的知识，证据里的引文仍然保留。概念、关系、事实、证据之间使用
`ON DELETE CASCADE`：没有文档支撑的知识不应成为孤儿。

## 3. OXR 接入方式

知识抽取不重新解析 PDF，而是直接读取 OXR 已经落库的结果：

1. 通过 `parsing_run.result_path` 读取 `result.json`；
2. 优先使用 `outputs.json.pages[].blocks[]`，保留 `page_num` 与 `idx`；
3. 应用 `parsing_block_edit` 的人工校对覆盖；
4. 没有 JSON 输出时退回 `outputs.markdown`（页码记为 1，无法定位到块）。

因此“在解析工作台校对完再抽取”与“直接抽取”走的是同一条数据路径；校对过的
内容会进入知识本体。

### 3.1 抽取流水线

`all_ontology/knowledge/extractor.py`：

- 按页和块把文档切成不超过约 6,000 字的片段，默认最多 12 片；
- 每个片段调用一次非推理模型，要求返回结构化 JSON：
  `summary / concepts / relations / facts`；
- 每条概念、关系必须能定位到原文；每条事实必须带 `evidence_quote`；
- `_evidence()` 会检查引文开头确实出现在片段里，**模型编造的引文会被丢弃**；
- 合并时按标准名/别名去重概念，按“起点 + 终点 + 关系名”去重关系，
  没有证据的事实不会入库；
- 同一文档重新抽取会替换该文档的关系、事实和证据；概念按 `key` 合并，
  已认证状态和已有属性保留。

抽取是后台任务，`knowledge_document.status` 从 `queued → extracting →
extracted/failed`；前端每 3 秒轮询文档状态。

### 3.2 为什么先切块再抽

整本手册塞进一次请求既会超上下文，也会让“这句话出自第几页”不可验证。按块
抽取的代价是跨块关系可能被拆开；当前用“关系端点缺失时补一个低可信度概念”
兜底，后续可以在网络层做跨块关系合并。

### 3.3 Chat 注入

Chat worker 在解析完追问后调用
`all_ontology.knowledge.context.retrieve_knowledge_context(processing_question)`：

- 只查询 `reviewed` / `certified` 的概念、事实、行动和风险；
- 中英文问题都会做词面检索（中文按 2–4 字 n-gram）；
- 事实会附上页码和原文证据；
- 命中的 Markdown 会追加到 text-to-SQL 的 system prompt，并明确要求
  “仅在制度/流程/角色/文档定义相关时使用，不要把知识事实当作数据库行”。

这是第一版检索：偏向精确、保守，不引入 embedding 依赖。后续可在网络数量变大时
增加向量召回与 rerank。

## 4. 借鉴 bkn-foundry 的部分

`bkn-foundry` 的 BKN 语言把业务知识网络拆成：

- `object_type`：对象类与数据属性；
- `relation_type`：两个对象类之间的有向关系与映射；
- `action_type`：可执行动作；
- `risk_type`：风险建模；
- `concept_group`：概念分组；
- 证据链与 Context Loader。

本轮先落地知识本体最核心、最容易验证的一段：

```text
concept      ↔ BKN object_type
relation     ↔ BKN relation_type
action       ↔ BKN action_type
risk         ↔ BKN risk_type
metric       ↔ BKN object_metric
concept group ↔ BKN concept_group
capability   ↔ BKN network capabilities
fact         ↔ evidence.json（All-Ontology 伴随文件）
data link    → 未来可写入 BKN 的 Data Source / Mapping Rules
```

**导出**：`GET /api/knowledge/networks/{id}/export` 返回
`{network}.bkn.tar.gz`，包含：

- `network.bkn`（`bkn_spec: "3.0"`）；
- `object_types/<concept-key>.bkn`；
- `relation_types/<relation-key>.bkn`；
- `action_types/<action-key>.bkn`（只导出能绑定到概念的）；
- `risk_types/<risk-key>.bkn`；
- `object_metrics/<metric-key>@1.json`；
- `concept_groups/<group-key>.bkn`；
- `evidence.json`（页码、块号、原文引文）；
- `README.md`。

每个对象类生成一个稳定的 `concept_id` 数据属性作为主键；每条关系生成
`concept_id → concept_id` 的占位映射，使包在没有物理资源时也能通过 BKN 结构
校验。等概念映射到真实目录表后，可以把这个占位映射替换成真实字段映射。

**导入**：`POST /api/knowledge/networks/{id}/import` 接受 `.tar/.tar.gz/.zip`，
解析 `network.bkn`、object/relation/action/risk/concept_group 文件并按 BKN id
upsert。缺失的端点对象会以同 id 的占位概念补全，避免关系丢失；导入不产生文档证据。

## 5. API

BFF 权限：读接口 `catalog: ['read']`，写接口 `catalog: ['edit']`。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/knowledge/networks` | 知识网络列表与计数 |
| POST | `/api/knowledge/networks` | 新建知识网络 |
| GET | `/api/knowledge/networks/{id}` | 网络详情 |
| PATCH | `/api/knowledge/networks/{id}` | 改名/描述/发布状态 |
| DELETE | `/api/knowledge/networks/{id}` | 删除网络及其知识 |
| GET/PUT | `/api/knowledge/networks/{id}/grants` | 读取/替换用户与部门授权 |
| GET | `/api/knowledge/networks/{id}/grant-audit` | 授权变更审计 |
| GET | `/api/knowledge/networks/{id}/concepts` | 概念列表（含证据、数据映射） |
| GET | `/api/knowledge/networks/{id}/relations` | 关系列表 |
| GET | `/api/knowledge/networks/{id}/facts` | 事实列表（含证据） |
| GET | `/api/knowledge/networks/{id}/actions` | 行动列表（含绑定概念与证据） |
| GET | `/api/knowledge/networks/{id}/risks` | 风险列表（含严重度、缓解措施与证据） |
| GET | `/api/knowledge/networks/{id}/metrics` | 对象指标列表 |
| POST | `/api/knowledge/networks/{id}/metrics` | 创建对象指标 |
| POST | `/api/knowledge/metrics/{id}/validate` | 校验指标表达式（SQL/公式） |
| POST | `/api/knowledge/metrics/{id}/preview` | 在概念绑定的目录表上执行指标并返回前 5 行 |
| GET | `/api/knowledge/networks/{id}/concept-groups` | 概念分组列表 |
| POST | `/api/knowledge/networks/{id}/concept-groups` | 创建概念分组 |
| GET | `/api/knowledge/networks/{id}/capabilities` | 能力依赖列表 |
| POST | `/api/knowledge/networks/{id}/capabilities` | 声明能力依赖 |
| POST | `/api/knowledge/actions/{id}/capabilities` | 把能力挂载到行动 |
| DELETE | `/api/knowledge/actions/{id}/capabilities/{capability_id}` | 卸载行动能力 |
| POST | `/api/knowledge/actions/{id}/execute` | 生成并保存 dry-run 执行计划 |
| GET | `/api/knowledge/networks/{id}/executions` | 行动执行记录 |
| GET | `/api/knowledge/networks/{id}/versions` | 版本列表 |
| POST | `/api/knowledge/networks/{id}/versions` | 创建完整快照 |
| POST | `/api/knowledge/versions/{id}/restore` | 恢复到某个版本 |
| GET | `/api/knowledge/versions/{id}/diff` | 对比历史版本与当前网络 |
| GET/POST | `/api/knowledge/networks/{id}/eval-cases` | 评测用例列表/创建 |
| DELETE | `/api/knowledge/eval-cases/{id}` | 删除评测用例 |
| GET/POST | `/api/knowledge/networks/{id}/eval-runs` | 评测运行列表/执行 |
| GET | `/api/knowledge/networks/{id}/documents` | 已接入文档及抽取状态 |
| POST | `/api/knowledge/networks/{id}/documents` | 绑定一个成功的解析 run 并开始抽取 |
| POST | `/api/knowledge/documents/{id}/extract` | 重新抽取 |
| DELETE | `/api/knowledge/documents/{id}` | 移除文档绑定（概念保留） |
| PATCH | `/api/knowledge/concepts/{id}` | 改名/描述/类型/认证状态 |
| PATCH | `/api/knowledge/relations/{id}` | 关系认证状态 |
| PATCH | `/api/knowledge/facts/{id}` | 事实认证状态 |
| GET | `/api/knowledge/data-targets?q=` | 搜索可映射的术语/数据表 |
| POST | `/api/knowledge/concepts/{id}/links` | 关联术语或目录表 |
| DELETE | `/api/knowledge/links/{id}` | 解除关联 |
| GET | `/api/knowledge/networks/{id}/graph` | 概念关系图 + 数据映射边 |
| GET | `/api/knowledge/networks/{id}/export` | BKN tar.gz 导出 |
| POST | `/api/knowledge/networks/{id}/import` | 导入 BKN tar.gz/zip 包 |
| POST | `/api/knowledge/networks/{id}/query` | 受控图遍历：起点、深度、方向、数据关联 |

MCP 只读工具新增：
`search_knowledge_networks`、`get_knowledge_graph`、`list_knowledge_facts`。

## 6. 前端

- 左侧导航新增 **Knowledge Ontology**；
- `/knowledge`：网络列表、创建网络；
- 创建网络时可选择 zone；未选表示所有已登录用户可见；
- 管理员可在网络详情中配置用户/部门的 `read/edit/manage` 授权；
- `/knowledge/{id}`：概览、概念、关系、行动、风险、指标、分组、能力、版本、评测、事实、文档、图谱；
- 概念详情可展开：属性、证据引文、数据本体映射搜索；
- 行动/风险页签可审核认证，分组页签可把相关概念组织成 BKN concept group；
- 文档页签可选择任意成功的 OXR 解析结果，轮询抽取进度；
- 图谱直接复用 `aip` Exploration 页的 `GraphCanvas`（Sigma + d3-force），
  不再使用单独实现的静态 SVG；概念、行动、风险和已映射的数据对象使用不同节点颜色。
- 图谱页签支持从某概念出发、按方向和深度做受控遍历查询。

页面组件在 `frontend/components/knowledgePage/`，API client 在
`frontend/api/knowledge.ts`，BFF 在 `frontend/app/api/knowledge/**`。

## 7. 验证

```powershell
uv run pytest all_ontology/knowledge/tests -q
uv run alembic check
uv run pytest all_ontology/dal/tests/test_models.py all_ontology/dal/tests/test_migration_revision.py -q
cd frontend
pnpm exec tsc --noEmit
pnpm exec eslint components/knowledgePage api/knowledge.ts app/knowledge app/api/knowledge
```

已覆盖：

- 分块保留页码/块号，引文能回定位；
- 概念/关系合并、别名、无证据事实丢弃；
- BKN 包结构、`bkn_spec: "3.0"`、对象/关系/行动/风险/分组文件与证据文件；
- BKN 导出后再导入另一个知识网络的结构往返；
- 真实 Postgres 上创建网络 → 写概念/关系/行动/风险/事实/证据 → 读回 → BKN 导出/导入 → 级联删除。

## 8. 当前边界与下一阶段

| 项目 | 当前状态 | 下一阶段 |
| --- | --- | --- |
| BKN `action_type` / `risk_type` | 已建模并可抽取/审核/导出 | 继续补充工具源、执行参数与影响契约 |
| BKN `concept_group` | 已支持创建、成员展示与导出 | 支持编辑成员与批量选择 |
| BKN object metric | 已支持创建、认证、校验、执行预览、导出与导入 | 增加更多 SQL 属性联动与指标版本 |
| BKN capabilities | 已支持声明、BKN 导出/导入 | 增加工具实际挂载与执行校验 |
| 行动能力挂载 | 已支持行动绑定 Function/MCP 并导出 Action Source | 增加参数绑定、授权与真实执行 |
| 行动执行 | 已支持 dry-run 计划、参数校验、风险提示和审计记录 | 接入独立执行服务后才允许真实工具调用 |
| 图查询 | 已支持受起点/深度/方向约束的只读遍历 | 如需完整 Cypher，后续接图数据库或递归 SQL 适配层 |
| 版本与回滚 | 已支持快照、列表、字段级差异和恢复 | 增加发布审批与自动快照策略 |
| 知识评测 | 已支持问题集、概念/事实命中检查和运行明细 | 增加答案正确性、证据覆盖率和基准集 |
| 细粒度权限 | 已支持 zone 回退、网络级 read/edit/manage 授权与审计 | 增加批量策略与临时授权 |
| BKN 导入 | 已支持结构导入 | 增加完整校验、冲突预览和版本合并策略 |
| 跨块关系合并 | 简单端点补全 | 全局实体消歧与关系对齐 |
| Chat / SQL 智能体使用知识 | 仅 MCP 只读工具 | 检索相关概念/事实并注入上下文，答案附证据 |
| 权限细粒度 | 复用 catalog read/edit | 按知识网络/分区授权 |
| 大体量文档 | 默认前 12 片 | 任务化、增量抽取、进度与取消 |

这几项不影响当前“数据本体 + 知识本体”的主链路可用性；它们是把知识本体从
“可审核的知识库”推进到“智能体默认上下文层”的下一步。
知识网络可选绑定 `zone_id`：空表示所有已登录用户可见；有值则复用 `aip`
现有的 zone/user/department 授权，列表、详情和 Chat 知识检索都按当前访问上下文过滤。
此外可以配置网络级用户/部门显式授权（read/edit/manage）；存在显式授权时，
它以网络 ACL 覆盖 zone 回退，管理员始终不受限。

## 9. 中英文与数据语言

- **界面文案**：组件里的英文就是源文案，`frontend/i18n/messages/zh.ts` 是唯一的中文表；
  新增 `t('...')` 必须同时补中文，且不得出现重复 key。
- **API 文案**：后端只返回英文源文案（错误、标签、默认标题）。前端在
  `frontend/api/requests.ts` 的错误入口统一调用 `t()`，因此知识、Chat、解析页面拿到的
  `message` 已按当前语言本地化；新增后端文案必须加入 `zh.ts`。
- **抽取内容**：抽取提示词要求“描述和事实使用原文语言”，英文 PDF 产出英文描述、
  中文 PDF 产出中文描述，专有名词始终保留原文。
- **BKN 交换**：包结构说明（Aliases、Extraction confidence、Severity、Mitigation 等）
  固定英文，便于 bkn-foundry 消费；对象名与描述保持原文，导入同时兼容中英文标签。
- **时间显示**：知识页统一用 `formatDateTime`，跟随语言开关（`zh-CN` / `en-US`），
  不再受浏览器默认语言影响。
- **Chat 知识上下文**：检索到的事实保持原文；上下文小标题与证据标签跟随提问语言，
  英文问题得到英文脚手架，中文问题保持中文。

