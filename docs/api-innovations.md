# 创新功能前后端 API 契约（api-innovations）

> 版本：v1.0（2026-11-18）  
> 维护者：backend-engineer  
> 状态：**已由 Lead 拍板的契约基线**，`frontend-engineer` 按此并行开发。  
> 若后端实现与此文档出现任何字段/路径差异，**以后端实际实现 + 本文档修订记录为准，且必须先回报 Lead**。

## 0. 通用约定

### 0.1 基础
- 全部接口都在 `/api` 前缀下，返回 JSON，`Content-Type: application/json; charset=utf-8`。
- 现有全局 CORS 与 `OPTIONS` 预检保持不变（`Access-Control-Allow-Origin: *`）。
- 金额一律为**元**，JSON 里是 number（两位小数），不使用字符串。分转元由后端完成。
- 时间一律为字符串：`YYYY-MM-DD HH:MM:SS`（本地时间，与现有表 `datetime` 一致）；支付单另有 ISO8601 的 `expire_at`（见 §4）。

### 0.2 鉴权方式与三套身份
系统有三套互不相同的身份，接口按需组合校验，**不要混用**：

| 身份 | 凭据 | 获取方式 | 说明 |
|---|---|---|---|
| 管理端 admin | Cookie `locker_admin`（`username\|ts\|sig`，HMAC 签名） | `POST /api/auth/login` | 登录后 Cookie 自动带上；管理端页面另有 302 门禁 |
| 触屏/手机端用户 USER | 请求头 `Authorization: Bearer <token>`（token 体为 `USER\|rid\|ts\|sig`） | `POST /api/auth/kiosk-login` | 手机号验证码登录 |
| 触屏/手机端快递员 COURIER | 请求头 `Authorization: Bearer <token>`（token 体为 `COURIER\|rid\|ts\|sig`） | `POST /api/auth/kiosk-login` | 工号登录 |

> **鉴权头口径（G-12 裁决，v1.1 修订）**：全站用户/快递员身份**只认**
> `Authorization: Bearer <token>`，与仓库既有 `backend/auth.py::kiosk_identity()` 实现一致。
> 早期草案写的 `X-Kiosk-Token` 已废弃，**不再作为可用 header**；服务端不解析该头。
> token 体仍为 `USER|rid|ts|sig` / `COURIER|rid|ts|sig`（格式未变，只是承载 header 名更正）。
>
> **例外（仅一处，设计如此）**：`POST /api/pay/notify/alipay` 是支付宝服务器 → 本服务的
> 服务端到服务端调用，**不可能携带用户 Bearer token**，因此该端点不做 Bearer 校验，
> 改由 **RSA2 验签 + 金额核验 + `(pay_no, trade_no)` 幂等键**把关（见 §4.4）。
> 强行给它加 Bearer 会让真实支付闭环直接 401。
>
> **已知欠账（非设计例外）**：`/api/device/*`（柜机轮询与回执）当前无鉴权，
> 属 docs/03 §7「已知限制」列明的未修欠账，**不是**本契约认可的例外设计。

后端辅助函数（`backend/auth.py`）：`admin_session_valid()`、`kiosk_identity()`、`require_kiosk_role(*roles)`。

### 0.3 统一错误响应
所有接口失败都返回该形状（HTTP 状态码见各接口小节）：

```json
{ "error": "人类可读的中文原因", "code": "MACHINE_READABLE_CODE" }
```

`code` 是本契约新增的稳定机读错误码（老接口可只有 `error`）。公共错误码：

| HTTP | code | 含义 |
|---|---|---|
| 400 | `BAD_REQUEST` | 参数缺失/类型错误/超长 |
| 400 | `VALIDATION_FAILED` | 业务校验不通过（含金额、枚举、越界） |
| 401 | `UNAUTHORIZED` | 未登录 / token 缺失或签名错误 / token 过期 |
| 403 | `FORBIDDEN` | 已登录但无权操作该资源（角色不符或不属于本人） |
| 403 | `ROLE_REQUIRED` | 需要特定角色（响应里带 `required_role`） |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 幂等冲突/状态不允许（如已支付的单再支付） |
| 429 | `RATE_LIMITED` | 触发频控（AI 接口） |
| 500 | `INTERNAL_ERROR` | 服务端异常（不应由业务输入触发） |
| 503 | `UPSTREAM_UNAVAILABLE` | 外部依赖不可用**且**本地兜底也失败（正常情况下不会出现） |

> **重要：外部依赖（DeepSeek / 高德 / 支付宝）不可用时，创新接口一律降级成功返回 200，绝不 500。**
> 降级时在响应体里用 `degraded: true` + `degraded_reason` 明示。

### 0.4 降级总原则
| 能力 | 有凭据且可用 | 无凭据 / 调用失败 |
|---|---|---|
| AI 包装推荐 | `source: "deepseek"`, `degraded: false` | `source: "rule"`, `degraded: true`, `degraded_reason: "..."` |
| AI 问答 | `source: "deepseek"` | `source: "rule"`（本地 FAQ 规则表），仍 200 |
| 地图找柜 | 带 `distance_m`、按距离+空闲加权排序 | 按 `cabinet_id` 排序，`distance_m: null`，`degraded: true` |
| 支付 | `provider: "alipay_sandbox"`（需沙箱凭据） | 默认 `provider: "mock"`，`mock: true`，页面明示"模拟支付" |

