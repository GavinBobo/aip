# 文档解析功能移植（OXR → All-Ontology）

> 任务：把 OXR（SoMark 的文档解析模型）的解析能力搬进 All-Ontology，
> 把本项目原来的"大模型设置"改成"模型设置"，并把 OXR 的模型设置一并放进去。
> 身份认证用 All-Ontology 现有的 better-auth + BFF 权限，不引入 OXR 的 `api_key` 表单参数。

## 1. 两个项目各有什么

| | OXR（`C:\Users\Administrator\Documents\OXR`） | All-Ontology（本仓库） |
| --- | --- | --- |
| 解析能力 | `oxr/` 包：版面分析（D-FINE 外部服务）→ OXR 识别模型（OpenAI 兼容）→ 阅读顺序 → 后处理 → Markdown/JSON | 无 |
| 服务 | FastAPI，`/parse/sync`、`/parse/async`、`/parse/async_check`、`/settings/model`、`/settings/layout` | FastAPI + Next.js BFF，权限在 BFF 层 |
| 认证 | 每个请求带 `api_key` 表单字段 | better-auth 会话 + `withPermission(...)` |
| 设置 | `data/model-settings.json`（文件） | `frontend.configurations` 键值表（Prisma） |
| 依赖 | `sopdf`、`opencv-python`、`openai`、`httpx`、`python-multipart` | 已有 fastapi/httpx/openai(经 langchain)，缺 `sopdf`、`opencv-python`、`python-multipart` |

OXR 的 Python 代码约 287 KB，其中真正要搬的是 `config/` `model/` `pipeline/` `utils/` 四块（约 200 KB）；
`server/`（含 demo 与内存队列）、`cli/` 不搬 —— 服务层由 All-Ontology 承担。

## 2. 目标结构

```
all_ontology/parsing/                 # 移植后的解析包（保持 OXR 内部结构，便于对照上游）
  __init__.py
  config/
    settings.py                        # 静态配置（来自 .env + 默认值）
    model_settings.py                  # 可持久化的模型设置模型（原样）
  model/
    client.py                          # OpenAI 兼容识别客户端
    layout_client.py                   # D-FINE 版面服务客户端
    backend.py                         # 后端选择：none / vllm / local
    prompts.py
  pipeline/                            # orchestrator / recognition / reading_order / postprocess...
  utils/
  service.py                           # 新增：把 OXR 的 routes.py 逻辑改写成 All-Ontology 的服务层
  router.py                            # 新增：/api/parsing/* 路由
  settings.py                          # 新增：读写 frontend.configurations 的解析设置
```

**唯一允许的改动**是 import 路径（`oxr.` → `all_ontology.parsing.`）和 OXR 的 `settings` 单例改成由本项目的配置注入。
其余解析逻辑逐行保留，这样上游修 bug 时能直接对照 diff。

## 3. 认证与权限

| 层 | 做法 |
| --- | --- |
| 浏览器 → Next | 新增 `frontend/app/api/parsing/**` 路由处理器，全部 `withPermission({ catalog: ['edit'] })`（管理员），和"模型设置"同权限 |
| Next → 后端 | `proxyToBackend(req, { userId: user.id })`，与现有 BFF 一致 |
| 后端 | 不需要再判权限：后端只监听 127.0.0.1，且 BFF 是唯一入口（与现有 `/api/erd/**` 同构） |

OXR 原来用 `api_key` 表单字段做鉴权，这个字段**不再需要**，解析请求体里直接去掉。

## 4. 设置项（"模型设置"页）

### 4.1 原有部分（保持不变，只改标题）

`llm_base_url` / `llm_api_key` / `llm_model` —— 会话模型（REASONING / NON_REASONING）。

### 4.2 新增部分（来自 OXR）

| 分组 | 键 | 说明 |
| --- | --- | --- |
| 识别后端 | `parsing_mode` | `none` / `vllm` / `local` |
| vLLM | `parsing_vllm_url`、`parsing_vllm_model`、`parsing_vllm_api_key`、`parsing_vllm_concurrency`、`parsing_vllm_timeout` | OpenAI 兼容端点 |
| 本地模型 | `parsing_local_model_dir`、`parsing_local_host`、`parsing_local_port`、`parsing_local_threads`、`parsing_local_dtype`、`parsing_local_startup_timeout` | 由本服务按需拉起 CPU 网关（`deploy/oxr_openai_cpu_server.py`） |
| 版面服务 | `parsing_layout_url`、`parsing_layout_batch_size`、`parsing_layout_concurrency`、`parsing_layout_timeout`、`parsing_layout_score_threshold`、`parsing_layout_nms_iou`、`parsing_layout_provides_reading_order` | D-FINE HTTP 服务 |

