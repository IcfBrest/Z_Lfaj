# 设计 — Phase 1：匹配打分闭环

## 事实与约束

- 岗位两表同构：共享 `job_postings`（admin 维护）与私有 `user_manual_jobs`（用户自粘），匹配结果用 `job_ref_type`/`job_ref_id` 多态引用（Phase 0 已定，`MatchResult` 已建表且带 `UNIQUE(user_id, resume_id, job_ref_type, job_ref_id, resume_version)`）。
- `llm_gateway.chat_structured(db, user_id, task_type, system_prompt, user_prompt, schema_model)` 已实现 temperature=0、pydantic 校验、失败回喂重试至多 2 次、每次尝试写 `llm_calls`；`TASK_TYPES` 含 `score`，`settings.default_score_model` 已存在。测试通过 monkeypatch `_invoke` 隔离网络。
- `task_runner.enqueue/run_with_status` 提供应用内后台任务（pending→running→done/failed，失败留可读错误并可经 `/api/tasks/{id}/retry` 重试）；Phase 1 不引入 arq/Redis。
- 简历以 `parsed_profile_json`（Master Profile）+ `version` 存储；`is_master` 保证每人一份。
- 岗位的经验/学历字段是自然语言字符串（`experience_required`、`education_required`），只有部分能稳定解析。
- 前端为 Vue 3 + 手写 `api.js`，无第三方 UI 库，页面由 `.card`/`table`/`tag` 组成。

## 目标与非目标

- 目标：给定一份简历和岗位库，产出可解释的 0~100 推荐分，岗位列表可按推荐排序、可看四维明细；重复打分零成本；新岗位可自动进入打分；权重可按用户调整。
- 非目标：向量/embedding 检索、跨用户共享打分结果（按用户隔离）、增量学习的排序模型、自动投递。

## 决策

### D1 三段式流水线：硬规则 → 粗排 → 精排

- **Choice**：`scoring.filter_jobs()`（零 token，排除项带 reason）→ `scoring.rank_candidates()`（关键词重叠分）→ `scoring.score_one()`（LLM）。
- **Rationale**：方案 4.4 明确要求该分层；硬规则与粗排把 LLM 调用量压到可控范围（默认每轮最多 20 个候选），符合"单用户 50 岗 < ¥1"的成本目标。
- **Alternatives**：直接全量精排（成本线性增长，50 岗即 50 次调用且无法解释"为什么没推荐"）；只做规则匹配（无解释力，跨行业失效）。
- **Consequences**：硬规则会误杀一部分本可投递的岗位，因此仅在双方字段都能稳定解析时才过滤（见 R1）。

### D2 维度分由 LLM 给、总分由代码加权

- **Choice**：LLM 只输出四维分（`技能匹配`/`经验相关度`/`职级与薪资匹配`/`行业/业务匹配`）+ 理由/匹配点/缺口；`total = round(Σ(dim × w) / Σw)` 在 `scoring.combine()` 计算，clamp 到 0~100。
- **Rationale**：跨模型更稳定，权重调整无需重新调用 LLM（改权重后可本地重算已有维度分）。
- **Alternatives**：让 LLM 直接给总分（换模型即漂移，且权重无法事后调整）。
- **Consequences**：LLM 输出的维度分需 clamp（`max(0, min(100, v))`），缺维度按 0 计并在 payload 标 `missing_dimensions`。

### D3 缓存 = 唯一约束 + 显式 force

- **Choice**：`score_one(force=False)` 先按 `(user_id, resume_id, job_ref_type, job_ref_id, resume_version)` 查已有结果，命中直接返回；`force=True` 删除旧行重算。转义任务不写缓存。
- **Rationale**：唯一约束已在 Phase 0 建好，天然是幂等键；简历升版本（`resume_version`）自动失效。
- **Alternatives**：另建 `match_cache` 表按内容 hash（重复存储，且岗位 JD 变更后无法感知——当前 `content_hash` 变更未实现，暂不做）。
- **Consequences**：岗位 JD 被重新解析后分数不会自动失效；Phase 3 引入 `content_hash` 变更检测时再加"JD 哈希"到缓存键。

