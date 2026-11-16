# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SQLAlchemy ORM 实体层（中文注释）。

## 这一层解决什么问题

``schema.py`` 用 SQLAlchemy Core 声明表，是 DDL 的唯一真相（Alembic 靠它
autogenerate）。Core 的好处是能精确表达窗口函数、``DISTINCT ON``、多表 union
这类集合运算；代价是“取一行、改两个字段、存回去”要写一整套
``select(cols) / update().values() / returning()``，读起来是 SQL 而不是业务。

本模块把**同一批 ``Table`` 对象**映射成 ORM 实体，因此：

* 不重新声明任何列 —— ``Zone.__table__ is schema.zone``，DDL 与本模块不可能漂移；
* Alembic 仍然只看 ``schema.py``，本模块对迁移零影响；
* 老的 Core 查询继续可用，两种写法可以在同一个事务里混用。

## 什么时候用哪一层

* **实体操作走 ORM**：取一个 zone、改它的名字、加一个画布节点、按外键遍历
  父子关系。写法是 ``session.get(Zone, id)`` / ``select(Zone)`` / ``zone.targets``。
* **集合运算留 Core**：跨库统计、``DISTINCT ON``、union、批量 upsert
  （``INSERT ... ON CONFLICT``）。用 ORM 表达这些只会更长更慢。

``all_ontology/dal/zones.py`` 是两种写法共存的范例：实体读写用 ORM，
``_databases_for_items`` 这类集合查询仍是 Core。

## 命名

类名用单数（``Zone``、``CatalogTable``），表名保持 ``schema.py`` 里的
snake_case。关联表（名字里带 ``__`` 的那批）也映射了实体，因为它们是真正的
业务概念（列级外键、语义外键、标签对象），不只是 join 的中间产物。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import DeclarativeBase, Mapped, relationship

from all_ontology.dal import schema as s


class Base(DeclarativeBase):
    """所有实体的基类。

    ``metadata`` 必须复用 ``schema.py`` 的那一个对象：Alembic 的 env.py 读的是
    它，换成新的 MetaData 会让 autogenerate 认为“所有表都不存在”。
    """

    metadata = s.METADATA


# ---------------------------------------------------------------------------
# 目录层：Database → Schema → Table → Column
# ---------------------------------------------------------------------------


class CatalogDatabase(Base):
    """目录数据库：一个被接入的数据源实例。

    删除这一行会级联删掉它的 schema、table、column 以及依赖它们的画布节点。
    ``connection`` 只在未配置 Vault 时才存连接表单；配置了 Vault 时凭据在
    Vault，这里保持 null，数据库名本身就是查找键。
    """

    __table__ = s.catalog_database

    id: Mapped[str]
    name: Mapped[str]
    connection: Mapped[dict[str, Any] | None]
    dialect: Mapped[str | None]
    description: Mapped[str | None]
    description_certified: Mapped[bool]
    imported_id: Mapped[str | None]
    owner_id: Mapped[str | None]
    created: Mapped[datetime | None]
    #: 最近一次元数据拉取时间；null 表示还没抓过。
    pulled: Mapped[datetime | None]

    # ``delete-orphan`` mirrors the ``ON DELETE CASCADE`` the foreign key already
    # declares. Without it SQLAlchemy's default on parent delete is to NULL the
    # child's foreign key, which the NOT NULL column rejects.
    schemas: Mapped[list[CatalogSchema]] = relationship(
        back_populates="database",
        order_by="CatalogSchema.name",
        cascade="all, delete-orphan",
    )


class CatalogSchema(Base):
    """目录 schema（Postgres 的 namespace，MySQL 里通常就是库名）。"""

    __table__ = s.catalog_schema

    id: Mapped[str]
    database_id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    description_certified: Mapped[bool]
    imported_id: Mapped[str | None]
    owner_id: Mapped[str | None]

    database: Mapped[CatalogDatabase] = relationship(back_populates="schemas")
    tables: Mapped[list[CatalogTable]] = relationship(
        back_populates="schema",
        order_by="CatalogTable.name",
        cascade="all, delete-orphan",
    )


