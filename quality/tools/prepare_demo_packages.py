# -*- coding: utf-8 -*-
"""录制前准备：在 CAB-001 上造 1 件待取 + 1 件超时未缴，供演示视频取件场景使用。

为什么需要这个脚本：
    reset_demo_data.py 设计上不会把 PICKED 改回 STORED（避免"已取件却还在柜里"
    的矛盾数据），所以反复录几轮之后，演示用的待取件就被取走了。
    而库里剩下的 STORED / EXPIRED 件分散在 CAB-002、CAB-030 等柜体，
    柜机首页默认在 CAB-001，取件接口会校验柜体归属 → 409。

做法（全部走真实业务接口，不直接写库伪造状态）：
    1) 调 POST /api/business/store 在 CAB-001 真实存一件（走完整格口分配 + 事务）
    2) 需要超时件时，把这件的 store_time/expire_time 改成已过期、状态置 EXPIRED
       —— 这一步是"把时间拨到 48 小时后"，模拟真实的超时状态，
          与压测脚本 scene_pay 的做法一致，属测试数据构造而非篡改业务结果。

产出：打印可直接用于录制的取件码，并写 quality/logs/video-shots/demo_codes.json
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, r"D:\softwaretest")
sys.path.insert(0, r"D:\softwaretest\backend")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:5000"
OUT = os.path.join(r"D:\softwaretest", "quality", "logs", "video-shots", "demo_codes.json")


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:  # noqa: BLE001
            return e.code, {"error": "non-json"}


def find_cabinet_id(code="CAB-001"):
    import db
    r = db.query_one("SELECT cabinet_id FROM t_cabinet WHERE cabinet_code=%s", (code,))
    return r["cabinet_id"] if r else None


def find_courier():
    import db
    r = db.query_one("SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
    return r["courier_id"] if r else None


def store_one(cabinet_id, phone, name, size="SMALL"):
    courier = find_courier()
    st, body = post("/api/business/store", {
        "courier_id": courier,
        "user_phone": phone,
        "user_name": name,
        "size_type": size,
        "weight": 0.5,
        "cabinet_id": cabinet_id,
    })
    if st not in (200, 201):
        raise SystemExit(f"[!] 存件失败 {st}: {body}")
    pkg = body.get("package") or {}
    return {
        "package_id": pkg.get("package_id"),
        "pickup_code": body.get("pickup_code"),
        "cabinet_code": pkg.get("cabinet_code"),
        "cell_code": pkg.get("cell_code"),
    }


def make_expired(package_id, hours=73):
    import db
    db.execute(
        "UPDATE t_package SET status='EXPIRED', overtime_fee=1.00, overtime_fee_paid=0, "
        "store_time=DATE_SUB(NOW(), INTERVAL %s HOUR), "
        "expire_time=DATE_SUB(NOW(), INTERVAL 1 HOUR) WHERE package_id=%s",
        (hours, package_id))
    r = db.query_one("SELECT status, overtime_fee_paid, overtime_fee FROM t_package "
                     "WHERE package_id=%s", (package_id,))
    # PyMySQL 的 DECIMAL 会返回 Decimal，json 不能直接序列化
    return ({"status": r["status"],
             "overtime_fee_paid": int(r["overtime_fee_paid"]),
             "overtime_fee": float(r["overtime_fee"] or 0)} if r else None)


def main():
    ap = argparse.ArgumentParser(description="为演示视频准备 CAB-001 上的可演示包裹")
    ap.add_argument("--cabinet", default="CAB-001")
    ap.add_argument("--phone", default="15800000001", help="收件人手机号（演示账号）")
    ap.add_argument("--no-expired", action="store_true", help="不造超时件")
    args = ap.parse_args()

    cab_id = find_cabinet_id(args.cabinet)
    if not cab_id:
        raise SystemExit(f"[!] 找不到柜体 {args.cabinet}")
    print(f"[*] 目标柜体 {args.cabinet} (id={cab_id})")

    result = {"cabinet": args.cabinet}

    print("[1/2] 造一件待取件（走真实 /api/business/store）")
    stored = store_one(cab_id, args.phone, "演示用户")
    print(f"     -> 取件码 {stored['pickup_code']}  格口 {stored['cell_code']}")
    result["stored"] = stored

    if not args.no_expired:
        print("[2/2] 造一件超时未缴件（存件后把时间拨到 73 小时前）")
        exp = store_one(cab_id, args.phone, "演示用户")
        # 清掉可能的流水残留，保证"未缴费"
        import db
        db.execute("DELETE FROM t_exception_log WHERE package_id=%s "
                   "AND exception_type='TIMEOUT'", (exp["package_id"],))
        state = make_expired(exp["package_id"])
        print(f"     -> 取件码 {exp['pickup_code']}  格口 {exp['cell_code']}  状态 {state}")
        result["expired"] = exp
        result["expired_state"] = state

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print("\n===== 录制用取件码 =====")
    print(f"  待取件    : {result['stored']['pickup_code']}  "
          f"({result['stored']['cabinet_code']} / {result['stored']['cell_code']})")
    if "expired" in result:
        print(f"  超时未缴  : {result['expired']['pickup_code']}  "
              f"({result['expired']['cabinet_code']} / {result['expired']['cell_code']})")
    print(f"  落盘      : {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
