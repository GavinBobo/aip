<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# ERD → 数据本体候选

ER 画布描述的是**设计意图**，catalog 描述的是**物理事实**，二者都不是可直接使用的数据本体。这个功能把它们对齐，生成一份可审阅的候选报告，并在用户明确选择后才写入语义层。

## 输入

- 当前 Zone 的 ER 画布：表卡片、分类、备注、关系、基数、连接列、虚拟表；
- catalog：库、Schema、表、列、主键、真实外键、类型、可空性、唯一性、采样值；
- 已编译语义层：Term、ColumnAttribute、语义外键。

## 输出

`GET /api/erd/canvases/{zone_id}/ontology-candidates`

报告包含：

- `entities`：每个表卡片的映射状态、语义角色、粒度、建议 Term、字段提示和问题；
- `relationships`：按基数推导出的 FK 方向、引用端/被引用端、类型兼容、唯一性、真实 FK、采样值重叠；
- `catalog_fks_not_drawn`：catalog 有、ERD 没画的外键；
- `gaps`：虚拟表、缺主键、缺 Term、多对多、类型不匹配等结构化差距；
- `summary`：映射率、Term 覆盖、关系验证率和 0–1 的就绪度。

报告是只读的。ERD 的备注只是设计提示，不会自动变成认证语义。

## 显式应用

`POST /api/erd/canvases/{zone_id}/ontology-candidates/apply`

请求体只携带 id 和开关：

```json
{
  "entity_node_ids": ["node-1"],
  "relationship_ids": ["rel-1"],
  "create_terms": true,
  "create_semantic_fks": true
}
```

服务端会重新生成报告，再应用当前候选：

- 只为还没有 Term 的表创建 Term；已有 Term 只在描述为空时补描述；
- 关系只有在两端都绑定 catalog、列存在且不是多对多时才应用；
- 按基数决定 FK 所有权，例如 `many-to-one` 的引用端是 source，`one-to-many` 的引用端是 target；
- 为被引用列创建/复用 ColumnAttribute，再写 `column__semantic_fk`；
- 跨库关系由 `merge_semantic_fk` 拒绝。

应用不会自动认证 Term 或列属性。认证仍然需要人工完成。

## 设计边界

- **虚拟表只做候选**：`table_id` 为空时只能提示，不能写语义外键；
- **ERD 不是物理真相**：真实 FK、唯一性和值重叠来自 catalog/Profiling，不来自画布；
- **采样值不是全量证明**：`value_overlap` 只是采样检查，低重叠或未采样都会给出提示；
- **多对多不硬造边**：需要桥接表后再建模；
- **复合键按单列应用**：当前语义外键是 Column → ColumnAttribute，复合键会逐列应用，报告会明确提示复核；
- **状态可复核**：报告保留 `validated` / `declared` / `probable` / `needs_review` / `logical_only` / `invalid`，不把“能推断”当成“已认证”。

## 验证

```powershell
uv run pytest all_ontology/semantic/tests/test_erd_candidates.py -q
uv run pytest all_ontology/server/erd/tests/test_ontology_endpoint.py -q
uv run pytest all_ontology/server/erd/tests/test_ontology_db.py -q
cd frontend
pnpm exec tsc --noEmit
pnpm exec eslint components/erdPage/ErdOntologyDialog.tsx components/erdPage/ErdToolbar.tsx
```