存储位置复用 `frontend.configurations`（不再用 OXR 的 `data/model-settings.json`），
这样备份、迁移、审计都跟本项目其余配置一致。

**生效方式**：后端在每次解析请求前读取一次设置（带 5 秒缓存），设置变了就地重建客户端；
不需要重启服务，也不需要像 LLM 设置那样"重启后生效"。

## 5. 后端接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/parsing/documents` | 上传一个文档，同步返回 Markdown/JSON 与版面 JSON |
| `POST` | `/api/parsing/jobs` | 提交异步任务，返回 `task_id` |
| `GET` | `/api/parsing/jobs/{task_id}` | 查询任务状态与结果 |
| `GET` | `/api/parsing/instances?limit=50` | 已保存的解析实例，最新在前；列表不带正文 |
| `GET` | `/api/parsing/instances/{document}/{run}` | 一个实例的完整结果（Markdown/JSON/元数据） |
| `GET` | `/api/parsing/instances/{document}/{run}/source` | 该实例解析的原始文件 |
| `DELETE` | `/api/parsing/instances/{document}/{run}` | 删除一个实例（源文件、结果与截取的图片） |
| `GET` | `/api/parsing/capabilities` | 当前后端模式、是否就绪、支持的元素格式（给前端渲染表单用） |
| `GET` | `/api/parsing/settings` | 生效中的解析设置（供模型设置页读取，密钥已遮蔽） |
| `POST` | `/api/parsing/backends/test` | 测试 vLLM / 版面服务连通性（对应 OXR 的 `/settings/model/test`） |
| `POST` | `/api/parsing/layout/test` | 只测版面服务 |

任务存储先用进程内 `MemoryTaskStore`（与 OXR 一致），并显式记录它的边界：
进程重启即丢失、多副本不共享。需要持久化时再换表（已列为后续项）。

**解析实例**是另一回事，它落在磁盘上而不是进程里：每次解析写在
`<upload_dir>/<document>/<run>/`，源文件与 `result.json` 放在一起。`run` 是
`YYYYMMDD-HHMMSS-<6 位十六进制>`，所以同一份文件重复上传是多个实例，不会覆盖别人
正在看的结果。列表是把这些 `result.json` 按修改时间倒序读出来的，没有第二份索引需要
保持一致；删除实例就是把那个目录删掉。`document` 与 `run` 都按正则校验，路径穿越
在进入文件系统之前就被拒绝（有单测）。

## 6. 前端

| 改动 | 位置 |
| --- | --- |
| "大模型设置" → "模型设置" | 路由 `settings/llm-settings` → `settings/model-settings`，导航文案、面包屑、i18n |
| 在模型设置页加"文档解析"分组 | 后端选择（none/vllm/local）、vLLM 参数、版面服务参数、"测试连接"按钮 |
| 新增"文档解析"页 | 上传（PDF/图片）、选项（输出格式、页眉页脚、公式/表格/图片格式、temperature 等）、进度、结果预览（Markdown 渲染 + JSON 查看 + 下载） |
| 文档解析页加左侧二级菜单 | "解析示例"（`/parsing`，解析页）与"创建批量解析任务"（`/parsing/instances`，实例列表），样式与设置页一致；`/parsing/batch` 跳转到实例列表 |
| 批量解析 | 一次选多份 PDF/图片，逐份排队、各自轮询进度；完成后可直接打开对应实例 |
| 实例详情 | `/parsing/instances/{document}/{run}`，Markdown/JSON/元数据/原始文件四个页签，可下载或删除 |

## 7. 分阶段

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| **P1 后端能力** ✅ | 移植 `config/model/pipeline/utils`，加 `service.py` / `router.py` / `settings.py` / `tasks.py`，补依赖 | 41 个文件移植、`import all_ontology.parsing.pipeline.orchestrator` 通过；9 个单测；`/api/parsing/capabilities` 200；无后端时 `POST /api/parsing/documents` 返回 503 + OXR 原文 |
| **P2 设置改造** ✅ | 路由改名（`settings/llm-settings` → `settings/model-settings`）、导航与面包屑、OXR 设置分组、测试连接按钮 | 页面读写通过；保存后后端 5 秒内生效（实测 `mode=vllm` → `state=configured`） |
| **P3 解析页面** ✅ | 上传（拖拽/选择）、选项表单、任务进度、Markdown/JSON/元数据三种预览、下载 .md/.json、失败提示 | 页面可用；**成功路径还差一个真实的识别端点**（见下） |
| **P4 可选** | 解析结果入库、与 ontology 的术语/表关联、任务持久化、本地 CPU 网关集成 | 按需 |

