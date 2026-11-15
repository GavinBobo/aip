# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The canvas assistant: turn one sentence into canvas edits.

The model never touches the database. It is handed a *summary* of the canvas the
browser holds, and returns a ``reply`` plus a list of :class:`ErdAssistantAction`
rows. The browser applies them through the same ``erdApi`` calls a person
clicking around would use, which is what makes the whole batch one undo step and
keeps multi-user state honest — the canvas is client-owned, so a server-side
write would leave the open board stale.

Two consequences shape this module:

* **Validation is not optional.** Model output is untrusted input: a hallucinated
  node id would otherwise reach ``PATCH /erd/nodes/{id}`` and 404 mid-batch,
  leaving half the request applied. Every action is checked against the canvas
  the caller sent, and anything impossible is dropped with a warning the panel
  shows.
* **The prompt is mostly constraints.** The interesting failure is not "the
  model cannot write JSON", it is the model inventing columns, binding tables
  that were never mentioned, or answering a question with twelve speculative
  edits. The system prompt says what not to do, and the validator enforces the
  parts that matter.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from auto_ontology.dal.schema import ERD_CARDINALITIES
from auto_ontology.server.erd.schemas import AssistantRequest
from auto_ontology.server.models import ErdAssistantAction, ErdAssistantReply
from auto_ontology.utils.llm_invoke import safe_invoke_structured_nr

logger = logging.getLogger(__name__)

#: A single instruction should never need more edits than this. A model that
#: wants more is usually re-describing the whole diagram, which is what import
#: is for — and a runaway batch is a canvas nobody can undo in one step.
MAX_ACTIONS = 40

_KINDS = frozenset(
    {
        "create_table",
        "add_column",
        "update_column",
        "rename_table",
        "set_table_note",
        "move_node",
        "delete_table",
        "bind_relationship",
        "delete_relationship",
    }
)

SYSTEM_PROMPT = """你是 Auto-Ontology 的 ER 画布助手。用户会用自然语言让你修改画布上的\
表结构或表之间的关系。你不是聊天机器人，你的输出会被直接执行。

你会收到当前画布的 JSON：tables（每张表的 id、name、columns、note）和 \
relationships（已有的连线，含 id、source/target 表名、连接列、基数）。

请返回：
- reply：一两句中文，说明你做了什么或为什么没做。不要复述整个画布。
- actions：要执行的修改，按顺序排列。不需要修改时返回空数组。
- warnings：留空，服务端会填。

可用的 action（kind）：
- create_table：新建一张"仅存在于图上"的表。必须给 name 和 columns（至少一列）；\
可给 note、x、y（省略坐标时前端会自动摆放）。
- add_column：给已有表加一列。需要 node_id、name；可给 data_type、note。
- update_column：改已有列的 data_type 或备注。需要 node_id、column；可给 data_type、note。
- rename_table：改表名。需要 node_id、name。
- set_table_note：写表备注。需要 node_id、note。
- move_node：挪动表。需要 node_id、x、y。
- delete_table：从画布移除表。需要 node_id。
- bind_relationship：建立两张表之间的关系。需要 source_node_id、target_node_id；\
建议同时给 source_columns、target_columns、cardinality（one-to-one / one-to-many / \
many-to-one / many-to-many），可给 label。
- delete_relationship：删除一条已有连线。需要 relationship_id。

硬性规则：
1. 只能用画布里已经存在的 id。不要编造 node_id、relationship_id 或列名。
2. 用户没提到的列不要自己加。新建表时列要来自用户的描述，不要套用模板。
3. 用户没要求就不要改已有的表名、已有列的字段和已有关系。
4. 绑定关系时，source_columns 里的列必须存在于 source 表，target_columns 同理；\
不确定用哪一列时，留空表示表级关系。
5. 一句话能说清的事不要拆成十几条 action。一次最多 40 条。
6. 需求有歧义（比如"把订单连起来"但没说是哪两张表）时，不要猜：\
reply 里问清楚，actions 返回空数组。
7. 用户问的是"这张表是干什么的"这类问题而不是修改时，只回答，不要改画布。
8. 一律用中文回答。"""


def _canvas_payload(request: AssistantRequest) -> str:
    """The canvas as compact JSON for the prompt.

    Notes are trimmed to 200 characters: a 4 KB table note is context the model
    does not need and would otherwise crowd out the tables it does.
    """
    canvas = request.canvas
    payload = {
        "tables": [
            {
                "id": node.id,
                "name": node.name,
                "virtual": node.table_id is None,
                "note": (node.note or "")[:200] or None,
                "columns": [
                    {
                        "name": column.name,
                        "data_type": column.data_type,
                        "note": column.note,
                    }
                    for column in node.columns
                ],
            }
            for node in canvas.nodes
        ],
        "relationships": [
            {
                "id": relationship.id,
                "source": relationship.source,
                "target": relationship.target,
                "source_columns": relationship.source_columns,
                "target_columns": relationship.target_columns,
                "cardinality": relationship.cardinality,
                "label": relationship.label,
            }
            for relationship in canvas.relationships
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_messages(request: AssistantRequest) -> list[Any]:
    """System prompt, the canvas, then the recent conversation and the ask."""
    messages: list[Any] = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"当前画布：\n{_canvas_payload(request)}"),
        SystemMessage(
            content="以上是当前画布。接下来是对话记录与用户的最新指令；"
            "只按最新指令行动，并遵守前面的硬性规则。"
        ),
    ]
    for turn in request.history[-8:]:
        content = turn.content[:1500]
        if turn.role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(SystemMessage(content=f"[你之前的回答] {content}"))
    messages.append(HumanMessage(content=request.message))
    return messages


