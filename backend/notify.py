# 消息通知模块
# 负责把业务事件（投递成功、超时催取、异常告警等）转换成通知记录，
# 由后台线程异步投递到短信 / 站内消息 / 外部推送三个渠道。
#
# 设计要点：
#   1) 幂等：t_notice 上 (biz_key, channel) 唯一，重复入队走 ON DUPLICATE KEY 静默命中，
#      重试只 UPDATE 同一行，绝不新增行——同一事件同一渠道永远只有一条记录。
#   2) 异步：enqueue() 只落库，实际发送交给 daemon worker 轮询，
#      避免渠道耗时拖慢存件/取件主流程。
#   3) 隔离：业务侧调用一律包 try/except 且放在事务提交之后，
#      通知失败不影响主流程（见 business.py 各埋点）。
#
# 渠道目前全部为模拟实现（写日志文件 / 落库），真实服务商只需在 _send_sms 里
# 补对应分支，不改调用方。
import os
import random
import re
import threading
import time
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

import db
from config import NOTIFY_CONFIG

try:
    from auth import ADMIN_ACCOUNTS, require_kiosk_role
except ImportError:      # 单独导入本模块时（如脚本测试）没有管理员账号也能工作
    ADMIN_ACCOUNTS = {}

    def require_kiosk_role(*_roles):     # 独立导入时的占位实现，保持模块可加载
        return None, ("请先在触屏端登录", 401)

notify_bp = Blueprint("notify", __name__, url_prefix="/api/notify")

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

# 需要手机号才能投递的渠道。管理员没有手机号，只能走 PUSH。
CHANNEL_NEEDS_PHONE = {"SMS": True, "INBOX": True, "PUSH": False}

_SIZE_CN = {"SMALL": "小件", "MEDIUM": "中件", "LARGE": "大件"}

_EXCEPTION_CN = {
    "TIMEOUT": "超时未取", "OVERWEIGHT": "超重", "DAMAGED": "包裹破损",
    "WRONG_CELL": "错投格口", "MISSED": "漏取", "RETURNED": "退回",
}


# ---- 通知模板 ----
# recipients 取值：
#   user    —— 包裹的归属用户。收件件是收件人，寄件单是下单的寄件人（均为 t_package.user_id）
#   courier —— 经手快递员
#   admin   —— 后台管理员（无手机号，固定走 PUSH）
# channels 对 user/courier 生效；admin 一律走 PUSH。
NOTICE_TEMPLATES = {
    "STORE_ARRIVAL": {
        "label": "投递成功",
        "title": "【智能快递柜】您的包裹已入柜",
        "content": "{user_name}您好，您的{size_cn}包裹已存入{cabinet_code}柜（{location}）"
                   "{cell_code}号格口，取件码 {pickup_code}，请于 {expire_time} 前取件。",
        "recipients": ["user"],
        "channels": ["SMS", "INBOX"],
    },
    "SEND_ORDER_CREATED": {
        "label": "寄件下单成功",
        "title": "【智能快递柜】寄件单已生成",
        "content": "{user_name}您好，您的寄件单已生成，揽收码 {pickup_code}，运单号 {tracking_no}。"
                   "请将{size_cn}包裹放入{cabinet_code}柜 {cell_code}号格口，"
                   "快递员将在 {expire_time} 前揽收。",
        "recipients": ["user"],
        "channels": ["SMS", "INBOX"],
    },
    "SEND_COLLECTED": {
        "label": "快递员已揽收",
        "title": "【智能快递柜】您的寄件已被揽收",
        "content": "{user_name}您好，运单号 {tracking_no} 的寄件已被{company_name}{courier_name}揽收，"
                   "收件人 {recipient_name}，正在派送中。",
        "recipients": ["user"],
        "channels": ["SMS", "INBOX"],
    },
    "SEND_CANCELLED": {
        "label": "寄件已撤回",
        "title": "【智能快递柜】您的寄件单已撤回",
        "content": "{user_name}您好，您的寄件单（揽收码 {pickup_code}，运单号 {tracking_no}）已撤回，"
                   "{cabinet_code}柜 {cell_code}号格口已释放，取件无需再等待揽收。",
        "recipients": ["user"],
        "channels": ["SMS", "INBOX"],
    },
    "PICKUP_REMIND": {
        "label": "到期前提醒",
        "title": "【智能快递柜】包裹待取提醒",
        "content": "{user_name}您好，您在{cabinet_code}柜的{size_cn}包裹尚未取走，"
                   "取件码 {pickup_code}，免费保管期到 {expire_time} 截止，请及时取件。",
        "recipients": ["user"],
        "channels": ["SMS", "INBOX"],
    },
    "EXPIRE_URGE": {
        "label": "超时催取",
        "title": "【智能快递柜】包裹已超时，请尽快取件",
        "content": "{user_name}您好，您在{cabinet_code}柜的{size_cn}包裹已超过免费保管期"
                   "（到期时间 {expire_time}）。取件需支付超时保管费 {overtime_fee}，"
                   "取件码 {pickup_code}，请尽快领取。",
        "recipients": ["user"],
        "channels": ["SMS", "INBOX"],
    },
    "EXCEPTION_ALERT": {
        "label": "异常告警",
        "title": "【智能快递柜】包裹异常：{exception_cn}",
        "content": "运单号 {tracking_no} 的包裹登记了异常（{exception_cn}），"
                   "位于{cabinet_code}柜 {cell_code}号格口，请及时处置。",
        "recipients": ["user", "admin"],
        "channels": ["SMS", "INBOX"],
    },
    "PICKUP_RECEIPT": {
        "label": "取件回执",
        "title": "【智能快递柜】取件成功",
        "content": "{user_name}您好，运单号 {tracking_no} 的包裹已于 {pickup_time} 取件成功，"
                   "感谢使用智能快递柜。",
        "recipients": ["user"],
        "channels": ["INBOX"],
    },
}

