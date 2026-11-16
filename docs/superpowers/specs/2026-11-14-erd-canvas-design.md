# ER 画布（Zone Canvas）设计

状态：已由用户确认（2026-11-14）

## 目标

在 All-Ontology 中提供一个 drawDB 风格的 ER 建模画布：

- 一个 zone 对应一张画布；
- 画布展示该 zone 覆盖的所有表（表、schema、数据库三种 zone 目标都支持）；
- 用户能拖动表和列、自己建立表/列之间的关联关系，并编辑基数；
- 支持 JSON 与 DBML 的导入、导出；
- 所有画布数据（节点坐标、关联）都持久化到 Postgres。

## 非目标（本期）

- 不写回语义层（`column__semantic_fk` / `table__join`）。画布上的关系是建模草稿，
  需要显式的「发布到语义层」后续动作才会影响 text-to-SQL。
- 不实现 DBML 的 Enum、Indexes、TableGroup、Project 等高级语法。
- 不支持协同编辑 / 实时光标。

## 许可与原创性

drawDB 仅作为交互参考。画布、布局、几何计算、DBML 解析/序列化全部在本仓库原创实现，
不复制 drawDB 源码。DBML 是公开的文本格式规范，按其语法自行实现解析器。

## 信息架构

左侧导航在 `Exploration` 之后新增 `ER Model`（中文「ER 建模」），路由 `/erd`。

页面结构：

```
┌ 页头：Zone 选择器 | 搜索表 | 导入 | 导出 | 自动整理 | 缩放 ─────────────┐
│                                                                        │
│  画布（点阵背景，可平移/缩放）                                          │
│   ┌──────────────┐        ┌──────────────┐                             │
│   │ orders       │───────▶│ customers    │                             │
│   │ 🔑 id        │        │ 🔑 id        │                             │
│   │    customer_id│       │    name      │                             │
│   └──────────────┘        └──────────────┘                             │
└────────────────────────────────────────────────────────────────────────┘
```

权限：

- 读画布：`zone:read`（viewer 可见，只读）
- 改画布：`zone:manage`（admin，可拖动、连线、导入）

## 数据模型

新增三张表（`all_ontology/dal/schema.py`，Alembic autogenerate）。

### `erd_canvas`

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | text PK | `gen_random_uuid()::text` |
| `zone_id` | text NOT NULL UNIQUE, FK `zone.id` ON DELETE CASCADE | 一个 zone 一张画布 |
| `viewport` | jsonb NULL | `{"x": number, "y": number, "zoom": number}` |
| `created` / `modified` | timestamptz | 审计字段 |

### `erd_node`

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | text PK | |
| `canvas_id` | text NOT NULL, FK `erd_canvas.id` ON DELETE CASCADE | |
| `table_id` | text NULL, FK `catalog_table.id` ON DELETE CASCADE | 目录表；虚拟表为 NULL |
| `name` | text NOT NULL | 显示名（目录表存 `schema.table`） |
| `x` / `y` | double precision NOT NULL DEFAULT 0 | 画布坐标 |
| `collapsed` | boolean NOT NULL DEFAULT false | 折叠只显示表头 |
| `columns` | jsonb NULL | 虚拟表的列快照 |
| `created` / `modified` | timestamptz | |

约束：partial unique index `(canvas_id, table_id) WHERE table_id IS NOT NULL`。

### `erd_relationship`

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | text PK | |
| `canvas_id` | text NOT NULL, FK `erd_canvas.id` ON DELETE CASCADE | |
| `source_node_id` | text NOT NULL, FK `erd_node.id` ON DELETE CASCADE | |
| `target_node_id` | text NOT NULL, FK `erd_node.id` ON DELETE CASCADE | |
| `source_columns` | text[] NOT NULL DEFAULT '{}' | 列名，可为空（表级关联） |
| `target_columns` | text[] NOT NULL DEFAULT '{}' | |
| `cardinality` | text NOT NULL DEFAULT 'many-to-one' | `one-to-one` / `one-to-many` / `many-to-one` / `many-to-many` |
| `label` | text NULL | 备注 |
| `created` / `modified` | timestamptz | |

约束：`CHECK (source_node_id <> target_node_id)`；`CHECK (cardinality IN (...))`。

## 画布生命周期

1. `GET /api/erd/canvases/{zone_id}` 时惰性创建画布。
2. 同步节点：把 zone 覆盖的表（`zone_covers_table()` 规则）补成节点。已存在则保留坐标。
   不再被 zone 覆盖的目录表节点连同其关联一起删除；虚拟表节点保留。
3. 新节点按网格自动排布（列数 ≈ √n，间距 320×260），并整体居中。
4. 返回节点时附带列信息：目录表读 `catalog_column`（名称、类型、主键、唯一、可空），
   虚拟表读 `columns` 快照。

