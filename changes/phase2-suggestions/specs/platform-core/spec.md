# 能力规格 — platform-core（Phase 2 增量）

## ADDED Requirements

### Requirement: 按岗位生成简历修改建议

The system SHALL 以一条已存在的匹配结果为输入生成简历修改建议，且 MUST 复用该次匹配的 `gaps`/`dimension_scores`/`verdict` 与岗位要求，不得重新解析简历或重新打分；输出 MUST 是结构化的逐条建议，每条形如 `{section, action, original, proposed, why, priority}`，并附带 `missing_keywords` 与 `honesty_warnings`；`section` MUST 指向简历画像中的具体字段（允许 `work[0].highlights` 这类下标路径），`priority` MUST 归一化为 `high`/`medium`/`low`。

#### Scenario: 生成建议

- **WHEN** 用户对一条已有匹配结果发起生成请求
- **THEN** 系统在后台产出 N 条（1 ≤ N ≤ 8）建议并落库，返回的任务完成后可经 API 读到建议列表，每条形如 `{section, action, original, proposed, why, priority}`，且 `missing_keywords` 至少覆盖该次 `gaps` 中出现的技能词

#### Scenario: 未打分不得生成

- **WHEN** 请求的 `match_id` 不存在或属于其他用户
- **THEN** 返回 404；简历未解析完成或没有匹配结果时返回 404 而非空建议

### Requirement: 防编造与可定位

The system SHALL 要求建议只有两类：改写既有事实（此时 `original` MUST 能在简历原文中定位）或补充岗位关键词；模型输出的任何无法追溯到简历原文的事实 MUST 进入 `honesty_warnings` 而不是 `proposed`。系统 MUST 对 `original` 非空的建议做确定性定位校验，定位不到时自动追加一条 `honesty_warnings`。

#### Scenario: 原文不可定位

- **WHEN** 模型给出的建议 `original` 为"负责某万亿级流量平台"，但简历原文中不存在该表述
- **THEN** 该条建议仍返回，但 `honesty_warnings` 中出现"建议 N 的原文未能在简历中定位，请核对"一类的提示

#### Scenario: 需要用户补充事实

- **WHEN** 岗位要求 Kafka 而简历完全没有相关经历
- **THEN** 建议 MUST 表述为"如有 Kafka 实际经验请补充"，并同时给出 `honesty_warnings` 提醒不得虚构，而不是直接编造一条 Kafka 经历

### Requirement: 建议缓存与隔离

The system SHALL 以 `(user_id, match_result_id, resume_version)` 作为建议缓存键：键相同的重复请求 MUST 返回既有建议且不产生新的 `llm_calls`；`force=true` MUST 重算并覆盖；建议列表与详情 MUST 严格按 `user_id` 隔离，他人建议返回 404。

#### Scenario: 重复生成零成本

- **WHEN** 同一用户对同一匹配结果连续两次非强制生成
- **THEN** 第二次不新增 `llm_calls`，`suggestions` 仍只有一行，返回的 `suggestion_id` 与首次相同

#### Scenario: 强制重算

- **WHEN** 用户以 `force=true` 再次生成
- **THEN** 新增一次 `llm_calls` 记录，该匹配结果的建议内容被替换

#### Scenario: 用户隔离

- **WHEN** 用户 B 用用户 A 的建议 id 请求详情或按 A 的 `match_id` 列表
- **THEN** 返回 404 或空列表，B 永远看不到 A 的建议内容
