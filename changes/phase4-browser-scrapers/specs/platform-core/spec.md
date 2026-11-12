# Delta Spec: platform-core

## ADDED Requirements

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