NOTICE_TYPE_CN = {k: v["label"] for k, v in NOTICE_TEMPLATES.items()}
CHANNEL_CN = {"SMS": "短信", "INBOX": "站内消息", "PUSH": "外部推送"}
STATUS_CN = {"PENDING": "待发送", "SENT": "已发送", "FAILED": "发送失败", "DEAD": "已放弃"}


# ---- 基础工具 ----
def _fmt_dt(v):
    """datetime → '2026.9.3 18:30'，与前端 fmtTime 的展示口径保持一致。"""
    if not v:
        return "-"
    if isinstance(v, str):
        return v
    return f"{v.year}.{v.month}.{v.day} {v.hour}:{v.minute:02d}"


def _write_log(line):
    """把模拟渠道的发送内容追加到日志文件，便于演示时现场查看。"""
    path = NOTIFY_CONFIG["log_path"]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    except OSError:
        pass      # 日志写不出去不影响通知流程本身


def _biz_key(notice_type, pkg, suffix=""):
    """业务事件键。以运单号 tracking_no 标识包裹而非 package_id：
    数据重灌(mock)后 package_id 会从头复用，若沿用旧键，新包裹的同一事件
    会被 t_notice 唯一键 uk_notice_idem(biz_key, channel) 上遗留的旧记录命中，
    导致入队被幂等吞掉——收件人收不到到货通知。
    带日期后缀的类型（如每日催取）可实现"每天一条"。"""
    key = f"{notice_type.lower()}:pkg:{pkg['tracking_no']}"
    return f"{key}:{suffix}" if suffix else key


# ---- 模板渲染与接收人解析 ----
def _build_context(pkg, detail, extra):
    """把包裹信息摊平成模板变量。extra 里的键可覆盖同名变量（用于异常类型等）。"""
    size_type = (pkg or {}).get("size_type") or detail.get("size_type") or ""
    fee = detail.get("overtime_fee")
    ctx = {
        "user_name":       detail.get("user_name") or "用户",
        "user_phone":      detail.get("user_phone") or "",
        "courier_name":    detail.get("courier_name") or "快递员",
        "company_name":    detail.get("company_name") or "快递公司",
        "tracking_no":     detail.get("tracking_no") or "",
        "pickup_code":     detail.get("pickup_code") or "",
        "cabinet_code":    detail.get("cabinet_code") or "",
        "location":        detail.get("location") or "",
        "cell_code":       detail.get("cell_code") or "",
        "size_cn":         _SIZE_CN.get(size_type, size_type),
        "store_time":      _fmt_dt(detail.get("store_time")),
        "expire_time":     _fmt_dt(detail.get("expire_time")),
        "pickup_time":     _fmt_dt(detail.get("pickup_time") or datetime.now()),
        "recipient_name":  detail.get("recipient_name") or detail.get("user_name") or "收件人",
        "overtime_fee":    f"¥{float(fee):.2f}" if fee is not None else "¥1.00",
        "exception_cn":    _EXCEPTION_CN.get((extra or {}).get("exception_type"), "未知异常"),
    }
    if extra:
        ctx.update(extra)
    return ctx


