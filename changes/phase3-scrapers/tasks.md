# Tasks — Phase 3：岗位采集

> 按序执行；每任务以 Proof 为完成标准。后端验证：`cd backend && .venv\Scripts\python.exe -m pytest -q`；前端验证：`cd frontend && npm run build`。
> 触发方式已确认：**管理后台手动按钮**；深度已确认：**列表字段 + 详情全文，不调用 LLM**。

- [x] 1 **数据模型与迁移**：`backend/app/models.py` 的 `JobPosting` 增加 `external_id`（`String(128)`, nullable）与唯一索引 `(company_id, source_type, external_id)`；新增 `backend/alembic/versions/d8a2e5f91c30_phase3_external_id.py`（`down_revision="c3f7a1d29b84"`，sqlite 用 `batch_alter_table`，downgrade 可回退）。**Proof**：空库 `alembic upgrade head` 后 `PRAGMA index_list('job_postings')` 含唯一索引，`downgrade -1` 干净回退；既有 62 项测试不回归。

- [x] 2 **采集客户端与站点注册表**：`backend/app/scrapers/base.py` 提供 `HttpError`、`fetch_json()`（`urllib` + `ProxyHandler({})`、超时、最多 2 次退避重试、按站点最小间隔限速）、`SourceAdapter` 协议；`backend/app/scrapers/sources.py` 暴露 `SOURCES`/`get_source()`；`backend/app/config.py` 增 `scraper_timeout_seconds`/`scraper_retries`/`scraper_min_interval`/`mihoyo_base_url`/`tencent_base_url`。**Proof**：`tests/test_scrapers.py` 覆盖 500 重试后抛错、请求间隔不小于 `min_interval`、未知站点 KeyError。

- [x] 3 **两个站点适配器**：`backend/app/scrapers/mihoyo.py`（列表 body `{"pageNo","pageSize","channelDetailIds":[1],"hireType":0}`；详情 body `{"id","channelDetailIds":[1,2]}`，取 `description`/`jobRequire`/`addition`）、`backend/app/scrapers/tencent.py`（`Query` + `ByPostId`，取 `Requirement`/`Responsibility`），统一产出字段字典（external_id/title/location/department/employment_type/experience_required/education_required/skills/responsibilities/requirements/nice_to_have/description_raw/source_url/source_type）。**Proof**：用真实响应样本断言两站点归一化字段齐全、`source_url` 非空、职责与要求按换行拆成列表。

- [x] 4 **同步内核 `backend/app/scrapers/sync.py`**：`sync_jobs(db, source, *, limit=None, fetch_detail=True, progress=None) -> dict`；按 `(company_id, source_type, external_id)` upsert，内容哈希变化才算 `updated`，每 50 条 commit，完整一轮才下架未出现岗位，单条详情失败计入 `failed` 不中断。**Proof**：`tests/test_scrapers.py` 覆盖首轮 4 条新增、次轮全 unchanged、改标题后 updated=1 且行数不变、`limit=5` 不下架、详情失败仍入库且有 failed 计数。

- [x] 5 **管理员接口与任务接线**：`backend/app/api/scrape.py` 提供 `POST /api/admin/scrape`（source 校验、`require_admin`、`enqueue("company_scrape", ...)`）与 `GET /api/admin/scrape/sources`（各站点 active/total/last_scraped_at）；`backend/app/api/tasks.py` 补 `company_scrape` 重试映射；`backend/app/main.py` 挂载。**Proof**：`tests/test_scrapers.py` 覆盖普通用户 403、未知站点 400、任务 result 五计数、sources 概况字段。

- [x] 6 **管理页采集卡片**：`frontend/src/views/Admin.vue` 增加站点选择（米哈游/腾讯/全部）、条数输入（空=全量）、是否抓详情、执行按钮、1.5s 轮询与五个计数展示、站点概况表。**Proof**：`npm run build` 通过。

- [x] 7 **端到端冒烟**：新增 `backend/tools/smoke_scrape_stub.py`（本地假站点，按路径返回米哈游/腾讯形状的列表与详情），`tools/smoke_e2e.py` 加采集段（入队 → 轮询 → 断言 created=4 → 第二轮 unchanged=4 → `/api/jobs/shared` 出现采集岗位），`tools/smoke_run.ps1` 起桩并把 `MIHOYO_BASE_URL`/`TENCENT_BASE_URL` 指向它。**Proof**：脚本输出 `SCRAPE OK`。

- [x] 8 **收尾整验**：全量 `pytest -q`、空库 `alembic upgrade head` + `downgrade -1`、`npm run build`；更新 `README.md`（Phase 3 完成、使用步骤、测试数）与 `doc/求职平台调研方案.md`（Phase 3 标记完成 + 实现说明）；`ssf sync` + 评审 + complete。**Proof**：三条命令全绿 + 文档与代码一致 + 工作流 closing。

## 执行记录（2026-11-12）

- `cd backend && .venv\Scripts\python.exe -m pytest -q` → **81 passed**（原 62 + 新增 19）。
- 迁移：空库 `alembic upgrade head` 后 `job_postings.external_id` 存在、`PRAGMA index_list` 含唯一索引 `uq_job_postings_source_external`；`downgrade -1` 后列与索引均消失。
- `cd frontend && npm run build` 通过（Admin 页 5.44 kB）。
- `pwsh -File tools\smoke_run.ps1` → **SMOKE OK**：米哈游首轮 created=3，次轮 unchanged=3；腾讯 limit=1 不下架、全量跑 created=1+unchanged=1；`/api/jobs/shared` 出现采集岗位且详情含【职责】/【要求】与岗位页链接；采集后再跑匹配 scored=5。
- 真实站点抽查（2026-11-12）：米哈游 total=668、腾讯 total=2164，各取首条跑通「列表 → 详情 → 归一化」，字段齐全。

### 与计划的差异

1. 注册表导出名用 `SOURCE_NAMES`（元组）+ `get_source()`，并非 `SOURCES` 字典（与原计划的命名出入，语义一致）。
2. 单测覆盖同步时用 2 条岗位（等价于计划里的 4 条），断言项一致：首轮新增、次轮 unchanged、改标题 updated=1、limit 不下架、详情失败仍入库。
3. 管理页没有「站点选择/全部」复合控件，改为每行站点一个「同步」按钮 + 全局「最多抓几条」与「只抓列表」开关（更少误操作；`POST /api/admin/scrape` 仍支持单站点参数）。
4. 冒烟输出用分段断言 + 末尾 `SMOKE OK`（沿用既有脚本风格），没有单独的 `SCRAPE OK` 行。
5. 修了两处实现期发现的 bug：① `split_lines` 的项目符号常量误写成元组，`str.strip(tuple)` 直接 `TypeError`（测试先暴露）；② `_upsert` 建新行时只写哈希字段，导致 `source_url` 永远为空——拆出 `PERSIST_FIELDS = HASH_FIELDS + ("source_url",)`，并在 unchanged 分支顺手刷新链接。
6. 腾讯「十年以上/二十五年」这类中文数字改为正则抓「…年」前的数字串再转换（原实现逐字替换，会把「二十五」拆成「2十五」）。