---

## 1. 创新点 1：AI 包装推荐（DeepSeek 智能寄件问答）

模块：`backend/integrations/deepseek_client.py`、`backend/packaging_rules.py`、`backend/assistant.py`、`backend/assistant_api.py`

### 1.1 健康检查 `GET /api/ai/health`

- 权限：**公开**（供前端探测能力，不泄露任何密钥）
- 响应 200：

```json
{ "provider": "deepseek", "configured": true, "mode": "deepseek" }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `provider` | string | 固定 `"deepseek"` |
| `configured` | boolean | 服务端是否读到 `DEEPSEEK_API_KEY`（**只回布尔，绝不回 Key**） |
| `mode` | `"deepseek" \| "rule"` | 当前实际生效模式（`configured` 为 false 时应为 `"rule"`） |

### 1.2 包装推荐 `POST /api/ai/pack-recommend`

- 权限：**公开**（寄件前咨询，无需登录）；有频控
- 请求体：

```json
{ "description": "一个玻璃杯和两本书" }
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `description` | string | 是 | 去空白后 1–500 字符；超长返回 400 `BAD_REQUEST`；空白返回 400 |

- 响应 200：

```json
{
  "source": "deepseek",
  "elapsed_ms": 812,
  "degraded": false,
  "degraded_reason": null,
  "forbidden": [ { "name": "锂电池", "reason": "航空禁运" } ],
  "sensitive": [ { "name": "玻璃杯", "reason": "易碎需缓冲" } ],
  "packaging": [ { "step": 1, "title": "气泡膜包裹", "detail": "玻璃杯至少包 3 层" } ],
  "size_type": "MEDIUM",
  "size_reason": "两本书+玻璃杯体积中等，需留缓冲空间",
  "materials": [ "气泡膜", "5 号纸箱", "易碎标签" ],
  "notice": "结果仅供参考，以快递员/承运商审核为准"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `source` | `"deepseek" \| "rule"` | **取值域固定这两个**，前端据此展示"AI 推荐"/"规则推荐"角标 |
| `elapsed_ms` | integer | 服务端耗时（含重试），便于观测 |
| `degraded` | boolean | true 表示走了本地规则兜底 |
| `degraded_reason` | string \| null | 降级原因（中文，可直接展示）：`"未配置 DEEPSEEK_API_KEY"` / `"调用超时"` / `"返回结构校验失败"` / `"上游错误 HTTP 429"` |
| `forbidden` | array | 禁寄/限寄物品；元素 `{name, reason}`；无则 `[]` |
| `sensitive` | array | 敏感/易损物品，需额外处理；元素同上；无则 `[]` |
| `packaging` | array | 打包步骤，`step` 从 1 连续递增；`title` 短标题、`detail` 具体做法 |
| `size_type` | `"SMALL" \| "MEDIUM" \| "LARGE"` | 建议格口规格，必须落在 `t_cell.size_type` 的取值域内 |
| `size_reason` | string | 选该规格的理由 |
| `materials` | array\<string> | 快递员需携带的包装材料清单 |
| `notice` | string | **固定文案**，含"以快递员/承运商审核为准"，前端必须原样展示 |

- 错误：
  - 400 `BAD_REQUEST`：`description` 缺失/非字符串/超长
  - 429 `RATE_LIMITED`：超频控（响应带 `retry_after_s`）
- **模型只给建议**：服务端会用 `packaging_rules.py` 对模型输出做二次校验（枚举修正、禁寄词强制补全、步骤数上下限），最终结构以服务端校验后为准。

### 1.3 AI 问答 `POST /api/ai/chat`

- 权限：**公开**
- 请求体：

```json
{ "message": "超时了怎么取件？", "session_id": "可选，字符串，<=64" }
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `message` | string | 是 | 1–500 字符 |
| `session_id` | string | 否 | 1–64 字符；不传则由后端生成。**当前为无状态实现：`session_id` 仅用于前端串联对话，不做服务端会话存储** |

- 响应 200：

```json
{ "source": "deepseek", "reply": "……", "session_id": "s_ab12cd34", "elapsed_ms": 320,
  "degraded": false, "degraded_reason": null }
```

- 错误：400 `BAD_REQUEST`、429 `RATE_LIMITED`

### 1.4 安全要求（后端实现约束，前端只需知道结论）
- `DEEPSEEK_API_KEY` 只从环境变量读取，**永不出现在任何响应、日志、错误信息里**；日志中如打印请求头一律脱敏为 `sk-***`。
- 超时默认 8s（`DEEPSEEK_TIMEOUT`），最多重试 2 次（`DEEPSEEK_MAX_RETRY`），重试仅对超时/5xx/429。
- 对上上游返回做严格 JSON Schema 校验，不合法即视为失败 → 降级本地规则。
- 禁寄/敏感物品只做**提示**，不自动确认订单；响应 `notice` 必须含"以快递员/承运商审核为准"。

---

## 2. 创新点 2：包装准备协同（备包装清单 + 快递员任务）