def _render(tpl, ctx):
    """渲染标题与正文；模板里出现未提供的占位符时抛错，避免带着 {xxx} 发出去。"""
    def fill(text):
        missing = [k for k in re.findall(r"\{(\w+)\}", text) if k not in ctx]
        if missing:
            raise KeyError(f"模板缺少变量: {', '.join(missing)}")
        return text.format(**ctx)

    return fill(tpl["title"])[:100], fill(tpl["content"])[:500]


def _resolve_recipients(notice_type, pkg, detail):
    """解析接收人，返回 [{role, recipient_id, name, phone}]。

    收件件与寄件单的归属用户含义不同：前者是收件人，后者是下单的寄件人，
    但都落在 t_package.user_id 上，因此统一按 user_id 取人即可，不会串号。
    """
    out = []
    for who in NOTICE_TEMPLATES[notice_type]["recipients"]:
        if who == "user" and pkg:
            out.append({
                "role": "USER",
                "recipient_id": pkg.get("user_id"),
                "name": detail.get("user_name"),
                "phone": detail.get("user_phone"),
            })
        elif who == "courier" and pkg:
            out.append({
                "role": "COURIER",
                "recipient_id": pkg.get("courier_id"),
                "name": detail.get("courier_name"),
                "phone": detail.get("courier_phone"),
            })
        elif who == "admin":
            # 管理员没有手机号，作为告警接收方记录姓名即可，投递时走 PUSH
            for username, acc in ADMIN_ACCOUNTS.items():
                out.append({
                    "role": "ADMIN",
                    "recipient_id": None,
                    "name": acc.get("name") or username,
                    "phone": None,
                })
    return [r for r in out if r["name"]]


# ---- 入队（幂等，只落库）----
def enqueue(notice_type, package_id, extra=None, biz_suffix=""):
    """按事件类型生成通知记录，返回新建/命中的 notice_id 列表。

    只写库、不发送，因此调用开销可以忽略。调用方必须在业务事务提交之后调用，
    并包在 try/except 里——通知是旁路能力，失败不能回滚主流程。
    """
    if not NOTIFY_CONFIG["enabled"]:
        return []
    tpl = NOTICE_TEMPLATES.get(notice_type)
    if not tpl or package_id is None:
        return []

    pkg = db.query_one("SELECT * FROM t_package WHERE package_id=%s", (package_id,))
    if not pkg:
        return []
    detail = db.query_one("SELECT * FROM v_package_detail WHERE package_id=%s", (package_id,)) or {}

    ctx = _build_context(pkg, detail, extra)
    try:
        title, content = _render(tpl, ctx)
    except KeyError as e:
        _write_log(f"[模板错误] {notice_type}: {e}")
        return []

    enabled = {c.upper() for c in NOTIFY_CONFIG["channels"]}
    key = _biz_key(notice_type, pkg, biz_suffix)
    ids = []
    for person in _resolve_recipients(notice_type, pkg, detail):
        # 管理员固定走 PUSH；其余接收人按模板声明的渠道
        channels = ["PUSH"] if person["role"] == "ADMIN" else tpl["channels"]
        for channel in channels:
            channel = channel.upper()
            if channel not in enabled:
                continue
            if CHANNEL_NEEDS_PHONE.get(channel) and not PHONE_RE.match(person["phone"] or ""):
                _write_log(f"[跳过] {channel} 缺少有效手机号 {notice_type} pkg={package_id}")
                continue
            row_id = db.insert(
                """INSERT INTO t_notice(notice_type, biz_key, channel, package_id,
                                        recipient_role, recipient_id, recipient_name,
                                        recipient_phone, title, content, status)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING')
                   ON DUPLICATE KEY UPDATE notice_id = LAST_INSERT_ID(notice_id)""",
                (notice_type, key, channel, package_id, person["role"],
                 person["recipient_id"], (person["name"] or "")[:30],
                 person["phone"], title, content))
            ids.append(row_id)
    return ids


