# ER 画布实施计划

> **执行方式：** 本仓库不是 git 仓库，无法按任务提交；按任务顺序执行并用命令验证。

**目标：** 在 All-Ontology 中实现按 zone 划分的 ER 画布：展示 zone 表、可拖拽建表间关联、JSON/DBML 导入导出、数据存 Postgres。

**架构：** 后端新增三张表与 `/api/erd` 路由（FastAPI + SQLAlchemy Core DAL，Alembic 迁移）；
前端新增 `/erd` 页面与自研 SVG+HTML 画布；权限沿用 `zone:read` / `zone:manage`。

**技术栈：** FastAPI、SQLAlchemy Core、Alembic、pytest、Next.js 16、React 19、Tailwind 4、TypeScript。

规格：`docs/superpowers/specs/2026-11-14-erd-canvas-design.md`

---

## Task 1：后端 schema + 迁移

**文件**
- 修改：`all_ontology/dal/schema.py`（新增 `erd_canvas`、`erd_node`、`erd_relationship`）
- 新增：`alembic/versions/<rev>_add_erd_canvas.py`（autogenerate）

**步骤**

- [ ] 在 `schema.py` 末尾追加三张表：`_id()` 主键、`zone_id` 唯一外键、`viewport` JSONB、
      `(canvas_id, table_id)` 部分唯一索引、`cardinality` CHECK、`source_node_id <> target_node_id` CHECK。
- [ ] 运行 `uv run alembic revision --autogenerate -m "add erd canvas tables"`。
- [ ] 检查生成的迁移只包含新增表/索引/约束。
- [ ] `uv run alembic upgrade head`，再用 `psql`（容器内）确认三张表存在。

**验证**：`docker exec postgres psql -U postgres -d all_ontology -c "\d erd_relationship"`

---

## Task 2：DAL（`all_ontology/dal/erd.py`）

**公开函数（签名固定，需写入 `dal_surface.json`）**

```python
def get_or_create_canvas(zone_id: str) -> dict[str, Any] | None
def get_canvas(zone_id: str) -> dict[str, Any] | None
def update_viewport(zone_id: str, viewport: dict[str, Any]) -> dict[str, Any] | None
def update_node(node_id: str, *, x: float | None, y: float | None, collapsed: bool | None) -> dict[str, Any] | None
def create_node(*, canvas_id: str, name: str, table_id: str | None, columns: list[dict[str, Any]] | None, x: float, y: float) -> dict[str, Any]
def delete_node(node_id: str) -> bool
def create_relationship(*, canvas_id: str, source_node_id: str, target_node_id: str, source_columns: list[str], target_columns: list[str], cardinality: str, label: str | None) -> dict[str, Any]
def update_relationship(rel_id: str, *, cardinality: str | None, label: str | None, source_columns: list[str] | None, target_columns: list[str] | None) -> dict[str, Any] | None
def delete_relationship(rel_id: str) -> bool
def replace_canvas_contents(canvas_id: str, nodes: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> dict[str, Any]
```

**行为**

- `get_or_create_canvas`：按 `zone_id` 找画布，没有则建；然后同步 zone 覆盖的表
  （复用 `zones.zone_covers_table()`），新表按网格布局，离开 zone 的目录表节点删除。
- 列信息：目录表 join `catalog_column`（按 `ordinal_position`），虚拟表读 `columns` jsonb。
- 所有写操作在 `write_transaction()` 内。

**测试**：`all_ontology/dal/tests/test_erd.py`（沿用 `test_zones.py` 的跳过条件与临时数据前缀）。

- [ ] 画布惰性创建 + 幂等
- [ ] zone 增加表后重进画布出现新节点；移除表后节点消失
- [ ] 坐标更新持久化
- [ ] 关联 CRUD 与级联删除
- [ ] 虚拟表在同步后保留

**验证**：`uv run pytest all_ontology/dal/tests/test_erd.py -q`

---

## Task 3：DBML 解析/序列化（`all_ontology/server/erd/dbml.py`）

**接口**

```python
class DbmlParseError(ValueError):
    def __init__(self, message: str, line: int) -> None: ...

def parse_dbml(text: str) -> tuple[list[dict], list[dict], list[str]]
def export_dbml(nodes: list[dict], relationships: list[dict]) -> str
```

解析结果节点：`{"name", "columns": [{"name","data_type","is_primary_key","is_unique","is_nullable","note"}], "note"}`
关联：`{"source","source_columns","target","target_columns","cardinality","label"}`

