<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# 用户与部门数据权限

第一阶段的权限模型以 **Zone 为数据授权对象**，以 **用户或部门为授权主体**。
它解决的是“同一次查询里能看见哪些数据”，不是页面按钮权限；页面和 API 的
admin/viewer 角色仍由 Better Auth 的角色权限控制。

## 数据模型

| 表 | 作用 |
| --- | --- |
| `department` | 部门主数据 |
| `department__member` | `user_id` 与 `dept_id` 的多对多成员关系 |
| `zone_grant` | 把 Zone 授权给一个 `user_id` 或一个 `dept_id`，并记录 `read/edit/manage` 权限 |
| `zone_grant_audit` | 每次替换授权时记录操作者、变更前后内容 |

一个普通用户的有效 Zone 是以下两部分的并集：

1. 直接授权给该 `user_id` 的启用 Zone；
2. 授权给该用户所属任一部门的启用 Zone。

管理员不展开授权列表，直接使用 DAL 既有的 `zone_ids=None` 全量语义。
普通用户没有授权时得到空列表，所有目录读取返回空集，而不是回退到全量。

同一 Zone 同时来自多个授权时取最高权限：

| 权限 | 能力 |
| --- | --- |
| `read` | 查看目录、语义、探索、ERD；使用问数 |
| `edit` | 在 `read` 基础上修改该 Zone 内的目录描述、术语、SQL 属性、ERD、自定义分析和知识网络 |
| `manage` | 在 `edit` 基础上管理该 Zone 的授权和启停 |

授权可以设置过期时间；过期授权在解析有效权限时立即失效。个人与部门授权
同时存在时按最高等级合并。

## 强制边界

Next.js 网关解析登录身份后，把用户 id 通过私有内部请求头传给 FastAPI。
FastAPI 中间件为每个 `/api/*` 请求解析一次 `RequestAccess`：

- 未带身份：401；
- 管理员：`zone_ids=None`；
- 普通用户：直接授权与部门授权的并集，空集表示默认拒绝。

目录树、术语、SQL 属性、探索、全局搜索和 ERD 都使用该 Zone 集合。问数链路
还会把允许的表 id 传进 agent；SQL 校验在生成与执行之间做最后一道确定性检查，
任何越权表都会以 `invalid_sql` 拒绝。检索候选同样按允许的表过滤，避免受限表名
进入提示词。

写操作不只看全局角色：`edit` 检查会解析对象涉及的全部表。术语或 SQL 属性跨
两个 Zone 时，调用者必须在两边都有 `edit`，否则整次修改被拒绝。

知识网络有独立的用户/部门授权表，并使用同一套权限等级；PQL 分析和连接列表
也已按有效 Zone 收敛。管理员授权变更会写入对应的 grant audit 表。

## 管理入口

管理员在 **Settings → Data Access** 中维护部门、用户部门归属和 Zone 授权。
对应接口：

| 接口 | 作用 |
| --- | --- |
| `GET /api/access/me` | 当前用户的有效部门与 Zone |
| `GET/POST /api/access/departments` | 部门列表与创建 |
| `PATCH/DELETE /api/access/departments/{dept_id}` | 部门编辑与删除 |
| `PUT /api/access/departments/{dept_id}/members` | 替换部门成员 |
| `GET /api/access/users` | 账号及其部门 |
| `PUT /api/access/users/{user_id}/departments` | 替换用户部门 |
| `PUT /api/zones/{zone_id}/access` | 替换 Zone 的用户/部门授权 |
| `GET /api/zones/{zone_id}/grant-audit` | 查看 Zone 授权变更记录 |

## 不变式

- 关闭的 Zone 即使有授权也不授予任何数据。
- 直接用户授权和部门授权是并集，权限等级取最高值，不存在负权限。
- Zone 的目标仍是数据库、Schema 或表；表级 Zone 只放行该表，不会扩成全库。
- 授权主体不存在时写入失败，不留下悬空的用户 id。
- 管理员可以在数据权限之外看到禁用 Zone，以便恢复管理。

当前阶段是资源级权限：Zone 决定可见的数据库、Schema 和表。表内行级过滤
（例如只允许本部门订单）尚未加入；预览、问数、指标预览和行动执行仍共享
该边界，后续需要在这些统一执行出口注入 `dept_id`/`user_id` 行策略。