模块：`backend/packaging_tasks.py`；表：`t_pack_material`、`t_pack_task`、`t_pack_task_item`、`t_package.pack_recommendation_id`

### 2.1 备包装材料台账

#### `GET /api/pack-materials`
- 权限：**COURIER 或 admin**（401 未登录 / 403 角色不符）
- 查询参数：无（全量，量小）
- 响应 200：

```json
{ "data": [ { "material_id": 1, "name": "气泡膜", "spec": "卷", "stock": 12, "threshold": 5, "unit": "卷" } ] }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `material_id` | integer | 主键 |
| `name` | string | 材料名 |
| `spec` | string \| null | 规格描述 |
| `stock` | integer | 当前库存（**>= 0**） |
| `threshold` | integer | 低库存阈值，`stock <= threshold` 时前端标红 |
| `unit` | string | 计量单位 |

#### `PUT /api/pack-materials/{id}`
- 权限：**COURIER 或 admin**
- 请求体：`{ "stock": 20 }`（也可带 `threshold`）
  - 只接受 `stock`、`threshold` 两个字段，其余字段忽略；`stock` 必须是整数且 `0 <= stock <= 100000`
- 响应 200：返回更新后的单条对象（同 §2.1 元素形状）
- 错误：400 `VALIDATION_FAILED`（负数/非整数/超上限）、404 `NOT_FOUND`

### 2.2 快递员"备包装"任务

#### `GET /api/courier/packaging-tasks`
- 权限：**COURIER**（admin 也可查全部）；COURIER 只返回 `assignee_courier_id = 本人` 的任务（越权访问他人任务 → 403）
- 查询参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `status` | string | 全部 | `PENDING` / `DONE` / `CANCELED` |
| `page` | int | 1 | |
| `size` | int | 20 | 1–100 |

- 响应 200：

```json
{ "count": 1, "page": 1, "size": 20,
  "data": [ {
    "task_id": 7, "package_id": 319, "tracking_no": "SF1234567890",
    "cabinet_id": 2, "cabinet_code": "CAB-002", "cell_code": "A01",
    "recommendation_id": 15, "size_type": "MEDIUM",
    "status": "PENDING", "created_at": "2026-11-18 14:00:00",
    "materials": [ { "name": "气泡膜", "qty": 1, "unit": "卷" } ]
  } ] }
```

- 错误：401 `UNAUTHORIZED`、403 `ROLE_REQUIRED`（`required_role: "COURIER"`）

#### `POST /api/courier/packaging-tasks/{task_id}/done`
- 权限：**COURIER（本人任务）或 admin**
- 请求体：`{ "note": "可选，<=200" }`
- 响应 200：`{ "task_id": 7, "status": "DONE", "done_at": "2026-11-18 15:00:00" }`
- 错误：404、403（非本人）、409 `CONFLICT`（已完成/已取消）

### 2.3 推荐结果被寄件单引用
- 内部约定：`POST /api/ai/pack-recommend` 的推荐会落 `t_pack_recommendation`，返回体**额外带** `recommendation_id`（新增字段，向后兼容）。
- 寄件单（`t_package`）新增可空列 `pack_recommendation_id`，指向该推荐；快递员"备包装"任务据此生成材料清单快照（材料名/数量在任务行内快照，材料台账后续改名不影响历史任务）。
- 前端如需在寄件流程中带上推荐：在现有寄件请求里加可选字段 `pack_recommendation_id`（integer）；该字段缺失时行为与改造前完全一致。

### 2.4 寄件单新增寄件人 / 收件人地址（BUG2，可选字段）

模块：`backend/business.py`（`send_order`、`_parse_address`、`_send_order_row`）

**背景**：寄件表单原先只有寄件人 / 收件人的姓名与手机号，没有地址；但"快递员上门揽收"和"收件人收货"都必须知道地址。本次为 `POST /api/business/send-order` 增加两个**可选**字段。

#### 请求新增字段（`POST /api/business/send-order`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sender_address` | `string \| null` | 否 | 寄件人地址，≤120 字符。不传 / 空串 / 纯空白一律按 `null` 入库 |
| `recipient_address` | `string \| null` | 否 | 收件人地址，同上规则 |

- **归一化**：先 `strip()` 去首尾空白；去完为空则视为未填（`null`）。
- **超长处理**：超过 120 字符返回 **400**，文案为
  `寄件人地址过长（最多 120 个字符，当前 N 个）` / `收件人地址过长（最多 120 个字符，当前 N 个）`。
  **明确不静默截断** —— 地址被截断会直接把件送错地方，宁可报错。
- **向后兼容**：两个字段都不传时，请求/响应/数据库行为与改造前**完全一致**，老调用方零影响。

请求示例：

```json
{ "user_phone": "13800000001", "user_name": "张三", "recipient_phone": "13900000002",
  "recipient_name": "李四", "size_type": "SMALL", "weight": 1.2, "company_id": 3, "cabinet_id": 1,
  "sender_address": "北京市海淀区中关村大街 1 号 3 单元 501",
  "recipient_address": "上海市浦东新区世纪大道 100 号 A 座 12 层" }
```

#### 响应新增字段