### 已完成工作的证据

- `all_ontology/parsing/` 41 个 `.py`，`ruff check` / `ruff format --check` 干净（`_vendor/xycut_plus_plus.py` 单独豁免，见 `pyproject.toml` 注释）
- `pytest all_ontology/parsing` → 9 passed；全量 `pytest all_ontology dev_tools` → 2692 passed
- `GET /api/parsing/capabilities` → 200，`ready:false`（未配置后端时）
- `POST /api/parsing/documents` → 503 `Model backend is not configured. Open Settings …`
- `PUT /api/configurations/parsing` → `{"ok":true}`；`GET` 回读 `mode=vllm, state=configured`
- 浏览器实测模型设置页：导航「模型设置」、原 LLM 表单、新「文档解析」分组（识别后端 / vLLM / 版面分析）
- `pnpm build` 通过，路由清单里有 `/parsing` 与 7 个 `/api/parsing/**`
- 浏览器实测解析页：上传 `111.pdf` → 状态 `processing` → `failed`，界面显示 OXR 的公开文案
  `Unable to process this document…` 并给出「去检查模型设置」链接（识别/版面服务未启动，符合预期）

### 真实模型验证（2026-11-15）

本机已经有 OXR 的全套运行环境，所以这条路径是**用真模型跑通的**，不是桩：

| 组件 | 地址 | 来源 |
| --- | --- | --- |
| D-FINE 版面服务 | `127.0.0.1:8081` | 用户已在运行（`OXR/service/layout_analyze`） |
| OXR-1.0 识别模型 | `127.0.0.1:8080/v1` | 用 OXR 自带 venv 启动 `deploy/oxr_openai_cpu_server.py`（2.9 GB 权重，CPU 16 线程） |

一页 1000×420 的中文采购订单图片：

- 同步接口 `POST /api/parsing/documents` 用时 **79.4s**，返回
  `# 采购订单 / 订单编号：PO-2026-00187 / 供应商：晨光文具有限公司 / 下单日期：2026-11-10 /
  合计金额：人民币 12,480.00 元 / 备注：请于11月20日前送达仓库。`
- 浏览器端走异步任务，状态 `processing → success`，Markdown 预览、JSON、元数据三个页签与
  `下载 .md / .json` 都正常。

### 端到端测试里揪出的一个真 bug

异步任务最初用裸 `asyncio.create_task` 调度，而事件循环只持**弱引用** —— 任务可能在跑到一半时
被 GC 掉，界面上就永远停在"解析中"，模型那边一条日志都没有。现在由 `service.start_job`
保存强引用并在结束时移除，`test_a_started_job_is_referenced_until_it_finishes` 钉住这条。

### 移植时的机械改动（仅这些）

1. `oxr.` → `all_ontology.parsing.` 的 import 前缀；
2. `model/backend.py` 的 `PROJECT_ROOT` 从 `parents[2]` 改为 `parents[3]`（包深了一层）；
3. 设 `settings.model_settings_path` 指向临时目录（数据库才是真相）；
4. `ruff format`（纯格式，便于对齐本仓库风格；与上游对比请用 `git diff -w`）。

## 8. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 依赖膨胀（opencv ~60 MB） | 只在 `parsing` extra 里声明，核心安装不受影响；Dockerfile 单独加 |
| OXR 上游更新后难对齐 | 保留原目录结构与文件名，只改 import 前缀；在包 `__init__` 注明来源 commit |
| 大文件/大 PDF 阻塞 | 与 OXR 一致：解析走异步任务；同步接口设上限并文档化 |
| 内存队列在多副本下不一致 | 文档注明；`jobs` 状态带 `instance` 标记，前端提示"换副本会丢任务" |
| 许可证 | OXR 是 `LicenseRef-OXR`（见其 LICENSE/NOTICE），移植代码需保留声明，并在 `THIRD_PARTY_NOTICES.md` 增加条目 |

## 9. 不做的事

- 不搬 OXR 的 `server/demo*`（演示 UI）与 `cli/`。
- 不保留 OXR 的 `api_key` 表单鉴权。
- 不用 OXR 的 `data/model-settings.json`。
- 不改 OXR 的解析算法、提示词、后处理规则。
