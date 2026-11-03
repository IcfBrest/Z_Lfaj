# 本机联调工具

这两个脚本只用于本机端到端冒烟，不参与生产路径，也不被 `app/` 引用。

- `smoke_llm_stub.py`：最小 OpenAI 兼容桩（`POST /v1/chat/completions` 固定返回一份合法打分 JSON），监听 `127.0.0.1:8099`。
- `smoke_e2e.py`：真实跑 uvicorn + sqlite + litellm，走完「注册 → 配 provider → 全量打分 → 结果/成本/排序 → 改权重重算」。

用法（在 `backend/` 下）：

```powershell
$env:DATABASE_URL='sqlite:///./data/smoke-e2e.db'
$env:SECRET_KEY='smoke-secret-key-1234567890'
$env:ENCRYPTION_KEY='smoke-encryption-key-1234567890'
Remove-Item .\data\smoke-e2e.db -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m alembic upgrade head
Start-Process .\.venv\Scripts\python.exe -ArgumentList 'tools/smoke_llm_stub.py'
Start-Process .\.venv\Scripts\python.exe -ArgumentList '-m','uvicorn','app.main:app','--port','8098'
.\.venv\Scripts\python.exe tools\smoke_e2e.py    # 末尾打印 SMOKE OK
```

注意：`litellm` 首次调用会尝试联网拉取价格表，离线环境下会有 10~20s 延迟（失败后回落到本地备份，不影响结果）。