class CatalogTable(Base):
    """目录表。

    ``pk`` 是主键列名数组（不是列 id），``table_type`` 区分 VIEW/表，
    ``is_junction_table`` 标记多对多中间表 —— 图谱推断靠它跳过“纯连接表”。
    """

    __table__ = s.catalog_table

    id: Mapped[str]
    schema_id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    description_certified: Mapped[bool]
    owner_id: Mapped[str | None]
    pk: Mapped[list[str]]
    table_type: Mapped[str | None]
    is_junction_table: Mapped[bool]
    imported_id: Mapped[str | None]

    schema: Mapped[CatalogSchema] = relationship(back_populates="tables")
    columns: Mapped[list[CatalogColumn]] = relationship(
        back_populates="table",
        order_by="CatalogColumn.ordinal_position",
        cascade="all, delete-orphan",
    )


class CatalogColumn(Base):
    """目录列。

    ``sample_values`` 是采样得到的示例值文本，给 LLM 判断语义用；
    ``pii_processed`` 表示这一列是否已经过 PII 识别。
    """

    __table__ = s.catalog_column

    id: Mapped[str]
    table_id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    description_certified: Mapped[bool]
    data_type: Mapped[str | None]
    sample_values: Mapped[str | None]
    format: Mapped[str | None]
    is_unique: Mapped[bool | None]
    is_nullable: Mapped[bool | None]
    #: 列在表中的原始顺序，决定画布与列表的展示顺序。
    ordinal_position: Mapped[int | None]
    pii_processed: Mapped[bool]
    imported_id: Mapped[str | None]

    table: Mapped[CatalogTable] = relationship(back_populates="columns")


# ---------------------------------------------------------------------------
# 语义层：术语、列属性、SQL 属性，以及它们与目录对象的关联
# ---------------------------------------------------------------------------


class Term(Base):
    """业务术语（术语表里的一行）。

    ``synonyms`` 是别名数组，检索时与 ``name`` 一起参与匹配；
    ``name_certified`` / ``description_certified`` 表示这两个字段是否经人工确认。
    删除术语会级联删掉它与表/列属性/SQL 属性的关联行。
    """

    __table__ = s.term

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    #: 术语来源（人工 / 模型生成 / 导入）。
    source: Mapped[str | None]
    synonyms: Mapped[list[str]]
    name_certified: Mapped[bool]
    description_certified: Mapped[bool]
    owner_id: Mapped[str | None]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]
    created_by: Mapped[str | None]
    modified_by: Mapped[str | None]
    imported_id: Mapped[str | None]


class ColumnAttribute(Base):
    """列属性：挂在某个目录列上的业务属性（典型是“度量”和“维度”）。

    ``source_column`` 冗余保存列名，方便展示时不回表；
    ``term_name`` 同理保存术语名。真正的关联在 :class:`ColumnAttributeTerm`。
    """

    __table__ = s.column_attribute

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    datatype: Mapped[str | None]
    source: Mapped[str | None]
    source_column: Mapped[str | None]
    term_name: Mapped[str | None]
    table_id: Mapped[str | None]
    certified: Mapped[bool]
    #: 模型给出的描述建议，人工确认前只作提示。
    description_suggestion: Mapped[str | None]
    pii_processed: Mapped[bool]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]
    created_by: Mapped[str | None]
    modified_by: Mapped[str | None]
    imported_id: Mapped[str | None]


class SqlAttribute(Base):
    """SQL 属性：用一段 SQL 表达式定义的指标（例如“毛利率”）。

    ``expression`` 是表达式本身，``source`` 记录它来自人工还是模型。
    """

    __table__ = s.sql_attribute

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    expression: Mapped[str | None]
    source: Mapped[str | None]
    certified: Mapped[bool]
    owner_id: Mapped[str | None]
    description_suggestion: Mapped[str | None]
    pii_processed: Mapped[bool]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]
    created_by: Mapped[str | None]
    modified_by: Mapped[str | None]
    imported_id: Mapped[str | None]


