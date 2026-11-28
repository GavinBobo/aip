# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ER canvas storage on Postgres.

Concentrated on the two behaviours that are easy to get wrong:

* **reconciliation** — a canvas tracks its zone on every read, adding a node for
  a table the zone gained and removing one it lost, while leaving diagram-only
  (virtual) nodes alone;
* **cascade** — deleting a node takes its relationships with it.

Needs a migrated database and skips without one.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytest.importorskip("sqlalchemy")

from all_ontology.dal import schema as s  # noqa: E402
from all_ontology.dal.erd import (  # noqa: E402
    create_node,
    create_note,
    create_area,
    create_version,
    create_relationship,
    delete_node,
    delete_note,
    delete_area,
    delete_version,
    delete_relationship,
    get_canvas,
    get_or_create_canvas,
    MAX_NODE_WIDTH,
    MIN_NODE_WIDTH,
    restore_node,
    restore_version,
    update_note,
    update_area,
    list_versions,
    restore_canvas_state,
    update_node,
    update_relationship,
    update_viewport,
)
from all_ontology.dal.session import store  # noqa: E402
from all_ontology.dal.zones import create_zone, delete_zone  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def require_schema():
    if not os.environ.get("POSTGRES_USER"):
        pytest.skip("POSTGRES_* not set")
    try:
        store().query_read("SELECT 1 FROM erd_canvas LIMIT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"all_ontology schema unavailable (alembic upgrade head): {exc}")


@pytest.fixture
def catalog():
    """One database, one schema, two tables with columns, plus a zone."""
    prefix = f"e-{uuid.uuid4().hex[:8]}"
    ids: dict[str, str] = {"prefix": prefix}

    def insert(table, **values):
        return store().query_write(
            table.insert().values(**values).returning(table.c.id)
        )[0]["id"]

    ids["db"] = insert(s.catalog_database, name=f"{prefix}-db")
    ids["schema"] = insert(s.catalog_schema, database_id=ids["db"], name="public")
    ids["customers"] = insert(
        s.catalog_table, schema_id=ids["schema"], name="customers", pk=["id"]
    )
    ids["orders"] = insert(
        s.catalog_table, schema_id=ids["schema"], name="orders", pk=["id"]
    )
    insert(
        s.catalog_column,
        table_id=ids["customers"],
        name="id",
        data_type="bigint",
        ordinal_position=1,
        is_nullable=False,
    )
    insert(
        s.catalog_column,
        table_id=ids["orders"],
        name="customer_id",
        data_type="bigint",
        ordinal_position=2,
        is_nullable=True,
    )

    ids["zone"] = create_zone(
        name=f"{prefix}-zone",
        description=None,
        color="#76b900",
        item_ids=[ids["orders"], ids["customers"]],
    )["id"]

    yield ids

    store().query_write(
        s.catalog_database.delete().where(s.catalog_database.c.id == ids["db"])
    )
    delete_zone(ids["zone"])


def _node_by_name(canvas: dict, name: str) -> dict:
    return next(node for node in canvas["nodes"] if node["name"] == name)


def test_canvas_is_created_once_and_reused(catalog) -> None:
    first = get_or_create_canvas(catalog["zone"])
    second = get_or_create_canvas(catalog["zone"])

    assert first["id"] == second["id"]
    assert first["zone_name"] == f"{catalog['prefix']}-zone"


def test_every_covered_table_becomes_a_node_with_its_columns(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    names = {node["name"] for node in canvas["nodes"]}
    assert names == {"public.customers", "public.orders"}

    customers = _node_by_name(canvas, "public.customers")
    assert customers["columns"][0]["name"] == "id"
    assert customers["columns"][0]["is_primary_key"] is True
    assert customers["table_id"] == catalog["customers"]


def test_a_table_added_to_the_zone_appears_on_the_next_read(catalog) -> None:
    third = store().query_write(
        s.catalog_table.insert()
        .values(schema_id=catalog["schema"], name="products")
        .returning(s.catalog_table.c.id)
    )[0]["id"]
    store().query_write(
        s.zone_target.insert().values(zone_id=catalog["zone"], table_id=third)
    )

    canvas = get_or_create_canvas(catalog["zone"])
    assert "public.products" in {node["name"] for node in canvas["nodes"]}


def test_a_table_removed_from_the_zone_loses_its_node(catalog) -> None:
    get_or_create_canvas(catalog["zone"])
    store().query_write(
        s.zone_target.delete().where(
            s.zone_target.c.zone_id == catalog["zone"],
            s.zone_target.c.table_id == catalog["orders"],
        )
    )

    canvas = get_or_create_canvas(catalog["zone"])
    assert "public.orders" not in {node["name"] for node in canvas["nodes"]}


def test_virtual_nodes_survive_reconciliation(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    created = create_node(
        canvas_id=canvas["id"],
        name="draft.audit_log",
        table_id=None,
        columns=[{"name": "id", "data_type": "uuid", "is_primary_key": True}],
        x=10,
        y=20,
    )

    again = get_or_create_canvas(catalog["zone"])
    node = _node_by_name(again, "draft.audit_log")
    assert node["id"] == created["id"]
    assert node["columns"][0]["name"] == "id"


def test_moving_a_node_is_persisted(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    node = _node_by_name(canvas, "public.customers")

    updated = update_node(node["id"], x=123.5, y=456.25, collapsed=None)
    assert updated is not None
    assert (updated["x"], updated["y"]) == (123.5, 456.25)

    reread = _node_by_name(get_canvas(catalog["zone"]), "public.customers")
    assert (reread["x"], reread["y"]) == (123.5, 456.25)


def test_a_table_width_is_persisted_and_clamped(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    customers = _node_by_name(canvas, "public.customers")

    resized = update_node(customers["id"], x=None, y=None, collapsed=None, width=360)
    assert resized is not None
    assert resized["width"] == 360
    reread = _node_by_name(get_canvas(catalog["zone"]), "public.customers")
    assert reread["width"] == 360

    narrow = update_node(customers["id"], x=None, y=None, collapsed=None, width=10)
    assert narrow is not None and narrow["width"] == MIN_NODE_WIDTH
    wide = update_node(customers["id"], x=None, y=None, collapsed=None, width=5000)
    assert wide is not None and wide["width"] == MAX_NODE_WIDTH

    snapshot = get_canvas(catalog["zone"])
    restored = restore_canvas_state(
        canvas["id"], snapshot["nodes"], snapshot["relationships"]
    )
    assert restored is not None
    assert _node_by_name(restored, "public.customers")["width"] == MAX_NODE_WIDTH


def test_a_table_category_is_canvas_metadata(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    customers = _node_by_name(canvas, "public.customers")

    updated = update_node(
        customers["id"], x=None, y=None, collapsed=None, category="  dimension  "
    )
    assert updated is not None and updated["category"] == "dimension"
    reread = _node_by_name(get_canvas(catalog["zone"]), "public.customers")
    assert reread["category"] == "dimension"
    snapshot = get_canvas(catalog["zone"])
    restored = restore_canvas_state(
        canvas["id"], snapshot["nodes"], snapshot["relationships"]
    )
    assert restored is not None
    assert _node_by_name(restored, "public.customers")["category"] == "dimension"

    cleared = update_node(customers["id"], x=None, y=None, collapsed=None, category="")
    assert cleared is not None and cleared["category"] is None


def test_catalog_column_appearance_is_canvas_only(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    customers = _node_by_name(canvas, "public.customers")

    updated = update_node(
        customers["id"],
        x=None,
        y=None,
        collapsed=None,
        column_appearance={
            "id": {"color": "#12AB34", "style": "bold"},
            "missing": {"color": "not-a-color", "style": "sparkles"},
        },
    )
    assert updated is not None
    assert len(updated["columns"]) == 1
    assert updated["columns"][0]["color"] == "#12ab34"
    assert updated["columns"][0]["style"] == "bold"
    # The catalog still supplies the schema itself.
    assert updated["columns"][0]["data_type"] == "bigint"

    reread = _node_by_name(get_canvas(catalog["zone"]), "public.customers")
    assert reread["columns"][0]["color"] == "#12ab34"
    assert reread["columns"][0]["style"] == "bold"


def test_virtual_columns_keep_color_and_style(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    created = create_node(
        canvas_id=canvas["id"],
        name="draft.styled",
        table_id=None,
        columns=[
            {
                "name": "id",
                "data_type": "uuid",
                "color": "#FF8800",
                "style": "monospace",
            }
        ],
        x=0,
        y=0,
    )
    assert created["columns"][0]["color"] == "#ff8800"
    assert created["columns"][0]["style"] == "monospace"


def test_a_canvas_only_table_can_be_edited_in_place(catalog) -> None:
    """drawDB-style table editing: rename and rewrite the columns."""
    canvas = get_or_create_canvas(catalog["zone"])
    created = create_node(
        canvas_id=canvas["id"],
        name="draft.audit_log",
        table_id=None,
        columns=[{"name": "id", "data_type": "uuid", "is_primary_key": True}],
        x=0,
        y=0,
    )

    edited = update_node(
        created["id"],
        x=None,
        y=None,
        collapsed=None,
        name="draft.audit_trail",
        columns=[
            {"name": "id", "data_type": "uuid", "is_primary_key": True},
            {"name": "created_at", "data_type": "timestamp", "is_nullable": False},
        ],
    )
    assert edited is not None
    assert edited["name"] == "draft.audit_trail"
    assert [column["name"] for column in edited["columns"]] == ["id", "created_at"]


def test_a_table_note_can_be_set_on_either_kind_of_node(catalog) -> None:
    """A note is documentation, not schema, so catalog tables may carry one too."""
    canvas = get_or_create_canvas(catalog["zone"])
    customers = _node_by_name(canvas, "public.customers")

    noted = update_node(
        customers["id"], x=None, y=None, collapsed=None, note="  customer master  "
    )
    assert noted is not None
    assert noted["note"] == "customer master"
    assert (
        _node_by_name(get_canvas(catalog["zone"]), "public.customers")["note"]
        == "customer master"
    )


def test_a_column_alias_can_be_set_on_a_catalog_table(catalog) -> None:
    """A column alias is documentation: the catalog's column list still wins."""
    canvas = get_or_create_canvas(catalog["zone"])
    customers = _node_by_name(canvas, "public.customers")

    annotated = update_node(
        customers["id"],
        x=None,
        y=None,
        collapsed=None,
        column_notes={"id": "  customer id  "},
    )
    assert annotated is not None
    # The node still carries the catalog's columns, not just the annotation.
    assert [column["name"] for column in annotated["columns"]] == ["id"]
    assert annotated["columns"][0]["data_type"] == "bigint"
    assert annotated["columns"][0]["note"] == "customer id"
    assert annotated["columns"][0]["is_primary_key"] is True

    reread = _node_by_name(get_canvas(catalog["zone"]), "public.customers")
    assert reread["columns"][0]["note"] == "customer id"


def test_clearing_a_column_alias_removes_it(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")
    update_node(
        orders["id"],
        x=None,
        y=None,
        collapsed=None,
        column_notes={"customer_id": "who placed it"},
    )

    cleared = update_node(
        orders["id"],
        x=None,
        y=None,
        collapsed=None,
        column_notes={"customer_id": "   "},
    )
    assert cleared is not None
    assert cleared["columns"][0]["note"] is None


def test_a_catalog_table_column_order_is_canvas_only(catalog) -> None:
    """The card may be reordered without pretending the database changed."""
    store().query_write(
        s.catalog_column.insert().values(
            table_id=catalog["orders"],
            name="status",
            data_type="text",
            ordinal_position=1,
            is_nullable=True,
        )
    )
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")
    assert [column["name"] for column in orders["columns"]] == [
        "status",
        "customer_id",
    ]

    reordered = update_node(
        orders["id"],
        x=None,
        y=None,
        collapsed=None,
        column_order=["customer_id", "status"],
    )
    assert reordered is not None
    assert reordered["column_order"] == ["customer_id", "status"]
    assert [column["name"] for column in reordered["columns"]] == [
        "customer_id",
        "status",
    ]
    # Only the display order moved; the catalog's own data is untouched.
    assert [column["data_type"] for column in reordered["columns"]] == [
        "bigint",
        "text",
    ]

    annotated = update_node(
        orders["id"],
        x=None,
        y=None,
        collapsed=None,
        column_notes={"status": "lifecycle"},
    )
    assert annotated is not None
    assert [column["name"] for column in annotated["columns"]] == [
        "customer_id",
        "status",
    ]
    assert annotated["columns"][1]["note"] == "lifecycle"

    reread = _node_by_name(get_canvas(catalog["zone"]), "public.orders")
    assert [column["name"] for column in reread["columns"]] == [
        "customer_id",
        "status",
    ]

    snapshot = get_canvas(catalog["zone"])
    restored = restore_canvas_state(
        canvas["id"], snapshot["nodes"], snapshot["relationships"]
    )
    assert restored is not None
    restored_orders = _node_by_name(restored, "public.orders")
    assert [column["name"] for column in restored_orders["columns"]] == [
        "customer_id",
        "status",
    ]
    assert restored_orders["columns"][1]["note"] == "lifecycle"


def test_a_canvas_only_table_can_be_reordered_by_column_name(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    created = create_node(
        canvas_id=canvas["id"],
        name="draft.audit_log",
        table_id=None,
        columns=[
            {"name": "id", "data_type": "uuid", "is_primary_key": True},
            {"name": "actor", "data_type": "text"},
            {"name": "created_at", "data_type": "timestamp"},
        ],
        x=0,
        y=0,
    )

    reordered = update_node(
        created["id"],
        x=None,
        y=None,
        collapsed=None,
        column_order=["created_at", "id", "actor"],
    )
    assert reordered is not None
    assert [column["name"] for column in reordered["columns"]] == [
        "created_at",
        "id",
        "actor",
    ]
    assert reordered["columns"][1]["is_primary_key"] is True

    edited = update_node(
        created["id"],
        x=None,
        y=None,
        collapsed=None,
        columns=[
            {"name": "actor", "data_type": "text"},
            {"name": "created_at", "data_type": "timestamp"},
            {"name": "id", "data_type": "uuid", "is_primary_key": True},
        ],
    )
    assert edited is not None
    assert edited["column_order"] is None
    assert [column["name"] for column in edited["columns"]] == [
        "actor",
        "created_at",
        "id",
    ]


def test_column_notes_survive_a_snapshot_restore(catalog) -> None:
    """Undo/redo round-trips the canvas through the browser's own snapshot."""
    canvas = get_or_create_canvas(catalog["zone"])
    customers = _node_by_name(canvas, "public.customers")
    update_node(
        customers["id"],
        x=None,
        y=None,
        collapsed=None,
        column_notes={"id": "customer id"},
    )
    snapshot = get_canvas(catalog["zone"])

    # A snapshot as the browser holds it carries whole nodes, aliases included.
    restore_canvas_state(canvas["id"], snapshot["nodes"], snapshot["relationships"])

    restored = _node_by_name(get_canvas(catalog["zone"]), "public.customers")
    assert restored["columns"][0]["note"] == "customer id"


def test_a_canvas_only_table_can_declare_indexes(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    created = create_node(
        canvas_id=canvas["id"],
        name="draft.events",
        table_id=None,
        columns=[{"name": "id", "data_type": "uuid"}],
        indexes=[{"name": "ix_events_id", "columns": ["id"], "unique": True}],
        x=0,
        y=0,
    )
    assert created["indexes"] == [
        {"name": "ix_events_id", "columns": ["id"], "unique": True}
    ]

    cleared = update_node(created["id"], x=None, y=None, collapsed=None, indexes=[])
    assert cleared is not None and cleared["indexes"] == []


def test_a_catalog_table_cannot_be_edited_by_hand(catalog) -> None:
    """Its columns mirror the source database; editing them here would lie."""
    canvas = get_or_create_canvas(catalog["zone"])
    customers = _node_by_name(canvas, "public.customers")
    with pytest.raises(ValueError):
        update_node(
            customers["id"],
            x=None,
            y=None,
            collapsed=None,
            name="public.customers_v2",
        )


def test_viewport_round_trips(catalog) -> None:
    get_or_create_canvas(catalog["zone"])
    assert update_viewport(catalog["zone"], {"x": 10, "y": 20, "zoom": 1.5})
    assert get_canvas(catalog["zone"])["viewport"] == {"x": 10, "y": 20, "zoom": 1.5}


def test_relationship_lifecycle(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")
    customers = _node_by_name(canvas, "public.customers")

    rel = create_relationship(
        canvas_id=canvas["id"],
        source_node_id=orders["id"],
        target_node_id=customers["id"],
        source_columns=["customer_id"],
        target_columns=["id"],
        cardinality="many-to-one",
        label="placed by",
    )
    assert rel["cardinality"] == "many-to-one"

    edited = update_relationship(
        rel["id"],
        cardinality="one-to-many",
        label=None,
        source_columns=None,
        target_columns=None,
    )
    assert edited is not None and edited["cardinality"] == "one-to-many"

    assert delete_relationship(rel["id"]) is True
    assert delete_relationship(rel["id"]) is False


def test_hiding_a_node_hides_its_relationships_until_restored(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")
    customers = _node_by_name(canvas, "public.customers")

    create_relationship(
        canvas_id=canvas["id"],
        source_node_id=orders["id"],
        target_node_id=customers["id"],
        source_columns=[],
        target_columns=[],
        cardinality="many-to-many",
        label=None,
    )

    assert delete_node(orders["id"]) is True
    assert get_canvas(catalog["zone"])["relationships"] == []

    assert restore_node(orders["id"]) is not None
    assert len(get_canvas(catalog["zone"])["relationships"]) == 1


def test_rejects_a_self_relationship_and_mismatched_columns(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")
    customers = _node_by_name(canvas, "public.customers")

    with pytest.raises(ValueError):
        create_relationship(
            canvas_id=canvas["id"],
            source_node_id=orders["id"],
            target_node_id=orders["id"],
            source_columns=[],
            target_columns=[],
            cardinality="one-to-one",
            label=None,
        )

    with pytest.raises(ValueError):
        create_relationship(
            canvas_id=canvas["id"],
            source_node_id=orders["id"],
            target_node_id=customers["id"],
            source_columns=["customer_id"],
            target_columns=[],
            cardinality="many-to-one",
            label=None,
        )


def test_unknown_zone_reads_as_none() -> None:
    assert get_or_create_canvas(str(uuid.uuid4())) is None
    assert get_canvas(str(uuid.uuid4())) is None
    assert update_viewport(str(uuid.uuid4()), {"x": 0, "y": 0, "zoom": 1}) is None


def test_notes_are_stored_moved_and_restored(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    note = create_note(
        canvas_id=canvas["id"],
        text="check the returns policy",
        x=10,
        y=20,
        color="#fff7cc",
    )
    assert note["text"] == "check the returns policy"
    assert _payload_note(canvas["zone_id"], note["id"])["x"] == 10

    moved = update_note(note["id"], text="revised", x=99)
    assert moved is not None and moved["x"] == 99 and moved["text"] == "revised"
    resized = update_note(note["id"], width=320, height=180)
    assert resized is not None and (resized["width"], resized["height"]) == (320, 180)

    snapshot_nodes = [
        {
            "id": n["id"],
            "table_id": n["table_id"],
            "name": n["name"],
            "x": n["x"],
            "y": n["y"],
            "collapsed": n["collapsed"],
        }
        for n in canvas["nodes"]
    ]
    restored = restore_canvas_state(canvas["id"], snapshot_nodes, [], [resized])
    assert restored is not None
    assert [row["id"] for row in restored["notes"]] == [note["id"]]
    assert restored["notes"][0]["text"] == "revised"
    assert (restored["notes"][0]["width"], restored["notes"][0]["height"]) == (320, 180)

    assert delete_note(note["id"]) is True
    assert get_canvas(catalog["zone"])["notes"] == []


def _payload_note(zone_id: str, note_id: str) -> dict:
    return next(note for note in get_canvas(zone_id)["notes"] if note["id"] == note_id)


def test_areas_are_stored_moved_and_restored(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    area = create_area(
        canvas_id=canvas["id"],
        name="Sales",
        color="#dbeafe",
        x=0,
        y=0,
        width=600,
        height=400,
    )
    assert area["name"] == "Sales"
    assert get_canvas(catalog["zone"])["areas"][0]["width"] == 600

    moved = update_area(area["id"], x=120, name="Sales domain")
    assert moved is not None and moved["x"] == 120 and moved["name"] == "Sales domain"

    snapshot_nodes = [
        {
            "id": n["id"],
            "table_id": n["table_id"],
            "name": n["name"],
            "x": n["x"],
            "y": n["y"],
            "collapsed": n["collapsed"],
        }
        for n in canvas["nodes"]
    ]
    restored = restore_canvas_state(canvas["id"], snapshot_nodes, [], [], [moved])
    assert restored is not None
    assert [row["id"] for row in restored["areas"]] == [area["id"]]
    assert restored["areas"][0]["name"] == "Sales domain"

    assert delete_area(area["id"]) is True
    assert get_canvas(catalog["zone"])["areas"] == []


def test_versions_snapshot_and_restore(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")
    original_x = orders["x"]

    version = create_version(catalog["zone"], "before edits", created_by="user-1")
    assert version is not None
    assert version["label"] == "before edits"
    assert version["node_count"] == len(canvas["nodes"])
    assert version["relationship_count"] == 0

    moved = update_node(orders["id"], x=original_x + 500, y=None, collapsed=None)
    assert moved is not None and moved["x"] == original_x + 500

    restored = restore_version(version["id"])
    assert restored is not None
    assert _node_by_name(restored, "public.orders")["x"] == original_x

    listed = list_versions(catalog["zone"])
    assert [row["id"] for row in listed] == [version["id"]]
    assert delete_version(version["id"]) is True
    assert list_versions(catalog["zone"]) == []


def test_restore_keeps_node_and_relationship_ids(catalog) -> None:
    """Undo/redo replays a snapshot; stable ids are what keep the stack coherent."""
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")
    customers = _node_by_name(canvas, "public.customers")
    rel = create_relationship(
        canvas_id=canvas["id"],
        source_node_id=orders["id"],
        target_node_id=customers["id"],
        source_columns=["customer_id"],
        target_columns=["id"],
        cardinality="many-to-one",
        label=None,
    )

    snapshot_nodes = [
        {
            "id": node["id"],
            "table_id": node["table_id"],
            "name": node["name"],
            "x": node["x"] + 10,
            "y": node["y"],
            "collapsed": node["collapsed"],
        }
        for node in canvas["nodes"]
    ]
    snapshot_relationships = [
        {
            "id": rel["id"],
            "source_node_id": rel["source_node_id"],
            "target_node_id": rel["target_node_id"],
            "source_columns": rel["source_columns"],
            "target_columns": rel["target_columns"],
            "cardinality": rel["cardinality"],
            "label": rel["label"],
        }
    ]

    restored = restore_canvas_state(
        canvas["id"], snapshot_nodes, snapshot_relationships
    )
    assert restored is not None
    assert {node["id"] for node in restored["nodes"]} == {
        node["id"] for node in canvas["nodes"]
    }
    assert restored["relationships"][0]["id"] == rel["id"]
    assert _node_by_name(restored, "public.orders")["x"] == orders["x"] + 10


def test_removing_a_catalog_table_hides_it_stably(catalog) -> None:
    """A zone still covers the table, so a plain delete would be undone."""
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")

    assert delete_node(orders["id"]) is True
    after = get_or_create_canvas(catalog["zone"])
    assert "public.orders" not in {node["name"] for node in after["nodes"]}
    assert [row["name"] for row in after["hidden_nodes"]] == ["public.orders"]

    restored = restore_node(orders["id"])
    assert restored is not None
    again = get_or_create_canvas(catalog["zone"])
    assert "public.orders" in {node["name"] for node in again["nodes"]}
    assert again["hidden_nodes"] == []


def test_removing_a_canvas_only_table_deletes_it(catalog) -> None:
    canvas = get_or_create_canvas(catalog["zone"])
    created = create_node(
        canvas_id=canvas["id"],
        name="draft.temp",
        table_id=None,
        columns=[],
        x=0,
        y=0,
    )
    assert delete_node(created["id"]) is True
    assert "draft.temp" not in {
        node["name"] for node in get_canvas(catalog["zone"])["nodes"]
    }
    assert restore_node(created["id"]) is None


def test_undoing_a_removal_restores_the_tombstoned_node(catalog) -> None:
    """The snapshot carries the node the tombstone replaced; they must not collide."""
    canvas = get_or_create_canvas(catalog["zone"])
    orders = _node_by_name(canvas, "public.orders")
    snapshot = [
        {
            "id": node["id"],
            "table_id": node["table_id"],
            "name": node["name"],
            "x": node["x"],
            "y": node["y"],
            "collapsed": node["collapsed"],
        }
        for node in canvas["nodes"]
    ]

    assert delete_node(orders["id"]) is True
    assert get_canvas(catalog["zone"])["hidden_nodes"]

    restored = restore_canvas_state(canvas["id"], snapshot, [])
    assert restored is not None
    assert "public.orders" in {node["name"] for node in restored["nodes"]}
    assert restored["hidden_nodes"] == []
