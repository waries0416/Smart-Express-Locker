"""外部集成统一异常。

为什么单独一个模块：四个创新点、三个外部服务都要抛"可降级失败"，
上层（assistant.py / location.py / payment.py）只需要认一个类型就能决定
是"降级成规则"还是"回落 mock"，不必逐个 import 具体客户端。
"""
class IntegrationError(Exception):
    """外部依赖不可用（超时 / 5xx / 429 / 返回结构不合法 / 未配置凭据）。

    retryable  —— 是否值得重试（仅超时、5xx、429 为 True；4xx 参数错误重试无意义）
    status     —— 上游 HTTP 状态码（可能为 None）
    reason     —— 可直接展示给用户的中文降级原因（写进响应 degraded_reason）
    """

    def __init__(self, reason, *, retryable=False, status=None):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.status = status

    def __str__(self):
        return self.reason