class Analysis(Base):
    """旧版自定义分析（只存名字与描述，SQL 不在本表）。"""

    __table__ = s.analysis

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    imported_id: Mapped[str | None]


class CustomAnalysis(Base):
    """自定义分析：绑定一条或多条观测到的 SQL（见 :class:`CustomAnalysisSql`）。"""

    __table__ = s.custom_analysis

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    imported_id: Mapped[str | None]


class PqlAnalysis(Base):
    """PQL 分析（预测式查询语言），与自定义分析并列的一种分析。"""

    __table__ = s.pql_analysis

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    pql: Mapped[str | None]
    imported_id: Mapped[str | None]


class TextAttribute(Base):
    """文本属性：自由文本形式的业务属性，只在迁移与兼容路径里出现。"""

    __table__ = s.text_attribute

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    imported_id: Mapped[str | None]


# ---------------------------------------------------------------------------
# 观测到的 SQL 及其涉及的列与表
# ---------------------------------------------------------------------------


class SqlQuery(Base):
    """一条被观测到的 SQL（去重后按 ``sql_full_query`` 聚合计数）。

    ``total_counter`` 是累计出现次数，``last_query_timestamp`` 是最近一次出现，
    ``nodes_count`` / ``join_count`` / ``union_count`` 是解析后的结构特征。
    """

    __table__ = s.sql_query

    id: Mapped[str]
    sql_full_query: Mapped[str]
    query_count: Mapped[int | None]
    created: Mapped[datetime | None]
    last_seen: Mapped[datetime | None]
    total_counter: Mapped[int | None]
    last_query_timestamp: Mapped[datetime | None]
    nodes_count: Mapped[int | None]
    join_count: Mapped[int | None]
    union_count: Mapped[int | None]


# ---------------------------------------------------------------------------
# 关联表：名字里只有一个 ``__``，左边是起点
# ---------------------------------------------------------------------------


class ColumnForeignKey(Base):
    """列级外键：``source_column_id`` 指向 ``target_column_id``。

    只存最后一次被观测到的时间，外键本身是源库里的事实，这里只是缓存。
    """

    __table__ = s.column__foreign_key

    source_column_id: Mapped[str]
    target_column_id: Mapped[str]
    last_seen: Mapped[datetime | None]


class ColumnJoin(Base):
    """列级可连接关系：两列在历史 SQL 里被 ``JOIN`` 连过。

    ``refs`` 记录支持这条边的 SQL 引用，用来给推断结果打分。
    """

    __table__ = s.column__join

    source_column_id: Mapped[str]
    target_column_id: Mapped[str]
    refs: Mapped[list[str]]


class ColumnUnion(Base):
    """列级可联合关系：两列在历史 SQL 里被 ``UNION`` 并列过。"""

    __table__ = s.column__union

    source_column_id: Mapped[str]
    target_column_id: Mapped[str]
    refs: Mapped[list[str]]


class ColumnHasAttribute(Base):
    """列 → 列属性 的关联（一个列可以有多个属性）。"""

    __table__ = s.column__has_attribute

    column_id: Mapped[str]
    attribute_id: Mapped[str]


class ColumnSemanticFk(Base):
    """列 → 列属性 的语义外键。

    ``use_in_join_paths`` 决定这条边是否参与自适应的 join 路径推断 ——
    误判的语义外键会把 SQL 连错，所以它是可关闭的。
    """

    __table__ = s.column__semantic_fk

    column_id: Mapped[str]
    attribute_id: Mapped[str]
    use_in_join_paths: Mapped[bool]


class ColumnAttributeTerm(Base):
    """列属性 → 术语 的关联。"""

    __table__ = s.column_attribute__term

    attribute_id: Mapped[str]
    term_id: Mapped[str]


class SqlAttributeTerm(Base):
    """SQL 属性 → 术语 的关联。"""

    __table__ = s.sql_attribute__term

    attribute_id: Mapped[str]
    term_id: Mapped[str]


class SqlAttributeSql(Base):
    """SQL 属性 → 观测到的 SQL 的关联。"""

    __table__ = s.sql_attribute__sql

    attribute_id: Mapped[str]
    sql_query_id: Mapped[str]