- `POST /api/business/send-order`（201）**响应顶层**新增 `sender_address` / `recipient_address`，**原样回显本次实际入库的值**（未填写为 `null`）。
  - ⚠️ 注意层级：这两个字段在**响应顶层**，不在 `package` 对象里 —— `package` 由 `_detail()` 从视图 `v_package_detail` 读出，而该视图**不含**这两列。前端取值请用 `resp.sender_address`，不是 `resp.package.sender_address`。
- `GET /api/business/send-lookup`（按揽收码/运单号/收件人手机号匹配）与 `GET /api/business/my-packages` 的寄件行，均通过同一构造函数 `_send_order_row()` 输出，因此**这些行里带**这两个字段；**历史寄件单为 `null`**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `sender_address` | `string \| null` | 寄件人地址；未填写或历史数据为 `null` |
| `recipient_address` | `string \| null` | 收件人地址；未填写或历史数据为 `null` |

#### 数据库变更

- `t_package` 新增两列：`sender_address VARCHAR(120) NULL`、`recipient_address VARCHAR(120) NULL`
- 迁移脚本：`db/migrations/004_sender_address.sql`（幂等：用 `information_schema` 判断后 `PREPARE`/`EXECUTE`，可重复执行；只加可空列，不 DROP、不改动既有数据）
- 重放：`python scripts/init_db.py --migrate` 或 `mysql -u root -p < db/migrations/004_sender_address.sql`

> 前端只需在寄件表单加两个输入框并在请求里带上字段；不填就不传，行为与旧版一致。

---

## 3. 创新点 3：高德地图找柜与智能选柜

模块：`backend/integrations/amap_client.py`、`backend/location.py`

### 3.1 附近柜机 `GET /api/cabinets/nearby`（**在原接口上增补字段，保留旧结构**）

- 权限：**公开**（与原接口一致）
- 查询参数：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `lat` | number | 否 | 用户纬度；与 `lng` 同时给出才生效 |
| `lng` | number | 否 | 用户经度 |
| `q` | string | 否 | 地点/编号模糊搜索（沿用旧参数） |

- 响应 200（**`cabinets[]` 数组内元素在原有字段基础上新增 3 个**，原有键名与含义一个都不改）：

```json
{ "count": 2, "degraded": false, "degraded_reason": null,
  "sorted_by": "distance+availability",
  "cabinets": [ {
      "cabinet_id": 2, "cabinet_code": "CAB-002", "location": "……",
      "cabinet_type": "社区柜", "status": "NORMAL",
      "total": 12, "free_cnt": 5, "free_small": 2, "free_medium": 2, "free_large": 1,
      "latitude": 39.908722, "longitude": 116.397499,
      "distance_m": 350, "score": 0.82, "recommended": true
  } ] }
```

新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `latitude` | number \| null | 柜体纬度；未维护坐标时为 `null` |
| `longitude` | number \| null | 柜体经度；未维护时为 `null` |
| `distance_m` | integer \| null | 与用户坐标的 Haversine 直线距离（米，四舍五入）；无用户坐标或无柜体坐标时 `null` |
| `score` | number \| null | 可用格口加权得分（0–1，越高越优）；无用户坐标时为 `null` |
| `recommended` | boolean | 是否被推荐为"首选柜"（本次结果中得分最高者，仅 1 个为 true；不可计算时全 false） |

- 排序规则：
  - 有 `lat`/`lng`：按 `score` 降序，再按 `distance_m` 升序，再按 `cabinet_id` 升序。
  - 无坐标/降级：维持 `cabinet_id` 升序（**与改造前完全一致的顺序**）。
  - 坐标缺失的柜体排在末尾（`distance_m: null`），不影响其它柜排序。
- 降级：`lat`/`lng` 非法（非数字、纬度不在 ±90、经度不在 ±180）→ 400 `BAD_REQUEST`；坐标合法但**所有柜体都没有坐标** → 200 + `degraded: true` + `degraded_reason: "柜体坐标未维护"`。
- 响应顶层新增 `degraded`、`degraded_reason`、`sorted_by`（`"distance+availability"` 或 `"cabinet_id"`）。

### 3.2 地图客户端配置 `GET /api/map/config`

- 权限：**公开**（浏览器端需要 JS API Key 才能画地图；返回的 key 均已在控制台绑定域名白名单）
- 响应 200：