**语法**（逐行状态机，先剥 `//` 注释，再按 `{`/`}` 维护块栈）

- `Table x.y as z {` → 新表；块内 `name type [attrs]` 或 `Note: '...'`
- 属性解析：`pk`、`increment`、`unique`、`not null`、`note: '...'`
- `Ref: a.b > c.d`、`Ref name: a.b < c.d`、`Ref { a.b - c.d }`
- 未知块（`Enum`/`Indexes`/`TableGroup`/`Project`）跳过并追加 warning

**测试**：`all_ontology/server/erd/tests/test_dbml.py`

- [ ] 解析 2 表 + Ref，基数与列名正确
- [ ] 序列化后重新解析结果一致（往返）
- [ ] 非法行给出行号
- [ ] 未知块产生 warning 而不是异常

---

## Task 4：路由与响应模型

**文件**
- 新增：`all_ontology/server/erd/__init__.py`、`router.py`、`schemas.py`
- 修改：`all_ontology/server/models.py`（`ErdNode`、`ErdRelationship`、`ErdCanvas`、`ErdImportResult`）
- 修改：`all_ontology/server/responses.py`（`ErdCanvasResponse`、`ErdExportResponse`、`ErdImportResponse`）
- 修改：`all_ontology/server/__main__.py`（注册 router）

**接口**：见规格第「API 契约」节。所有 handler 写 docstring（OpenAPI 会带出去）。

**验证**

- [ ] `uv run python -m dev_tools.generate_backend_openapi`
- [ ] `curl -s http://127.0.0.1:3001/api/openapi.json | jq '.paths | keys'` 含 `/api/erd/...`

---

## Task 5：前端 API 层

- [ ] `frontend/types/erd.ts`：`ErdCanvas`、`ErdNode`、`ErdColumn`、`ErdRelationship`、`ErdCardinality`
- [ ] `frontend/api/erd.ts`：`erdApi.getCanvas/updateViewport/updateNode/createNode/deleteNode/createRelationship/updateRelationship/deleteRelationship/import/export`
- [ ] `frontend/app/api/erd/**/route.ts`：GET 走 `zone: ['read']`，写走 `zone: ['manage']`，全部 `proxyToBackend`

**验证**：`cd frontend && npx tsc --noEmit`（或 `pnpm build` 时类型检查）

---

## Task 6：画布组件

- [ ] `frontend/lib/erd/geometry.ts`：`portPoint()`、`bezierPath()`、`screenToWorld()`
- [ ] `frontend/lib/erd/layout.ts`：`gridLayout(nodes)`、`layeredLayout(nodes, edges)`
- [ ] `TableCard.tsx`：表头（拖拽）+ 列（主键/唯一/可空徽标 + 左右端口）
- [ ] `RelationshipEdge.tsx`：贝塞尔路径 + 基数标签 + 选中态
- [ ] `ErdCanvas.tsx`：视口 transform、平移/缩放、节点拖拽、连线拖拽、框选删除
- [ ] `ErdToolbar.tsx` / `ImportExportDialog.tsx`
- [ ] `ErdView.tsx`：加载画布、zone 切换、防抖保存、错误提示

**验证**：`pnpm lint`、`pnpm build`

---

## Task 7：页面、导航、国际化

- [ ] `frontend/app/erd/page.tsx`
- [ ] `frontend/common/NavRail.tsx`：在 Exploration 后插入 `{ icon: IconName.Exploration, href: '/erd', label: 'ER Model' }`
- [ ] `frontend/common/icons` 增加 `Erd` 图标（若无合适图标则复用 `Exploration`）
- [ ] `frontend/i18n/messages/zh.ts` 补全全部新文案

---

## Task 8：验证与运行

- [ ] `uv run ruff check all_ontology/ && uv run ruff format all_ontology/`
- [ ] `uv run pytest all_ontology dal dev_tools -q`（至少跑新增测试 + `test_dal_surface.py`）
- [ ] `uv run python -m all_ontology.dal.tests.test_dal_surface` 更新快照
- [ ] `cd frontend && npx prettier --write . && pnpm lint && pnpm build`
- [ ] 重启后端（`uvicorn --reload` 会自动重载；新表需先 `alembic upgrade head`）
- [ ] 浏览器打开 `http://localhost:3010/erd`，建一条关联并刷新页面确认持久化
