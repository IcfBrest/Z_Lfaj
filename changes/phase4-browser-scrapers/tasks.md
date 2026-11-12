# Tasks: Phase 4 三家站点接入

- [x] 1 **分页契约与同步内核**：在 `app/scrapers/base.py` 增加 `iter_pages(source, limit)`，`sync.py` 改用它遍历，Phase 3 适配器行为不变。**Proof**：`pytest tests/test_scrapers.py -q` 旧用例全绿。
- [x] 2 **浏览器工具层**：新增 `app/scrapers/browser.py`（`BrowserConfig`、`BrowserUnavailable`、`open_page` 上下文管理器，延迟导入 playwright，默认 `channel=msedge`）。**Proof**：`import app.scrapers.browser` 在未安装 playwright 的环境也不报错（函数内延迟导入），缺失时抛 `BrowserUnavailable`。
- [x] 3 **字节跳动适配器**：`app/scrapers/bytedance.py`，用 `pages(limit)` 驱动浏览器翻页并拦截 `api/v1/search/job/posts`，`normalize` 映射标题/城市/部门/职责/要求/发布时间。**Proof**：单测用假采集器断言 limit 截断与归一化字段。
- [x] 4 **哔哩哔哩适配器**：`app/scrapers/bilibili.py`，先 GET csrf token 再带 `x-appkey/x-csrf/lunar-id/x-usertype/x-channel` 头 POST `positionList`，`normalize` 按「工作职责/任职要求」切段。**Proof**：单测断言两次请求顺序、请求头与归一化结果。
- [x] 5 **美团适配器**：`app/scrapers/meituan.py`，POST `getJobList`，`normalize` 映射 `jobDuty`/`jobRequirement`/`cityList`/`workYear`。**Proof**：单测断言请求 body 形状与归一化结果。
- [x] 6 **注册表与配置**：`SOURCE_NAMES` 扩到 5 个站点，`get_source` 支持三家；`config.py` 增加浏览器与三家 base URL 配置。**Proof**：`GET /api/admin/scrape/sources` 返回 5 个站点。
- [x] 7 **测试**：`backend/tests/test_scrapers.py` 增加三家归一化、分页契约、浏览器缺失、csrf 流程、limit 截断等用例。**Proof**：`pytest -q` 全绿且数量增加。
- [x] 8 **冒烟与文档**：冒烟桩增加 B站/美团响应，`smoke_e2e.py` 增加两家采集断言；README 与调研文档补 Phase 4 状态。**Proof**：`pwsh -File tools/smoke_run.ps1` 输出 `SMOKE OK`。

## 执行记录（2026-11-12）

- `cd backend && .venv\Scripts\python.exe -m pytest -q` → **95 passed, 97 warnings in 9.49s**（Phase 3 的 81 项 + 本阶段 14 项）。
- `cd frontend && npm run build` → **✓ built in 1.32s**（`Admin-DLepksec.js 5.55 kB`，多一个「需浏览器」标注）。
- `pwsh -NoProfile -File tools\smoke_run.ps1` → **SMOKE OK**：五站点在册、mihoyo created=3 / 次轮 unchanged=3、tencent 1+1、bilibili created=2（要求/加分项齐全、链路 `https://jobs.bilibili.com/social/positions/<id>`）、meituan created=2（`北京市、上海市` / `3-5年` / `数据/算法`）、字节在冒烟里为 0（浏览器不参与冒烟）。
- 真实站点抽查（2026-11-12，`backend/data/_live_phase4.py`）：B站 50 条/页、total=491（10 页）；美团 50 条/页、total=3382（68 页）；字节首页 10 条、`count=10000`（站内展示上限，实际按页翻）。归一化后职责/要求/加分项条数：B站 6/4/1、美团 5/6/0、字节 4/5/0，城市与部门字段均正确（美团「北京市、上海市」、字节「北京」/「职能 / 支持」）。

### 与计划的差异

1. **分类从「三家都 Playwright」改为「一家浏览器 + 两家纯 HTTP」**：实测 B站列表只要 csrf 三件套（`x-appkey/x-usertype/lunar-id`）、美团 `getJobList` 明文无鉴权，只有字节需要页面签名，因此只给字节接 Playwright，另外两家走现成的 `HttpClient`（更快、无浏览器依赖）。
2. **不再抓详情页**：三家列表响应都自带 JD 全文（字节 `description`/`requirement`、B站 `positionDescription`、美团 `jobDuty`/`jobRequirement`），`fetch_detail=False` 直接复用。
3. **`SourceAdapter` 协议新增可选分页入口**：适配器可以暴露 `pages(limit)`（浏览器驱动的自定义翻页），`sync_jobs` 通过 `iter_pages` 统一调度；没有该入口的适配器仍走 `list_page`，Phase 3 行为不变。
4. **字节分页选择器**：`.atsx-pagination-item[title='N']`，并先移除 `.hire-ai-assistant-guide-cn-*` 引导遮罩；找不到目标页直接结束本轮而不是报错。
5. **B站小标题**：计划写的是「工作职责/任职要求」，实测第二条是「工作要求」，`SECTION_MARKERS` 已补「工作要求」并把「加分项」归 `nice_to_have`。
6. **页面链接与 API 地址分离**：B站采集时 `base_url` 可被指向桩服务，但入库的 `source_url` 必须指真实站点，故 `BilibiliSource` 单独有 `site_url` 字段。
7. **冒烟里字节不跑**：需要本机 Edge，CI/无浏览器环境下跳过；`sources` 里以 `mode=browser` 标注，前端显示「需浏览器」。
8. **配置项命名**：`scraper_browser_channel/headless/timeout_ms/max_pages` + 三家 `*_base_url`（其中字节用 `bytedance_list_url` 指列表页）。