# AI 求职助手平台

多用户 AI 求职工作台：公司官网岗位采集（规划中）→ 岗位库 → 简历结构化 → 人岗匹配打分 → 简历修改建议。

当前进度：**Phase 0 完成**（骨架 + 多用户 + 多模型 + 手动导入）。路线图与全部设计决策见 [doc/求职平台调研方案.md](doc/求职平台调研方案.md)。

## 本机开发

```bash
# 后端（Python 3.13+）
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Windows Git Bash
cp ../.env.example .env                              # 填 ENCRYPTION_KEY（Fernet 生成命令见文件内注释）
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload

# 前端（Node 20+）
cd frontend
npm install
npm run dev    # http://localhost:5173，已代理 /api 到 8000

# 测试
cd backend && .venv/Scripts/python -m pytest -q
```

生产部署用 `docker compose up -d`（web + postgres:16，web 容器自动执行 alembic 迁移）。

## 首次使用

1. 注册第一个账号（**空库首个用户免邀请码并自动成为管理员**——邀请码由管理员创建，避免鸡生蛋）。
2. 管理员在「管理」页生成邀请码 → 朋友凭码注册。
3. 每人在「设置」页配置自己的模型 Provider（DeepSeek/Kimi/GLM/Qwen 等 OpenAI 兼容接口，Key 加密存储、仅显示掩码）。
4. 「岗位」页粘贴 JD → 后台解析入库（管理员可选入共享库，普通用户为私有岗位）。
5. 「简历」页上传 PDF/DOCX/MD → 本地抽取 + LLM 结构化；**脱敏默认开启**（姓名/手机号/邮箱出站前替换为占位符，原文加密存储）。

## 安全基线

- 用户密码 scrypt 散列；JWT 会话（7 天）。
- API Key 与简历原文用 Fernet 加密落库（主密钥来自 `ENCRYPTION_KEY` 环境变量，不入库不入 git，**请备份**）。
- LLM 出站消息脱敏；任何接口不回显完整 Key。
- 数据隔离：简历/私有岗位/调用记录仅本人可见（有权限测试覆盖）。

## 目录

```
backend/    FastAPI + SQLAlchemy + Alembic（app/ 源码，tests/ 34 项测试）
frontend/   Vue 3 + Vite（登录/岗位/简历/设置/管理五页）
doc/        调研方案（v2 终稿）与 spec-superflow 变更工件
changes/    spec-superflow 工作流状态（phase0-platform-skeleton）
```