def _node_ids(request: AssistantRequest) -> dict[str, Any]:
    return {node.id: node for node in request.canvas.nodes}


def _clean_name(value: str | None) -> str:
    return (value or "").strip()


def validate_actions(
    actions: list[ErdAssistantAction], request: AssistantRequest
) -> tuple[list[ErdAssistantAction], list[str]]:
    """Drop actions that cannot be applied, and say why.

    Kept pure (no database, no LLM) so the rules are testable directly. The
    browser applies what comes back, which means an action that slips through
    here becomes a failed ``erdApi`` call in the middle of a batch.
    """
    nodes = _node_ids(request)
    relationships = {row.id: row for row in request.canvas.relationships}
    accepted: list[ErdAssistantAction] = []
    warnings: list[str] = []

    for action in actions:
        kind = action.kind
        if kind not in _KINDS:
            warnings.append(f"未知操作 {kind!r}，已忽略")
            continue
        if kind in {
            "add_column",
            "update_column",
            "rename_table",
            "set_table_note",
            "move_node",
            "delete_table",
        }:
            node = nodes.get(action.node_id or "")
            if node is None:
                warnings.append(f"表 id {action.node_id!r} 不在画布上，已忽略 {kind}")
                continue
            # A catalog table mirrors the source database: its name and columns
            # are read-only here, and the API rejects writes that pretend
            # otherwise. Catching it now turns a mid-batch 400 into a sentence
            # the panel can show.
            schema_locked = node.table_id is not None
            if kind == "add_column":
                if schema_locked:
                    warnings.append(
                        f"{node.name} 来自源库，画布上不能新增列；"
                        "需要扩展字段时请新建一张虚拟表再连关系"
                    )
                    continue
                name = _clean_name(action.name)
                if not name:
                    warnings.append("add_column 缺少列名，已忽略")
                    continue
                if any(column.name == name for column in node.columns):
                    warnings.append(f"{node.name} 已有列 {name!r}，已忽略 add_column")
                    continue
                action.name = name
            elif kind == "update_column":
                if not any(column.name == action.column for column in node.columns):
                    warnings.append(
                        f"{node.name} 没有列 {action.column!r}，已忽略 update_column"
                    )
                    continue
                if schema_locked:
                    # Only the alias is the canvas's to write; the type is the
                    # database's. Keep the note, drop the rest.
                    if action.data_type:
                        warnings.append(
                            f"{node.name}.{action.column} 的类型来自源库，这里只改备注"
                        )
                    action.data_type = None
                    if not (action.note or "").strip():
                        warnings.append(
                            f"{node.name}.{action.column} 没有要写的备注，已忽略"
                        )
                        continue
            elif kind == "rename_table":
                if schema_locked:
                    warnings.append(f"{node.name} 的名称来自源库，画布上不能改名")
                    continue
                if not _clean_name(action.name):
                    warnings.append(f"{kind} 缺少名称，已忽略")
                    continue
                action.name = _clean_name(action.name)
        elif kind == "create_table":
            name = _clean_name(action.name)
            columns = [column for column in action.columns if _clean_name(column.name)]
            if not name:
                warnings.append("create_table 缺少表名，已忽略")
                continue
            if not columns:
                warnings.append(f"新建表 {name!r} 没有任何列，已忽略")
                continue
            action.name = name
            action.columns = columns
        elif kind == "bind_relationship":
            source = nodes.get(action.source_node_id or "")
            target = nodes.get(action.target_node_id or "")
            if source is None or target is None:
                warnings.append(
                    f"关系两端的表不在画布上（{action.source_node_id!r} → "
                    f"{action.target_node_id!r}），已忽略 bind_relationship"
                )
                continue
            if source.id == target.id:
                warnings.append(f"{source.name} 不能连自己，已忽略 bind_relationship")
                continue
            missing = [
                column
                for column in action.source_columns
                if not any(item.name == column for item in source.columns)
            ] + [
                column
                for column in action.target_columns
                if not any(item.name == column for item in target.columns)
            ]
            if missing:
                warnings.append(
                    f"{source.name} → {target.name} 的连接列 {missing} 不存在，已忽略"
                )
                continue
            cardinality = (action.cardinality or "many-to-one").strip()
            if cardinality not in ERD_CARDINALITIES:
                warnings.append(f"基数 {cardinality!r} 不合法，改用 many-to-one")
                cardinality = "many-to-one"
            action.cardinality = cardinality
        elif kind == "delete_relationship":
            if action.relationship_id not in relationships:
                warnings.append(
                    f"关系 id {action.relationship_id!r} 不在画布上，已忽略 delete_relationship"
                )
                continue

        accepted.append(action)
        if len(accepted) >= MAX_ACTIONS:
            warnings.append(f"一次最多执行 {MAX_ACTIONS} 条修改，其余已忽略")
            break

    return accepted, warnings


def ask(request: AssistantRequest) -> ErdAssistantReply:
    """Ask the model, validate its answer, and return what may be applied.

    Returns a reply with no actions when the model is unavailable — the panel
    shows the text instead of failing the whole bubble.
    """
    raw = safe_invoke_structured_nr(build_messages(request), ErdAssistantReply)
    if raw is None:
        logger.warning("ERD assistant returned no structured output")
        return ErdAssistantReply(
            reply=(
                "助手暂时没有响应：模型服务不可用、超时，或凭据被拒绝。"
                "具体原因见后端日志（搜索 ERD assistant）。"
            ),
            actions=[],
            warnings=[],
        )

    accepted, warnings = validate_actions(list(raw.actions), request)
    return ErdAssistantReply(
        reply=(raw.reply or "").strip() or "已按你的要求更新画布。",
        actions=accepted,
        warnings=warnings,
    )
