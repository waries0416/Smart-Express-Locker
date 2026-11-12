# 创新接口公共工具：统一错误码、身份判定、频控
#
# 为什么单独抽一层：
#   四组创新接口（AI / 地图 / 支付 / 备包装）由 4 个蓝图实现，但错误响应形状、
#   身份判定规则、频控策略必须**逐字一致**——否则前端要为每个接口写一套分支。
#   契约 docs/api-innovations.md §0.3 统一了错误体，本模块是它唯一的实现点。
#
# 鉴权约定（Lead G-12 裁决）：
#   · 用户/快递员身份统一走请求头 `Authorization: Bearer <token>`；
#   · token 格式 USER|rid|ts|sig / COURIER|rid|ts|sig，由 auth.kiosk_identity() 校验；
#   · 管理端身份走 Cookie `locker_admin` 或 `Authorization: Bearer <admin-token>`；
#   · **例外**：服务端到服务端端点（如支付宝异步通知）不带用户 token，
#     改用 RSA2 验签 + 幂等键，见 payment_api.pay_notify_alipay()。
import threading
import time

from flask import jsonify, request

import auth


# ---------------------------------------------------------------------------
# 统一错误响应（契约 §0.3）
# ---------------------------------------------------------------------------
def error(message, code="BAD_REQUEST", status=400, **extra):
    """返回 (Flask 响应, HTTP 状态码)，形状固定为 {error, code, ...extra}。"""
    body = {"error": message, "code": code}
    body.update(extra)
    return jsonify(body), status


def bad_request(message="请求参数不正确"):
    return error(message, "BAD_REQUEST", 400)


def validation_failed(message="参数校验不通过"):
    return error(message, "VALIDATION_FAILED", 400)


def unauthorized(message="请先登录"):
    return error(message, "UNAUTHORIZED", 401)


def forbidden(message="无权执行该操作"):
    return error(message, "FORBIDDEN", 403)


def not_found(message="资源不存在"):
    return error(message, "NOT_FOUND", 404)


def conflict(message="当前状态不允许该操作"):
    return error(message, "CONFLICT", 409)


def role_required(required_role, message=None):
    """403 ROLE_REQUIRED，响应里带 required_role（契约 §0.3）。"""
    return error(
        message or f"该操作需要 {required_role} 身份",
        "ROLE_REQUIRED", 403, required_role=required_role,
    )


def internal_error(message="服务端处理失败"):
    return error(message, "INTERNAL_ERROR", 500)


# ---------------------------------------------------------------------------
# 身份判定
# ---------------------------------------------------------------------------
def admin_logged_in():
    """管理端会话是否有效（Cookie 或 Bearer 均可，复用既有 auth.py）。"""
    return auth.admin_session_valid()


def kiosk_ident():
    """触屏/手机端身份 (role, rid) 或 None。"""
    return auth.kiosk_identity()


def require_admin():
    """要求管理端身份；返回 None 表示通过，否则返回错误响应元组。"""
    if not admin_logged_in():
        return unauthorized("未登录或登录已过期（管理端）")
    return None


def require_admin_or_kiosk(*roles):
    """管理端 **或** 指定触屏角色之一。

    返回 (identity, error_response)：
      · 管理端 → (("ADMIN", None), None)
      · 触屏   → ((role, rid), None)
      · 否则   → (None, error_response)
    角色不符返回 403 ROLE_REQUIRED（带 required_role），未登录返回 401。
    """
    if admin_logged_in():
        return ("ADMIN", None), None
    ident = kiosk_ident()
    if not ident:
        return None, unauthorized("请先登录（管理端或触屏端）")
    if roles and ident[0] not in roles:
        return None, role_required(" 或 ".join(roles))
    return ident, None


def is_admin(identity):
    """identity 是否为管理端（用于区分"本人"校验是否需要跳过）。"""
    return bool(identity) and identity[0] == "ADMIN"


# ---------------------------------------------------------------------------
# 频控（内存滑动窗口）
# ---------------------------------------------------------------------------
# 为什么用内存而不是 Redis：本项目是课程设计单进程演示，限流只需挡住
# 误触与脚本刷量；重启即清零反而方便演示。多进程部署时应换 Redis——
# 这一点写在这里，避免后来者误以为它是生产级方案。
class SlidingWindowLimiter:
    def __init__(self, limit, window_seconds):
        self.limit = int(limit)
        self.window = float(window_seconds)
        self._hits = {}
        self._lock = threading.Lock()

    def hit(self, key):
        """记一次访问。返回 (allowed, retry_after_s)。"""
        if self.limit <= 0:
            return True, 0
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            bucket = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(bucket) >= self.limit:
                retry = max(1, int(round(bucket[0] + self.window - now)))
                self._hits[key] = bucket
                return False, retry
            bucket.append(now)
            self._hits[key] = bucket
            return True, 0

    def reset(self, key=None):
        """清空（单测用；也便于演示时手动解封）。"""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


def client_key(prefix):
    """频控键：优先取真实客户端 IP（兼容反向代理），退化为 remote_addr。

    注意：这里**不**按 token 分桶——公开接口本来就可能没有 token，
    按 IP 限流才挡得住匿名刷量。
    """
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    ip = fwd or request.remote_addr or "unknown"
    return f"{prefix}:{ip}"


# AI 接口频控：每分钟 20 次（演示足够，也能挡住脚本刷量）
AI_LIMITER = SlidingWindowLimiter(limit=20, window_seconds=60)


def rate_limited(retry_after_s):
    """429 RATE_LIMITED，带 retry_after_s（契约 §1.2）。"""
    return error(
        f"请求太频繁，请 {retry_after_s} 秒后再试",
        "RATE_LIMITED", 429, retry_after_s=retry_after_s,
    )
