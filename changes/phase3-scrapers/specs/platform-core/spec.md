# Phase 3 规格增补：岗位采集

## ADDED Requirements

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
