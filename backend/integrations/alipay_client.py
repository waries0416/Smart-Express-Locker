"""支付宝沙箱客户端（RSA2 签名 / 验签 / 下单参数）。

范围说明（docs/api-innovations.md §4.0）：
  · 默认 PAYMENT_PROVIDER=mock，本模块**只在真实沙箱模式**下被调用；
  · 缺任一凭据时 available() 为 False，payment.py 自动回落 mock 并置 degraded，
    绝不尝试真实扣款；
  · 本模块只做「密码学 + 参数拼装」，不落库、不判断业务幂等（在 payment.py）。

安全红线：
  · ALIPAY_PRIVATE_KEY / ALIPAY_PUBLIC_KEY 只从环境变量读，
    永不出现在响应、日志、异常文案里；本模块对外只暴露 available() 布尔。
  · 验签失败一律返回 False，不抛异常给调用方（回调要稳定返回 fail 文本）。

为什么用 cryptography 而不是 pycryptodome：
  前者是本项目环境已装且是纯 Python 包（含 Rust 轮子），Windows 无需编译；
  后者需要额外安装 Crypto。若两者都不可用，签名功能降级为 unavailable，
  由 payment.py 回落 mock —— 绝不静默"跳过验签"。
"""
import base64
import logging
import os

from .errors import IntegrationError

log = logging.getLogger("integrations.alipay")

SANDBOX_GATEWAY = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
PROD_GATEWAY = "https://openapi.alipay.com/gateway.do"

# 参与签名时**必须排除**的字段：
#   · 请求签名（gateway.do 同步接口）：只排除 sign；**sign_type 要参与签名**。
#     2026-11-20 BUG1 实测证据：沙箱网关在 isv.invalid-signature 的 sub_msg 里
#     回显了它自己拼的待签串，其中明确包含 `sign_type=RSA2`；旧实现把 sign_type
#     也排除了，导致所有真实请求（page.pay / precreate）都被判「验签出错」——
#     页面支付跳过去只会看到支付宝的验签错误页，自然也就永远没有可扫的二维码。
#   · 异步通知验签：按支付宝文档要排除 sign 与 sign_type 两个字段（见 NOTIFY_SIGN_EXCLUDE）。
SIGN_EXCLUDE = ("sign",)
NOTIFY_SIGN_EXCLUDE = ("sign", "sign_type")

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
def sign_content(params, exclude=SIGN_EXCLUDE):
    """按支付宝规则拼待签名串：剔除 exclude 中的字段与空值，键名 ASCII 升序，k=v 用 & 连接。

    注意 exclude 的差异（BUG1 修复点）：
      · 请求签名用默认值 SIGN_EXCLUDE = ("sign",)：sign_type 参与签名；
      · 异步通知验签用 NOTIFY_SIGN_EXCLUDE = ("sign", "sign_type")。
    """
    items = []
    for k in sorted((params or {}).keys()):
        if k in exclude:
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
    """惰性导入 cryptography；不可用时返回 None（上层据此回落 mock）。

    用 try-import 而非 importlib.find_spec：单测会 mock 掉 cryptography 模块，
    必须走真实导入路径才能命中 mock。
    """
    try:
        import cryptography  # pylint: disable=unused-import  # noqa: F401
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
    """校验异步通知：拼待验签串 → 用支付宝公钥验签。返回 bool。

    异步通知的待验签串要排除 sign 与 sign_type（与同步请求签名规则不同）。
    """
    sig = (params or {}).get("sign") or ""
    if not sig:
        return False
    return verify(sign_content(params, NOTIFY_SIGN_EXCLUDE), sig)


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


def _post_form(url, params, timeout):
    """POST application/x-www-form-urlencoded 并解析 JSON 响应（只用标准库）。

    为什么不用 requests：requirements.txt 里没有 requests，项目约定
    「外部调用优先 urllib，减少依赖面」（见 requirements.txt 注释与 deepseek_client）。
    """
    import json as _json
    import urllib.parse
    import urllib.request
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return _json.loads(raw.decode("utf-8", "replace"))


def _call_api(method, biz, *, notify_url=None, timeout=8.0):
    """通用 OpenAPI 调用：拼公共参数 → 签名 → POST → 返回该 method 的 response 节点。

    两个与网关打交道的硬性细节（BUG1 实测）：
      · `sign_type` **参与签名**（请求签名只排除 sign，见 SIGN_EXCLUDE）；
      · `charset` 必须放在 **URL 查询串**里：body 里的非 ASCII 值（如中文 subject）
        会被网关按默认字符集解码，导致待签串与签名不一致（isv.invalid-signature）。
    沙箱网关偶发 ConnectionError（实测 5 次里 2 次），故对同一请求重试 3 次；
    precreate/query/close 都是幂等的，重试安全。
    """
    if not available():
        raise IntegrationError(unavailable_reason() or "支付宝沙箱未就绪")
    cfg = load_config()
    import json as _json
    params = {
        "app_id": cfg["app_id"],
        "method": method,
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
    import time
    last_exc = None
    data = None
    for attempt in range(3):
        try:
            data = _post_form(f"{cfg['gateway']}?charset=utf-8",
                              {k: v for k, v in params.items() if k != "charset"},
                              timeout)
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
    if data is None:
        raise IntegrationError(
            f"支付宝请求失败：{type(last_exc).__name__}") from None
    return (data or {}).get(method.replace(".", "_") + "_response") or {}


def precreate(pay_no, amount, subject, *, notify_url=None, timeout_express="10m",
              timeout=8.0):
    """调 alipay.trade.precreate 换「扫码支付」二维码内容（qr_code）。

    时效说明（重要，BUG 定位结论）：
      · precreate 生成的 qr_code 自身有效期是 **2 小时**（支付宝固定规则）；
      · 同一 out_trade_no **重复 precreate 只会返回同一张旧码**，不会刷新；
      · 码被扫过/交易超时后再扫，支付宝会提示"二维码已失效"。
    所以调用方（payment）在复用旧单时**必须换 out_trade_no** 才能拿到新码，
    这也是本次"扫码提示已过期"的根因。
    """
    biz = {
        "out_trade_no": pay_no,
        "total_amount": f"{float(amount):.2f}",
        "subject": subject,
        "timeout_express": timeout_express,
    }
    node = _call_api("alipay.trade.precreate", biz, notify_url=notify_url,
                     timeout=timeout)
    qr = node.get("qr_code")
    if not qr:
        detail = " ".join(str(x) for x in (node.get("code"), node.get("sub_code"),
                                           node.get("msg"), node.get("sub_msg")) if x)
        raise IntegrationError(f"支付宝预下单失败：{detail[:200]}")
    return qr


def query_trade(pay_no, *, timeout=8.0):
    """查询交易状态（复用旧单前确认是否已支付）。

    返回 response 节点：trade_status=WAIT_BUYER_PAY/TRADE_SUCCESS/TRADE_FINISHED/
    TRADE_CLOSED、trade_no、total_amount；交易不存在时 code=40004 + sub_code=ACQ.TRADE_NOT_EXIST。
    """
    return _call_api("alipay.trade.query", {"out_trade_no": pay_no}, timeout=timeout)


def close_trade(pay_no, *, timeout=8.0):
    """关闭未支付交易（best-effort）。返回 response 节点，code=10000 表示已关闭。"""
    return _call_api("alipay.trade.close", {"out_trade_no": pay_no}, timeout=timeout)


def _now_str():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
