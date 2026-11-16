# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The canvas assistant's guard rails.

The model is untrusted input here: it sees ids and must use them, but nothing
stops it inventing one. These tests pin the rules that keep a bad answer from
turning into half-applied edits in the browser -- no database, no LLM.
"""

from __future__ import annotations

import json

from all_ontology.server.erd.assistant import (
    MAX_ACTIONS,
    build_messages,
    validate_actions,
)
from all_ontology.server.erd.schemas import (
    AssistantCanvas,
    AssistantColumn,
    AssistantNode,
    AssistantRelationship,
    AssistantRequest,
    AssistantTurn,
)
from all_ontology.server.models import ErdAssistantAction, ErdAssistantColumn


def _canvas() -> AssistantCanvas:
    return AssistantCanvas(
        nodes=[
            AssistantNode(
                id="n-orders",
                name="public.orders",
                columns=[
                    AssistantColumn(name="id", data_type="bigint"),
                    AssistantColumn(name="customer_id", data_type="bigint"),
                ],
            ),
            AssistantNode(
                id="n-customers",
                name="public.customers",
                columns=[AssistantColumn(name="id", data_type="bigint")],
            ),
        ],
        relationships=[
            AssistantRelationship(
                id="r-1",
                source="public.orders",
                target="public.customers",
                source_columns=["customer_id"],
                target_columns=["id"],
            )
        ],
    )


def _request(message: str = "把订单和客户连起来") -> AssistantRequest:
    return AssistantRequest(zone_id="z-1", message=message, canvas=_canvas())


def test_a_proposed_edit_on_a_missing_table_is_dropped() -> None:
    actions = [ErdAssistantAction(kind="add_column", node_id="n-ghost", name="ts")]
    accepted, warnings = validate_actions(actions, _request())
    assert accepted == []
    assert any("n-ghost" in warning for warning in warnings)


def test_adding_a_column_that_already_exists_is_dropped() -> None:
    actions = [ErdAssistantAction(kind="add_column", node_id="n-orders", name=" id ")]
    accepted, warnings = validate_actions(actions, _request())
    assert accepted == []
    assert any("已有列" in warning for warning in warnings)


def test_a_new_table_needs_a_name_and_at_least_one_column() -> None:
    unnamed = ErdAssistantAction(
        kind="create_table", name="  ", columns=[ErdAssistantColumn(name="id")]
    )
    empty = ErdAssistantAction(kind="create_table", name="draft.events", columns=[])
    accepted, _ = validate_actions([unnamed, empty], _request())
    assert accepted == []


def test_a_relationship_over_a_column_that_does_not_exist_is_dropped() -> None:
    action = ErdAssistantAction(
        kind="bind_relationship",
        source_node_id="n-orders",
        target_node_id="n-customers",
        source_columns=["buyer_id"],
        target_columns=["id"],
    )
    accepted, warnings = validate_actions([action], _request())
    assert accepted == []
    assert any("buyer_id" in warning for warning in warnings)


def test_a_relationship_between_a_table_and_itself_is_dropped() -> None:
    action = ErdAssistantAction(
        kind="bind_relationship",
        source_node_id="n-orders",
        target_node_id="n-orders",
    )
    accepted, warnings = validate_actions([action], _request())
    assert accepted == []
    assert any("不能连自己" in warning for warning in warnings)


def test_an_unknown_cardinality_falls_back_rather_than_failing() -> None:
    action = ErdAssistantAction(
        kind="bind_relationship",
        source_node_id="n-orders",
        target_node_id="n-customers",
        cardinality="orders-to-customer",
    )
    accepted, warnings = validate_actions([action], _request())
    assert [item.cardinality for item in accepted] == ["many-to-one"]
    assert any("基数" in warning for warning in warnings)


def test_deleting_a_relationship_that_is_not_there_is_dropped() -> None:
    action = ErdAssistantAction(kind="delete_relationship", relationship_id="r-9")
    accepted, warnings = validate_actions([action], _request())
    assert accepted == []
    assert any("r-9" in warning for warning in warnings)


def test_a_well_formed_batch_survives_intact() -> None:
    actions = [
        ErdAssistantAction(
            kind="bind_relationship",
            source_node_id="n-orders",
            target_node_id="n-customers",
            source_columns=["customer_id"],
            target_columns=["id"],
            cardinality="many-to-one",
        ),
        ErdAssistantAction(kind="add_column", node_id="n-orders", name=" created_at "),
        ErdAssistantAction(kind="set_table_note", node_id="n-orders", note="订单主表"),
        ErdAssistantAction(kind="delete_relationship", relationship_id="r-1"),
    ]
    accepted, warnings = validate_actions(actions, _request())
    assert len(accepted) == 4
    assert warnings == []
    # Names are trimmed on the way through, not trusted as sent.
    assert accepted[1].name == "created_at"


def test_a_runaway_batch_is_capped_and_says_so() -> None:
    actions = [
        ErdAssistantAction(kind="add_column", node_id="n-orders", name=f"col_{index}")
        for index in range(MAX_ACTIONS + 5)
    ]
    accepted, warnings = validate_actions(actions, _request())
    assert len(accepted) == MAX_ACTIONS
    assert any(str(MAX_ACTIONS) in warning for warning in warnings)


def test_unknown_kinds_are_reported_not_executed() -> None:
    accepted, warnings = validate_actions(
        [ErdAssistantAction(kind="drop_database")], _request()
    )
    assert accepted == []
    assert any("drop_database" in warning for warning in warnings)


def _catalog_request() -> AssistantRequest:
    """A canvas whose tables come from the catalog, so their schema is read-only."""
    canvas = AssistantCanvas(
        nodes=[
            AssistantNode(
                id="n-orders",
                name="public.orders",
                table_id="t-1",
                columns=[AssistantColumn(name="id", data_type="bigint")],
            )
        ]
    )
    return AssistantRequest(zone_id="z-1", message="改一下", canvas=canvas)


def test_a_catalog_table_cannot_gain_a_column() -> None:
    actions = [ErdAssistantAction(kind="add_column", node_id="n-orders", name="x")]
    accepted, warnings = validate_actions(actions, _catalog_request())
    assert accepted == []
    assert any("来自源库" in warning for warning in warnings)


def test_a_catalog_table_cannot_be_renamed() -> None:
    actions = [ErdAssistantAction(kind="rename_table", node_id="n-orders", name="o2")]
    accepted, warnings = validate_actions(actions, _catalog_request())
    assert accepted == []
    assert any("不能改名" in warning for warning in warnings)


def test_a_catalog_column_keeps_only_its_alias() -> None:
    actions = [
        ErdAssistantAction(
            kind="update_column",
            node_id="n-orders",
            column="id",
            data_type="text",
            note="订单主键",
        )
    ]
    accepted, warnings = validate_actions(actions, _catalog_request())
    assert len(accepted) == 1
    # The type is the database's; the alias is the canvas's.
    assert accepted[0].data_type is None
    assert accepted[0].note == "订单主键"
    assert any("只改备注" in warning for warning in warnings)


def test_the_prompt_carries_the_canvas_and_the_recent_turns() -> None:
    request = AssistantRequest(
        zone_id="z-1",
        message="再给它加一个时间戳",
        canvas=_canvas(),
        history=[
            AssistantTurn(role="user", content="给订单加备注"),
            AssistantTurn(role="assistant", content="好的"),
        ],
    )
    messages = build_messages(request)
    joined = "\n".join(str(message.content) for message in messages)
    assert "public.orders" in joined
    # The canvas travels as JSON the model can address ids from.
    canvas_line = next(
        message.content
        for message in messages
        if message.content.startswith("当前画布")
    )
    payload = json.loads(canvas_line.split("\n", 1)[1])
    assert [table["id"] for table in payload["tables"]] == ["n-orders", "n-customers"]
    assert "给订单加备注" in joined
    assert messages[-1].content == "再给它加一个时间戳"
