# Delta Spec: platform-core

## ADDED Requirements

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

## MODIFIED Requirements

无。

## REMOVED Requirements

无。
