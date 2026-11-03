# Tasks — Phase 1：匹配打分闭环

> 按序执行；每任务以 Proof 为完成标准。后端验证：`cd backend && .venv\Scripts\python.exe -m pytest -q`；前端验证：`cd frontend && npm run build`。
> 触发方式已确认：**只做手动打分**，不实现新岗位自动入队。

- [x] 1 **数据模型与迁移**：`backend/app/models.py` 的 `User` 增加 `score_weights`（JSON，可空，空=均等）；新增 Alembic 迁移（`add_column`，downgrade 可回退）。**Proof**：空库 `alembic upgrade head` 成功且 `users` 含该列；`pytest -q` 既有用例不回归。

- [x] 2 **打分内核 `backend/app/scoring.py`**：`DIMENSIONS` 四常量；`filter_jobs(profile, jobs)` 解析经验/学历并给出排除理由（解析失败放行）；`rank_candidates(profile, jobs, limit=20)` 关键词重叠 + 标题词 + 地点加权降序；`combine(dimension_scores, weights)` 加权 + clamp + 缺失维度记录；`score_one(db, user, resume, job_ref_type, job_ref_id, force=False)` 组 prompt、调 `chat_structured`、按唯一键缓存/覆盖、写 `match_results`。**Proof**：`tests/test_scoring.py` 覆盖过滤、放行、排序、加权、clamp、缺键、缓存命中、force 覆盖。

- [x] 3 **匹配 API `backend/app/api/matches.py`**：`POST /api/matches/run`（resume_id 可空→默认 master，limit、force）与 `POST /api/matches/jobs/{ref_type}/{job_id}` 入队 `match_run`/`match_job` 后台任务并返回 `task_id`；`GET /api/matches` 按分数降序返回列表；`GET /api/matches/{match_id}` 返回详情；`PUT /api/matches/weights` 写入用户权重；`app/main.py` 挂载路由。**Proof**：`tests/test_matches.py` 覆盖 202 入队、任务完成后写结果、列表排序、详情 404 隔离、权重校验与持久化。

- [x] 4 **岗位列表附带推荐分**：`GET /api/jobs/shared` 与 `/mine` 每项增加 `match_id`/`match_score`（取当前用户 master 简历在该岗位上的最新结果，无则 null），支持 `sort=score` 时已打分在前、未打分在后。**Proof**：`tests/test_matches.py` 断言无结果时字段为 null、有结果时与 `match_results` 一致。

- [x] 5 **前端岗位页 `frontend/src/views/Jobs.vue`**：列表新增"推荐分"列（未打分显示"—"）、排序切换（默认推荐分降序）、点击行展开详情面板（四维分条、reasons、matching_points、gaps）、"为当前简历打分"按钮（轮询任务状态，完成后刷新）。**Proof**：`npm run build` 通过 + 手动走查打分流程。

- [x] 6 **前端设置页 `frontend/src/views/Settings.vue`**：四维权重输入（0~100，总和>0 才能保存）、"立即全量重算"按钮（调 run + force）、成本汇总补 `score` 任务行。**Proof**：`npm run build` 通过 + 权重保存后岗位页分数按新权重重算。

- [x] 7 **端到端冒烟（sqlite）**：admin 建公司 → 粘贴 3 个 JD → 上传 1 份简历 → 全量打分 → `GET /api/matches` 返回 3 条降序 → 重复打分 `llm_calls` 不增长。**Proof**：记录冒烟命令输出与 3 条分数。

- [x] 8 **收尾整验**：全量 `pytest -q`、空库 `alembic upgrade head`、`npm run build`、对照 proposal Acceptance 逐条核对并更新 `doc/求职平台调研方案.md` 的 Phase 1 状态。**Proof**：三条命令全绿 + Acceptance 勾选记录。

## 执行记录（2026-11-03）

- 命令基线（均在 `backend/`）：`pytest -q` → **55 passed**；`alembic upgrade head`（空 sqlite）→ 12 表，`users.score_weights`、`background_tasks.params` 均在位；`npm run build`（`frontend/`）→ 通过。
- 任务 2 的实际签名：`score_one(db, user, resume, job: JobView, force=False)`——岗位以 `JobView`（`ref_type` + `ref_id` 同构视图）传入，比 `job_ref_type`/`job_ref_id` 两个标量更省重复查询；`JobView.as_snapshot()` 落进 payload 供详情页展示。
- 任务 3 实际包含：`Task.params`（任务参数与结果回写，重试复用）与 `GET /api/tasks/{id}` 返回 `result`，前端据此展示"已打分/缓存/排除"计数。
- 任务 7 的冒烟改用**本地 OpenAI 兼容桩**（无真实 Key）：`backend/tools/smoke_llm_stub.py` + `backend/tools/smoke_e2e.py`，真实链路 = uvicorn + sqlite + litellm → 桩服务；结果：硬规则排除 1 个"10年+"岗位、打分 1 个（65 分）、`llm_calls` 记录 score 调用、权重改 100/0/0/0 后 force 重算得 80 分。重复打分不增长由 `tests/test_matches.py::test_cache_prevents_repeat_calls_and_force_overwrites` 覆盖。
