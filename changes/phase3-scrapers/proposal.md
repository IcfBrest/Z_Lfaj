# Phase 3：岗位采集（米哈游 / 腾讯）

## Why

当前岗位库只有两条入口：管理员手动粘贴 JD、用户自己粘贴私有 JD。用户看到的共享岗位数取决于站长手工搬运，而米哈游（670 岗）与腾讯（2168 岗）两个站点的公开接口在本机实测可直接取到标题、城市、职责全文与要求全文。没有采集，匹配打分和建议环节都缺少真实数据，产品的核心链路无法被验证。

## What Changes

新增"岗位采集"能力：站长在管理后台点一次按钮，后台任务按站点分页抓取岗位列表与详情，写入平台共享岗位库（`job_postings`），按外部 id 去重、按内容哈希判断是否需要更新、整轮抓完后把已下架岗位标记为 `is_active=false`。

具体落点：

- `backend/app/scrapers/`：`base.py`（带重试与限速的 JSON 客户端）、`mihoyo.py`、`tencent.py`、`sync.py`（去重/更新/下架）、`sources.py`（站点注册表）。
- `job_postings` 增加 `external_id` 列与 `(company_id, source_type, external_id)` 唯一索引，作为稳定去重键。
- `POST /api/admin/scrape`（仅管理员）+ `GET /api/admin/scrape/sources`（各站点岗位数与最近同步时间）。
- `Admin.vue` 新增"岗位采集"卡片：选站点、可限条数、可选是否抓详情、执行并轮询进度。
- 测试与冒烟：新增 `tests/test_scrapers.py`；`tools/smoke_e2e.py` 增加本地假站点的采集段。

## Scope

**In**

- 米哈游：`POST https://ats.openout.mihoyo.com/ats-portal/v1/job/list`（分页 50）+ `POST /v1/job/info`（body `{"id": "<jobId>", "channelDetailIds": [1, 2]}`）。
- 腾讯：`GET https://careers.tencent.com/tencentcareer/api/post/Query`（分页 50）+ `GET .../post/ByPostId?postId=<id>&language=zh-cn`。
- 列表字段 + 详情全文（职责 / 要求 / 加分项），**不调用 LLM**，零模型成本。
- 去重、内容变更检测、下架标记、每轮统计（新增 / 更新 / 未变 / 下架 / 失败）。
- 管理员手动触发 + 后台任务 + 前端轮询；可限制条数（调试/分步采集）。

**Out**

- 字节 / B 站 / 美团（需要 Playwright 与登录态，属 Phase 4）。
- 定时自动采集（不引入调度器；站长点按钮即可）。
- 岗位详情页的 LLM 结构化解析（本阶段直接存原文，解析能力在导入侧已有，后续可复用）。
- 多站点并发抓取（串行执行，避免被风控）。
- 增量爬取策略（本阶段每轮全量对比哈希，2900 岗约 40 分钟以内可接受）。

## Impact

- 数据库：`job_postings` 加列 + 唯一索引（迁移 `d8a2e5f91c30`），现有行 `external_id` 为 NULL，不影响手动导入的岗位。
- 接口：新增 2 个管理员接口；`/api/jobs/shared` 返回的岗位数量将从此由采集决定，`match_id/match_score` 逻辑不变。
- 外部依赖：仅标准库 `urllib`，不引入 requests/httpx（与现有 LLM 网关一致，减少依赖面）。
- 风险：站点接口变更（失配时采集任务失败并记录 error，不影响其他功能）、被限流（默认每请求间隔 1 秒、串行、可配）。

## Proof

- `cd backend && .venv\Scripts\python.exe -m pytest -q` 全绿（新增采集用例覆盖归一化、去重、更新、下架、限速、鉴权）。
- 空库 `alembic upgrade head` 后 `job_postings` 含 `external_id` 且唯一索引存在；`alembic downgrade -1` 可回退。
- `pwsh -File tools/smoke_run.ps1` 在本地假站点上跑通一次采集：任务 done、`GET /api/jobs/shared` 出现采集来的岗位、重复执行第二轮全部"未变"且不重复插入。
- 真实站点一次小样本采集（`limit=5`）成功入库，`source_url` 可打开对应岗位页。
