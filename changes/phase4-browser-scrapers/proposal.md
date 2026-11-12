# Proposal: Phase 4 三家站点接入（字节 / B站 / 美团）

## Why

Phase 3 打通了「适配器 → 归一化 → 幂等入库 → 后台任务 → 管理页」的采集链路，但只接了米哈游和腾讯两家。用户在方案里列出的第一梯队还有字节跳动、哔哩哔哩、美团；其中：

- **字节跳动**的岗位列表接口带 `_signature`，签名由页面 JS 现算，直接 HTTP 请求被拒（405/空）。只有让浏览器打开真实页面、由页面自己发请求，才能拿到数据。
- **哔哩哔哩**的接口要求 `x-csrf` + `lunar-id` + `x-appkey` 头，走纯 HTTP 就能满足（已实测 491 条/10 页）。
- **美团**的 `getJobList` 是完全明文的无鉴权 POST（已实测 3379 条/68 页）。

也就是说 Phase 4 需要一次性引入「浏览器驱动」这一层，同时把「浏览器不是必需」的站点继续用 HTTP 采，避免为了一个站点把整条链路拖进重依赖。

## What Changes

- 新增分页契约 `pages(limit)`：`sync_jobs` 通过统一迭代器取数据，适配器可以覆盖它来走浏览器翻页。
- 新增浏览器工具层 `backend/app/scrapers/browser.py`：延迟导入 `playwright`，复用系统 Edge 通道，缺依赖时抛可读异常而不是让服务起不来。
- 新增三个适配器：`bytedance`（浏览器驱动）、`bilibili`（HTTP + csrf 头）、`meituan`（HTTP 明文 POST）。
- `sources.SOURCE_NAMES` 扩到 5 个站点；管理页的站点卡片自动多出三行（前端无需改动）。
- 新增配置：浏览器通道/无头模式/最大页数，三家站点的 base URL，便于测试与冒烟指向本地桩。

## Impact

- 受影响代码：`app/scrapers/{base,sync,sources,browser,bytedance,bilibili,meituan}.py`、`app/config.py`、`app/api/scrape.py`（文案与可用站点）、`tests/test_scrapers.py`、`tools/smoke_*.py|ps1`。
- 新增运行时依赖：`playwright`（仅浏览器驱动站点用到，缺失时其他站点照常工作）。
- 数据模型不变（沿用 `job_postings.external_id` + 内容哈希 + 整轮下架）。
- 风险：字节站内每页 10 条、上限 1000 页，全量约需较长时间；用「最多抓几条」与默认 `max_pages` 双重约束，避免一次误触发把任务跑成几小时。

## Scope

**In**：三家站点适配器、浏览器工具层、分页契约、配置项、单元测试、冒烟覆盖（B站/美团走桩，字节用假浏览器）、文档与任务记录。
**Out**：定时调度、并发采集、登录态采集、字节/B站/美团的详情页二次抓取（列表已含 JD 正文）、前端新的采集交互。