```json
{ "provider": "amap", "js_key": "abc123...", "security_js_code": "def456...", "configured": true }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `provider` | string | 固定 `"amap"` |
| `js_key` | string \| null | **AMAP_JS_KEY**（JS API 2.0 Key，浏览器端使用，可下发）；未配置为 `null` |
| `security_js_code` | string \| null | **AMAP_JS_SECURITY_CODE**（JS API 安全密钥，浏览器端使用，可下发）；未配置为 `null` |
| `configured` | boolean | `js_key` 非空才为 true |
| `web_service_available` | boolean | 服务端是否配置了 `AMAP_WEB_KEY`（**只回布尔**） |

#### Key 分级（务必区分，违反即安全事故）

| 环境变量 | 用途 | 能否下发到前端 |
|---|---|---|
| `AMAP_JS_KEY` | JS API 2.0 浏览器端加载地图 | ✅ 可以（**必须在高德控制台配置域名白名单/绑定域名**，否则不要下发） |
| `AMAP_JS_SECURITY_CODE` | JS API 2.0 安全密钥（`securityJsCode`） | ✅ 可以（同上，需绑定域名） |
| `AMAP_WEB_KEY` | Web 服务 API：地理编码/逆地理编码/POI 检索 | ❌ **永远只在服务端使用，禁止出现在任何响应、日志、前端代码里** |

- 无 `AMAP_JS_KEY`：`configured: false`，`js_key: null`，前端自动降级为"列表 + 示意图"。
- 服务端地理编码/逆地理编码失败（无 Key/无网络/限流）：相关接口仍返回 200 + `degraded: true`，**不 500**。

### 3.3 地址解析 `GET /api/location/resolve`

- 权限：**公开**
- 查询参数：`address`（string，1–200 字符，必填）或 `lat`+`lng`（逆地理编码）
- 响应 200：

```json
{ "provider": "amap", "degraded": false, "degraded_reason": null,
  "location": { "lng": 116.397499, "lat": 39.908722, "formatted_address": "北京市东城区……",
                "province": "北京市", "city": "北京市", "district": "东城区" },
  "nearest_cabinets": [ { "cabinet_id": 2, "distance_m": 350 } ] }
```

- 降级（无 `AMAP_WEB_KEY` 或无网络）：`provider: "local"`，`degraded: true`，`location: null`，`nearest_cabinets` 仍按本地柜体坐标计算（有坐标时）。
- 错误：400 `BAD_REQUEST`（`address` 与 `lat/lng` 都没给，或坐标非法）

---

## 4. 创新点 4：支付宝沙箱 / 模拟支付

模块：`backend/integrations/alipay_client.py`、`backend/payment.py`、`backend/payment_api.py`  
表：`t_pay_order`、`t_pay_callback_log`

### 4.0 模式
- `PAYMENT_PROVIDER=mock|alipay`，**默认 `mock`**。
- `mock` 模式下所有接口、页面、响应都必须带 `mock: true` 与中文 `provider_label: "模拟支付"`，页面上必须有醒目的"模拟支付，不产生真实扣款"标识。
- `alipay` 模式需要 `ALIPAY_APP_ID` / `ALIPAY_PRIVATE_KEY` / `ALIPAY_PUBLIC_KEY` 齐全且 `ALIPAY_SANDBOX=1`；缺凭据时**自动回落 mock** 并在响应里 `degraded: true`，绝不尝试真实扣款。
- 真实模式：RSA2 验签、金额核验、商家订单号核验、事务 + 幂等键；重复回调/重复提交**不得重复入账**。

### 4.1 创建支付单 `POST /api/pay/create`

- 权限：**USER / admin，或匿名凭取件码（仅超时费）**
  - USER：只能为**本人**名下包裹创建 → `biz_id` 必须是本人 `t_package.package_id`，否则 403 `FORBIDDEN`
  - admin：可为任意
  - **匿名（无任何登录 token）**：凭 `pickup_code` 建单，仅 `biz_type=OVERTIME` 且包裹为 `EXPIRED` 未缴费时可用（触屏端「凭码取件 → 超时缴费」场景，见下方 4.1a）
- 请求体：

```json
{ "biz_type": "OVERTIME", "biz_id": 319, "provider": "mock" }
```

```json
{ "biz_type": "OVERTIME", "biz_id": 319, "pickup_code": "274653" }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `biz_type` | `"OVERTIME" \| "SEND"` | 是 | `OVERTIME`=超时保管费；`SEND`=寄件费 |
| `biz_id` | integer | 是 | `OVERTIME` 时为 `package_id`；`SEND` 时为寄件单 id |
| `provider` | `"mock" \| "alipay_sandbox"` | 否 | 缺省取服务端 `PAYMENT_PROVIDER`；**请求里给的 provider 不能越过服务端配置**（服务端没配 alipay 时降级 mock） |
| `pickup_code` | string | 否 | **匿名建单必填**，6 位取件码；仅 `biz_type=OVERTIME` 生效。**有登录态时该字段被忽略、不参与授权** |

- **服务端金额快照**：金额由后端依据 `biz_type`+`biz_id` 重新计算，写入 `t_pay_order.amount`；**请求里带 `amount` 字段一律忽略**。
- **鉴权优先级**：先尝试登录态（`Authorization: Bearer`）；**只有在登录态缺失时**才看 `pickup_code`。有 token 时即使带了码，仍按 token 的归属校验走，码被忽略 —— 这样持码者无法绕过归属校验去操作他人的支付单。
- 响应 200（幂等：同 `biz_type`+`biz_id` 已有 `PENDING` 未过期单则**复用原单**返回，不新建）：**匿名与登录态返回结构完全一致**（都含 `qr_code_url` / `redirect_url`）。