## API 契约

全部挂在 `/api/erd`，响应沿用项目 `{"data": ...}` / `{"data": [...], "count": n}` 信封。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/erd/canvases/{zone_id}` | 画布 + 节点 + 关联 + viewport |
| PATCH | `/erd/canvases/{zone_id}` | 更新 viewport |
| PATCH | `/erd/nodes/{node_id}` | 更新 x/y/collapsed |
| POST | `/erd/nodes` | 新建虚拟表节点 |
| DELETE | `/erd/nodes/{node_id}` | 删除节点（级联删关联） |
| POST | `/erd/relationships` | 新建关联 |
| PATCH | `/erd/relationships/{id}` | 改基数/备注/列 |
| DELETE | `/erd/relationships/{id}` | 删除关联 |
| POST | `/erd/canvases/{zone_id}/import` | 导入 `{format: "json"|"dbml", content: string, replace: bool}` |
| GET | `/erd/canvases/{zone_id}/export?format=json\|dbml` | 导出文本 |

GET 画布的返回形状：

```json
{
  "data": {
    "id": "...",
    "zone_id": "...",
    "zone_name": "Sales",
    "viewport": {"x": 0, "y": 0, "zoom": 1},
    "nodes": [
      {
        "id": "...", "table_id": "...", "name": "public.orders",
        "x": 120, "y": 80, "collapsed": false,
        "columns": [
          {"name": "id", "data_type": "bigint", "is_primary_key": true,
           "is_unique": true, "is_nullable": false}
        ]
      }
    ],
    "relationships": [
      {
        "id": "...", "source_node_id": "...", "target_node_id": "...",
        "source_columns": ["customer_id"], "target_columns": ["id"],
        "cardinality": "many-to-one", "label": null
      }
    ]
  }
}
```

## 原生 JSON 格式

```json
{
  "format": "all-ontology-erd",
  "version": 1,
  "zone_id": "...",
  "viewport": {"x": 0, "y": 0, "zoom": 1},
  "nodes": [
    {"name": "public.orders", "table_id": "…", "x": 0, "y": 0,
     "columns": [{"name": "id", "data_type": "bigint", "is_primary_key": true}]}
  ],
  "relationships": [
    {"source": "public.orders", "target": "public.customers",
     "source_columns": ["customer_id"], "target_columns": ["id"],
     "cardinality": "many-to-one", "label": null}
  ]
}
```

导出无损（含坐标、虚拟表、基数、备注）。导入时节点按 `table_id`、其次按 `name` 匹配；
匹配不到则建虚拟表节点。

## DBML 子集

支持：

- `Table schema.name as alias { ... }`
- 列定义 `name type [pk, increment, unique, not null, note: '...']`
- 表级 `Note: '...'`
- `Ref: a.col < b.col`、`Ref name: a.col > b.col`、`Ref { a.col - b.col }`
- 四种基数映射：`>` → many-to-one，`<` → one-to-many，`-` → one-to-one，`<>` → many-to-many

忽略并在导入结果里报告：`Enum`、`Indexes`、`TableGroup`、`Project`、`Note` 之外的块。

导出时写 `Table`、列、`Note`、`Ref`，并附带 `// exported from All-Ontology` 头注释。

## 前端组件

| 文件 | 职责 |
| --- | --- |
| `frontend/app/erd/page.tsx` | 路由入口 |
| `frontend/components/erdPage/ErdView.tsx` | 页面状态：zone 选择、加载、保存编排 |
| `frontend/components/erdPage/ErdCanvas.tsx` | 平移/缩放、拖拽、连线交互 |
| `frontend/components/erdPage/TableCard.tsx` | 表卡片（表头/列/连接点） |
| `frontend/components/erdPage/RelationshipEdge.tsx` | 贝塞尔连线与基数标记 |
| `frontend/components/erdPage/ErdToolbar.tsx` | 搜索、自动整理、缩放、导入导出 |
| `frontend/components/erdPage/ImportExportDialog.tsx` | 导入导出面板 |
| `frontend/lib/erd/layout.ts` | 自动布局（分层 + 网格） |
| `frontend/lib/erd/geometry.ts` | 端口坐标、贝塞尔路径、视口变换 |

画布实现要点：

- 单层 `div` 应用 `transform: translate(x,y) scale(z)`；表卡片是 HTML，连线是 SVG。
- 指针事件：空白拖拽平移；表头拖拽移动（`pointerdown` + `setPointerCapture`）；
  列端口拖拽画临时线，松开在目标列/表上建关联。
- 滚轮缩放以指针为锚点；`Ctrl/⌘ + 滚轮` 同样缩放，普通滚轮平移画布。
- 位置保存 400ms 防抖；失败回滚并 toast。
- 连线几何：从源端口到目标端口的三次贝塞尔，控制点水平偏移 `max(60, |dx|/2)`。

