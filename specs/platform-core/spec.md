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

### Requirement: 管理员可触发站点采集

系统 MUST 允许管理员按站点触发岗位采集任务；非管理员 MUST 被拒绝。

#### Scenario: 管理员触发米哈游采集

- **WHEN** 管理员向 `POST /api/admin/scrape` 提交 `{"source": "mihoyo"}` 且当前没有冲突运行
- **THEN** 接口返回 202 与 `task_id`，后台开始分页抓取列表与详情，任务结束时 `task.result` 含 `created/updated/unchanged/deactivated/failed` 计数

#### Scenario: 普通用户触发被拒绝

- **WHEN** 非管理员用户调用 `POST /api/admin/scrape`
- **THEN** 返回 403，且不创建任务、不发出任何外部请求

#### Scenario: 未知站点被拒绝

- **WHEN** 管理员提交 `{"source": "bytedance"}`
- **THEN** 返回 400，错误信息列出可用站点

### Requirement: 采集幂等且能识别内容变更

系统 MUST 以站点外部 id 去重；同一岗位二次采集 MUST 不新增行，内容变化时 MUST 更新同一行。

#### Scenario: 重复采集不重复插入

- **WHEN** 对同一批岗位连续执行两轮采集，第二轮岗位内容未变
- **THEN** `job_postings` 行数不变，第二轮结果 `created=0` 且 `unchanged` 等于岗位数

#### Scenario: 内容变化被更新

- **WHEN** 岗位标题或职责在站点侧发生变化后再次采集
- **THEN** 同一 `external_id` 的行被更新，`content_hash` 变化，`updated` 计数加一，行数不增加

#### Scenario: 外部 id 为空的手动岗位不受影响

- **WHEN** 库中已存在管理员手动导入（`external_id` 为 NULL）的岗位，随后执行采集
- **THEN** 手动岗位保持原样，采集只新增/更新自己来源的岗位

### Requirement: 采集后标记已下架岗位

系统 MUST 在未截断的完整一轮采集结束后，把该站点本轮未出现的岗位标记为 `is_active=false`；截断运行 MUST NOT 下架任何岗位。

#### Scenario: 完整采集标记下架

- **WHEN** 某岗位在上一轮存在、本轮列表不再返回，且本轮为完整采集
- **THEN** 该岗位 `is_active` 变为 false，`deactivated` 计数加一

#### Scenario: 截断采集不下架

- **WHEN** 以 `limit=5` 执行采集
- **THEN** 未出现在前 5 条中的既有岗位保持 `is_active=true`

### Requirement: 采集结果进入共享岗位库并可被匹配

系统 MUST 把采集到的岗位写入平台共享岗位库，带来源标记与可点击的原始链接，且管理员可查看各站点岗位规模与最近同步情况。

#### Scenario: 采集后的岗位出现在共享列表

- **WHEN** 采集成功入库后用户访问 `GET /api/jobs/shared`
- **THEN** 返回的岗位包含新采集的标题/城市/职责/要求，`source_type` 为 `mihoyo` 或 `tencent`，`source_url` 非空

#### Scenario: 采集岗位可被匹配打分

- **WHEN** 用户对共享岗位执行 `POST /api/matches/run`
- **THEN** 采集来的岗位参与硬规则过滤与打分，与手动导入的岗位行为一致

#### Scenario: 管理员查看站点概况

- **WHEN** 管理员访问 `GET /api/admin/scrape/sources`
- **THEN** 返回每个站点的 `active_jobs`、`total_jobs` 与 `last_scraped_at`（无采集记录时为空）

### Requirement: 采集器支持浏览器驱动站点

系统 SHALL 允许管理员为需要浏览器渲染或带动态签名的站点（如字节跳动）触发采集：后台任务启动无头浏览器打开站点列表页，通过页面内翻页并拦截接口响应取得岗位数据，按「最多抓几条」与站点默认页数上限截断。

#### Scenario: 字节跳动采集成功

- **WHEN** 管理员以 `source=bytedance`、`limit=20` 触发采集
- **THEN** 后台任务以 done 结束，`params.result` 中 `created` 与站点返回条数一致（20 以内），且岗位标题、城市、职责、要求写入共享库

#### Scenario: 浏览器不可用

