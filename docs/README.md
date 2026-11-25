<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# docs 索引

这个目录只放**给人读的文档**和**生成物**。接口的唯一权威是 `openapi/`，代码约定写在仓库根的 `CLAUDE.md`，对外发布的 agent skills 在 `skills/`。

## 架构与规划

| 文档 | 回答什么问题 |
| --- | --- |
| [architecture/project-review.md](./architecture/project-review.md) | 这个仓库长什么样、有哪些结构问题、按什么顺序重构、哪些已经做完 |
| [architecture/deployment-plan.md](./architecture/deployment-plan.md) | 用公司现有 PostgreSQL 怎么部署：DBA 前置条件、两个 schema 的初始化顺序、三种部署形态、连接数预算与故障排查 |
| [architecture/semantic-quality-1.3.md](./architecture/semantic-quality-1.3.md) | Auto-Ontology 1.3 的语义质量功能哪些已移植、哪些是独立架构迁移 |
| [architecture/performance-notes.md](./architecture/performance-notes.md) | 已落地的算法、启动时间与结构清理优化，附验证基线 |
| [architecture/image-understanding.md](./architecture/image-understanding.md) | 文档图片的 VLM 解读、两张记录表与知识证据图片引用链路 |
| [architecture/document-parsing-v2-plan.md](./architecture/document-parsing-v2-plan.md) | 文档解析从“解析示例”到可靠工作台、可校对结果库的建设方案（P0/P1） |
| [architecture/knowledge-ontology.md](./architecture/knowledge-ontology.md) | 数据本体之外的知识本体：OXR 文档抽取、概念/关系/事实/证据、数据映射与 BKN 导出 |
| [architecture/bkn-integration-plan.md](./architecture/bkn-integration-plan.md) | 对 bkn-foundry / bkn-studio 的能力复盘：哪些已进 aip、哪些还没进、后续优先级 |
| [architecture/data-access.md](./architecture/data-access.md) | 用户与部门 Zone 数据权限：数据模型、默认拒绝、请求解析、问数防线与管理入口 |

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
| [openapi/all-ontology-api.json](./openapi/all-ontology-api.json) | `python -m dev_tools.generate_backend_openapi` |
| `openapi/backend.json`、`openapi/ingestion.json` | 同上，分服务导出 |
| [assets/](./assets/) | README 用的截图/示意图 |

## 设计记录

`superpowers/specs/` 与 `superpowers/plans/` 是功能开发当时的设计稿与执行计划，保留作为决策上下文；**它们描述的是当时的想法，不是当前行为的权威**，与代码冲突时以代码和 `openapi/` 为准。

## 写文档的三条约定

1. **可验证**：写"已经做了"就要能被命令验证（跑哪个测试、看哪个端口），做不到就写"计划中"。
2. **不重复**：安装命令归 `DEPLOYMENT.md`，接口形状归 `docs/openapi/`，这里只写"为什么"和"顺序"。
3. **不放凭据**：这个目录会进公开镜像/仓库，任何 hostname、token、密码都不要写进来。
