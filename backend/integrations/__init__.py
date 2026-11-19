# 外部服务集成层（DeepSeek / 高德 / 支付宝）
#
# 设计约束（与 docs/api-innovations.md §0.3 / §0.4 对齐）：
#   · 本目录下所有客户端**只**做"协议 + 容错"，不写业务；
#   · 外部不可用一律抛 IntegrationError，由上层降级为 200 + degraded，**绝不冒泡成 500**；
#   · 任何密钥只从环境变量读，且不写进任何日志、响应、异常信息。
#
# 分层：
#   integrations/deepseek_client.py  → AI 包装推荐 / 问答的模型调用
#   integrations/amap_client.py      → 地理编码 / 逆地理编码（Web 服务 Key，仅服务端）
#   integrations/alipay_client.py    → RSA2 签名 / 验签 / 下单参数（沙箱）
