<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# 语义桥（Semantic Bridge）

数据本体和知识本体不是两套孤立的目录。语义桥负责把“文档里说的东西”接到“数据里能算的东西”和“执行层能做的事”上。

## 三条桥

| 桥 | 知识侧 | 数据/执行侧 | 现有表 |
| --- | --- | --- | --- |
| 概念 → 术语/表 | 文档概念 | glossary term / catalog table | `knowledge_concept__data` |
| 指标 → SQL 属性 | 知识指标 | reviewed SQL expression | `knowledge_metric.sql_attribute_id` |
| 动作 → 能力 | 文档动作 | Skill / Function / MCP / knowledge base | `knowledge_action__capability` |

## API

```text
GET /api/knowledge/networks/{network_id}/bridge
```

返回：

- `summary`：概念、指标、动作各自的 total / linked / coverage；
- `concepts`：每个概念及其已关联的术语/表；
- `metrics`：每个指标及其 SQL 属性；
- `actions`：每个动作及其执行能力；
- `capabilities`：当前网络可挂载的能力清单。

覆盖率的定义：

```text
coverage = (linked concepts + linked metrics + linked actions)
           / (all concepts + all metrics + all actions)
```

它是运营信号，不是认证。一个已关联对象仍可能是 draft。

## 前端

`/knowledge/bridge` 是统一的语义桥工作台：

- 概念：搜索术语/表并关联；
- 指标：选择 SQL 属性并关联；
- 动作：选择能力并关联；
- 顶部显示三条桥的覆盖率和总体覆盖率；
- 关联后立即刷新覆盖数据。

## 权限

- 读取 bridge：`catalog:read` / 知识网络 `read`；
- 修改映射：沿用现有概念、指标、动作的 `edit` / `contribute` 权限；
- 映射目标仍受 Zone 和 catalog 可见性约束。

## 与规则的关系

规则不是指标。规则应成为知识本体的一等对象，并通过桥引用：

- 规则 → 指标/字段：规则的可计算操作数；
- 规则 → 动作：规则命中后的执行动作；
- 规则 → 概念：规则适用的业务对象；
- 规则 → 证据：规则来自哪份文档、哪一页。

语义桥先把现有的三条链路运营起来；规则桥是下一步，不应把规则降级成指标。

## 验证

```powershell
uv run pytest ontology_studio/server/knowledge/tests/test_bridge_endpoint.py -q
cd frontend
pnpm exec tsc --noEmit
pnpm exec eslint components/knowledgePage/KnowledgeBridgeView.tsx
```
