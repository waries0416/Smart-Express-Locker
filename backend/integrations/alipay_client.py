# 支付宝沙箱客户端（RSA2 签名 / 验签 / 下单参数）
#
# 范围说明（docs/api-innovations.md §4.0）：
#   · 默认 PAYMENT_PROVIDER=mock，本模块**只在真实沙箱模式**下被调用；
#   · 缺任一凭据时 available() 为 False，payment.py 自动回落 mock 并置 degraded，
#     绝不尝试真实扣款；
#   · 本模块只做「密码学 + 参数拼装」，不落库、不判断业务幂等（在 payment.py）。
#
# 安全红线：
#   · ALIPAY_PRIVATE_KEY / ALIPAY_PUBLIC_KEY 只从环境变量读，
#     永不出现在响应、日志、异常文案里；本模块对外只暴露 available() 布尔。
#   · 验签失败一律返回 False，不抛异常给调用方（回调要稳定返回 fail 文本）。
#
# 为什么用 cryptography 而不是 pycryptodome：
#   前者是本项目环境已装且是纯 Python 包（含 Rust 轮子），Windows 无需编译；
#   后者需要额外安装 Crypto。若两者都不可用，签名功能降级为 unavailable，
#   由 payment.py 回落 mock —— 绝不静默"跳过验签"。
import base64
import logging
import os

from .errors import IntegrationError

log = logging.getLogger("integrations.alipay")

SANDBOX_GATEWAY = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
PROD_GATEWAY = "https://openapi.alipay.com/gateway.do"

# 参与验签时**必须排除**的字段（支付宝文档：sign 与 sign_type 不参与签名）
SIGN_EXCLUDE = ("sign", "sign_type")

# 供单测替换：真实环境下由 _load_private_key/_load_public_key 提供
_KEY_BACKEND = None


def _env(name, default=""):
    return (os.getenv(name) or "").strip() or default


def load_config():
    cfg = {
        "app_id": _env("ALIPAY_APP_ID"),
        "private_key": _env("ALIPAY_PRIVATE_KEY"),
        "public_key": _env("ALIPAY_PUBLIC_KEY"),
        "sandbox": _env("ALIPAY_SANDBOX", "1") != "0",
        "notify_url": _env("ALIPAY_NOTIFY_URL"),
    }
    gateway = _env("ALIPAY_GATEWAY")
    cfg["gateway"] = gateway or (SANDBOX_GATEWAY if cfg["sandbox"] else PROD_GATEWAY)
    return cfg


def available():
    """真实沙箱模式是否就绪：三件凭据齐全 **且** ALIPAY_SANDBOX=1 **且** cryptography 可用。

    为什么要连带校验 cryptography（R8 修复）：
      签名/验签是真实沙箱的**必要条件**。旧实现只校验凭据，在"凭据齐全但
      cryptography 装不上"时会误报 available()=True，于是 payment.server_provider()
      返回 alipay_sandbox、不再回落 mock；随后下单成功（200）却因
      build_page_pay_params() 抛 IntegrationError 被 _build_alipay_redirect 吞掉，
      redirect_url/qr_code_url 为 null，而 mock-succeed 又被 403 拒绝——
      用户付不了钱、又退不回去，属于**静默半失效**。
      把依赖纳入就绪判定后，这条路径统一走既有回落：server_provider() → mock，
      并给出明确的 degraded_reason（degraded=True），前端不会拿到"200 + 空跳转地址"。

    只回布尔；不泄漏任何凭据片段（_crypto() 只做 import 探测，不涉及密钥）。
    """
    cfg = load_config()
    if not (cfg["app_id"] and cfg["private_key"] and cfg["public_key"] and cfg["sandbox"]):
        return False
    return _crypto() is not None


def unavailable_reason():
    """给上层写 degraded_reason 用的中文原因。"""
    cfg = load_config()
    if not cfg["sandbox"]:
        return "未启用支付宝沙箱（ALIPAY_SANDBOX=0）"
    missing = []
    if not cfg["app_id"]:
        missing.append("ALIPAY_APP_ID")
    if not cfg["private_key"]:
        missing.append("ALIPAY_PRIVATE_KEY")
    if not cfg["public_key"]:
        missing.append("ALIPAY_PUBLIC_KEY")
    if missing:
        return "未配置 " + "/".join(missing)
    # 凭据齐全但仍不可用 ⇒ 签名库缺失（R8：不再静默半失效）
    if _crypto() is None:
        return "缺少 cryptography 签名库，无法进行支付宝签名，已回落模拟支付"
    return ""


