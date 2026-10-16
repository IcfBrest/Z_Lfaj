# Tasks — Phase 0：平台骨架 + 多用户 + 多模型 + 手动导入

> 按序执行；每任务以 proof 为完成标准。验证命令：`pytest -q`（backend）。

- [x] 1 **仓库与骨架**：backend/（FastAPI + SQLAlchemy + Alembic，应用工厂、配置加载、/healthz）；frontend/（Vue 3 + Vite 骨架、路由与 API client 雏形）；docker-compose.yml（web + postgres:16）；.env.example（DB 连接、加密主密钥、JWT 密钥、默认模型分配）。**Proof**：compose 起后 `GET /healthz` 200；空库 `alembic upgrade head` 成功；`npm run build` 通过。
- [x] 2 **数据模型（Phase 0 全集）**：users（is_admin、invited_by_code）、invitation_codes（一次性、可作废）、user_providers（api_key_encrypted、按任务类型默认模型）、companies、job_postings（content_hash、source_type）、user_manual_jobs、resumes（版本化、is_master、parsed_profile_json、原文加密）、llm_calls（记账全集）；共享岗与私有岗字段同构。**Proof**：迁移空库/带库均可执行；pytest 模型写读往返一致。
- [x] 3 **认证与邀请码**：邀请码注册（未用/未作废校验，注册即消耗并记 used_by）；登录发 JWT；admin 依赖守卫；管理员重置用户密码。**Proof**：pytest — 正常注册；同一邀请码二次使用拒绝；作废邀请码拒绝；登录换有效 token；非 admin 调管理接口 403。
- [x] 4 **管理界面基础（API+页面）**：admin API（用户列表/禁用、邀请码生成/列表/作废）；前端管理页两块。**Proof**：API pytest 含权限矩阵；页面手动走查。
- [x] 5 **provider 配置与连通性**：user_providers CRUD（仅本人）；api_key Fernet 加密落库、接口永回掩码；连通性测试端点（最小 chat 探测，返回成功/失败与延迟）；按任务类型默认模型配置。**Proof**：pytest — 掩码断言（响应不含完整 key）；非本人 403；连通性 mock 上游验证成败两分支。
- [x] 6 **LLM 网关**：统一 `chat(messages, model, json_schema)`（LiteLLM，OpenAI 兼容）；JSON 校验失败把错误拼回重试至多 2 次；temperature=0；每次调用（含失败）写 llm_calls（tokens/耗时/预估成本）。**Proof**：pytest（mock SDK）— 好响应直返；坏 JSON 两次后第三次成功；三次全坏报错且 llm_calls 留痕；记账字段完整。
- [x] 7 **岗位手动导入**：管理员建公司；"粘贴 JD"端点（admin→共享 job_postings，普通用户→user_manual_jobs，source_type=manual）；应用内后台任务执行解析→统一 Schema→入库；任务状态可查、失败可重试。**Proof**：pytest（mock LLM 夹具）— 两类落表正确；失败留可读错误且重试后成功；content_hash 生成。
- [x] 8 **简历上传与解析**：上传 PDF/DOCX/MD（类型/大小限制）；本地抽取（PyMuPDF/python-docx/直读，空文本明确报错）；LLM 结构化 Master Profile；版本化 + is_master 唯一；脱敏（出站消息身份字段占位符化、原文 Fernet 加密存储）。**Proof**：pytest — 三种格式夹具解析成功；空文本报错分支；脱敏断言（mock 收到的消息不含真实姓名/手机号）；is_master 唯一性；用户隔离（B 读 A 403/404）。
- [x] 9 **前端最小页面集**：登录/注册（邀请码）；设置页（provider CRUD + 连通性测试 + 本人成本汇总）；公司/岗位列表（粘贴导入 + 任务状态轮询）；简历管理（上传/查看解析/设 master）。**Proof**：`npm run build` 通过 + 全流程手动走查。
- [x] 10 **收尾整验**：全量 `pytest -q`；alembic 空库重建；前端 build；对照 proposal Acceptance 逐条核对。**Proof**：验证命令全绿；Acceptance 清单逐项打勾记录。
