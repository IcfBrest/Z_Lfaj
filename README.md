# AI 求职助手平台

多用户 AI 求职工作台：公司官网岗位采集（规划中）→ 岗位库 → 简历结构化 → 人岗匹配打分 → 简历修改建议。

当前进度：**Phase 1 完成**（骨架 + 多用户 + 多模型 + 手动导入 + 人岗匹配打分）。下一步是 Phase 2 简历修改建议。路线图与全部设计决策见 [doc/求职平台调研方案.md](doc/求职平台调研方案.md)。

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
6. 「岗位」页点「给当前简历批量打分」：先硬规则过滤（经验差 >2 年、学历不够，附排除理由），再按关键词粗排取前 20，最后 LLM 四维打分 + 代码加权；列表显示推荐分并可查看维度分/理由/缺口。单岗也可单独打分，结果按 (简历版本, 岗位) 缓存。
7. 「设置」页调整四维权重（技能匹配/经验相关度/职级与薪资匹配/行业业务匹配），保存后可按新权重重算全部分数。

## 安全基线

- 用户密码 scrypt 散列；JWT 会话（7 天）。
- API Key 与简历原文用 Fernet 加密落库（主密钥来自 `ENCRYPTION_KEY` 环境变量，不入库不入 git，**请备份**）。
- LLM 出站消息脱敏；任何接口不回显完整 Key。
- 数据隔离：简历/私有岗位/调用记录仅本人可见（有权限测试覆盖）。

## 目录

```
backend/    FastAPI + SQLAlchemy + Alembic（app/ 源码，tests/ 55 项测试，tools/ 本机联调冒烟脚本）
frontend/   Vue 3 + Vite（登录/岗位/简历/设置/管理五页）
doc/        调研方案（v2 终稿）与 spec-superflow 变更工件
changes/    spec-superflow 工作流状态（phase0 已收尾，phase1-match-scoring 进行中）
```
