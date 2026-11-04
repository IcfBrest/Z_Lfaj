# 提案 — Phase 2：简历修改建议

## Why

Phase 1 已经能给"简历 × 岗位"打出可解释的四维分，并把缺口写进 `match_results.payload_json.gaps`。但用户拿到 62 分和"缺少 Kafka 实战"之后，下一步该改简历的哪一行、怎么改，仍然要靠自己。`suggestions` 表在 Phase 0 就建好了却从未写入，`llm_gateway` 的 `suggest` 任务类型也只有默认模型配置、没有调用方。本变更把 Phase 1 的缺口结论变成可执行的逐条修改建议：section 定位到简历字段、original 引用原文、proposed 给出可替换文本、why 说明理由、priority 排序，并用确定性的"原文可定位"校验 + 模型自陈的 `honesty_warnings` 兜住"编造经历"这条红线。

## What Changes

- **数据模型**：`suggestions` 增加 `match_result_id`（FK，绑定具体某次打分结果）与 `resume_version`，并加唯一约束 `(user_id, match_result_id, resume_version)` 作为缓存键。
- **触发方式（用户已确认）**：按单个岗位生成——输入是某条 `match_results`，不是整份简历的通用优化；由匹配详情里的按钮手动触发，不做自动生成。
- **建议内核** `app/suggestions.py`：`build_suggestion_prompt()`（简历画像 + 岗位要求 + 已有 gaps/四维分）→ `chat_structured(task_type="suggest")` → `SuggestionPayload`（逐条建议 + `missing_keywords` + `honesty_warnings`）→ 落 `suggestions` 表；生成后跑一次确定性校验：`original` 若在简历原文中定位不到，自动追加一条 `honesty_warnings`。
- **建议 API** `app/api/suggestions.py`：`POST /api/suggestions`（match_id + force，202 入队后台任务）、`GET /api/suggestions?match_id=`（按新到旧）、`GET /api/suggestions/{id}`（详情），全部按 `user_id` 隔离。
- **前端**：岗位页匹配详情卡片新增"生成修改建议"按钮与建议列表（优先级标签、section、原文→改写对照、理由、缺失关键词、防编造警告），生成期间轮询任务状态。
- **验收**：新测试覆盖生成、缓存、强制重算、隔离、原文不可定位时追加警告；本地 sqlite 冒烟跑通"打分 → 生成建议 → 重复生成零 LLM 调用"。

## Scope

- **In**：建议内核、API、`suggestions` 表结构与迁移、前端匹配详情改造、pytest 覆盖、端到端冒烟。
- **Out**：简历正文自动改写与成品导出（DOCX/PDF/LaTeX，方案 5.x 明确留到以后）、整份简历的通用体检、建议采纳状态追踪、多轮对话式修改、把建议回写进 `parsed_profile_json`。

## Impact

- 后端：`app/models.py`（Suggestion 三处）、新 `app/suggestions.py`、新 `app/api/suggestions.py`、`app/schemas_llm.py`（两个新模型）、`app/api/tasks.py`（重试映射）、`app/main.py`（挂路由）、`alembic/versions/`（新迁移）、`tests/`（新测试）。
- 前端：`src/views/Jobs.vue`（详情卡片扩展）、`src/style.css`（建议卡片样式）。
- 数据：`suggestions` 表加 2 列 + 1 个唯一约束；不改 `match_results`。
- 成本：单次生成约 2~3k tokens（简历画像 + 岗位要求 + gaps），DeepSeek 级约 ¥0.005/次；按匹配结果缓存，重复点击不重复计费。

## Proof of Completion

- `cd backend && .venv\Scripts\python.exe -m pytest -q` 全绿（含新增 `tests/test_suggestions.py`）。
- 空库 `alembic upgrade head` 成功，`suggestions` 含 `match_result_id`、`resume_version` 与唯一约束。
- `cd frontend && npm run build` 通过。
- 冒烟：1 份简历 + 2 个岗位 → 打分 → 对其中 1 条生成建议 → 返回 3~5 条含 section/priority 的建议与 `missing_keywords`；再次生成同一匹配结果时 `llm_calls` 不增长。
