# Phase 3 设计：岗位采集

## 事实与约束（本机实测，2026-11-12）

- 米哈游列表 `POST https://ats.openout.mihoyo.com/ats-portal/v1/job/list`，body `{"pageNo": 1, "pageSize": 50, "channelDetailIds": [1], "hireType": 0}`；返回 `data.list[]`（`id`/`title`/`addressDetailList[].addressDetail`/`competencyType`/`jobNature`/`tagList`/`jobSummary`）与 `data.total`（当前 670）。`pageSize=50` 有效。
- 米哈游详情 `POST .../v1/job/info`，body 必须是 `{"id": "<jobId>", "channelDetailIds": [1, 2]}`（用 `jobId`/`channelDetailId` 会报 `职位id不可为空`/`职位渠道不可以为空`）；返回 `data.description`（职责）、`data.jobRequire`（要求）、`data.addition`（加分项）、`data.title`、`data.competencyType`、`data.jobNature`、`data.tagList`。
- 腾讯列表 `GET https://careers.tencent.com/tencentcareer/api/post/Query?keyword=&pageIndex=1&pageSize=50&language=zh-cn&area=cn`；返回 `Data.Count`（2168）与 `Data.Posts[]`（`PostId`/`RecruitPostName`/`LocationName`/`CategoryName`/`BGName`/`Responsibility`/`RequireWorkYearsName`/`PostURL`/`LastUpdateTime`）。列表已含职责摘要。
- 腾讯详情 `GET .../post/ByPostId?postId=<id>&language=zh-cn`；返回 `Data.Requirement`（要求全文）、`Data.Responsibility`、`Data.PostURL`。
- 两个接口都不需要签名与登录态；本机在关闭系统代理时直连 200，开启代理时反而 `Could not connect to server`。
- 现有 `job_postings` 无外部 id 列，只有 `source_url` 与 `content_hash`；`content_hash` 在手动导入侧=JD 文本哈希，采集侧将改为"归一化字段的规范化 JSON 哈希"。

## 目标与非目标

- 目标：一条命令/一次点击把两个站点的岗位全量同步进共享岗位库，且重复执行幂等；能识别下架；失败可观察。
- 非目标：不做调度、不做 Playwright、不做 LLM 结构化、不做多站点并发、不做增量游标。

## Decisions

### D1 去重键用 `external_id` + 唯一索引，而不是 `source_url`

- Choice：`job_postings` 新增 `external_id`（`String(128)`, nullable），加唯一索引 `(company_id, source_type, external_id)`；采集时按此 upsert。
- Rationale：米哈游的公开岗位页是 hash 路由，无法从接口拿到稳定可点的 URL，只能用 id 自行拼接（拼接规则一旦调整就会变）；腾讯的 `PostURL` 里也带 `postId`。把 id 作为真键、URL 作为展示字段，两者解耦后重跑不会因 URL 变化而重复插入。
- Alternatives：只用 `source_url`（米哈游拼错就全表重复）、只用 `content_hash`（正文小改就新增一条，岗位数会膨胀）。
- Consequences：手动导入的岗位 `external_id` 为 NULL，SQLite/PG 的唯一索引允许多个 NULL，互不冲突。

### D2 采集流程 = 列表分页 → 逐条详情 → 归一化 → upsert → 整轮后下架

- Choice：`sync_jobs()` 先翻完列表（受 `limit` 截断），再对每条抓详情（可关），逐条 upsert 并每 50 条 commit 一次；只有在**本轮未截断**（`limit is None`）时才做下架标记，且下架范围严格限定为 `company_id + source_type` 且 `id not in seen_ids`。
- Rationale：截断运行只用于调试，若此时也下架，会把没抓到的岗位误判为已下架。
- Alternatives：先写完再统一 diff（内存大、失败丢全部进度）；每条 commit（慢 3~5 倍）。
- Consequences：中途失败会留下部分更新，但下一轮会自然补齐；下架判定保守，宁可漏标不误标。

### D3 内容哈希覆盖"会展示的字段"，用规范化 JSON 计算

- Choice：`content_hash = sha256(json.dumps(record, sort_keys=True, ensure_ascii=False))`，record 只含 title/location/employment_type/department/experience_required/education_required/skills/responsibilities/requirements/nice_to_have/description_raw。
- Rationale：哈希只反映用户可见内容，`scraped_at` 之类的元数据不参与，避免每轮全量"更新"；字段顺序无关。
- Alternatives：哈希原始响应（噪声多，接口加字段就全量更新）。
- Consequences：接口新增字段不影响；字段语义变化需要人改代码。

### D4 限速与失败容忍都是"每请求"，不是"每轮"

- Choice：`HttpClient` 内置 `min_interval`（默认 1.0s，按站点可配）与最多 2 次重试（5xx/网络错误退避 1s、2s）；单条详情失败只累加 `failed` 并记录前 5 条错误，不中断整轮；整轮失败（首页就挂）才把任务标记 failed。
- Rationale：2900 岗总会遇到个别超时，整轮失败代价太大；1 秒间隔对 670+2168 岗约 47 分钟，属可接受后台时长。
- Alternatives：并发 + 指数退避（更快但更容易触发风控，且本阶段无收益）。
- Consequences：任务耗时较长，前端只能轮询，不能同步等待（已按后台任务实现）。

### D5 站点注册表 + 可配置 base URL

- Choice：`sources.py` 暴露 `SOURCES = {"mihoyo": MihoyoSource(), "tencent": TencentSource()}`，两站点类都从 `Settings` 读 `scraper_*_base_url`（默认官方地址）。
- Rationale：测试与冒烟可以指向本地假站点，不必联网、不必打桩到函数级；真实环境改环境变量即可切换。
- Alternatives：测试 monkeypatch 每个请求函数（脆弱、覆盖不到 URL 拼接）。
- Consequences：Settings 多 2 个字段；默认值与官方地址一致，行为不变。

### D6 采集只写共享岗位库，不碰用户私有岗位

- Choice：只写 `job_postings`，`source_type` 记 `mihoyo`/`tencent`；公司记录按名称 `get_or_create`（`career_url` 填官网）。
- Rationale：共享库是所有用户的匹配来源，私有岗位是用户自己粘的，两者语义不同。
- Alternatives：也写 `user_manual_jobs`（会让每个用户都看到重复岗位）。
- Consequences：用户删除私有岗位不影响采集数据；管理员可继续手动导入，两者共存。

## 风险与验证

| 风险 | 影响 | 验证方式 |
| --- | --- | --- |
| 站点接口改字段/改路径 | 采集任务 failed，岗位库停止增长 | `test_scrapers.py` 用真实响应样本做归一化断言；失败信息写进 `BackgroundTask.error`，前端可见 |
| 米哈游详情缺 `channelDetailIds` | 全部详情失败 | 已在真实接口实测出正确 body 形状（`{"id","channelDetailIds":[1,2]}`），写进代码注释与测试 |
| 唯一索引在已有数据上失败 | 迁移失败 | SQLite/PG 唯一索引允许多 NULL；`alembic downgrade` 回退验证 |
| 全量采集把 sqlite 写锁占满 | 前端其他请求 500ms 级抖动 | 每 50 条 commit + 单线程；冒烟用 `limit=5` 验证；真实全量由站长在低峰执行 |
| 系统代理导致 SSL 连接失败 | 本机采集全挂 | 客户端显式 `ProxyHandler({})`，与 `tools/smoke_e2e.py` 同一处理 |
