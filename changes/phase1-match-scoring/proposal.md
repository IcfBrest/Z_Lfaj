# 提案 — Phase 1：匹配打分闭环

## Why

Phase 0 已能手动导入岗位（共享 `job_postings` / 私有 `user_manual_jobs`）并把简历解析成 Master Profile，但两类数据之间没有任何关联：岗位列表只能按 ID 倒序看，用户无法知道"哪些岗位值得投"。`match_results` 表在 Phase 0 已建好却从未写入，`llm_gateway` 的 `score` 任务类型也只有默认模型配置、没有调用方。本变更把这条路打通：岗位库 → 硬规则过滤 → 粗排 → LLM 精排 → 加权总分 → 结果缓存 → 岗位列表按推荐排序与详情展示，使"简历 + 岗位库 → 投递优先级"这条主链路第一次可用。

## What Changes

- **数据模型**：`users` 增加 `score_weights`（四维权重 JSON，空=均等）；`match_results` 复用既有唯一约束 `(user_id, resume_id, job_ref_type, job_ref_id, resume_version)` 作为缓存键。
- **触发方式（用户已确认）**：只做手动触发——全量打分、单岗打分、按新权重重算；不做"新岗位自动入队"，成本完全由用户点击决定。
- **打分内核** `app/scoring.py`：硬规则过滤（经验差 > 2 年、学历低于硬门槛 → 排除并给理由，零 token）→ 粗排（技能/标题关键词重叠，零 token，取 Top N）→ LLM 精排（四维 rubric，JSON 强校验，复用 `chat_structured`）→ 代码加权总分。
- **匹配 API** `app/api/matches.py`：全量打分、单岗打分、结果列表（按分排序）、结果详情、权重读写、自动打分开关。
- **前端**：岗位页新增"推荐分"列与排序、点击行展开详情（四维分/理由/匹配点/缺口）与"为当前简历打分"按钮；设置页新增四维权重与"立即全量重算"。
- **验收**：新测试覆盖过滤/粗排/加权/缓存/开关；本地 sqlite 冒烟跑通"导入 JD → 上传简历 → 打分 → 排序 → 重复打分零 LLM 调用"。

## Scope

- **In**：上述打分内核、API（手动触发）、岗位列表附带推荐分、前端岗位页与设置页改造、Alembic 迁移、pytest 覆盖。
- **Out**：新岗位自动打分/自动入队（本轮明确不做，成本交由用户手动决定）、embedding/FTS 粗排（保持关键词重叠，Phase 4 后再评估）、向量缓存、批量评分进度条（复用现有任务状态轮询）、跨简历对比、投递状态管理、抓取类数据源（Phase 3/4）。

## Impact

- 后端：`app/models.py`、新 `app/scoring.py`、新 `app/api/matches.py`、`app/api/jobs.py`（列表附带推荐分）、`app/main.py`（挂路由）、`alembic/versions/`（新迁移）、`tests/`（新测试）。
- 前端：`src/views/Jobs.vue`、`src/views/Settings.vue`、`src/style.css`（分数条样式）。
- 数据：`users.score_weights` 一列；`match_results` 开始写入（无结构变更）。
- 成本：每次精排约 3k tokens，DeepSeek 级约 ¥0.006/岗；50 岗全量 < ¥1（对照方案 4.4）。

## Proof of Completion

- `cd backend && .venv\Scripts\python.exe -m pytest -q` 全绿（含新增 `tests/test_scoring.py`、`tests/test_matches.py`）。
- `cd backend && .venv\Scripts\python.exe -m alembic upgrade head` 在空库上成功建出含新列的 `users`。
- `cd frontend && npm run build` 通过。
- 冒烟：sqlite 库中导入 3 个 JD + 1 份简历 → 全量打分 → `/api/matches` 返回按 `score` 降序的 3 条 → 再次全量打分时 `llm_calls` 不增加（缓存命中）。
