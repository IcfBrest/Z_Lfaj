# 设计 — Phase 2：简历修改建议

## 事实与约束

- `Suggestion` 表 Phase 0 已建：`id/user_id/resume_id/job_ref_type/job_ref_id/payload_json/created_at`，**没有** `match_result_id`、`resume_version`、唯一约束——缓存键需要补列（本变更负责）。
- `match_results.payload_json` 已含 `dimension_scores`、`weights`、`total`、`verdict`、`reasons`、`matching_points`、`gaps`、`missing_dimensions`、`job_snapshot`、`resume_version`，因此建议生成不需要重新解析岗位或重新打分。
- `llm_gateway.chat_structured(db, user_id, task_type, system_prompt, user_prompt, schema_model)`：temperature=0、pydantic 校验、失败回喂重试至多 2 次、每次尝试写 `llm_calls`；`TASK_TYPES` 已含 `suggest`，`settings.default_suggest_model` 已存在。
- `task_runner.enqueue(..., params=...)` + `run_with_status` + `Task.params["result"]` 回写（Phase 1 建的）可直接复用，前端已有点击后轮询任务状态的模式。
- 简历 `parsed_profile_json` 的类型见 `schemas_llm.ResumeProfile`（basic_info/education/work/projects/skills/certificates/self_summary），生成建议时把它摊平成文本供模型引用原文。
- 前端无 UI 库，页面由 `.card`/`table`/`.tag` 组成，详情卡片已在 Phase 1 实现，可直接在其下方追加建议区。

## 目标与非目标

- 目标：对任意一条已存在的匹配结果，产出一组可定位、可执行、可解释的简历修改建议，并显式标出"需要用户补充真实信息"的地方；重复生成不重复计费。
- 非目标：自动改写简历文件、成品导出、建议采纳状态、整份简历通用体检、多轮对话。

## 决策

### D1 建议绑定 `match_result_id`，用它做缓存键

- **Choice**：`suggestions` 加 `match_result_id`（FK → `match_results.id`）与 `resume_version`，唯一约束 `(user_id, match_result_id, resume_version)`；`generate()` 先查同键，命中直接返回，`force=True` 则删除旧行重生成。
- **Rationale**：建议的输入就是"这次打分的结论"，绑定 match 比绑定 (岗位, 简历) 更准确——重新打分（换权重/换模型）后旧建议理应失效，而 `match_result_id` 天然覆盖这点；简历升版本会重打分并产生新 match，也自动失效。
- **Alternatives**：按 `(resume_id, job_ref_type, job_ref_id)` 缓存（重新打分后仍复用旧建议，会与新的 gaps 打架）；不缓存（用户双击即双倍成本）。
- **Consequences**：同一匹配结果只有一条建议（可 force 覆盖）；历史建议不保留，若要"版本对比"将来另建表。

### D2 输出固定为"逐条建议 + 缺失关键词 + 防编造警告"

- **Choice**：`SuggestionPayload { suggestions: [{section, action, original, proposed, why, priority}], missing_keywords: [str], honesty_warnings: [str] }`；`action ∈ {改写, 新增, 删除, 补充关键词}`，`priority ∈ {high, medium, low}`（模型给的其它值统一降级为 medium）。
- **Rationale**：与方案 4.5 的字段一一对应；`section` 用 `ResumeProfile` 的字段名（`work[0].highlights` 这种下标路径也允许）便于前端定位与将来做"点建议跳字段"；优先级让用户先改关键项。
- **Alternatives**：自由 Markdown 建议（不可结构化、无法定位、无法统计）；只给 `missing_keywords`（等于没给改法）。
- **Consequences**：模型必须严格 JSON；建议条数上限 8 条（超出截断），避免一次生成过长导致成本失控。

### D3 防编造 = prompt 红线 + 确定性校验 + 显式警告三件套

- **Choice**：① system prompt 写明"只能基于简历原文与岗位要求；不得虚构公司/项目/学历/数字；无法证实的内容写进 honesty_warnings 而不是 proposed"；② 生成后用 `profile_text(profile)` 做确定性校验，`original` 非空但定位不到 → 追加 `honesty_warnings`（"建议 N 的原文未能在简历中定位，可能是模型改写，请核对"）；③ 前端把 `honesty_warnings` 用醒目样式单列，不与建议混排。
- **Rationale**：验收要求"人工抽查无编造经历"，纯靠 prompt 不可验证；②把"是否可追溯"变成可测断言（测试可直接喂一条定位不到的 original）。
- **Alternatives**：只靠 prompt（不可测）；二次 LLM 审核（再花一次钱且引入新幻觉）。
- **Consequences**：`original` 为空字符串的"新增"类建议不参与定位校验（新增本就没有原文），但必须给出 `why`。

### D4 只读建议，不回写简历

- **Choice**：生成结果只落 `suggestions`，不修改 `parsed_profile_json`、不生成文件、不提供"一键应用"。
- **Rationale**：方案明确"Phase 2 只输出建议清单，不做成品导出"；自动改写会让用户失去控制权，且改动简历原文需要版本管理（当前 `Resume.version` 只用于同名重传）。
- **Alternatives**：提供"应用建议"直接改画像（需要画像版本与回滚，超出本轮）。
- **Consequences**：用户需手动复制 `proposed`；后续若要"应用"，可在此 payload 上加 `applied_at` 字段。

### D5 手动触发，入口在匹配详情

- **Choice**：`POST /api/suggestions {match_id, force}` 入队后台任务；前端在 Phase 1 的匹配详情卡片里加按钮，生成期间 1.5s 轮询，完成后展示建议列表。
- **Rationale**：与 Phase 1"只做手动触发"的决策一致，成本由点击决定；一次生成只服务一个岗位，用户能立刻看到该岗位的改法。
- **Alternatives**：打分完成后自动生成（每次打分都多一次调用，成本翻倍）；独立"建议"页面（多一跳，且缺少岗位上下文）。
- **Consequences**：未打分就不能生成建议（404/400 提示先打分）。

## 风险与验证

- **R1 模型编造经历**：prompt 红线 + `original` 定位校验 + `honesty_warnings` 展示；验证：`tests/test_suggestions.py` 喂一条 `original` 不在简历里的建议，断言 payload 里出现警告。
- **R2 模型输出非 JSON/字段缺失**：`chat_structured` 已有校验重试；`SuggestionItem` 对 `priority`/`action` 做归一化，缺失字段给空串；建议条数 > 8 截断。验证：单测喂缺字段/超量 payload。
- **R3 建议与打分结论不一致**：prompt 里直接带上该次 `gaps`、`dimension_scores` 与 `verdict`，要求至少覆盖 gaps 的一半；验证：单测断言 prompt 文本包含 gaps 内容。
- **R4 并发重复生成**：唯一约束兜底，`IntegrityError` 回滚后回读已有行；验证：连续两次非 force 调用只留一行、只计一次调用。
