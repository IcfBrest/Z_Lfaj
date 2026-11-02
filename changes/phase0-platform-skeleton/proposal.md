# 变更提案 — Phase 0：平台骨架 + 多用户 + 多模型 + 手动导入

> 来源：doc/求职平台调研方案.md（v2 终稿）五阶段路线图之 Phase 0。
> 授权：三轮 grilling 16 项决策共识（2026-10-15 用户确认"共识达成"）。

## 背景（Why）

求职是用户的当下刚需，而平台的差异化价值（官网岗位采集、人岗匹配打分、简历修改建议）全部依赖三类基础设施：多用户账号体系、可插拔的多模型网关、结构化解析管线。先把这些地基立起来，并用"手动粘贴 JD + 简历解析"这条最小闭环验证端到端可用，后续每一期的采集与匹配才能长在稳定地基上。同时刻意把技术上最不确定的爬虫排除在本期之外，使 Phase 0 零外部依赖风险、可独立验收。

## 变更内容（What Changes）

- 全新仓库落地（此前仅 doc/ 文档）：FastAPI 后端 + Vue 3 前端 + Docker Compose（web + postgres:16）+ Alembic 迁移。
- 新增多用户能力：邀请码注册（空库首用户免码并成为管理员）、JWT 登录、admin 角色守卫、用户/邀请码管理界面。
- 新增每用户模型接入：provider 配置（key 加密落库、仅掩码回显、连通性测试、按任务类型覆盖模型）。
- 新增 LLM 网关：统一结构化输出入口（JSON prompt + pydantic 校验 + 错误回喂重试 ≤2 次）、temperature=0、按用户记账（llm_calls）。
- 新增岗位手动导入：管理员建公司；粘贴 JD 后台解析入共享库或用户私有库；任务状态可查、失败可重试。
- 新增简历导入：PDF/DOCX/MD 本地抽取 + 两遍 LLM 解析（身份抽取→脱敏→Master Profile）；原文加密存储；版本化与 master 标记。

## 范围（Scope）

### 范围内（In Scope）

上述六项全部交付且通过 `pytest -q`（34 项）、空库 `alembic upgrade head`（12 表）、`npm run build`、真实 PG16 端到端冒烟（注册/邀请码/权限/公司/成本）。

### 范围外（Out of Scope）

匹配打分与自动排队（Phase 1）、修改建议（Phase 2）、米哈游/腾讯 HTTP 采集（Phase 3）、Playwright 采集（Phase 4）、Redis/arq 队列、简历成品导出、Ollama、向量检索、海外 ATS、移动端、邮件服务。扫描件 OCR 仅返回明确错误，不做识别。

## 风险（Risks）

| 风险 | 缓解 |
|------|------|
| 各家模型 json_schema 支持度不一 | 统一走"JSON prompt + 本地校验重试"，不依赖各家差异 |
| 扫描版 PDF 抽取为空 | 明确 400 错误引导换文件，OCR 留未来 |
| LiteLLM 版本漂移 | requirements 固定版本；网关单点收口 |
| 加密主密钥管理 | 仅存环境变量，不入库不入 git，README 注明备份要求 |
| greenfield 无 CI | 每任务以 pytest proof 收口，CI 随建仓另行变更 |

## 影响与验证

- **影响区域**：全仓库（新建 backend/、frontend/、docker-compose.yml、.env.example、README.md）；不改任何既有系统。
- **完成证明**：`cd backend && ./.venv/Scripts/python.exe -m pytest -q` 全绿；空库迁移 12 表；前端构建通过；proposal Acceptance 六条逐项有测试锚定（邀请码三态、首用户引导、provider 掩码与隔离、网关重试与记账、JD 双轨落表与重试、简历三格式与脱敏出站断言）。