class CustomAnalysisSql(Base):
    """自定义分析 → 观测到的 SQL 的关联。"""

    __table__ = s.custom_analysis__sql

    analysis_id: Mapped[str]
    sql_query_id: Mapped[str]


class SqlQueryColumn(Base):
    """观测到的 SQL → 它读到的列。"""

    __table__ = s.sql_query__column

    sql_query_id: Mapped[str]
    column_id: Mapped[str]


class SqlQueryTable(Base):
    """观测到的 SQL → 它读到的表。"""

    __table__ = s.sql_query__table

    sql_query_id: Mapped[str]
    table_id: Mapped[str]


class TableJoin(Base):
    """表级可连接关系。

    ``join_columns`` 是 ``[{"source": ..., "target": ...}, ...]`` 形式的连接列清单，
    让 UI 不必为了显示一条边再回表查列。
    """

    __table__ = s.table__join

    source_table_id: Mapped[str]
    target_table_id: Mapped[str]
    join_columns: Mapped[list[dict[str, Any]]]


class TableTerm(Base):
    """表 → 术语 的关联。"""

    __table__ = s.table__term

    table_id: Mapped[str]
    term_id: Mapped[str]


# ---------------------------------------------------------------------------
# 标签与规则
# ---------------------------------------------------------------------------


class Tag(Base):
    """标签：可以打在术语、表、列、列属性、SQL 属性上（见 :class:`TagTarget`）。"""

    __table__ = s.tag

    id: Mapped[str]
    name: Mapped[str]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]
    created_by: Mapped[str | None]
    modified_by: Mapped[str | None]

    targets: Mapped[list[TagTarget]] = relationship(back_populates="tag")


class TagTarget(Base):
    """标签落在一个对象上。

    七个可空外键里只有一个是非空的 —— 一张表表达五种对象，靠
    :class:`Rule` 自动打标时写 ``rule_id``，人工打的留空。
    """

    __table__ = s.tag_target

    id: Mapped[str]
    tag_id: Mapped[str]
    term_id: Mapped[str | None]
    table_id: Mapped[str | None]
    column_id: Mapped[str | None]
    column_attribute_id: Mapped[str | None]
    sql_attribute_id: Mapped[str | None]
    tagged: Mapped[datetime | None]
    tagged_by: Mapped[str | None]
    #: 由哪条规则打的；人工打标为 null。
    rule_id: Mapped[str | None]

    tag: Mapped[Tag] = relationship(back_populates="targets")


class Rule(Base):
    """打标规则：命中 ``search_term`` 的对象自动获得关联的标签。

    ``text_match_option`` 决定匹配方式，``filters`` 是附加条件（库/schema 等）。
    """

    __table__ = s.rule

    id: Mapped[str]
    name: Mapped[str]
    search_term: Mapped[str | None]
    text_match_option: Mapped[str | None]
    filters: Mapped[dict[str, Any] | None]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]
    created_by: Mapped[str | None]
    modified_by: Mapped[str | None]


class RuleTag(Base):
    """规则 → 标签，``position`` 保留标签的展示顺序。"""

    __table__ = s.rule__tag

    rule_id: Mapped[str]
    tag_id: Mapped[str]
    position: Mapped[int | None]


# ---------------------------------------------------------------------------
# 分区（权限范围）
# ---------------------------------------------------------------------------


class Zone(Base):
    """分区：一组目录对象的集合，是权限的最小单位。

    ``name`` 的唯一性不是列约束能表达的 —— 它在“同一批数据库内”按 trim 后
    的小写比较唯一，所以由 DAL 在应用层校验（见 ``dal/zones.py``）。
    ``enabled`` 关掉后成员看不到它，管理员仍能看到并管理。
    """

    __table__ = s.zone

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    color: Mapped[str | None]
    enabled: Mapped[bool]

    targets: Mapped[list[ZoneTarget]] = relationship(
        back_populates="zone", cascade="all, delete-orphan"
    )