- **WHEN** 运行环境未安装 `playwright` 或浏览器启动失败
- **THEN** 该次采集任务以 failed 结束并写入可读错误（提示安装 playwright 或检查浏览器），其他站点的采集不受影响

### Requirement: 采集器支持免鉴权明文接口站点

系统 SHALL 为提供明文列表接口的站点（哔哩哔哩、美团）提供纯 HTTP 采集路径：哔哩哔哩先取 csrf token 再带鉴权头请求列表，美团直接以固定 body 分页请求，二者都不需要启动浏览器。

#### Scenario: 哔哩哔哩采集成功

- **WHEN** 管理员以 `source=bilibili` 触发采集
- **THEN** 系统先请求 csrf token，再分页请求岗位列表（每页 50 条），把岗位入库，并且不启动浏览器

#### Scenario: 美团采集成功

- **WHEN** 管理员以 `source=meituan`、`limit=100` 触发采集
- **THEN** 系统以 `pageSize=50` 分页请求，入库不超过 100 条岗位，`params.result.total` 为站点声明的总条数

### Requirement: 新增站点复用既有幂等与下架规则

三家新增站点 SHALL 复用 Phase 3 的去重键（公司 + 站点 + 外部 id）、内容哈希与「整轮采集后标记下架」规则：同一岗位重复采集不产生新行，标题或正文变化记为 updated，完整一轮未出现的岗位标记为下架。

#### Scenario: 重复采集幂等

- **WHEN** 对同一站点连续执行两次完整采集
- **THEN** 第二次结果为 `created=0`、`unchanged=N`，共享库总行数不变

#### Scenario: 完整一轮后下架

- **WHEN** 某站点完整一轮采集中某岗位不再出现（未使用 limit 截断）
- **THEN** 该岗位被标记为下架，且不出现在共享岗位库的默认列表里

### Requirement: 一键投递并快照岗位信息

系统 SHALL 允许用户对共享岗位库或私有手动岗位一键创建投递记录：记录归属当前用户，自动快照公司名、岗位标题、地点与岗位链接，并在已有匹配结论时快照当时的匹配分。

#### Scenario: 从共享岗位库投递

- **WHEN** 用户对某个共享岗位提交投递
- **THEN** 系统创建一条 `status=applied` 的投递记录，返回该岗位的标题、公司名与匹配分（若有），并记录投递时间

#### Scenario: 重复投递

- **WHEN** 同一用户对同一岗位再次提交投递
- **THEN** 系统返回 409 与已有记录 id，不创建重复行

#### Scenario: 跨用户隔离

- **WHEN** 用户 A 查询或修改用户 B 的投递记录
- **THEN** 系统返回 404，不泄露记录是否存在

### Requirement: 投递状态按固定阶段推进

系统 SHALL 以 `applied → written_test → interview → offer` 为主链路，`rejected`、`withdrawn` 为终止态；非终止态之间允许跳跃，终止态不可再变更；每次状态变化追加一条时间线事件。

#### Scenario: 推进阶段

- **WHEN** 用户把投递从 `applied` 推进到 `interview`（跳过笔试）
- **THEN** 记录状态变为 `interview`，时间线新增一条 `applied → interview` 事件，最近活动时间刷新

#### Scenario: 终止态保护

- **WHEN** 用户对已经是 `rejected` 的记录请求修改状态
- **THEN** 系统返回 400 并说明终止态不可变更，记录保持原状

#### Scenario: 非法状态

- **WHEN** 用户提交不在枚举内的状态值
- **THEN** 系统返回 400 并列出可用状态

### Requirement: 投递进展可见并标出停滞

系统 SHALL 提供投递列表与统计：列表按最近活动排序，为每条非终止态记录给出「距上次活动天数」，并把 ≥ 7 天未更新的标为停滞；统计返回各状态计数与停滞数。

#### Scenario: 停滞标记

- **WHEN** 某条投递处于 `interview` 且已 10 天未更新
- **THEN** 列表中该记录的 `days_since_update=10` 且 `is_stale=true`

#### Scenario: 按状态筛选

- **WHEN** 用户按 `status=offer` 筛选
- **THEN** 只返回该用户处于 `offer` 状态的记录，统计保持全量口径