### D4 权重存 `users.score_weights`，空值即均等

- **Choice**：`users.score_weights` 为 JSON（四维 → 非负数值），`null`/`{}` 解释为 25/25/25/25；API `PUT /api/matches/weights` 校验每维 0~100 且和 > 0。
- **Rationale**：权重是用户偏好，放 `users` 表最省事；不需要新表与额外 join。
- **Alternatives**：`settings` 全局配置（多用户下不可调）；每次打分请求都传权重（前端要持久化，等于再造一张表）。
- **Consequences**：改权重后历史分数按旧权重重算过；提供 `POST /api/matches/recompute`（同 run + force）让用户主动刷新。

### D5 只做手动触发，不做自动入队（用户 2026-11-03 决定）

- **Choice**：打分只由显式请求触发（全量 `POST /api/matches/run`、单岗、按新权重重算）；`job_parse` 完成后不自动排队。
- **Rationale**：用户选择"只做手动打分，不做自动打分"，把 LLM 成本完全交给点击行为；自动入队需要再引入开关列与额外的任务编排，收益（少点一次）不抵复杂度。
- **Alternatives**：解析完成自动入队 + `users.auto_score` 开关（多一列、多一条任务链，成本不可控）。
- **Consequences**：新导入的岗位在用户点"打分"前没有推荐分，岗位页需明确展示"未打分"状态；后续若要自动打分，可在此 API 上加钩子而不改内核。

### D6 粗排 = 技能重叠 + 标题词 + 地点，None 值不惩罚

- **Choice**：`rank_candidates` 计算 `skill_overlap = |简历skills ∩ 岗位skills| / max(1, |岗位skills|)`、`title_hit`（简历工作/项目标题词是否出现在岗位标题）、`location_hit`，加权求和后降序，取 `limit`（默认 20）。
- **Rationale**：零成本、可解释、无外部依赖；对中文岗位文本，字符级子串匹配已足够区分相关性。
- **Alternatives**：jieba 分词（新增依赖且需词典）；SQLite FTS5（跨 PG 不可移植）。
- **Consequences**：粗排只决定"先给谁花钱"，不产生用户可见分数。

### D7 维度键与 Schema 固定为四个中文键

- **Choice**：`scoring.DIMENSIONS = ("技能匹配", "经验相关度", "职级与薪资匹配", "行业/业务匹配")`，`schemas_llm.MatchScore` 用 `dict[str, int]` 接收并用常量校验额外键（多出的丢、缺的记 0）。
- **Rationale**：中文键直接对应方案 4.4 的 rubric，前端无需映射表；`dict` 比 `TypedDict` 更能容错模型多余输出。
- **Alternatives**：英文键 + 前端映射（多一层易错映射）；`Literal` 严格校验（模型偶发改写键名即整次失败）。
- **Consequences**：键名变更需同步 `DIMENSIONS`、前端标签与既有 `payload_json`。

## 风险与验证

- **R1 硬规则误杀**：`experience_required`（如"3-5年"）与 `education_required`（如"本科及以上"）是自由文本。缓解：只在能解析出明确数值/等级时比较；经验差阈值 2 年、学历按 大专<本科<硕士<博士 映射，映射失败即放行。验证：`tests/test_scoring.py` 覆盖"无法解析不过滤"。
- **R2 LLM 输出维度分越界/缺键**：`combine()` clamp + `missing_dimensions` 记录；验证：单测直接喂 120/-5/缺键。
- **R3 全量打分成本**：一次全量默认只精排 `limit=20` 个候选（其余留待下次或调大 limit）；验证：`test_matches.py` 断言候选超过 limit 时只调用 limit 次。
- **R4 后台任务并发写库**：`run_with_status` 每次新开 Session，`MatchResult` 唯一约束兜底重复插入（捕获 IntegrityError 后回读）。验证：`test_scoring.py` 对同一岗连续调用两次只留一行。
