# platform-core

## Purpose

建立平台的第一块能力基线：多用户账号体系、每用户模型接入、统一 LLM 网关、岗位手动导入与简历脱敏解析。这是后续采集（Phase 3/4）与匹配打分（Phase 1）共同依赖的地基。

## Requirements

### Requirement: 邀请码注册与认证

The system SHALL 支持邀请码制注册与 JWT 登录：空库首个注册用户免邀请码并自动成为管理员；此后注册必须凭有效一次性邀请码；已使用或已作废的邀请码 SHALL 被拒绝；管理员 SHALL 能生成/作废邀请码、列出用户、禁用/启用账号、重置密码；非管理员访问管理接口 SHALL 返回 403。

#### Scenario: 首用户引导

- **WHEN** 平台用户表为空且用户提交不含邀请码的注册
- **THEN** 注册成功且该用户 is_admin=true；此后无邀请码注册返回 400

#### Scenario: 邀请码一次性

- **WHEN** 同一邀请码被用于第二次注册，或该码已被作废
- **THEN** 注册返回 400 且错误信息指明"已使用"或"已作废"

### Requirement: 每用户模型接入

The system SHALL 允许每个用户配置多个 OpenAI 兼容 provider；api_key SHALL 以 Fernet 加密落库且任何 API 响应只出现掩码；provider 仅本人可读/改/删；更新时回传掩码 SHALL 不覆盖已存 key；连通性测试 SHALL 返回成败与延迟并记入调用账本。

#### Scenario: key 永不回显

- **WHEN** 创建、列表或更新 provider
- **THEN** 所有响应体中不出现完整 key，仅 `前4位***` 掩码

#### Scenario: 用户隔离

- **WHEN** 用户 B 以任何接口访问用户 A 的 provider
- **THEN** 返回 404，且 B 的列表为空

### Requirement: 统一 LLM 网关

The system SHALL 经 chat_structured 完成所有结构化调用：temperature=0、JSON 输出经 pydantic 校验、失败把校验错误回喂重试至多 2 次、三次全败抛可读错误；每次尝试（含失败）SHALL 写入 llm_calls（user/task_type/provider/model/tokens/耗时/状态）；未配置 provider 时 SHALL 回退 settings 分级默认模型。

#### Scenario: 坏输出恢复

- **WHEN** 模型第一次返回非 JSON、第二次返回合法 JSON
- **THEN** 调用成功且 attempts=2，账本含一条 error 与一条 ok 记录

#### Scenario: 三次全败

- **WHEN** 模型连续三次输出均无法通过校验
- **THEN** 抛出含"3 次尝试"的可读错误，账本留三条 error 记录

### Requirement: 岗位手动导入

The system SHALL 支持粘贴 JD 后台解析：admin 指定公司入共享 job_postings、否则入用户私有 user_manual_jobs；两表字段同构（统一岗位 Schema）、source_type=manual、content_hash=SHA256(原文)；任务状态 pending/running/done/failed 可查，failed 保留可读错误且可重试成功。

#### Scenario: 双轨落表

- **WHEN** admin 带 company_id 提交、普通用户不带提交
- **THEN** 前者入 job_postings 且按公司可查，后者入 user_manual_jobs 仅本人可查

#### Scenario: 失败重试

- **WHEN** 解析任务失败后调用 retry 且模型恢复
- **THEN** 任务变 done，岗位字段与夹具一致，content_hash 为 64 位十六进制

### Requirement: 简历导入与脱敏解析

The system SHALL 支持 PDF/DOCX/MD 上传（≤10MB）与零 token 本地抽取；空文本（扫描件）返回 400 明确错误；解析 SHALL 两遍执行：身份抽取（原文出站）→ 掩码（手机/身份证/邮箱正则 + 姓名精确替换）→ 结构化 Master Profile；原文 SHALL Fernet 加密落库；同名版本递增；每用户至多一个 is_master 且可切换；简历及解析结果仅本人可读；可删除。

#### Scenario: 出站脱敏

- **WHEN** 上传含真实姓名/手机号/邮箱的简历并解析
- **THEN** 结构化那遍出站消息不含真实身份值，且含 __NAME__/__PHONE__/__EMAIL__ 占位符

#### Scenario: master 唯一

- **WHEN** 用户上传第二份简历后将第二份设为 master
- **THEN** 全局恰好一份 is_master=true 且指向第二份

### Requirement: 成本记账

The system SHALL 提供 llm_calls 按用户记录与汇总接口（按 task_type+model 聚合次数/输入输出 token/耗时），用户只能看到自己的数据。

#### Scenario: 汇总隔离

- **WHEN** 用户 B 查询成本汇总
- **THEN** 仅返回 B 自己的调用聚合，不出现 A 的任何记录

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
