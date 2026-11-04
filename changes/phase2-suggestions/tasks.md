# Tasks — Phase 2：简历修改建议

> 按序执行；每任务以 Proof 为完成标准。后端验证：`cd backend && .venv\Scripts\python.exe -m pytest -q`；前端验证：`cd frontend && npm run build`。
> 触发方式已确认：**按单个岗位生成**（输入是某条匹配结果），手动点击，不自动生成。

- [x] 1 **数据模型与迁移**：`backend/app/models.py` 的 `Suggestion` 增加 `match_result_id`（FK，索引）与 `resume_version`，加唯一约束 `(user_id, match_result_id, resume_version)`；新增 Alembic 迁移（sqlite 用 `batch_alter_table`，downgrade 可回退）。**Proof**：空库 `alembic upgrade head` 成功且 `suggestions` 含两列与唯一约束；`pytest -q` 既有用例不回归。

- [x] 2 **建议内核 `backend/app/suggestions.py`**：`profile_text(profile)` 摊平简历文本；`build_suggestion_prompt(profile, job, match_payload)`（含四维分、gaps、岗位要求、原文）；`SuggestionPayload` 归一化（action/priority 白名单、条数截断到 8、缺字段补空串）；`locate_original()` 确定性校验并追加 `honesty_warnings`；`generate(db, user, match, force=False)` 查缓存 / 调 `chat_structured(task_type="suggest")` / 落库（`IntegrityError` 回读）。**Proof**：`tests/test_suggestions.py` 覆盖 prompt 含 gaps、原文定位失败时追加警告、缺字段归一化、条数截断。

- [x] 3 **建议 API `backend/app/api/suggestions.py`**：`POST /api/suggestions`（body `{match_id, force}`，202 入队 `suggestion_generate`）、`GET /api/suggestions?match_id=`（新到旧）、`GET /api/suggestions/{id}`；全部按 `user_id` 隔离，match 不存在或非本人 404；`app/main.py` 挂载；`app/api/tasks.py` 重试映射补上。**Proof**：`tests/test_suggestions.py` 覆盖 202 入队、任务完成后可读、缓存不重复调用、force 重算、详情 404 隔离、列表过滤。

- [x] 4 **前端 `frontend/src/views/Jobs.vue`**：匹配详情卡片加"生成修改建议"按钮（轮询任务，完成后拉列表）、建议列表（优先级标签、section、原文→改写对照、理由）、`missing_keywords` chips、`honesty_warnings` 醒目提示块；`src/style.css` 补样式。**Proof**：`npm run build` 通过。

- [x] 5 **端到端冒烟（sqlite）**：复用 `backend/tools/` 的桩服务，1 份简历 + 2 岗位打分后对 1 条生成建议，断言建议条数、字段完整、`missing_keywords` 非空、`honesty_warnings` 存在（桩返回一条定位不到的 original）；重复生成时 `llm_calls` 不增长。**Proof**：记录冒烟输出。

- [x] 6 **收尾整验**：全量 `pytest -q`、空库 `alembic upgrade head`、`npm run build`，更新 README 与 `doc/求职平台调研方案.md` 的 Phase 2 状态，`ssf sync` + 评审 + complete。**Proof**：三条命令全绿 + 状态标记。

## 执行记录（2026-11-04）

- 验证命令与结果：`cd backend && .venv\Scripts\python.exe -m pytest -q` → **62 passed**（原 55 + 本变更 7）；
  `alembic upgrade head`（空 sqlite）→ 12 张表，`suggestions` 列为
  `[id, user_id, resume_id, job_ref_type, job_ref_id, payload_json, created_at, match_result_id, resume_version]`，
  `downgrade -1` 可回退到 7 列；`cd frontend && npm run build` → 通过（Jobs 产物 8.79 kB）。
- 冒烟：`cd backend && pwsh -File tools/smoke_run.ps1` → SMOKE OK（打分 65 → 权重改 100/0/0/0 后 80 → 生成建议 3 条 /
  缺失关键词 2 个 / 防编造提醒 2 条；重复生成不新增 `suggest` 记账）。
- 实现差异说明：
  - 任务 2 的 `build_suggestion_prompt` 实际命名为 `build_prompt`（与 `scoring.build_prompt` 保持一致），签名
    `build_prompt(profile, job: scoring.JobView, match_payload) -> (system, user)`。
  - `chat_structured` 返回的 `result.data` 是 dict（不是 pydantic 实例），`generate` 里显式转 `SuggestionPayload(**result.data)`。
  - 新增"防编造"的第二道确定性校验：`original` 非空但在 `profile_text` 里定位不到时，除保留建议外追加一条
    `honesty_warnings`（比设计里"仅提示"更进一步，避免把无法核对的原文当事实展示）。
  - 任务 5 的桩服务需要同时返回打分与建议两种 JSON，故 `smoke_llm_stub.py` 按请求体里是否出现"修改建议/简历顾问"分流。
- 额外修复（冒烟中发现）：`litellm` 首次导入耗时 4~7 秒，且默认会联网拉模型价目表（本机 10 秒超时后回落），
  这段耗时发生在请求线程里会把事件循环一起卡住，导致首个打分请求/健康检查超时。修复：`app/llm_gateway.py` 新增
  `prepare()`（设 `LITELLM_LOCAL_MODEL_COST_MAP=True`、`LITELLM_LOG=ERROR`，导入并 `suppress_debug_info`），
  由 `app/main.py` 的 `lifespan` 在启动阶段同步预热。