class ZoneTarget(Base):
    """分区指向的一个对象：数据库、schema 或表，三列里只有一列非空。"""

    __table__ = s.zone_target

    id: Mapped[str]
    zone_id: Mapped[str]
    database_id: Mapped[str | None]
    schema_id: Mapped[str | None]
    table_id: Mapped[str | None]

    zone: Mapped[Zone] = relationship(back_populates="targets")


# ---------------------------------------------------------------------------
# ER 画布：每个 zone 一块画布
# ---------------------------------------------------------------------------


class ErdCanvas(Base):
    """画布：一个 zone 一个，``viewport`` 保存平移/缩放（``{x, y, zoom}``）。

    删除 zone 时级联删除画布，画布再级联删除节点、关系、便签、区域、版本。
    """

    __table__ = s.erd_canvas

    id: Mapped[str]
    zone_id: Mapped[str]
    viewport: Mapped[dict[str, Any] | None]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]

    nodes: Mapped[list[ErdNode]] = relationship(
        back_populates="canvas", cascade="all, delete-orphan"
    )
    relationships: Mapped[list[ErdRelationship]] = relationship(
        back_populates="canvas", cascade="all, delete-orphan"
    )
    notes: Mapped[list[ErdNote]] = relationship(
        back_populates="canvas", cascade="all, delete-orphan"
    )
    areas: Mapped[list[ErdArea]] = relationship(
        back_populates="canvas", cascade="all, delete-orphan"
    )
    versions: Mapped[list[ErdCanvasVersion]] = relationship(
        back_populates="canvas", cascade="all, delete-orphan"
    )


class ErdNode(Base):
    """画布上的一张表卡片。

    ``table_id`` 为空表示“只存在于图上的虚拟表”。``columns`` 对虚拟表是完整的
    列定义，对目录表只存建模者写的列别名（``[{"name": ..., "note": ...}]``）。
    ``hidden`` 是删除目录表时留下的墓碑，避免下一次对账把它又加回来。
    """

    __table__ = s.erd_node

    id: Mapped[str]
    canvas_id: Mapped[str]
    table_id: Mapped[str | None]
    name: Mapped[str]
    x: Mapped[float]
    y: Mapped[float]
    collapsed: Mapped[bool]
    columns: Mapped[list[dict[str, Any]] | None]
    indexes: Mapped[list[dict[str, Any]] | None]
    note: Mapped[str | None]
    hidden: Mapped[bool]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]

    canvas: Mapped[ErdCanvas] = relationship(back_populates="nodes")


class ErdRelationship(Base):
    """两张表之间的连接线。

    ``source_columns`` / ``target_columns`` 是连接用到的列名（可空表示表级关系），
    ``cardinality`` 取 ``one-to-one`` / ``one-to-many`` / ``many-to-one`` /
    ``many-to-many``。
    """

    __table__ = s.erd_relationship

    id: Mapped[str]
    canvas_id: Mapped[str]
    source_node_id: Mapped[str]
    target_node_id: Mapped[str]
    source_columns: Mapped[list[str]]
    target_columns: Mapped[list[str]]
    cardinality: Mapped[str]
    label: Mapped[str | None]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]

    canvas: Mapped[ErdCanvas] = relationship(back_populates="relationships")
    # Two foreign keys to the same table, so the join has to be told which is
    # which. Strings because a ``__table__``-mapped class has no class-level
    # column attributes to reference at definition time.
    source: Mapped[ErdNode] = relationship(
        foreign_keys="ErdRelationship.source_node_id"
    )
    target: Mapped[ErdNode] = relationship(
        foreign_keys="ErdRelationship.target_node_id"
    )


class ErdNote(Base):
    """画布上的一张便签。"""

    __table__ = s.erd_note

    id: Mapped[str]
    canvas_id: Mapped[str]
    text: Mapped[str]
    x: Mapped[float]
    y: Mapped[float]
    width: Mapped[float]
    height: Mapped[float]
    color: Mapped[str | None]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]

    canvas: Mapped[ErdCanvas] = relationship(back_populates="notes")


