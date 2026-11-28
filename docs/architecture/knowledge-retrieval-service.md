<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# 知识本体检索服务

这是独立于 Chat 的一等检索服务：人可以用它搜索文档知识，Agent 可以用它取带引用的上下文。

## 检索对象

- `knowledge_chunk`：抽取时保留的文档正文片段，带页码范围、块号范围；
- `knowledge_document`：文档标题、摘要、来源和解析状态；
- `knowledge_concept`：概念、别名、描述、认证状态；
- `knowledge_relation`：概念之间的有向关系；
- `knowledge_fact`：实例级事实，附页码、块号和原文引证；
- `knowledge_action` / `knowledge_risk` / `knowledge_metric`：动作、风险、指标；
- `knowledge_evidence`：旧文档和精确引用的兜底通道。

`knowledge_chunk` 是为了让检索不只命中“抽取出来的事实”，还能命中制度原文和段落上下文。重新抽取会在同一事务里替换文档的分块。

## 两种检索策略

| 模式 | 覆盖范围 | 用途 |
| --- | --- | --- |
| `human` | 草稿、已审阅、已认证；所有已抽取文档片段 | 编辑、审核、查资料 |
| `agent` | 只取 `reviewed` / `certified` 图对象；片段只来自至少有一个已审/已认证对象的文档 | Chat、Agent 上下文、执行前依据 |

这种分层避免两种错误：编辑看不到草稿，或 Agent 把未经审核的抽取结果当成制度事实。

## API

```text
POST /api/knowledge/search
```

```json
{
  "query": "采购审批",
  "network_id": "optional-network-id",
  "document_id": "optional-document-id",
  "mode": "human",
  "kinds": ["chunk", "concept", "fact", "evidence"],
  "limit": 20,
  "include_evidence": true
}
```

响应包含：

- `results`：按分数排序的片段、文档、概念、关系、事实、动作、风险、指标、证据；
- `citation`：页码、块号、原文、来源文件；
- `evidence`：图对象对应的原文证据；
- `facets`：类型、知识网络、文档的命中统计；
- `context`：可直接注入 Agent prompt 的紧凑 Markdown。

## 排序

当前是词面召回 + 规则排序：

1. 英文按词、中文按 2/3/4 字 n-gram 生成有界 token；
2. 在标题、名称、描述、正文、事实、关系、风险、指标表达式中做 `ILIKE`；
3. 按“精确短语 + token 覆盖率 + 类型权重 + 认证状态”排序；
4. 片段和 evidence 做去重；图对象附上原文证据。

它在当前规模下可解释、无需额外索引服务。后续可以在同一结果形状上增加向量召回和 rerank，而不改变前端或 Agent 接口。

## 权限与范围

路由使用与知识网络相同的 Zone / 用户 / 部门授权：

- 指定 `network_id` 时先校验该网络的 `read` 权限；
- 不指定时使用 `visible_network_ids(...)` 过滤到调用者可见的网络；
- 文档片段、概念、事实和证据都按同一网络范围过滤。

## 前端

- `/knowledge/search`：独立检索页；
- 左侧 Knowledge Ontology 侧栏有 **Knowledge search** 入口；
- 支持网络过滤、类型过滤、Human / Agent-ready 切换、引用展示、Agent 上下文复制。

## 验证

```powershell
uv run pytest all_ontology/knowledge/tests/test_search.py -q
uv run pytest all_ontology/server/knowledge/tests/test_search_endpoint.py -q
uv run alembic check
cd frontend
pnpm exec tsc --noEmit
pnpm exec eslint components/knowledgePage/KnowledgeSearchView.tsx
```