def safe_enqueue(notice_type, package_id=None, extra=None, biz_suffix=""):
    """业务侧统一入口：吞掉一切异常，保证通知绝不影响主流程。

    业务模块一律调这个函数，不要直接调 enqueue()。
    """
    try:
        return enqueue(notice_type, package_id, extra=extra, biz_suffix=biz_suffix)
    except Exception as e:
        _write_log(f"[入队失败] {notice_type} pkg={package_id}: {type(e).__name__}: {e}")
        return []


# ---- 渠道适配器（统一签名：(是否成功, 错误说明)）----
def _send_sms(notice):
    provider = NOTIFY_CONFIG["sms_provider"]
    if provider != "mock":
        return False, f"短信服务商 {provider} 未接入（当前仅 mock）"
    _write_log(f"[SMS] → {notice['recipient_phone']} 《{notice['title']}》{notice['content']}")
    return True, None


def _send_inbox(notice):
    # 站内消息不需要外部通道：t_notice 记录本身就是收件箱，前端按手机号拉取
    return True, None


def _send_push(notice):
    _write_log(f"[PUSH] → {notice['recipient_name']} 《{notice['title']}》{notice['content']}")
    return True, None


def _send(channel, notice):
    """投递单条通知。返回 (是否成功, 错误说明)。"""
    if random.random() < NOTIFY_CONFIG["fail_rate"]:
        return False, "模拟渠道故障（fail_rate 命中）"
    handlers = {"SMS": _send_sms, "INBOX": _send_inbox, "PUSH": _send_push}
    handler = handlers.get(channel)
    if not handler:
        return False, f"未知渠道 {channel}"
    try:
        return handler(notice)
    except Exception as e:                       # 渠道异常不能让 worker 挂掉
        return False, f"{type(e).__name__}: {e}"


# ---- 投递与重试 ----
def _next_retry_at(retry_count):
    backoff = NOTIFY_CONFIG["retry_backoff"] or [30]
    idx = min(max(retry_count - 1, 0), len(backoff) - 1)
    return datetime.now() + timedelta(seconds=backoff[idx])


def dispatch_pending(limit=None):
    """取出到期待发/待重试的通知逐条投递，返回本轮统计。"""
    limit = limit or NOTIFY_CONFIG["batch_size"]
    rows = db.query(
        """SELECT * FROM t_notice
           WHERE status IN ('PENDING','FAILED')
             AND (next_retry_at IS NULL OR next_retry_at <= NOW())
           ORDER BY notice_id LIMIT %s""", (limit,))
    stat = {"total": len(rows), "sent": 0, "failed": 0, "dead": 0}
    for notice in rows:
        ok, err = _send(notice["channel"], notice)
        if ok:
            db.execute(
                "UPDATE t_notice SET status='SENT', sent_at=NOW(), last_error=NULL "
                "WHERE notice_id=%s", (notice["notice_id"],))
            stat["sent"] += 1
            continue

        retry_count = int(notice["retry_count"]) + 1
        if retry_count >= NOTIFY_CONFIG["max_retry"]:
            db.execute(
                "UPDATE t_notice SET status='DEAD', retry_count=%s, next_retry_at=NULL, "
                "last_error=%s WHERE notice_id=%s",
                (retry_count, (err or "")[:200], notice["notice_id"]))
            stat["dead"] += 1
        else:
            db.execute(
                "UPDATE t_notice SET status='FAILED', retry_count=%s, next_retry_at=%s, "
                "last_error=%s WHERE notice_id=%s",
                (retry_count, _next_retry_at(retry_count), (err or "")[:200],
                 notice["notice_id"]))
            stat["failed"] += 1
        _write_log(f"[失败] notice={notice['notice_id']} {notice['channel']} {err}")
    return stat


def auto_expire_overdue():
    """自动超时流转：把已过免费取件期的收件包裹置为 EXPIRED。

    缺失此环节时，包裹到期后永远停留在 STORED：不收超时费、不发催收，
    超时率统计也失真——超时只能靠管理员手动"强制超时"或 mock 数据产生。
    本函数由 worker 每轮在生成提醒/催收之前先执行，一次性把
    direction='RECEIVE' 且 status='STORED' 且 expire_time 已到的包裹流转为
    EXPIRED：t_package 的 AFTER UPDATE 触发器会自动登记一条 TIMEOUT 异常
    流转记录（occur_time 取原 expire_time），随后本轮的 EXPIRE_URGE 扫描
    即可对它们入队催收，用户取件也会进入超时缴费(NEED_PAYMENT 402)流程。
    注意寄件方向(SEND_WAIT_PICKUP)的 expire_time 是"揽收截止"语义，
    不在此自动流转。
    """
    rows = db.query(
        """SELECT package_id FROM t_package
           WHERE direction='RECEIVE' AND status='STORED'
             AND expire_time <= NOW()""")
    n = 0
    for r in rows:
        # UPDATE 再带一次 status='STORED' 条件，保证行级幂等（并发/重复调用不重复计）
        n += db.execute(
            "UPDATE t_package SET status='EXPIRED' "
            "WHERE package_id=%s AND status='STORED'", (r["package_id"],))
    return n


