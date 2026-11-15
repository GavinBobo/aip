# docs 索引

这个目录只放**给人读的文档**和**生成物**。接口的唯一权威是 `openapi/`，代码约定写在仓库根的 `CLAUDE.md`，对外发布的 agent skills 在 `skills/`。

## 架构与规划

| 文档 | 回答什么问题 |
| --- | --- |
| [architecture/project-review.md](./architecture/project-review.md) | 这个仓库长什么样、有哪些结构问题、按什么顺序重构、哪些已经做完 |
| [architecture/deployment-plan.md](./architecture/deployment-plan.md) | 用公司现有 PostgreSQL 怎么部署：DBA 前置条件、两个 schema 的初始化顺序、三种部署形态、连接数预算与故障排查 |

## 领域说明

| 文档 | 内容 |
| --- | --- |
| [authentication.md](./authentication.md) | better-auth、cookie、权限模型 |
| [connections.md](./connections.md) | 数据源连接、文件投放目录（`shared/`）、连接向导 |
| [conversation-api.md](./conversation-api.md) | 对话接口与流式协议 |
| [mcp.md](./mcp.md) | MCP server 暴露的只读工具 |

## 生成物

| 路径 | 生成方式 |
| --- | --- |
| [openapi/auto-ontology-api.json](./openapi/auto-ontology-api.json) | `python -m dev_tools.generate_backend_openapi` |
| `openapi/backend.json`、`openapi/ingestion.json` | 同上，分服务导出 |
| [assets/](./assets/) | README 用的截图/示意图 |

## 设计记录

`superpowers/specs/` 与 `superpowers/plans/` 是功能开发当时的设计稿与执行计划，保留作为决策上下文；**它们描述的是当时的想法，不是当前行为的权威**，与代码冲突时以代码和 `openapi/` 为准。

## 写文档的三条约定

1. **可验证**：写"已经做了"就要能被命令验证（跑哪个测试、看哪个端口），做不到就写"计划中"。
2. **不重复**：安装命令归 `DEPLOYMENT.md`，接口形状归 `docs/openapi/`，这里只写"为什么"和"顺序"。
3. **不放凭据**：这个目录会进公开镜像/仓库，任何 hostname、token、密码都不要写进来。
