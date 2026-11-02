# Design — Phase 0：平台骨架 + 多用户 + 多模型 + 手动导入

> 记录实现期实际落定的关键接口与决策（与代码一致，作为 bridging 评审锚点）。

## 模块边界与接口

```
app/
├── main.py            create_app()：路由装配 + CORS + /healthz
├── config.py          Settings（pydantic-settings，.env 加载，lru_cache）
├── db.py              Base/engine/SessionLocal/get_db（URL 驱动，sqlite 与 pg 双兼容）
├── models.py          ORM 12 表（含 Phase 1/2 预留表 match_results/suggestions）
├── security.py        hash_password/verify_password(scrypt)、create_jwt/decode_jwt、
│                      encrypt_text/decrypt_text(Fernet 主密钥派生)、mask_secret
├── llm_gateway.py     resolve_provider(db,user_id,task_type)->(provider,model)
│                      chat_structured(db,user_id,task_type,system,user,schema)->LlmResult
│                      _invoke(provider,model,messages)   ← 测试唯一切入点
│                      _record(...)                        llm_calls 记账
├── task_runner.py     enqueue(background_tasks,db,kind,user,runner,ref)/run_with_status
├── parsers.py         parse_jd（单遍）；extract_identity→mask_text→parse_resume_profile（两遍脱敏）
├── resume_extract.py  extract_text(bytes,format)：pdf(PyMuPDF)/docx(python-docx)/md
└── api/               deps(get_current_user/require_admin) + 8 个路由模块
```

## 关键决策

1. **同步 SQLAlchemy**（非 async）：个人规模足够，测试简单；后台解析用 FastAPI BackgroundTasks + BackgroundTask 状态表，Phase 1 换 arq 时 run_* 签名不变。
2. **测试缝合点**：唯一业务缝合点 = HTTP API（TestClient）；`llm_gateway._invoke` 为 LLM 边界桩位；不做 SiteAdapter（Phase 3 引入）。测试库 SQLite（全可移植类型），PG 由迁移+冒烟覆盖。
3. **密码** scrypt（stdlib，无第三方依赖）；**JWT** PyJWT HS256 7 天；**字段加密** Fernet，密钥=SHA256(ENCRYPTION_KEY) 派生，主密钥只存环境变量。
4. **provider 解析**：用户多 provider 取第一个启用的；模型 = task_models[task] > default_model > settings 分级默认。
5. **结构化输出**：不依赖各家 json_schema 能力，统一"JSON prompt + pydantic 校验 + 错误回喂重试（≤2）"，每次尝试（含失败）写 llm_calls。
6. **脱敏两遍法**：第一遍 LLM 抽身份（原文出站不可避免）→ 正则+精确替换掩码 → 第二遍结构化只见占位符；原文 Fernet 加密落库。
7. **引导规则**：空库首用户免邀请码注册并自动成为 admin（PG 外键下邀请码由 admin 创建，避免鸡生蛋；有回归测试）。
8. **岗位双表同构**：job_postings（共享）与 user_manual_jobs（私有）字段一致，match_results 用 job_ref_type/job_ref_id 多态引用，Phase 1 匹配逻辑对两者透明。
9. **Mimosa hook 交互**：ORM 参数化查询与测试假凭据的告警经人工核查为误报；源码类写入一律走 Write/Edit 工具配合扫描。