def scan_expiring():
    """扫描在柜包裹，按序执行：① 自动超时流转 → ② 到期前提醒 → ③ 超时催取。

    ① 把已到期收件包裹转为 EXPIRED（见 auto_expire_overdue）；
    ② 对仍 STORED 且将到期（到期前 remind_before_hours 小时内）的包裹提醒一次，
       幂等键不带后缀，一个包裹免费期内只提醒一次；
    ③ 对 EXPIRED 包裹催取，biz_key 带日期后缀，同一包裹每天最多催一次。
    """
    stat = {"auto_expired": 0, "remind": 0, "urge": 0}
    stat["auto_expired"] = auto_expire_overdue()

    hours = NOTIFY_CONFIG["remind_before_hours"]
    rows = db.query(
        """SELECT package_id FROM t_package
           WHERE direction='RECEIVE' AND status='STORED'
             AND expire_time > NOW()
             AND expire_time <= DATE_ADD(NOW(), INTERVAL %s HOUR)""", (hours,))
    for r in rows:
        stat["remind"] += len(enqueue("PICKUP_REMIND", r["package_id"]))

    today = datetime.now().strftime("%Y-%m-%d")
    rows = db.query(
        """SELECT package_id FROM t_package
           WHERE direction='RECEIVE' AND status='EXPIRED'""")
    for r in rows:
        stat["urge"] += len(enqueue("EXPIRE_URGE", r["package_id"], biz_suffix=today))
    return stat


# ---- 后台 worker ----
_worker_thread = None
_worker_lock = threading.Lock()


def _worker_loop():
    while True:
        try:
            scan_expiring()
            dispatch_pending()
        except Exception as e:                   # 单轮异常不能终止线程
            _write_log(f"[worker异常] {type(e).__name__}: {e}")
        time.sleep(NOTIFY_CONFIG["worker_interval"])


def start_worker():
    """启动轮询线程。daemon=True 随主进程退出，重复调用只会启动一次。"""
    global _worker_thread
    if not NOTIFY_CONFIG["enabled"]:
        return False
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return False
        _worker_thread = threading.Thread(target=_worker_loop, name="notify-worker", daemon=True)
        _worker_thread.start()
        _write_log("[worker] 通知轮询线程已启动")
        return True


# ---- 对外接口 ----
def _filters(args):
    """把查询参数拼成 WHERE 子句。"""
    wheres, params = [], []
    if args.get("type"):
        wheres.append("notice_type=%s"); params.append(args["type"])
    if args.get("status"):
        wheres.append("status=%s"); params.append(args["status"])
    if args.get("channel"):
        wheres.append("channel=%s"); params.append(args["channel"])
    if args.get("phone"):
        wheres.append("recipient_phone=%s"); params.append(args["phone"])
    if args.get("package_id"):
        wheres.append("package_id=%s"); params.append(args["package_id"])
    return (" WHERE " + " AND ".join(wheres)) if wheres else "", params


def _decorate(row):
    row["notice_type_cn"] = NOTICE_TYPE_CN.get(row["notice_type"], row["notice_type"])
    row["channel_cn"] = CHANNEL_CN.get(row["channel"], row["channel"])
    row["status_cn"] = STATUS_CN.get(row["status"], row["status"])
    return row


@notify_bp.route("/", methods=["GET"])
def list_notices():
    """通知流水列表，支持按类型 / 状态 / 渠道 / 手机号 / 包裹筛选。"""
    args = request.args
    where_sql, params = _filters(args)
    try:
        page = max(1, int(args.get("page", 1)))
        size = min(200, max(1, int(args.get("size", 20))))
    except ValueError:
        page, size = 1, 20

    total = db.query_one(f"SELECT COUNT(*) AS c FROM t_notice{where_sql}", params)["c"]
    rows = db.query(
        f"SELECT * FROM t_notice{where_sql} ORDER BY notice_id DESC LIMIT %s OFFSET %s",
        params + [size, (page - 1) * size])
    return jsonify({
        "total": total, "page": page, "size": size,
        "data": [_decorate(r) for r in rows],
    })


