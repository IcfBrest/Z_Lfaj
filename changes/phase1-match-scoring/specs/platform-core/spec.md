# 能力规格 — platform-core（Phase 1 增量）

## ADDED Requirements

### Requirement: 匹配打分流水线

The system SHALL 以"硬规则过滤 → 粗排 → LLM 精排"三段式为人岗配对打分：硬过滤 MUST 零 token 且对被排除岗位给出可读理由；粗排 MUST 零 token 并只决定精排顺序；精排 MUST 经 `chat_structured`（temperature=0、JSON 校验、失败重试）产出四维分 `技能匹配`/`经验相关度`/`职级与薪资匹配`/`行业/业务匹配`、`verdict`、`reasons`、`matching_points`、`gaps`；总分 MUST 由代码按权重加权计算并 clamp 到 0~100，不得直接采用模型给出的总分。

#### Scenario: 硬门槛排除

- **WHEN** 岗位要求经验明确为 5 年而简历 `years_of_experience` 为 1，或岗位要求"硕士及以上"而简历最高学历为"本科"
- **THEN** 该岗位不进入精排，过滤结果含 `job_ref_type`/`job_ref_id`/`reason`，且该次运行不产生该岗位的 `llm_calls` 记录

#### Scenario: 字段无法解析时放行

- **WHEN** 岗位 `experience_required` 为"经验不限"或 `education_required` 为空
- **THEN** 该岗位不被硬规则排除，仍可进入后续排序

#### Scenario: 维度分越界与缺键

- **WHEN** 模型返回某维度 120 或缺少 `行业/业务匹配`
- **THEN** 该维度被 clamp 到 100，缺失维度按 0 计并在结果 `payload_json` 的 `missing_dimensions` 中列出，最终总分仍落在 0~100

### Requirement: 打分结果缓存与成本

The system SHALL 以 `(user_id, resume_id, job_ref_type, job_ref_id, resume_version)` 为缓存键：键相同的重复打分 MUST 直接返回既有结果且不产生新的 `llm_calls`；显式 `force=true` MUST 重算并覆盖旧结果；`resume_version` 变化 MUST 视为未命中。单轮运行 SHALL 支持 `limit`（默认 20）限定精排数量。

#### Scenario: 重复打分零成本

- **WHEN** 同一用户对同岗位连续两次非强制打分
- **THEN** 第二次不新增 `llm_calls` 记录，`match_results` 仍只有一行，分数相同

#### Scenario: 强制重算

- **WHEN** 用户以 `force=true` 再次打分
- **THEN** 新增一次 `llm_calls` 记录，`match_results` 该键的行被替换为新分数

#### Scenario: 简历升版本自动失效

- **WHEN** 用户删除并重新上传同名简历使 `resume_version` 增加后再打分
- **THEN** 旧版本结果不被复用，写入新版本的一行

### Requirement: 权重与推荐排序

The system SHALL 允许每个用户设置四维权重（每维 0~100，总和必须 > 0，未设置时按均等计），并 MUST 用同一套权重计算总分；岗位列表与匹配列表 SHALL 能按推荐分降序返回，未打分的岗位排在已打分的之后。

#### Scenario: 权重重算

- **WHEN** 用户把 `技能匹配` 权重设为 100、其余为 0
- **THEN** 该岗位总分等于 `技能匹配` 维度分（允许整数舍入误差 0）

#### Scenario: 非法权重

- **WHEN** 提交全 0 权重或某维为负
- **THEN** 返回 400，且用户既有权重保持不变

### Requirement: 匹配结果可见性

The system SHALL 提供匹配列表与详情接口，且 MUST 严格按 `user_id` 隔离：他人结果返回 404；列表项 SHALL 含岗位标题/公司/总分/verdict/四维分；详情 SHALL 含 `reasons`、`matching_points`、`gaps` 与岗位原文摘要。

#### Scenario: 用户隔离

- **WHEN** 用户 B 用用户 A 的匹配结果 id 请求详情或列表
- **THEN** 返回 404，B 的列表不包含 A 的结果
