#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端到端闭环核验 · 智能快递柜管理系统（R3b）

闭环定义（任务要求）：
    寄件下单 → AI 包装推荐 → 地图找柜 → 快递员投递(揽收+存柜)
             → 用户取件 → 超时支付

设计原则
--------
1) **每一步都断言**，不是"跑通了就写通过"。每步记录：期望、实际 HTTP 状态、
   关键字段，任一不符则整条闭环判失败，并打印原始响应便于定位。
2) **不依赖演示数据是否已灌入**：自己造件、自己清理，跑完库回到原状。
3) **绝不伪造**：AI/地图若无凭据会降级，这里断言的是"降级也必须 200 且结构合法"，
   而不是硬要求 `source=deepseek` —— 那才是真实的契约（docs/api-innovations.md §0.4）。
4) 支持两种后端模式：
     --mode http   打真实 HTTP 服务（默认，需要服务在跑）
     --mode inproc 用 Flask test_client 进程内跑（服务不可用时的等效验证）

用法：
    python scripts/verify_e2e.py --host http://127.0.0.1:5000
    python scripts/verify_e2e.py --mode inproc
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def pkg_status(body):
    """从响应体的 package 里取状态。

    注意字段名是 `pkg_status`（v_package_detail 视图的字段名），不是 `status`。
    视图里 status 被重命名为 pkg_status 以避免与格口状态混淆，
    这里做一次兼容读取，两种都认，避免因字段名误判成失败。
    """
    pkg = (body or {}).get("package") or {}
    return pkg.get("pkg_status") or pkg.get("status")


class Step:
    def __init__(self, no, name):
        self.no = no
        self.name = name
        self.ok = True
        self.details = []
        self.error = None
        self.request = None
        self.status = None
        self.body = None