class ErdArea(Base):
    """画布上的区域分组矩形（按几何包含关系决定成员，不额外建关联表）。"""

    __table__ = s.erd_area

    id: Mapped[str]
    canvas_id: Mapped[str]
    name: Mapped[str]
    color: Mapped[str | None]
    x: Mapped[float]
    y: Mapped[float]
    width: Mapped[float]
    height: Mapped[float]
    created: Mapped[datetime | None]
    modified: Mapped[datetime | None]

    canvas: Mapped[ErdCanvas] = relationship(back_populates="areas")


class ErdCanvasVersion(Base):
    """画布的版本快照。

    ``snapshot`` 是整块画布的 JSON，恢复时整体替换节点/关系/便签/区域。
    """

    __table__ = s.erd_canvas_version

    id: Mapped[str]
    canvas_id: Mapped[str]
    label: Mapped[str]
    snapshot: Mapped[dict[str, Any] | None]
    created_by: Mapped[str | None]
    created: Mapped[datetime | None]

    canvas: Mapped[ErdCanvas] = relationship(back_populates="versions")


# ---------------------------------------------------------------------------
# 运行期：上传的数据集、用户组、编译历史
# ---------------------------------------------------------------------------


class UploadedDataset(Base):
    """通过“Excel / CSV”连接上传的数据集，字节以 Parquet 形式存在库里。

    放在 Postgres 而不是挂载卷，是因为后端与摄取服务是两个独立容器/部署，
    只有一方能看到的文件会产出一个谁都查不了的目录。``name`` 唯一，它就是
    ``fileupload://<name>`` 里的那个名字。
    """

    __table__ = s.uploaded_dataset

    id: Mapped[str]
    name: Mapped[str]
    filename: Mapped[str | None]
    table_name: Mapped[str]
    row_count: Mapped[int | None]
    size_bytes: Mapped[int]
    content: Mapped[bytes]
    created: Mapped[datetime | None]


class UserGroup(Base):
    """用户组：一组账号 + 一个组级角色（admin / viewer）。

    账号本身在 Prisma 的 ``frontend."user"`` 表里，成员表只存 Better Auth 的
    user id，**没有外键** —— 两个 schema 由不同的迁移工具管。
    """

    __table__ = s.user_group

    id: Mapped[str]
    name: Mapped[str]
    description: Mapped[str | None]
    color: Mapped[str | None]
    role: Mapped[str | None]
    created: Mapped[datetime | None]


class UserGroupMember(Base):
    """组成员关系（group → frontend user id）。"""

    __table__ = s.user_group__member

    group_id: Mapped[str]
    user_id: Mapped[str]


class SemanticCompilationHistory(Base):
    """一次语义编译运行的记录。

    ``status`` 只允许 ``succeeded`` / ``failed``（见 ``schema.RUN_SUCCEEDED``），
    由表上的 check 约束保证。
    """

    __table__ = s.semantic_compilation_history

    id: Mapped[int]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    status: Mapped[str | None]


__all__ = [
    "Analysis",
    "Base",
    "CatalogColumn",
    "CatalogDatabase",
    "CatalogSchema",
    "CatalogTable",
    "ColumnAttribute",
    "ColumnAttributeTerm",
    "ColumnForeignKey",
    "ColumnHasAttribute",
    "ColumnJoin",
    "ColumnSemanticFk",
    "ColumnUnion",
    "CustomAnalysis",
    "CustomAnalysisSql",
    "ErdArea",
    "ErdCanvas",
    "ErdCanvasVersion",
    "ErdNode",
    "ErdNote",
    "ErdRelationship",
    "PqlAnalysis",
    "Rule",
    "RuleTag",
    "SemanticCompilationHistory",
    "SqlAttribute",
    "SqlAttributeSql",
    "SqlAttributeTerm",
    "SqlQuery",
    "SqlQueryColumn",
    "SqlQueryTable",
    "TableJoin",
    "TableTerm",
    "Tag",
    "TagTarget",
    "Term",
    "TextAttribute",
    "UploadedDataset",
    "UserGroup",
    "UserGroupMember",
    "Zone",
    "ZoneTarget",
]
