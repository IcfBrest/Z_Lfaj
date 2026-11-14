# Tasks: 投递记录与面试跟踪（Phase 5）

- [x] 1 **数据模型与迁移**：在 `backend/app/models.py` 增加 `Application`（`applications`，含 `UniqueConstraint(user_id, job_ref_type, job_ref_id)`、`status`、`applied_at`、`last_activity_at`）与 `ApplicationEvent`（`application_events`，`ondelete=CASCADE`），新建 `backend/alembic/versions/e4b7c2f10a93_phase5_applications.py`（`down_revision="d8a2e5f91c30"`）。**Proof**：空库 `alembic upgrade head` 后 `applications`/`application_events` 两表存在、唯一索引可查，`downgrade -1` 后两表消失。

- [x] 2 **投递内核**：新建 `backend/app/applications.py`——`STATUSES`/`TERMINAL`/`NEXT_STATUS` 常量、`resolve_job(db, user, ref_type, ref_id)` 解析快照（共享岗位读 `job_postings`+`companies`，私有读 `user_manual_jobs`）、`pick_resume(db, user, resume_id)`（默认 master）、`find_match`、`create_application(...)`（重复抛 `DuplicateApplication`）、`transition(app, status, note)`（状态机 + 事件）、`serialize(app, now)`（`days_since_update`/`is_stale`）、`stats(db, user)`。**Proof**：被 API 与测试直接调用，无循环导入。

- [x] 3 **投递接口**：新建 `backend/app/api/applications.py` 并在 `main.py` 挂载——`POST /api/applications`（409/400 分支齐全）、`GET /api/applications`（`status`/`sort=recent|stale`/`limit`）、`GET /api/applications/{id}`（含 `events`）、`PATCH /api/applications/{id}`（状态机校验）、`GET /api/applications/stats`。**Proof**：他人记录 404，非法状态 400，终止态 400。

- [x] 4 **前端投递页**：新建 `frontend/src/views/Applications.vue`（状态筛选 chips + 计数、卡片列表、停滞角标、备注编辑、时间线展开、推进按钮与目标状态下拉），注册路由 `/applications` 与导航项，`style.css` 补 `.app-*` 样式。**Proof**：`npm run build` 通过，页面可筛选/推进/备注。

- [x] 5 **岗位侧入口**：`frontend/src/views/Jobs.vue`（共享岗位库与匹配结果两处）增加「标记为已投递」，成功后显示「已投递 · 查看」并跳转投递页；`Admin.vue` 不动。**Proof**：重复点击走 409 分支时提示「已经投过」。

- [x] 6 **测试**：新建 `backend/tests/test_applications.py`，覆盖创建快照（含共享/私有岗位）、重复投递 409、状态机（跳跃、终止态、非法值、幂等）、备注刷新活动时间、列表排序与 `is_stale`、`stats`、跨用户 404、默认 master 简历与显式简历、匹配分快照。**Proof**：`pytest -q` 全绿且总数从 95 增加。

- [x] 7 **冒烟扩展**：`backend/tools/smoke_e2e.py` 末端增加投递段（投递某共享岗位 → 列表出现且 `status=applied` → PATCH 到 `interview` → 详情时间线 2 条 → `stats` 计数与 `stale` 字段正确 → 第二个用户看不到）。**Proof**：`pwsh -File tools\smoke_run.ps1` 输出 `SMOKE OK`。

- [x] 8 **文档**：`README.md` 进度改 Phase 5 完成并补「投递」使用步骤；`doc/求职平台调研方案.md` 的 Phase 5 段改为已完成并写实现说明（快照策略、状态机、唯一约束、不做通知）。**Proof**：两处文档与实现一致。

## 执行记录（2026-11-14）

- `cd backend && .venv\Scripts\python.exe -m pytest -q` → `112 passed, 99 warnings`（Phase 5 新增 17 项，原 95 项无回归）。
- 迁移：空库 `alembic upgrade head` 后 `applications`/`application_events` 两表与索引（`ix_applications_user_id`、`ix_application_events_application_id`、唯一约束 `sqlite_autoindex_applications_1`）齐全；`alembic downgrade -1` 后两表消失。临时库 `data/mig-phase5.db` 已删。
- `cd frontend && npm run build` → `✓ built in 1.63s`（`Applications-BEIDwD82.js 5.58 kB`、`Jobs-DaHy8QLh.js 10.11 kB`）。
- `pwsh -NoProfile -File tools/smoke_run.ps1` → `SMOKE OK`：投递 201（快照标题/公司/链接/匹配分 80、`days_since_update=0`）、重复投递 409 且 `application_id` 一致、PATCH 到 `interview`、时间线 `['applied','interview']`、非法状态 400、`stats` 为 `total=1 / interview=1 / stale=0 / active=1`。
- 与计划的差异：① 任务 7 原写「第二个用户看不到」，实际冒烟只有一个用户，改为同用户列表/统计断言（跨用户隔离由单元测试 `test_other_user_cannot_see_or_touch` 覆盖）；② `scoring.JobView` 增加 `source_url` 字段以支持快照；③ `api.js` 的错误处理改为兼容结构化 `detail`（409 需要 `application_id`）；④ 终止态（已拒/已放弃）不计入 `stale`，避免"没动静"角标骚扰已结束的投递。