class E2E:
    def __init__(self, client, verbose=True):
        self.c = client
        self.verbose = verbose
        self.steps = []
        self.ctx = {}

    # ---- 公共请求封装：兼容 http 与 inproc ----
    def _req(self, method, path, **kw):
        """统一发请求并解析 JSON。

        Flask test_client 的响应对象没有 .get_data()（那是 Werkzeug Request 的方法），
        它的正文是 .data / .get_json()；requests 的是 .json() / .text。
        这里两种都兼容，否则 inproc 模式下所有响应都会被误判成"不是 JSON"。
        """
        if method == "GET":
            r = self.c.get(path, **kw)
        else:
            r = self.c.post(path, **kw)
        status = r.status_code
        body = None
        if hasattr(r, "get_json"):
            try:
                body = r.get_json()
            except Exception:  # noqa: BLE001
                body = None
        elif hasattr(r, "json"):
            try:
                body = r.json()
            except Exception:  # noqa: BLE001
                body = None
        if body is None:
            raw = getattr(r, "data", b"")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            body = raw
        return status, body

    def step(self, no, name):
        s = Step(no, name)
        self.steps.append(s)
        return s

    def check(self, s, cond, label, actual=None):
        if not cond:
            s.ok = False
            s.details.append(f"✗ {label}" + (f"（实际: {actual}）" if actual is not None else ""))
        else:
            s.details.append(f"✓ {label}")
        return cond

    # ==================================================================
    def run(self):
        phone = f"15{random.randint(10 ** 8, 10 ** 9 - 1)}"
        recip = f"13{random.randint(10 ** 8, 10 ** 9 - 1)}"
        self.ctx["phone"] = phone

        # ---------- 1. 寄件下单 ----------
        s = self.step(1, "寄件下单（POST /api/business/send-order）")
        try:
            _, comp = self._req("GET", "/api/entities/express_companies?page=1&size=5")
            rows = (comp.get("rows") or comp.get("data") or []) if isinstance(comp, dict) else []
            company_id = rows[0]["company_id"] if rows else 1
            _, cab = self._req("GET", "/api/cabinets/nearby")
            cabs = cab.get("cabinets") or []
            cand = [x for x in cabs if x.get("free_cnt", 0) > 0] or cabs
            cabinet_id = cand[0]["cabinet_id"] if cand else 1
            self.ctx["cabinet_id"] = cabinet_id

            payload = {
                "user_phone": phone, "user_name": "E2E 寄件人",
                "recipient_phone": recip, "recipient_name": "E2E 收件人",
                "size_type": "MEDIUM", "company_id": company_id,
                "cabinet_id": cabinet_id, "weight": 1.5,
            }
            s.request = payload
            status, body = self._req("POST", "/api/business/send-order", json=payload)
            s.status, s.body = status, body
            self.check(s, status == 201, "HTTP 201", status)
            if isinstance(body, dict):
                self.check(s, bool(body.get("order_code")), "返回揽收码 order_code",
                           body.get("order_code"))
                self.check(s, bool(body.get("tracking_no")), "返回运单号")
                self.ctx["order_code"] = body.get("order_code")
                self.ctx["send_pid"] = (body.get("package") or {}).get("package_id")
                self.ctx["company_id"] = company_id
            else:
                self.check(s, False, "响应为 JSON", str(body)[:100])
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 2. AI 包装推荐 ----------
        s = self.step(2, "AI 包装推荐（POST /api/ai/pack-recommend）")
        try:
            s.request = {"description": "一个玻璃杯和两本书"}
            status, body = self._req("POST", "/api/ai/pack-recommend",
                                     json=s.request)
            s.status, s.body = status, body
            self.check(s, status == 200, "HTTP 200（降级也必须是 200）", status)
            if isinstance(body, dict):
                self.check(s, body.get("source") in ("deepseek", "rule"),
                           f"source ∈ {{deepseek, rule}}（实际 {body.get('source')}）")
                self.check(s, body.get("size_type") in ("SMALL", "MEDIUM", "LARGE"),
                           f"size_type 合法（{body.get('size_type')}）")
                self.check(s, isinstance(body.get("packaging"), list) and
                           len(body.get("packaging")) > 0, "packaging 非空数组")
                self.check(s, isinstance(body.get("materials"), list),
                           "materials 为数组")
                self.check(s, "以快递员" in (body.get("notice") or "")
                           or "审核" in (body.get("notice") or ""),
                           "notice 含承运商/审核免责文案")
                self.ctx["rec_id"] = body.get("recommendation_id")
                self.check(s, body.get("recommendation_id") is not None,
                           "返回 recommendation_id（落库证据）")
            else:
                self.check(s, False, "响应为 JSON", str(body)[:100])
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 3. 地图找柜 ----------
        s = self.step(3, "地图找柜（GET /api/cabinets/nearby?lat&lng）")
        try:
            s.request = {"lat": 39.908722, "lng": 116.397499}
            status, body = self._req("GET", "/api/cabinets/nearby?lat=39.908722&lng=116.397499")
            s.status, s.body = status, body
            self.check(s, status == 200, "HTTP 200", status)
            if isinstance(body, dict):
                cabs = body.get("cabinets") or []
                self.check(s, len(cabs) > 0, f"返回柜体列表（{len(cabs)} 个）")
                self.check(s, "sorted_by" in body,
                           f"sorted_by 字段存在（{body.get('sorted_by')}）")
                if cabs:
                    first = cabs[0]
                    self.check(s, "distance_m" in first, "柜体含 distance_m")
                    self.check(s, "score" in first, "柜体含 score")
                    rec = [c for c in cabs if c.get("recommended")]
                    self.check(s, len(rec) <= 1,
                               f"recommended 至多 1 个（实际 {len(rec)}）")
                    self.check(s, (first.get("latitude") is not None),
                               "柜体含纬度坐标", first.get("latitude"))
            else:
                self.check(s, False, "响应为 JSON", str(body)[:100])
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 4. 快递员揽收 ----------
        s = self.step(4, "快递员揽收（POST /api/business/collect）")
        try:
            _, cou = self._req("GET", "/api/entities/couriers?page=1&size=1")
            rows = (cou.get("rows") or cou.get("data") or []) if isinstance(cou, dict) else []
            courier_id = rows[0]["courier_id"] if rows else 1
            self.ctx["courier_id"] = courier_id
            s.request = {"order_code": self.ctx.get("order_code"), "courier_id": courier_id}
            status, body = self._req("POST", "/api/business/collect", json=s.request)
            s.status, s.body = status, body
            self.check(s, status == 200, "HTTP 200", status)
            if isinstance(body, dict):
                st = pkg_status(body)
                self.check(s, st == "SEND_COLLECTED",
                           f"包裹状态变 SEND_COLLECTED（实际 {st}）")
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 5. 快递员投递存柜 ----------
        s = self.step(5, "快递员投递存柜（POST /api/business/store, from_send_code）")
        try:
            s.request = {"courier_id": self.ctx.get("courier_id"),
                         "from_send_code": self.ctx.get("order_code"),
                         "pack_recommendation_id": self.ctx.get("rec_id")}
            status, body = self._req("POST", "/api/business/store", json=s.request)
            s.status, s.body = status, body
            self.check(s, status in (200, 201), "HTTP 200/201", status)
            if isinstance(body, dict):
                self.check(s, bool(body.get("pickup_code")),
                           f"生成取件码（{body.get('pickup_code')}）")
                self.check(s, bool(body.get("cell_code")),
                           f"分配格口（{body.get('cabinet_code')} / {body.get('cell_code')}）")
                self.ctx["pickup_code"] = body.get("pickup_code")
                self.ctx["deliver_pid"] = (body.get("package") or {}).get("package_id")
                pkg = body.get("package") or {}
                self.check(s, pkg.get("from_send_id") == self.ctx.get("send_pid"),
                           "投递件关联到原寄件单（from_send_id）",
                           pkg.get("from_send_id"))
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 6. 用户取件预告 ----------
        s = self.step(6, "用户取件预告（GET /api/m/pickup/preview）")
        try:
            token, uid = self._user_login(phone)
            self.ctx["token"] = token
            hdr = {"Authorization": f"Bearer {token}"} if token else {}
            self.check(s, bool(token), "手机号验证码登录换取 token")
            status, body = self._req(
                "GET", f"/api/m/pickup/preview?code={self.ctx.get('pickup_code')}",
                headers=hdr)
            s.status, s.body = status, body
            self.check(s, status == 200, "HTTP 200", status)
            if isinstance(body, dict):
                self.check(s, body.get("cabinet_code") is not None, "返回柜机编号")
                self.check(s, "cell_code" not in body or body.get("cell_hint"),
                           "取件前不泄露格口号（cell_hint 提示）")
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 7. 用户取件 ----------
        s = self.step(7, "用户取件（POST /api/business/pickup）")
        try:
            s.request = {"pickup_code": self.ctx.get("pickup_code")}
            status, body = self._req("POST", "/api/business/pickup", json=s.request)
            s.status, s.body = status, body
            self.check(s, status == 200, "HTTP 200", status)
            if isinstance(body, dict):
                st = pkg_status(body)
                self.check(s, st == "PICKED", f"包裹置为 PICKED（实际 {st}）")
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 8. 超时 → 支付闸门 ----------
        s = self.step(8, "超时未缴费取件被 402 拦截（支付闸门）")
        try:
            st2, b2 = self._req("POST", "/api/business/store", json={
                "courier_id": self.ctx.get("courier_id"), "user_phone": phone,
                "user_name": "E2E 超时件", "size_type": "SMALL", "weight": 0.3})
            self.check(s, st2 in (200, 201), "造一件新包裹", st2)
            if isinstance(b2, dict):
                pid = (b2.get("package") or {}).get("package_id")
                code2 = b2.get("pickup_code")
                self.ctx["expire_pid"] = pid
                self.ctx["expire_code"] = code2
                # 强制置为超时（走真实业务接口，不用 SQL 改库）
                st3, b3 = self._req("POST", f"/api/business/{pid}/force-expire")
                self.check(s, st3 == 200, f"force-expire 成功", st3)
                st4, b4 = self._req("POST", "/api/business/pickup",
                                    json={"pickup_code": code2})
                s.status, s.body = st4, b4
                self.check(s, st4 == 402, "未缴费取件返回 402 NEED_PAYMENT", st4)
                if isinstance(b4, dict):
                    self.check(s, b4.get("error") == "NEED_PAYMENT",
                               "错误码为 NEED_PAYMENT", b4.get("error"))
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 9. 支付 ----------
        s = self.step(9, "超时支付（POST /api/business/pay-overtime）")
        try:
            s.request = {"package_ids": [self.ctx.get("expire_pid")]}
            status, body = self._req("POST", "/api/business/pay-overtime", json=s.request)
            s.status, s.body = status, body
            self.check(s, status == 200, "HTTP 200", status)
            if isinstance(body, dict):
                self.check(s, int(body.get("paid_count") or 0) == 1,
                           f"paid_count == 1（实际 {body.get('paid_count')}）")
                self.check(s, float(body.get("total_fee") or 0) > 0,
                           f"实收金额 > 0（{body.get('total_fee')}）")
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        # ---------- 10. 缴费后取件放行 ----------
        s = self.step(10, "缴费后取件放行（闭环收尾）")
        try:
            status, body = self._req("POST", "/api/business/pickup",
                                     json={"pickup_code": self.ctx.get("expire_code")})
            s.status, s.body = status, body
            self.check(s, status == 200, "缴费后取件返回 200", status)
            if isinstance(body, dict):
                st = pkg_status(body)
                self.check(s, st == "PICKED", f"包裹最终 PICKED（实际 {st}）")
        except Exception as exc:  # noqa: BLE001
            s.ok, s.error = False, f"{type(exc).__name__}: {exc}"

        return self.steps

    def _user_login(self, phone):
        """手机号验证码登录（dev 模式回传 dev_code）。"""
        st, body = self._req("POST", "/api/m/auth/send-code", json={"phone": phone})
        if st != 200 or not isinstance(body, dict):
            return None, None
        code = body.get("dev_code")
        if not code:
            return None, None
        st2, b2 = self._req("POST", "/api/m/auth/login",
                            json={"phone": phone, "code": code})
        if st2 != 200 or not isinstance(b2, dict):
            return None, None
        return b2.get("token"), (b2.get("identity") or {}).get("id")