## 错误处理

- 画布不存在 / zone 不存在：404，前端显示空状态并允许重试。
- 导入解析失败：400 + `detail` 指出行号与原因；前端展示在对话框里，不改动画布。
- 导入部分不支持的语法：200，响应带 `warnings` 列表。
- 写操作失败：保留本地状态并提示「保存失败」，下一次成功写入会覆盖。

## 测试

后端：

- `all_ontology/dal/tests/test_erd.py`：画布惰性创建、节点同步（新增/删除）、
  坐标更新、关联 CRUD、级联删除、虚拟表保留。
- `all_ontology/server/erd/tests/test_dbml.py`：DBML 解析/序列化往返、
  四种基数、note、注释与未知块警告、错误行号。

前端：

- `pnpm lint`、`pnpm build`、`npx prettier --check .`。

接口文档：`uv run python -m dev_tools.generate_backend_openapi`。

## 迁移

- 新增 Alembic 版本，单一 `upgrade`/`downgrade`，不触碰既有表。
- 回滚只删三张新表。

## 第二批：继续借鉴 drawDB

在第一版基础上补充了五组能力，仍然全部原创实现。

### SQL DDL 导出与导入

- 导出：`GET /api/erd/canvases/{zone_id}/export?format=sql&dialect=postgres|mysql|sqlite`。
  `CREATE TABLE` 加 `PRIMARY KEY` / `NOT NULL` / `UNIQUE`，再按"多"的一端生成
  `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY`。SQLite 不支持事后加外键，
  因此外键写在 `CREATE TABLE` 内。
- 类型按建模时的写法原样输出，不做跨方言翻译——错误的自动映射比数据库报错更糟。
- 多对多不臆造中间表，只在文件末尾注释说明需要 junction table。
- 导入：`POST .../import {"format":"sql"}`，解析 `CREATE TABLE`（列、表级主键/唯一、
  内联与表级外键）和 `ALTER TABLE ... ADD FOREIGN KEY`；引号、注释、多行语句都处理。

### 画布内编辑表结构

- `PATCH /api/erd/nodes/{id}` 接受 `name` 与 `columns`，只允许**画布内虚拟表**；
  目录表直接拒绝（400），因为它的列镜像源数据库，改了就是在说谎。
- UI：虚拟表卡片出现铅笔按钮，打开编辑对话框，可改名、增删列、切换 PK/唯一/必填。

### 撤销 / 重做

- 浏览器端维护快照栈（最多 50 步），`Ctrl/⌘+Z` 撤销、`Ctrl/⌘+Shift+Z` 或 `Ctrl+Y` 重做。
- 每次拖动、折叠、连线、改基数、删除、导入、自动整理、编辑表之前入栈。
- 重放通过 `PUT /api/erd/canvases/{zone_id}/state` 整体替换，**保留节点与关联 id**，
  否则历史栈会指向已删除的行。工具栏有撤销/重做按钮，空栈时禁用。

### 图片导出

- `lib/erd/svgExport.ts` 直接按模型生成独立 SVG（不抓 HTML），保证任何浏览器/矢量工具打开一致；
  PNG 用该 SVG 以 2 倍分辨率栅格化。

### 乌鸦脚基数标记

- 连线两端按基数画记号：一端为竖线（1），多端为三叉（N）；画布与 SVG 导出使用同一规则。

### 表备注

- `erd_node.note` 存一句自由文本；卡片头显示 ▤ 并带 tooltip。
- 目录表只能编辑备注，名称与列只读（它们镜像源数据库）；虚拟表两者都可改。
- 备注随导出走：DBML 写表格级 `Note:`，PostgreSQL 写 `COMMENT ON TABLE`，
  MySQL 写 `ALTER TABLE ... COMMENT =`，SQLite 写 `-- note:`（它没有注释语句）。

### 画布检查

- 只在前端计算，不阻塞任何操作：重复列、空表、重名表、以及**关联引用了已不存在的列**。
- 最后一项来自可编辑表带来的真实风险：删掉一列后，原来的连线仍然存在。
  面板可直接定位或删除该关联。

### 折叠后的连线

- 折叠的卡片没有行，端口坐标退回卡片中心（`columnPort` 统一处理），
  避免连线锚到卡片下方看不见的位置。画布和 SVG 导出共用这一几何。

### 多选与批量操作

- Shift/Ctrl/⌘ 点击表头切换选中；普通点击替换选择。
- 拖动任一选中卡片，整组一起移动；位置在松手时逐个保存。
- `Ctrl+D` 复制所选：目录表复制成画布内虚拟表（它会复制列与备注），
  被复制表之间的关联也一并复制。
- `Delete` 或工具栏按钮删除所选，使用应用内确认框。

### 隐藏表（tombstone）