```json
{ "pay_id": 9, "pay_no": "P20261118001", "amount": 1.00,
  "provider": "mock", "provider_label": "模拟支付", "mock": true,
  "status": "PENDING", "expire_at": "2026-11-18T15:10:00+08:00",
  "degraded": false, "degraded_reason": null,
  "qr_code_url": null, "redirect_url": null, "reused": false }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `pay_id` | integer | 支付单主键 |
| `pay_no` | string | 商户订单号（唯一，前缀 `P`+日期+序号） |
| `amount` | number | **服务端快照金额**，前端只展示不提交 |
| `provider` | `"mock" \| "alipay_sandbox"` | 实际生效渠道 |
| `provider_label` | string | 中文展示文案：`"模拟支付"` / `"支付宝沙箱"` |
| `mock` | boolean | 是否模拟渠道 |
| `status` | `"PENDING" \| "SUCCESS" \| "FAILED" \| "CLOSED"` | 新建时为 `PENDING` |
| `expire_at` | string | ISO8601 带时区，默认 10 分钟后 |
| `qr_code_url` | string \| null | **支付宝预下单二维码内容**（如 `https://qr.alipay.com/bax...`）；mock 为 `null` |
| `redirect_url` | string \| null | **支付宝网页收银台跳转地址**；mock 为 `null` |
| `reused` | boolean | `true` 表示复用了已有未过期 `PENDING` 单，未新建 |

**关于 `qr_code_url` / `redirect_url`（BUG1 修复点，行为约定）**

| 场景 | `qr_code_url` | `redirect_url` | 其他字段 |
|---|---|---|---|
| `mock` 模式（默认） | `null` | `null` | `mock: true`、`provider: "mock"`、`provider_label: "模拟支付"` |
| `alipay` 沙箱，预下单成功 | 非空（`alipay.trade.precreate` 返回的二维码内容） | 非空（带签名的 `page.pay` 跳转地址） | `provider: "alipay_sandbox"`、`mock: false`、`degraded: false` |
| `alipay` 沙箱，预下单失败 | **回退为 `redirect_url` 的值**（用跳转地址当二维码内容，扫码即打开 H5 收银台） | 非空 | **建单仍成功（200）**，不影响下单 |

- 旧实现里 `qr_code_url` **恒为 `null`**（只有 `redirect_url`），前端拿不到任何可编码成二维码的内容，于是页面"没有二维码"——这就是 BUG1。现在真实模式保证两个字段都有可渲染的值。
- 优先级：真二维码 → （失败时）跳转地址；**两种情况下前端都能直接渲染**，不需要自己判空分支。
- 非 `PENDING` 状态（已 `SUCCESS`/`CLOSED`/`FAILED`）下，两个字段均为 `null`（不再需要展示收款码）。

- 错误：400 `BAD_REQUEST`（缺字段/枚举非法）、401（**无任何凭证**）、403 `FORBIDDEN`（越权包裹）、404 `NOT_FOUND`（biz 不存在）、409 `CONFLICT`（该单已支付成功）

### 4.1a 匿名持取件码缴费（方案 A）

模块：`backend/payment_api.py`（`create_pay`）、`backend/payment.py`（`verify_overtime_pickup_code`）

**为什么需要**：触屏端「凭取件码取件 → 发现超时 → 缴费」是**匿名流程** —— 用户在柜机前输 6 位取件码，不可能先登录拿 token。若不放行，该场景完全无法缴费。

**信任模型**：与 `POST /api/business/pickup` **完全一致** —— 取件码本身就是该场景的凭证，持有 6 位码即视为有权处置这一件包裹的超时费。不引入新的信任假设。

**约束（缺一不可）**：
1. 仅当**完全没有登录态**时才启用该通道；有 token 时码被忽略（见 §4.1 鉴权优先级）。
2. 仅 `biz_type=OVERTIME`；`SEND` 会返回 403 `该支付需登录后发起`。
3. 包裹必须是 `EXPIRED` 且**未缴费**（没超时不出现付费入口；已付再建单会重复扣钱）。
4. 码必须与 `biz_id` 指向**同一件** `RECEIVE` 包裹。

**错误码（实测核对）**：

| 场景 | 状态码 | `code` / `error` |
|---|---|---|
| 无 token 且无 `pickup_code` | **401** | `UNAUTHORIZED` `请先登录（管理端或触屏端）` |
| 码错 / 与 `biz_id` 不匹配 / 包裹不存在 | **403** | `FORBIDDEN` `取件码与包裹不匹配` |
| `biz_type=SEND` + 码 | **403** | `FORBIDDEN` `该支付需登录后发起` |
| 包裹非 `EXPIRED`（如 `STORED`） | **409** | `CONFLICT` `该包裹当前无需支付超时费` |
| 已缴费 | **409** | `CONFLICT` `该包裹超时费已支付，无需重复支付` |
| 同 IP 超过 **10 次/分钟** | **429** | 带 `Retry-After` |

> 注：错码、包裹不存在、码与 id 不匹配**统一返回同一句 403 文案** —— 不区分"包裹不存在"和"码不对"，避免用错误码差异探测包裹存在性。

**频控**：`create` 与 `poll` 使用**两个独立**的 IP 滑动窗口桶（10/min 与 120/min），正常轮询不会吃掉建单额度。6 位码空间 10⁶，10 次/分钟下爆破不现实。

**成功响应**：与登录态建单**结构完全一致**（含 `qr_code_url` / `redirect_url`）。

### 4.2 查询支付单 `GET /api/pay/{pay_id}`

- 权限：**USER（本人）/ COURIER（相关）/ admin**
- 响应 200：

