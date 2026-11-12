# Design: Phase 4 三家站点接入

## 目标

在不改动 Phase 3 数据契约的前提下，把字节跳动（浏览器驱动）、哔哩哔哩（HTTP+csrf）、美团（HTTP 明文）三家接进现有采集链路，并且保持「缺浏览器依赖时其余站点照常可用」。

## 决策

### D1 分页契约：`pages(limit)` 生成器，`list_page` 保留为默认实现

`sync_jobs` 原先直接 `while page_no: source.list_page(page_no)`。浏览器驱动的站点无法「按页码随时取一页」——它必须在一个打开的浏览器会话里连续翻页。因此 `base.py` 新增：

```python
def iter_pages(source, limit=None) -> Iterator[tuple[int, list[dict], int]]:
    custom = getattr(source, "pages", None)
    if callable(custom):
        yield from custom(limit)
        return
    # 默认：沿用 list_page 逐页取，直到空页 / 不足一页 / 到达总数
```

`sync_jobs` 改为遍历 `iter_pages(source, limit)`，内部仍按 `limit` 截断、每 50 条提交、整轮结束才下架。**Phase 3 的两个适配器一行不改**，因为默认分支完全等价于原逻辑。

### D2 浏览器层：延迟导入 + 系统通道

`browser.py` 提供：

```python
class BrowserUnavailable(RuntimeError): ...

@dataclass
class BrowserConfig:
    channel: str = "msedge"      # 复用系统 Edge，免 playwright install
    headless: bool = True
    timeout_ms: int = 90_000

@contextmanager
def open_page(config: BrowserConfig) -> Iterator[Any]: ...
```

`playwright` 在 `open_page` 内部才 import；抛 `BrowserUnavailable` 时上层把任务标成 failed 并写「未安装 playwright（pip install playwright 并确保系统有 Edge/Chrome）」。这样服务器部署时不装浏览器也不影响米哈游/腾讯/B站/美团。

### D3 字节跳动：页面内翻页 + 拦截响应，绝不逆向签名

- 打开 `https://jobs.bytedance.com/experienced/position`，用 `page.expect_response` 捕获首屏的 `api/v1/search/job/posts`。
- 首屏有引导遮罩 `.hire-ai-assistant-guide-cn-mask` / `.hire-ai-assistant-guide-cn-feature` 拦截指针事件：先 `remove()` 掉，再用 `evaluate("el => el.click()")` 点分页项（`.atsx-pagination-item`，按可见文本匹配页码）。
- 每页 10 条，站内分页上限 1000 页；适配器默认 `max_pages=20`（200 条），并受 `limit` 约束。**不实现 `_signature` 计算**——签名由站点脚本生成，属于对方的反爬机制，逆向它既不必要也不合规。
- `data.job_post_list[]` 自带 `description`/`requirement`，因此 `fetch_detail=False`，`detail()` 直接返回空。

### D4 哔哩哔哩：一次 csrf + 复用 HttpClient

- `GET /api/auth/v1/csrf/token`（带 `x-appkey: ops.ehr-api.auth`、`x-usertype: 2`、`lunar-id: lunar-<ms>-<rand>`）→ `data` 即 csrf 值。
- 之后所有请求带 `x-csrf`、`x-appkey`、`x-usertype`、`x-channel: social`、`lunar-id`。
- `POST /api/srs/position/positionList`，body `{"pageSize":50,"pageNum":N,"positionName":"","postCode":[],…,"recruitType":0,…}`，响应 `data.{list,pages,size,total}`；`pageSize=50` 实测有效（491 条 / 10 页）。
- `HttpClient` 增加 `http.cookiejar` 支持：站点在 csrf 请求里下发 `buvid3` 等 cookie，带上是更接近真实浏览器的行为，也避免个别环境校验。

### D5 美团：明文 POST

`POST /api/official/job/getJobList`，body 固定骨架 + `page.{pageNo,pageSize}`；`pageSize=50`、`totalCount≈3379`、`totalPage=68`。响应 `data.{list,page}`，条目含 `jobUnionId`/`name`/`jobFamily`/`jobFamilyGroup`/`cityList[].name`/`jobDuty`/`jobRequirement`/`workYear`。

### D6 归一化：正文拆分与字段映射

三家的正文都是「小标题 + 若干条」的自由文本，统一用 `base.split_sections(text, markers)` 按小标题切段：

- 字节：`description` → responsibilities，`requirement` → requirements；`city_info.name` 或 `city_list[].name` 取城市；`job_category.name` 当部门；`recruit_type` 映射全职/实习。
- B站：`positionDescription` 里含「工作职责:」「任职要求:」两个小标题，切段后分别填 responsibilities/requirements；`workLocation`、`postCodeName`、`positionTypeName`、`pushTime`。
- 美团：`jobDuty`（含「岗位职责」）、`jobRequirement`（含「岗位要求」）同样切段；城市 `cityList[].name` 用「、」连接（去掉末尾「市」不做，保留站点原文）；`workYear` → `experience_required`。

`description_raw` 保留原始全文，`source_url` 用各站详情路由（字节 `…/experienced/position/<id>/detail`、B站 `…/social/positions/<id>`、美团 `…/web/position/detail?jobUnionId=<id>`）。

## 测试策略

- `iter_pages` 默认分支：Phase 3 现有 19 项测试继续保证。
- 新适配器用**录制的真实响应片段**（精简到 2~3 条）做归一化断言，不联网。
- 字节的浏览器部分抽成 `_collect` 注入点：测试里替换成假采集器，断言 `limit` 截断、`page_size` 判断、`normalize` 结果。
- B站测两次请求顺序（先 csrf 后 list）与请求头；美团测 body 形状与分页参数。
- 冒烟：B站/美团走本地桩（模拟响应），字节跳过（浏览器不可在 CI/冒烟环境稳定运行），由单测的假采集器覆盖。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 字节页面结构改版导致选择器失效 | 选择器集中在模块常量里；失败时任务记录可读错误，不影响其他站点 |
| 浏览器启动慢/内存高 | 每次采集只开一个浏览器、采完即关；默认限制页数 |
| B站 csrf 失效或换算法 | 每轮采集重新取 token；失败退回「本轮无数据」并记录错误 |
| 美团接口加签名 | 适配器只依赖 URL+body，改版时集中改一处 |
