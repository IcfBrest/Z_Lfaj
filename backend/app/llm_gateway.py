"""统一 LLM 网关：provider 解析、结构化输出校验重试、按用户记账。

测试通过 monkeypatch `_invoke` 隔离底层 SDK；本模块不直接 import litellm，
在 _invoke 内部延迟导入，保证测试环境轻量。
"""

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from .config import get_settings
from .models import LlmCall, UserProvider, utcnow
from .security import decrypt_text

TASK_TYPES = ("parse", "score", "suggest")

_PREPARE_LOCK = threading.Lock()
_PREPARED = False


def prepare() -> None:
    """导入 litellm 并关掉会卡住进程的联网行为（幂等、异常不外抛）。

    litellm 首次导入要 4~7 秒，默认还会去 GitHub 拉模型价目表（本机 10 秒超时后
    才回落本地表），这段耗时若发生在请求线程里会把事件循环一起卡住——所以改由
    应用启动时预热，并用 LITELLM_LOCAL_MODEL_COST_MAP 直接走内置价目表。
    """
    global _PREPARED
    if _PREPARED:
        return
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    os.environ.setdefault("LITELLM_LOG", "ERROR")
    with _PREPARE_LOCK:
        if _PREPARED:
            return
        try:
            import litellm  # noqa: F401

            litellm.suppress_debug_info = True
        except Exception:  # noqa: BLE001 - 预热失败不影响后续按需导入
            return
        _PREPARED = True



@dataclass
class LlmResult:
    data: Any  # 已通过校验的结构化输出（dict）或纯文本
    attempts: int
    input_tokens: int
    output_tokens: int
    duration_ms: int


class LlmGatewayError(Exception):
    pass


class ProviderNotConfigured(LlmGatewayError):
    pass


def resolve_provider(db: Session, user_id: int | None, task_type: str) -> tuple[UserProvider | None, str]:
    """返回 (provider, model)。用户未配置时返回 (None, settings 默认模型)。"""
    settings = get_settings()
    fallback = {
        "parse": settings.default_parse_model,
        "score": settings.default_score_model,
        "suggest": settings.default_suggest_model,
    }.get(task_type, settings.default_parse_model)

    if user_id is None:
        return None, fallback

    providers = (
        db.query(UserProvider)
        .filter(UserProvider.user_id == user_id, UserProvider.enabled.is_(True))
        .all()
    )
    if not providers:
        return None, fallback
    provider = providers[0]
    model = (provider.task_models or {}).get(task_type) or provider.default_model or fallback
    return provider, model


def _invoke(provider: UserProvider | None, model: str, messages: list[dict]) -> dict:
    """底层调用。返回 {"content": str, "input_tokens": int, "output_tokens": int}。

    独立成函数便于测试打桩。生产路径走 LiteLLM 的 OpenAI 兼容入口。
    """
    prepare()
    from litellm import completion  # 延迟导入（正常的预热路径见 prepare）

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }
    if provider is not None:
        kwargs.update(
            api_key=decrypt_text(provider.api_key_encrypted),
            base_url=provider.base_url,
        )
    response = completion(**kwargs)
    usage = getattr(response, "usage", None)
    return {
        "content": response.choices[0].message.content or "",
        "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
    }


def _record(
    db: Session,
    user_id: int | None,
    task_type: str,
    provider: UserProvider | None,
    model: str,
    result: dict,
    duration_ms: int,
    status: str,
    error: str | None,
) -> None:
    db.add(
        LlmCall(
            user_id=user_id,
            task_type=task_type,
            provider_name=provider.name if provider else "default",
            model=model,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            cost_estimate=0.0,  # 价格表未配置前不估价，token 数已记录
            duration_ms=duration_ms,
            status=status,
            error=error,
        )
    )
    db.commit()


def chat_structured(
    db: Session,
    user_id: int | None,
    task_type: str,
    system_prompt: str,
    user_prompt: str,
    schema_model: type[BaseModel],
) -> LlmResult:
    """结构化调用：要求模型输出 JSON，本地 pydantic 校验；失败把错误拼回重试至多 N 次。"""
    provider, model = resolve_provider(db, user_id, task_type)
    settings = get_settings()
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    max_attempts = 1 + settings.llm_max_retries
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        try:
            raw = _invoke(provider, model, messages)
        except Exception as exc:  # 网络层/鉴权层错误也要记账
            duration_ms = int((time.monotonic() - started) * 1000)
            _record(db, user_id, task_type, provider, model, {}, duration_ms, "error", str(exc)[:500])
            raise LlmGatewayError(f"模型调用失败：{exc}") from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        content = raw["content"]
        try:
            data = _extract_json(content)
            validated = schema_model.model_validate(data)
            _record(
                db, user_id, task_type, provider, model, raw, duration_ms, "ok", None
            )
            return LlmResult(
                data=validated.model_dump(),
                attempts=attempt,
                input_tokens=raw["input_tokens"],
                output_tokens=raw["output_tokens"],
                duration_ms=duration_ms,
            )
        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            _record(
                db, user_id, task_type, provider, model, raw, duration_ms, "error", last_error[:500]
            )
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"你的上一条输出无法通过校验（{last_error}）。"
                        "请只输出一个符合要求的 JSON 对象，不要包含任何其他文字或代码块标记。"
                    ),
                }
            )

    raise LlmGatewayError(f"模型输出在 {max_attempts} 次尝试后仍未通过校验：{last_error}")


def _extract_json(content: str) -> Any:
    """容错解析：直接 loads，失败则截取首尾大括号之间的片段。"""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"输出中没有 JSON 对象：{content[:120]!r}")
        return json.loads(text[start : end + 1])