```json
{ "pay_id": 9, "pay_no": "P20261118001", "status": "PENDING", "amount": 1.00,
  "provider": "mock", "provider_label": "模拟支付", "mock": true,
  "paid_at": null, "created_at": "2026-11-18 15:00:00",
  "fail_reason": null, "biz_type": "OVERTIME", "biz_id": 319,
  "expire_at": "2026-11-18T15:10:00+08:00" }
```

- `paid_at`：`SUCCESS` 时为支付完成时间字符串，否则 `null`
- `fail_reason`：`FAILED`/`CLOSED` 时为中文原因，否则 `null`
- **本接口不返回 `qr_code_url` / `redirect_url`**：这两个字段只出现在 `POST /api/pay/create` 的建单响应里（用于首次展示收款码）。查询接口用于轮询支付状态，不含收款码。前端如需重新展示二维码，请调用 `create`（同 `biz_type`+`biz_id` 的未过期 `PENDING` 单会被复用，`reused: true`，不会重复建单）。
- 错误：401、403 `FORBIDDEN`、404 `NOT_FOUND`
- **匿名场景请改用 §4.2a 的 `POST /api/pay/{pay_id}/poll`** —— 本接口要求登录态，匿名调用必然 401。

### 4.2a 匿名轮询支付状态 `POST /api/pay/{pay_id}/poll`

模块：`backend/payment_api.py`（`poll_pay_by_pickup_code`）

- 权限：**无需鉴权**，凭 `pickup_code` 授权
- 为什么不放宽 `GET /api/pay/{id}`：那个接口的语义是"本人 / 管理端查询"，放宽会破坏归属校验。触屏端匿名缴费只需要"这一笔单的状态"，用取件码做同源校验即可。
- 请求体：

```json
{ "pickup_code": "274653" }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `pickup_code` | string | 是 | 6 位取件码；必须与该支付单对应的包裹一致 |

- 响应 200：**字段与 `GET /api/pay/{pay_id}` 完全一致**，**不含 `qr_code_url` / `redirect_url`**。

```json
{ "pay_id": 9, "pay_no": "P20261118001", "status": "PENDING", "amount": 1.00,
  "provider": "mock", "provider_label": "模拟支付", "mock": true,
  "paid_at": null, "created_at": "2026-11-18 15:00:00",
  "fail_reason": null, "biz_type": "OVERTIME", "biz_id": 319,
  "expire_at": "2026-11-18T15:10:00+08:00" }
```

- **只读**：不修改任何状态（不改支付单、不改包裹、不写流水），可安全轮询。
- 错误（实测核对）：

| 场景 | 状态码 | `code` / `error` |
|---|---|---|
| 缺 `pickup_code` | **400** | `BAD_REQUEST` `缺少 pickup_code` |
| 支付单不存在 | **404** | `NOT_FOUND` `支付单不存在` |
| 码不匹配 / 该单非 `OVERTIME` | **403** | `FORBIDDEN` `取件码与支付单不匹配` / `该支付单不支持取件码查询` |
| 同 IP 超过 **120 次/分钟** | **429** | 带 `Retry-After` |

> 频控 120/min 的依据：触屏端约 2 秒轮询一次 ≈ 30 次/分钟，留 4 倍余量；同时能挡住"顺序猜 `pay_id` + 猜码"的脚本。

### 4.3 模拟支付成功 `POST /api/pay/{pay_id}/mock-succeed`

- 权限：**admin**（模拟环境下手动触发，便于演示）
- **仅 `PAYMENT_PROVIDER=mock` 且该单 `provider=mock` 时生效**；非 mock 一律拒绝：
  - 非 mock → 403 `FORBIDDEN`，`code: "MOCK_NOT_ALLOWED"`，`error: "当前为真实支付模式，禁止使用模拟支付接口"`
- 请求体：`{}`（**不接受任何金额/状态字段；即使传了也全部忽略**）
- 响应 200：

```json
{ "pay_id": 9, "status": "SUCCESS", "amount": 1.00, "mock": true,
  "provider_label": "模拟支付", "paid_at": "2026-11-18 15:01:00", "idempotent": false }
```

- 重复调用：返回 200 + `idempotent: true`，`paid_at` 保持首次值，**不重复入账**
- 错误：401、403、404、409 `CONFLICT`（已 FAILED/CLOSED）

### 4.4 支付回调（真实模式）`POST /api/pay/notify/alipay`

- 权限：**公开**（支付宝服务器回调），但必须 RSA2 验签
- 内容类型：`application/x-www-form-urlencoded`（支付宝异步通知格式）
- 成功处理：返回**纯文本** `success`（支付宝要求，不能是 JSON）
- 验签失败/金额不符/订单号不符：返回纯文本 `fail`，并写 `t_pay_callback_log`，**不入账**
- 幂等：以 `(pay_no, trade_no)` 建唯一键；重复通知只记日志不重复入账，仍返回 `success`
- mock 模式下该接口返回 403 + JSON 错误（不暴露任何真实凭据）

### 4.5 支付流水（管理端）`GET /api/pay/records`

- 权限：**admin**
- 查询参数：`page`(默认 1)、`size`(默认 20，1–100)、`status`、`provider`、`biz_type`
- 响应 200：

```json
{ "count": 42, "page": 1, "size": 20,
  "data": [ { "pay_id": 9, "pay_no": "P20261118001", "biz_type": "OVERTIME", "biz_id": 319,
              "amount": 1.00, "status": "SUCCESS", "provider": "mock",
              "provider_label": "模拟支付", "mock": true,
              "created_at": "2026-11-18 15:00:00", "paid_at": "2026-11-18 15:01:00" } ] }
