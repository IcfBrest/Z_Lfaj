# Design: 投递记录与面试跟踪（Phase 5）

## 数据模型

### applications

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int PK | |
| `user_id` | FK users | 记录归属，所有查询按它隔离 |
| `job_ref_type` | str(32) | `job_posting`（共享库）或 `user_manual_job`（私有） |
| `job_ref_id` | int | 对应表主键，不设 FK（两表共用一套 ref，用类型区分） |
| `resume_id` | FK resumes, 可空 | 投递时用的简历 |
| `match_result_id` | FK match_results, 可空 | 投递前若已有匹配结论则挂上 |
| `company_name` / `title` | str | **快照**：岗位后续被采集更新或下架也不影响历史记录 |
| `location` | str 可空 | 快照，便于列表展示 |
| `source_url` | str 可空 | 快照，方便回看原岗位 |
| `match_score` | int 可空 | 快照，投递当下的匹配分 |
| `status` | str(16) | `applied` / `written_test` / `interview` / `offer` / `rejected` / `withdrawn` |
| `note` | Text 可空 | 用户随手记（如「内推人：张三」） |
| `applied_at` | datetime | 投递时间，默认创建时刻 |
| `last_activity_at` | datetime | 最近一次状态变更或备注修改时间，「N 天无动静」由它推算 |
| `created_at` / `updated_at` | datetime | |

约束：`UniqueConstraint(user_id, job_ref_type, job_ref_id)` —— 同一用户对同一岗位只有一条记录，重复投递返回 409 并带上已有记录 id，避免用户手抖建两条。

### application_events

| 字段 | 说明 |
| --- | --- |
| `id` | PK |
| `application_id` | FK applications，级联删除 |
| `user_id` | 冗余存一份，便于按用户做审计 |
| `from_status` | 可空（创建事件为空） |
| `to_status` | 事件后的状态 |
| `note` | 可空，本次推进的备注 |
| `created_at` | |

## 状态机

```
applied → written_test → interview → offer
   ↘         ↘            ↘         ↘
      rejected / withdrawn（任意非终止态可直接进入）
```

规则：

1. 非终止态之间**允许跳跃**（很多公司没有笔试，或直接约面），只要目标状态合法即可。
2. `rejected`、`withdrawn` 是终止态，进入后**不允许再变更**（再改返回 400）。
3. 状态值不在枚举内返回 400；同一状态重复设置视为幂等（不追加事件、不动 `last_activity_at`）。
4. 备注（`note`）可随时改，改备注刷新 `last_activity_at` 但不产生状态事件。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/applications` | body `{job_ref_type, job_ref_id, resume_id?, note?}`；解析岗位快照（标题/公司/地点/链接）与可选的 `match_score`，默认用当前 master 简历；重复投递 409 |
| GET | `/api/applications` | 参数 `status?`、`sort=recent\|stale`、`limit`；返回含 `days_since_update`、`is_stale`（非终止态且 ≥7 天） |
| GET | `/api/applications/{id}` | 详情 + `events` 时间线（升序） |
| PATCH | `/api/applications/{id}` | body `{status?, note?}`，按状态机校验并追加事件 |
| GET | `/api/applications/stats` | 各状态计数 + `total` + `stale` 数 |

所有接口按 `current_user` 过滤；他人记录一律 404（不泄露存在性）。

## 与既有模块的关系

- **岗位来源**：`job_ref_type=job_posting` 读 `job_postings` + `companies.name`；`user_manual_job` 读 `user_manual_jobs.company_name`。两者都不改表结构。
- **简历**：默认取 `is_master=True` 的最新版本；显式传 `resume_id` 时校验归属。
- **匹配分**：取该岗位最近一条 `MatchResult.score`（用户 + 岗位 + master 简历版本），没有就留空——投递不应强制先打分。
- **不触发 LLM**，不建后台任务，纯同步写。

## 前端

- 新路由 `/applications`，导航加「投递」。
- 页面结构：顶部状态筛选 chips（带计数）→ 列表卡片（公司 · 岗位 · 阶段徽标 · 匹配分 · 「N 天无动静」角标 · 备注）→ 展开后显示时间线 + 「推进到下一步」按钮（跳到下一阶段，跳过笔试时提供下拉选目标状态）+ 备注输入。
- 共享岗位库与匹配结果卡片上增加「标记为已投递」，成功后按钮变为「已投递 · 查看」，点击跳转投递页。

## 取舍

- **快照 vs 关联**：岗位会被采集任务改写（标题变化、下架），若只存外键，历史会漂移；因此标题/公司/地点/链接在投递时冻结，同时保留 ref 以便回看当前状态。
- **唯一约束 vs 允许重复**：同一岗位多次投递（换简历版本再投）在求职里罕见但存在；本轮选唯一约束 + 409 提示，避免列表噪音；后面真需要再加「重复投递」动作。
- **不做通知**：与用户确认过，先只做「多久没动静」的可见性（排序 + 角标），不做邮件/桌面推送。
