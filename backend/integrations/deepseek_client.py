"""DeepSeek 客户端（仅服务端调用）。

职责边界：
  · 只负责「把消息发出去、把 JSON 拿回来、把失败翻译成可降级的 IntegrationError」；
  · 不做任何业务判断（枚举修正、禁寄补全在 packaging_rules.py）；
  · 不落库、不碰 Flask request 上下文 —— 便于离线单测直接替换 HTTP 层。

安全红线（docs/api-innovations.md §1.4）：
  · DEEPSEEK_API_KEY 只从环境变量读，**永不**出现在响应/日志/异常文案里；
  · 任何需要打印请求头的地方一律走 mask_secret()，输出 `sk-***`。

容错策略（§1.4）：
  · 单次超时 DEEPSEEK_TIMEOUT（默认 8s），最多重试 DEEPSEEK_MAX_RETRY（默认 2）次；
  · **只对**超时 / 5xx / 429 重试；4xx 参数类错误重试没有意义，直接降级。
"""
import json
import logging
import os
import socket
import urllib.error
import urllib.request

from .errors import IntegrationError

log = logging.getLogger("integrations.deepseek")

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 8.0
DEFAULT_MAX_RETRY = 2

# 供单测替换的 HTTP 函数：签名 (url, payload_dict, headers_dict, timeout) -> dict
# 生产实现见 _http_post_json；单测直接 monkeypatch 本模块属性即可全离线。
_HTTP_POST = None


def _env_float(name, default):
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return v if v > 0 else default


def _env_int(name, default):
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return v if v >= 0 else default


def load_config():
    """从环境变量读配置（每次调用都重读，便于测试用 monkeypatch 改环境变量）。"""
    return {
        "api_key": (os.getenv("DEEPSEEK_API_KEY") or "").strip(),
        "base_url": ((os.getenv("DEEPSEEK_BASE_URL") or "").strip() or DEFAULT_BASE_URL).rstrip("/"),
        "model": (os.getenv("DEEPSEEK_MODEL") or "").strip() or DEFAULT_MODEL,
        "timeout": _env_float("DEEPSEEK_TIMEOUT", DEFAULT_TIMEOUT),
        "max_retry": _env_int("DEEPSEEK_MAX_RETRY", DEFAULT_MAX_RETRY),
        "enabled": (os.getenv("AI_ENABLED", "1") or "1").strip() != "0",
    }


def configured():
    """服务端是否具备可用的 AI 调用条件（只回布尔，**绝不回 Key**）。"""
    cfg = load_config()
    return bool(cfg["enabled"] and cfg["api_key"])


def mode():
    """当前实际生效模式：'deepseek' 或 'rule'。"""
    return "deepseek" if configured() else "rule"


def mask_secret(value, keep=0):
    """把密钥脱敏成 `sk-***` 形态，用于日志。

    只保留可辨识前缀（默认不保留任何字符），长度本身也不泄漏。
    """
    s = str(value or "")
    if not s:
        return ""
    prefix = s[:keep] if keep > 0 else ""
    return f"{prefix}***" if keep > 0 else "***"


def _http_post_json(url, payload, headers, timeout):
    """真实 HTTP 调用（POST JSON）。返回解析后的 dict。

    仅在 _HTTP_POST 未被替换时使用；任何网络层问题都翻译为 IntegrationError。
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定域名)
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _post(url, payload, headers, timeout):
    fn = _HTTP_POST or _http_post_json
    return fn(url, payload, headers, timeout)


def _classify_error(exc):
    """把 urllib / socket 异常翻译成 (中文原因, retryable, status)。"""
    if isinstance(exc, urllib.error.HTTPError):
        code = int(getattr(exc, "code", 0) or 0)
        retryable = code == 429 or 500 <= code <= 599
        return f"上游错误 HTTP {code}", retryable, code
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "调用超时", True, None
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "调用超时", True, None
        return "网络不可达", True, None
    return "上游调用失败", False, None


def complete(messages, *, response_format=None, temperature=0.2):
    """调用 DeepSeek chat completions，返回助手消息的 content 字符串。

    失败一律抛 IntegrationError；永不返回 None，也永不把 Key 写进异常。
    """
    cfg = load_config()
    if not cfg["enabled"]:
        raise IntegrationError("AI 功能已被 AI_ENABLED=0 关闭")
    if not cfg["api_key"]:
        raise IntegrationError("未配置 DEEPSEEK_API_KEY")

    url = f"{cfg['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Accept": "application/json",
    }
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if response_format:
        payload["response_format"] = response_format

    attempts = cfg["max_retry"] + 1
    last = IntegrationError("上游调用失败")
    for i in range(attempts):
        try:
            data = _post(url, payload, headers, cfg["timeout"])
        except IntegrationError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 统一翻译，绝不冒泡成 500
            reason, retryable, status = _classify_error(exc)
            last = IntegrationError(reason, retryable=retryable, status=status)
            # 日志只记原因与序号，绝不记 headers / payload 里的敏感内容
            log.warning("deepseek 调用失败（第 %s/%s 次）：%s", i + 1, attempts, reason)
            if retryable and i < attempts - 1:
                continue
            raise last from None

        if not isinstance(data, dict):
            raise IntegrationError("返回结构校验失败")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise IntegrationError("返回结构校验失败")
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = (msg or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise IntegrationError("返回结构校验失败")
        return content.strip()

    raise last


def _strip_fence(text):
    """剥掉模型偶尔自带的 ```json / ``` 围栏。"""
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    s = s[3:]
    if s.lstrip().lower().startswith("json"):
        s = s.lstrip()[4:]
    end = s.rfind("```")
    if end >= 0:
        s = s[:end]
    return s.strip()


def complete_json(messages, *, temperature=0.2):
    """要求模型返回 JSON 对象；解析失败即为「返回结构校验失败」→ 上层降级。"""
    content = complete(
        messages,
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    try:
        data = json.loads(_strip_fence(content))
    except (ValueError, TypeError):
        raise IntegrationError("返回结构校验失败") from None
    if not isinstance(data, dict):
        raise IntegrationError("返回结构校验失败")
    return data
