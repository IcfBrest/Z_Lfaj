# Proposal — Phase 0：平台骨架 + 多用户 + 多模型 + 手动导入

> 来源：doc/求职平台调研方案.md（v2 终稿）五阶段路线图之 Phase 0。
> 授权：三轮 grilling 16 项决策共识（2026-10-15 用户确认"共识达成"）。

## Scope

在空仓库（greenfield，当前仅有 doc/）搭建平台第一块可运行增量：**不含采集、不含匹配打分**的最小多用户系统。

1. **项目骨架**：FastAPI（Python 3.12+，SQLAlchemy + Alembic）+ Vue 3 + Vite 前端 + Docker Compose（web + postgres 16）；`.env.example`；本机开发可跑。
2. **认证与多用户**：users / invitation_codes 表；邀请码注册（一次性、可作废、复用拒绝）→ JWT 登录；admin 角色守卫；管理界面基础（用户列表 + 邀请码生成/作废）。
3. **模型接入（每用户自带 key）**：user_providers CRUD（key 服务端加密落库、任何接口不回显明文、一键连通性测试）；按任务类型（解析/精排/建议）配置默认模型。
4. **LLM 网关**：统一 `chat(messages, model, json_schema)` 入口（LiteLLM 底座，OpenAI 兼容）；结构化输出失败时把校验错误喂回重试至多 2 次；每次调用写 llm_calls（按用户记 token 与预估成本）；temperature=0。
5. **岗位手动导入**：companies 表（管理员手动建公司）；粘贴 JD 文本 → 后台任务解析 → 入库（管理员导入进共享 job_postings，普通用户进私有 user_manual_jobs）；解析失败状态可见可重试；岗位统一 Schema（见调研方案 4.2）。
6. **简历导入与解析**：上传 PDF/DOCX/Markdown → 本地文本抽取（PyMuPDF/pdfplumber/python-docx）→ LLM 结构化为 Master Profile（basic_info/education/work/projects/skills/certificates/self_summary）→ 版本化存储 + is_master 标记；**脱敏模式**：姓名/手机号/身份证在出站调用前替换为占位符，原文字段本地加密存储。
7. **前端页面（最小集）**：登录/注册（邀请码）、设置（provider 管理 + 成本面板雏形）、公司/岗位列表（含粘贴导入入口）、简历管理（上传/查看解析结果/设 master）。

## Acceptance

- 两个账号各自配置不同 provider key，互不可见。
- 粘贴 5 个真实 JD 文本，全部解析为规范结构化数据入库（字段完整、source_type=manual）。
- 上传真实 PDF 与 DOCX 简历各 1 份，解析出的结构化字段准确（人工抽查：教育/工作经历/技能无遗漏错位）。
- 已使用或已作废的邀请码注册被拒绝；非 admin 访问管理接口返回 403。
- 用户 A 无法通过任何 API 读取用户 B 的简历、私有岗位、解析结果（隔离测试）。
- API 响应中 key 永为掩码；开启脱敏后，发往 LLM 的请求体不含真实姓名/手机号（断言于测试）。
- `pytest -q` 全绿；`alembic upgrade head` 从空库可重复执行；前端 `npm run build` 通过。

## Risks

| 风险 | 缓解 |
|------|------|
| 各家模型 json_schema 支持度不一 | 网关统一走"JSON prompt 约束 + 本地校验重试"路径，不依赖各家 schema 能力差异 |
| 扫描版/图片型 PDF 解析出空文本 | 抽取结果为空时报明确错误引导换文件；OCR 留未来（out of scope） |
| LiteLLM 版本兼容漂移 | requirements 固定版本；网关收口在一处，升级影响面可控 |
| 加密密钥管理（DB 加密用的主密钥） | 主密钥放 .env（服务端环境变量），不入库不入 git；文档注明备份要求 |
| greenfield 无 CI | 本地 pytest 为每任务的 proof；仓库建好后补 CI（另行 change） |

## Out of Scope

匹配打分与自动排队（Phase 1）、修改建议（Phase 2）、米哈游/腾讯 HTTP 采集（Phase 3）、Playwright 采集（Phase 4）、Redis/arq 队列（Phase 1 随批量打分引入，本期解析用应用内后台任务）、简历成品导出、Ollama、向量检索、海外 ATS、移动端、邮件服务。