```

- 错误：401、403 `ROLE_REQUIRED`

### 4.6 支付闸门（**保持不变**）
- 超时未缴费的取件**仍然**被 402 拦截：`{"error": "NEED_PAYMENT", "package_id": <id>, "amount": <fee>, "message": "..."}`。
- 只有对应 `biz_type=OVERTIME`、`biz_id=该 package_id` 且 `status=SUCCESS` 的支付单存在时，取件才放行。
- **绝不相信前端传来的"已支付"标记或金额**。

---

## 5. 权限要求汇总表

| 接口 | 权限 | 越权响应 |
|---|---|---|
| `GET /api/ai/health` | 公开 | — |
| `POST /api/ai/pack-recommend` | 公开（频控） | 429 |
| `POST /api/ai/chat` | 公开（频控） | 429 |
| `GET /api/cabinets/nearby` | 公开 | — |
| `GET /api/map/config` | 公开 | — |
| `GET /api/location/resolve` | 公开 | — |
| `GET /api/pack-materials` | COURIER 或 admin | 401 / 403 `ROLE_REQUIRED` |
| `PUT /api/pack-materials/{id}` | COURIER 或 admin | 401 / 403 |
| `GET /api/courier/packaging-tasks` | COURIER（本人）或 admin | 401 / 403 `ROLE_REQUIRED` |
| `POST /api/courier/packaging-tasks/{id}/done` | COURIER（本人）或 admin | 401 / 403 |
| `POST /api/pay/create` | USER（本人包裹）或 admin；**或匿名凭 `pickup_code`（仅 OVERTIME）** | 401（无任何凭证）/ 403 `FORBIDDEN` / 409 `CONFLICT` / 429 |
| `GET /api/pay/{pay_id}` | USER（本人）/ COURIER（相关）/ admin | 401 / 403 |
| `POST /api/pay/{pay_id}/poll` | **公开（凭 `pickup_code`），只读** | 400 / 403 / 404 / 429 |
| `POST /api/pay/{pay_id}/mock-succeed` | admin 且 mock 模式 | 401 / 403 `MOCK_NOT_ALLOWED` |
| `POST /api/pay/notify/alipay` | 公开但需 RSA2 验签 | 返回 `fail` 文本 |
| `GET /api/pay/records` | admin | 401 / 403 `ROLE_REQUIRED` |

---

## 6. 环境变量清单（详见根目录 `.env.example`）

| 变量 | 默认 | 说明 | 可下发前端 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | DeepSeek API Key；空则 AI 全走本地规则 | ❌ |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 基址 | ❌ |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 | ❌ |
| `DEEPSEEK_TIMEOUT` | `8` | 单次超时（秒） | ❌ |
| `DEEPSEEK_MAX_RETRY` | `2` | 最大重试次数 | ❌ |
| `AI_ENABLED` | `1` | 总开关，0 则直接走规则 | — |
| `AMAP_JS_KEY` | 空 | JS API 2.0 Key（浏览器） | ✅ 需绑定域名白名单 |
| `AMAP_JS_SECURITY_CODE` | 空 | JS API 安全密钥（浏览器） | ✅ 需绑定域名白名单 |
| `AMAP_WEB_KEY` | 空 | Web 服务 Key（服务端地理编码） | ❌ 禁止下发 |
| `AMAP_TIMEOUT` | `5` | 高德请求超时（秒） | ❌ |
| `PAYMENT_PROVIDER` | `mock` | `mock` \| `alipay` | — |
| `PAYMENT_EXPIRE_MINUTES` | `10` | 支付单有效期 | — |
| `ALIPAY_APP_ID` | 空 | 支付宝应用 ID | ❌ |
| `ALIPAY_PRIVATE_KEY` | 空 | 应用私钥（RSA2） | ❌ |
| `ALIPAY_PUBLIC_KEY` | 空 | 支付宝公钥（验签用） | ❌ |
| `ALIPAY_SANDBOX` | `1` | 1=沙箱网关 | — |
| `ALIPAY_GATEWAY` | 沙箱地址 | 网关 URL | ❌ |

---

## 7. 修订记录

| 版本 | 日期 | 变更 | 作者 |
|---|---|---|---|
| v1.0 | 2026-11-18 | 首版；按 Lead 拍板的契约基线落盘，覆盖 4 组创新功能 + 权限汇总 + 环境变量清单 | backend-engineer |
| v1.1 | 2026-11-18 | **G-12 裁决**：鉴权头由 `X-Kiosk-Token` 统一改为 `Authorization: Bearer <token>`（以既有 `auth.py` 实现为准）；明确标注 `POST /api/pay/notify/alipay` 为服务端到服务端例外（RSA2 验签 + 幂等键，无需用户 token）；标注 `/api/device/*` 无鉴权属已知欠账而非设计例外 | backend-engineer |