def cleanup(ctx):
    """清理本次 E2E 造的数据（只删自己造的，不碰演示数据）。"""
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    try:
        import db
    except Exception as exc:  # noqa: BLE001
        print(f"  [清理跳过] 无法导入 db: {exc}")
        return
    pids = [p for p in (ctx.get("send_pid"), ctx.get("deliver_pid"),
                        ctx.get("expire_pid")) if p]
    removed = 0
    for pid in pids:
        cell = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))
        for table in ("t_notice", "t_exception_log", "t_pickup_record", "t_device_command"):
            try:
                db.execute(f"DELETE FROM {table} WHERE package_id=%s", (pid,))
            except Exception:  # noqa: BLE001
                pass
        for sql in ("DELETE FROM t_pack_task WHERE package_id=%s",
                    "DELETE FROM t_pay_order WHERE biz_type='OVERTIME' AND biz_id=%s",
                    "DELETE FROM t_package WHERE package_id=%s"):
            try:
                db.execute(sql, (pid,))
            except Exception:  # noqa: BLE001
                pass
        removed += 1
        if cell and cell.get("cell_id"):
            try:
                still = db.query_one(
                    "SELECT COUNT(*) AS n FROM t_package WHERE cell_id=%s "
                    "AND status IN ('STORED','EXPIRED','SEND_WAIT_PICKUP',"
                    "'SEND_COLLECTED','EXCEPTION')", (cell["cell_id"],))
                if int(still["n"]) == 0:
                    db.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s",
                               (cell["cell_id"],))
            except Exception:  # noqa: BLE001
                pass
    # 清理本次 AI 推荐落库
    if ctx.get("rec_id"):
        try:
            db.execute("DELETE FROM t_pack_recommendation WHERE recommendation_id=%s",
                       (ctx["rec_id"],))
        except Exception:  # noqa: BLE001
            pass
    print(f"  已清理 {removed} 件 E2E 包裹"
          + (f" 与 1 条推荐记录" if ctx.get("rec_id") else ""))