@notify_bp.route("/stats", methods=["GET"])
def stats():
    """通知概览：按状态汇总、按渠道 × 状态交叉、按类型汇总。"""
    by_status = {r["status"]: r["c"] for r in
                 db.query("SELECT status, COUNT(*) AS c FROM t_notice GROUP BY status")}
    by_channel = [{"channel": r["channel"], "status": r["status"], "count": r["c"]}
                  for r in db.query(
                      "SELECT channel, status, COUNT(*) AS c FROM t_notice "
                      "GROUP BY channel, status ORDER BY channel, status")]
    by_type = [{"notice_type": r["notice_type"], "count": r["c"]} for r in
               db.query("SELECT notice_type, COUNT(*) AS c FROM t_notice "
                        "GROUP BY notice_type ORDER BY c DESC")]
    pending = db.query_one(
        "SELECT COUNT(*) AS c FROM t_notice WHERE status IN ('PENDING','FAILED')")["c"]
    return jsonify({
        "total": sum(by_status.values()),
        "by_status": by_status,
        "by_channel": by_channel,
        "by_type": by_type,
        "pending": pending,
        "worker_alive": bool(_worker_thread and _worker_thread.is_alive()),
        "enabled": NOTIFY_CONFIG["enabled"],
    })


@notify_bp.route("/inbox", methods=["GET"])
def inbox():
    """用户站内消息：凭触屏登录 token 取身份，只返回发给该账号的 INBOX 消息。

    改进：旧版凭"任意手机号"即可拉取对应消息（越权查询，且与操作者无绑定）；
    现改为消息绑定到登录账号（recipient_role+recipient_id），实现通知精确送达。
    """
    ident, err = require_kiosk_role("USER")
    if err:
        return jsonify({"error": err[0]}), err[1]
    _, uid = ident
    rows = db.query(
        """SELECT * FROM t_notice
           WHERE recipient_role='USER' AND recipient_id=%s
             AND channel='INBOX' AND status='SENT'
           ORDER BY COALESCE(sent_at, created_at) DESC LIMIT %s""",
        (uid, min(100, max(1, int(request.args.get("size", 20))))))
    data = []
    for r in rows:
        item = _decorate(dict(r))
        item["read"] = bool(item.get("read_at"))
        data.append(item)
    return jsonify({"count": len(data), "data": data})


@notify_bp.route("/inbox/unread", methods=["GET"])
def inbox_unread():
    """未读站内信计数：供触屏端登录用户轮询，驱动首页红点角标与"新通知到达"增量提示。

    计数口径与 inbox 完全一致：本人(recipient_role+recipient_id)、INBOX 渠道、已发送且未读。
    """
    ident, err = require_kiosk_role("USER")
    if err:
        return jsonify({"error": err[0]}), err[1]
    _, uid = ident
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM t_notice "
        "WHERE recipient_role='USER' AND recipient_id=%s "
        "AND channel='INBOX' AND status='SENT' AND read_at IS NULL",
        (uid,))
    n = int(dict(row)["n"]) if row else 0
    return jsonify({"count": n})


@notify_bp.route("/inbox/read", methods=["POST"])
def inbox_read():
    """站内信标记已读：按登录账号把该用户的 INBOX 消息全部置为已读。"""
    ident, err = require_kiosk_role("USER")
    if err:
        return jsonify({"error": err[0]}), err[1]
    _, uid = ident
    updated = db.execute(
        "UPDATE t_notice SET read_at=NOW() "
        "WHERE recipient_role='USER' AND recipient_id=%s "
        "AND channel='INBOX' AND status='SENT' AND read_at IS NULL",
        (uid,))
    return jsonify({"updated": updated})