- 目录表的"从画布移除"过去会被下一次 zone 同步加回来。现在改为
  `erd_node.hidden = true`：行保留、不再参与渲染，同步也不会重建。
- 隐藏节点上的关联一起从响应中消失，恢复后回来——不需要删除连线。
- 工具栏「已隐藏 (N)」列出被隐藏的表并可恢复。
- 撤销一次移除时快照里包含该节点，`restore_canvas_state` 让快照优先，
  不会与 tombstone 主键冲突。

### 确认框

- 删除操作改用应用内 Modal（`ConfirmDialog`）。原生 `confirm()` 会阻塞渲染进程，
  一个卡住的对话框会冻住整个画布。

### 索引

- `erd_node.indexes` 存 `[{name, columns[], unique}]`；目录表的真实索引来自源库、
  没有被采集，所以只有虚拟表允许编辑。
- 编辑器里有索引分区：名称（可空）、逗号分隔的列、是否唯一。
- DBML：读/写 `Indexes { (a, b) [unique, name: 'x'] }`；导入不再把它当不支持块。
- SQL：每个索引生成 `CREATE [UNIQUE] INDEX ... ON ...`，导入时解析并挂回对应表；
  引用了文档里不存在的表会给出 warning。
- 校验：索引引用了不存在的列 → error；同一张表两个同名索引 → warning。

### 顺带修的两个解析/命名缺陷

- DBML 跳过 `Enum` 块时会把 `depth` 减成负数，导致紧随其后的 `Table` 被当成
  单行表（列全部丢失）。跳过块现在只维护自己的计数器。
- SQL 约束名由非 ASCII 列名清洗后可能完全重合（两个中文外键都变成
  `fk_<table>`）。清洗丢失信息时会附加原串的短哈希，保证唯一。

### 便签

- `erd_note` 表：canvas_id、text、x/y、宽高、颜色。便签没有列、没有关联、
  也没有目录身份，所以单独建表而不是塞进 `erd_node`。
- 画布上可直接拖动（表头区域拖）、直接编辑文字（失焦保存）、✕ 删除。
- 撤销/重做快照包含便签；JSON 导出/导入包含便签（replace 时一并替换）。
- DBML/SQL 没有"便签"概念，导出时不出现；PNG/SVG 会把便签画进图里
  （按宽高做简单的按字符换行）。

### 区域分组

- `erd_area` 表：名称、颜色、矩形。成员关系是**几何的**（表中心落在矩形内即属于该区域），
  不额外维护成员表——拖区域时按拖动开始那一刻的成员一起平移，避免拖进来的表在下一帧瞬移。
- 区域渲染在表卡片下面（和 drawDB 一样）；矩形本身也是拖拽面，因为卡片可能盖住标题栏。
- 右下角手柄调整宽高；工具栏「添加区域」放在现有图表下方，并自动 fit 视图，
  否则新区域总在屏幕外。
- 撤销/重做、JSON 导入导出包含区域；DBML/SQL 不表达"区域"。

### 网格吸附与小地图

- 工具栏可开关「吸附网格」：拖动表/区域、拉伸区域时把绝对位置对齐到 20px 栅格
  （取整绝对坐标而不是增量，反复拖动不会累积漂移）。
- 工具栏可开关「小地图」：右下角 176×118 的缩略图，画出表、区域、便签和当前视口框；
  点击或拖动缩略图直接把视口移到对应位置。小地图自身阻止事件冒泡，
  避免和画布平移同时生效。

### 复制 / 粘贴

- `Ctrl+C` 把所选表（含两端都在选区内的关联）写入 `localStorage`，所以切到别的 zone
  也能粘贴；工具栏同时提供「复制 / 粘贴」按钮（键盘在嵌入式浏览器里不一定可靠）。
- `Ctrl+V` 粘贴为画布内虚拟表，名字冲突时自动加 `(copy)`、`(copy 2)`；
  每次粘贴偏移 +40，连续粘贴不会叠在一起；被复制表之间的关联一并重建。

### 版本历史

- `erd_canvas_version` 存整份画布快照（表、关联、便签、区域，含 id），
  以一份 JSONB 文档保存而不是影子表——版本永远整体读取，不按字段查询。
- 工具栏「版本」打开历史面板：可写说明保存当前版本；列表按时间倒序显示
  表数/关联数；可恢复（覆盖当前画布，可撤销）或删除某个版本。
- 恢复走 `restore_canvas_state`，节点/关联 id 原样回填，因此历史里的关联仍然对得上。

### 表模板

- 工具栏「模板」提供三套起步结构：客户与订单（3 表 / 2 关联）、事件日志、日期与商品维度。
- 模板插入为画布内虚拟表（不动数据目录），放在现有图表下方并自动适配视图；
  名字冲突自动加 `(1)` 后缀，模板内部的关联一并创建。