def main():
    ap = argparse.ArgumentParser(description="端到端闭环核验")
    ap.add_argument("--host", default="http://127.0.0.1:5000")
    ap.add_argument("--mode", default="http", choices=["http", "inproc"])
    ap.add_argument("--keep", action="store_true", help="保留造的数据（默认清理）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    print("=" * 78)
    print(" 端到端闭环核验 · 智能快递柜管理系统")
    print("=" * 78)
    print(f" 模式 : {args.mode}")
    print(f" 时间 : {datetime.now(TZ).isoformat(timespec='seconds')}")

    if args.mode == "http":
        try:
            import requests
        except ImportError:
            print("缺少 requests"); return 2
        s = requests.Session()
        s.trust_env = False
        try:
            h = s.get(f"{args.host}/api/health", timeout=10)
            print(f" 服务 : {args.host}  health={h.status_code}")
            if h.status_code != 200:
                print("[!] 服务不健康，改用 --mode inproc 或先修服务")
                return 2
        except Exception as exc:  # noqa: BLE001
            print(f"[!] 连不上 {args.host}: {exc}")
            print("[!] 提示：服务不可用时用 --mode inproc 做进程内等效验证")
            return 2
        base = args.host.rstrip("/")

        class HttpAdapter:
            def get(self, path, **kw):
                return s.get(base + path, timeout=60, **kw)

            def post(self, path, **kw):
                return s.post(base + path, timeout=60, **kw)

        client = HttpAdapter()
    else:
        sys.path.insert(0, ROOT)
        sys.path.insert(0, os.path.join(ROOT, "backend"))
        os.environ.setdefault("NOTIFY_WORKER", "0")
        import app as app_module  # noqa: E402
        app_module.app.config.update(TESTING=True)
        client = app_module.app.test_client()
        print(" 服务 : 进程内 test_client")

    e2e = E2E(client)
    try:
        steps = e2e.run()
    finally:
        if not args.keep:
            cleanup(e2e.ctx)

    print("\n" + "-" * 78)
    print(f"{'#':<3}{'步骤':<44}{'结果':<8}")
    print("-" * 78)
    for st in steps:
        mark = "✅ PASS" if st.ok else "❌ FAIL"
        print(f"{st.no:<3}{st.name[:43]:<44}{mark}")
        for d in st.details:
            print(f"     {d}")
        if st.error:
            print(f"     ✗ 异常: {st.error}")
        if not st.ok and st.body is not None:
            print(f"     响应: {json.dumps(st.body, ensure_ascii=False)[:300]}")
    print("-" * 78)

    passed = sum(1 for st in steps if st.ok)
    total = len(steps)
    ok = passed == total
    print(f"\n闭环结果：{passed}/{total} 步通过 —— "
          + ("✅ 端到端闭环全部通过" if ok else "❌ 存在失败步骤"))
    print(f"闭环路径：寄件下单 → AI 包装推荐 → 地图找柜 → 快递员揽收 → 投递存柜 → "
          f"取件预告 → 用户取件 → 支付闸门(402) → 超时支付 → 缴费后取件放行")

    if args.json_out:
        payload = {
            "生成时间": datetime.now(TZ).isoformat(timespec="seconds"),
            "模式": args.mode,
            "通过": passed, "总数": total, "闭环通过": ok,
            "步骤": [{"编号": st.no, "名称": st.name, "ok": st.ok,
                      "状态码": st.status, "断言": st.details,
                      "请求": st.request, "异常": st.error} for st in steps],
        }
        os.makedirs(os.path.dirname(args.json_out) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"逐步骤结果已写入: {args.json_out}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