# ---------------------------------------------------------------------------
# 待签名串拼装（纯函数，离线可测）
# ---------------------------------------------------------------------------
def sign_content(params):
    """按支付宝规则拼待签名串：剔除 sign/sign_type 与空值，键名 ASCII 升序，k=v 用 & 连接。"""
    items = []
    for k in sorted((params or {}).keys()):
        if k in SIGN_EXCLUDE:
            continue
        v = params.get(k)
        if v is None or v == "":
            continue
        items.append(f"{k}={v}")
    return "&".join(items)


def _normalize_pem(raw, kind):
    """把「一行 base64」或「带 BEGIN 头的 PEM」统一成标准 PEM。"""
    s = (raw or "").strip().replace("\\n", "\n")
    if not s:
        raise IntegrationError("密钥为空")
    if "-----BEGIN" in s:
        return s
    body = "".join(s.split())
    header = "PRIVATE KEY" if kind == "private" else "PUBLIC KEY"
    lines = [f"-----BEGIN {header}-----"]
    for i in range(0, len(body), 64):
        lines.append(body[i:i + 64])
    lines.append(f"-----END {header}-----")
    return "\n".join(lines)


def _crypto():
    """惰性导入 cryptography；不可用时返回 None（上层据此回落 mock）。"""
    try:
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import padding  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    return True


def sign(data, private_key_pem=None):
    """RSA2(SHA256withRSA) 签名，返回 base64 字符串。"""
    if _KEY_BACKEND is not None:            # 单测注入的假签名器
        return _KEY_BACKEND("sign", data)
    if not _crypto():
        raise IntegrationError("缺少 cryptography，无法进行支付宝签名")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pem = _normalize_pem(private_key_pem or load_config()["private_key"], "private")
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        sig = key.sign(data.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    except IntegrationError:
        raise
    except Exception:  # noqa: BLE001
        raise IntegrationError("支付宝私钥格式不正确") from None
    return base64.b64encode(sig).decode()


def verify(data, signature, public_key_pem=None):
    """RSA2 验签。**任何异常都返回 False**——回调必须稳定给出 fail，不能 500。"""
    if _KEY_BACKEND is not None:
        return bool(_KEY_BACKEND("verify", data, signature))
    if not _crypto():
        return False
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        pem = _normalize_pem(public_key_pem or load_config()["public_key"], "public")
        key = serialization.load_pem_public_key(pem.encode())
        sig = base64.b64decode(signature or "")
        key.verify(sig, data.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError, AttributeError):
        return False
    except Exception:  # noqa: BLE001
        log.warning("alipay 验签异常（已按失败处理）")
        return False


def verify_callback(params):
    """校验异步通知：拼待验签串 → 用支付宝公钥验签。返回 bool。"""
    sig = (params or {}).get("sign") or ""
    if not sig:
        return False
    return verify(sign_content(params), sig)


# ---------------------------------------------------------------------------
# 下单参数（真实沙箱才用；mock 模式不会走到这里）
# ---------------------------------------------------------------------------
def build_page_pay_params(pay_no, amount, subject, *, notify_url=None, timeout_express="10m"):
    """拼 alipay.trade.page.pay 的跳转参数（含签名）。

    返回 dict：调用方把它拼成 query string 作为 redirect_url。
    """
    cfg = load_config()
    if not available():
        raise IntegrationError(unavailable_reason() or "支付宝沙箱未就绪")
    biz = {
        "out_trade_no": pay_no,
        # 金额必须是字符串且两位小数；由服务端快照金额转来
        "total_amount": f"{float(amount):.2f}",
        "subject": subject,
        "product_code": "FAST_INSTANT_TRADE_PAY",
        "timeout_express": timeout_express,
    }
    import json as _json
    params = {
        "app_id": cfg["app_id"],
        "method": "alipay.trade.page.pay",
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": _now_str(),
        "version": "1.0",
        "notify_url": notify_url or cfg["notify_url"] or "",
        "biz_content": _json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
    }
    params = {k: v for k, v in params.items() if v != ""}
    params["sign"] = sign(sign_content(params))
    return params


def gateway_with_params(params):
    """把参数字典拼成完整跳转 URL。"""
    import urllib.parse
    qs = urllib.parse.urlencode(params)
    return f"{load_config()['gateway']}?{qs}"


def _now_str():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