@notify_bp.route("/inbox/<int:notice_id>/read", methods=["POST"])
def inbox_read_one(notice_id):
    """单条站内信标记已读：校验消息确实属于当前登录用户后再置 read_at。

    与全量已读（/inbox/read）不同，这里按 notice_id 精确命中一条，
    用于消息列表每条消息的「标为已读」按钮；他人消息（0 行命中）不会被误改。
    """
    ident, err = require_kiosk_role("USER")
    if err:
        return jsonify({"error": err[0]}), err[1]
    _, uid = ident
    updated = db.execute(
        "UPDATE t_notice SET read_at=NOW() "
        "WHERE notice_id=%s AND recipient_role='USER' AND recipient_id=%s "
        "AND channel='INBOX' AND status='SENT' AND read_at IS NULL",
        (notice_id, uid))
    if not updated:
        # 命中 0 行：要么消息不存在，要么不属于本人 / 已读。给出可读提示。
        notice = db.query_one("SELECT notice_id FROM t_notice WHERE notice_id=%s", (notice_id,))
        if not notice:
            return jsonify({"error": "消息不存在"}), 404
        return jsonify({"updated": 0, "already": True, "message": "该消息已读或不属于当前账号"})
    return jsonify({"updated": 1, "notice_id": notice_id})


@notify_bp.route("/<int:notice_id>/retry", methods=["POST"])
def retry_notice(notice_id):
    """手动重投：把通知复位为待发送并立即投递一次（DEAD 死信也能复活）。"""
    notice = db.query_one("SELECT * FROM t_notice WHERE notice_id=%s", (notice_id,))
    if not notice:
        return jsonify({"error": "通知不存在"}), 404
    db.execute(
        """UPDATE t_notice SET status='PENDING', retry_count=0, next_retry_at=NULL,
           last_error=NULL WHERE notice_id=%s""", (notice_id,))
    ok, err = _send(notice["channel"], notice)
    if ok:
        db.execute(
            "UPDATE t_notice SET status='SENT', sent_at=NOW(), last_error=NULL "
            "WHERE notice_id=%s", (notice_id,))
        return jsonify({"message": "重投成功", "notice_id": notice_id, "sent": True})
    db.execute(
        "UPDATE t_notice SET status='FAILED', retry_count=1, next_retry_at=%s, last_error=%s "
        "WHERE notice_id=%s", (_next_retry_at(1), (err or "")[:200], notice_id))
    return jsonify({"error": f"重投失败：{err}", "notice_id": notice_id, "sent": False}), 502


@notify_bp.route("/scan", methods=["POST"])
def scan():
    """手动触发一次超时扫描（演示用：立即生成到期提醒与超时催取，不等下一轮轮询）。"""
    stat = scan_expiring()
    return jsonify({"message": "扫描完成", **stat})


@notify_bp.route("/dispatch", methods=["POST"])
def dispatch():
    """手动触发一次投递（演示用：立即发送所有到期通知）。"""
    return jsonify({"message": "投递完成", **dispatch_pending()})


@notify_bp.route("/test", methods=["POST"])
def send_test():
    """发送一条测试通知，用于验证渠道是否连通。"""
    body = request.get_json(silent=True) or {}
    channel = (body.get("channel") or "SMS").upper()
    if channel not in CHANNEL_CN:
        return jsonify({"error": "渠道必须为 SMS/INBOX/PUSH"}), 400
    phone = (body.get("phone") or "").strip() or None
    if CHANNEL_NEEDS_PHONE.get(channel) and not PHONE_RE.match(phone or ""):
        return jsonify({"error": "该渠道需要有效的 11 位手机号"}), 400

    notice_id = db.insert(
        """INSERT INTO t_notice(notice_type, biz_key, channel, package_id, recipient_role,
                                recipient_id, recipient_name, recipient_phone, title, content, status)
           VALUES('PICKUP_RECEIPT',%s,%s,NULL,'USER',NULL,%s,%s,%s,%s,'PENDING')""",
        (f"test:{uuid.uuid4().hex[:12]}", channel, (body.get("name") or "测试用户")[:30], phone,
         (body.get("title") or "【智能快递柜】测试通知")[:100],
         (body.get("content") or "这是一条测试通知，用于验证通知渠道是否连通。")[:500]))
    notice = db.query_one("SELECT * FROM t_notice WHERE notice_id=%s", (notice_id,))
    ok, err = _send(channel, notice)
    if ok:
        db.execute("UPDATE t_notice SET status='SENT', sent_at=NOW() WHERE notice_id=%s",
                   (notice_id,))
        return jsonify({"message": "测试通知已发送", "notice_id": notice_id, "sent": True}), 201
    db.execute("UPDATE t_notice SET status='FAILED', retry_count=1, last_error=%s "
               "WHERE notice_id=%s", ((err or "")[:200], notice_id))
    return jsonify({"error": f"发送失败：{err}", "notice_id": notice_id, "sent": False}), 502
