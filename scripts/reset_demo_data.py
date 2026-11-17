# 演示数据准备脚本
#
# 作用：把演示账号名下的包裹调整成"可演示"的状态组合——
#   若干件正常待取（STORED，未超时）+ 至少一件超时待缴费（EXPIRED，未缴费），
#   这样触屏端"扫码取件 → 立即取件"与"超时缴费 → 自动开柜"两条路径都能演示。
#
# 为什么需要它：跑过端到端测试或反复演示后，包裹会被逐个取走（PICKED），
#   库里只剩超时件甚至一件不剩，演示时"待取列表"是空的。此脚本可随时复原。
#
# 用法：
#   .venv\Scripts\python.exe scripts\reset_demo_data.py
#   .venv\Scripts\python.exe scripts\reset_demo_data.py --phone 15800000001 --stored 3
#   .venv\Scripts\python.exe scripts\reset_demo_data.py --clean   # 顺带清理验证码/指令/票据临时数据
#
# 安全边界：
#   · 只动指定手机号用户名下的包裹，不动别人的数据；
#   · 只把 EXPIRED（未取件、无取件流水）改成 STORED，不碰 PICKED 记录，避免产生"已取件却又在柜"的矛盾数据；
#   · 格口状态本来就因 EXPIRED 处于 OCCUPIED，改状态不需要动 t_cell。
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import db  # noqa: E402


def find_user(phone):
    return db.query_one("SELECT user_id, name, phone FROM t_user WHERE phone=%s", (phone,))


def reset(phone, want_stored, keep_expired, clean):
    user = find_user(phone)
    if not user:
        print(f"[x] 手机号 {phone} 未建档，无法准备演示数据")
        return 1
    uid = user["user_id"]
    print(f"[*] 演示账号：{user['name']}（{phone}）user_id={uid}")

    # 只挑 EXPIRED 且从未取过的件：这些件仍占着格口，状态改成 STORED 不会产生矛盾
    expired = db.query("""
        SELECT package_id, tracking_no, pickup_code, status, cabinet_id, cell_id
        FROM t_package
        WHERE user_id=%s AND direction='RECEIVE' AND status='EXPIRED'
          AND pickup_time IS NULL
        ORDER BY package_id""", (uid,))
    if not expired:
        print("[!] 该账号名下没有可复用的超时件，请先在触屏端存一件或重新导入种子数据")
        return 1

    stored_now = db.query_one(
        "SELECT COUNT(*) AS n FROM t_package WHERE user_id=%s AND direction='RECEIVE' "
        "AND status='STORED'", (uid,))["n"]
    print(f"[*] 当前待取（STORED）：{stored_now} 件，可复用超时件：{len(expired)} 件")

    need = max(0, want_stored - int(stored_now))
    turned = expired[:need]
    for p in turned:
        # 存入时间设为 6 小时前，到期时间设为 42 小时后 → 未超时、离超时还有距离
        db.execute("""
            UPDATE t_package
            SET status='STORED',
                store_time=DATE_SUB(NOW(), INTERVAL 6 HOUR),
                expire_time=DATE_ADD(NOW(), INTERVAL 42 HOUR),
                pickup_time=NULL, overtime_fee=NULL, overtime_fee_paid=0
            WHERE package_id=%s""", (p["package_id"],))
        print(f"    + 转回待取：{p['tracking_no']}  取件码 {p['pickup_code']}")

    # 保留 keep_expired 件超时未缴费的，用于演示缴费流程
    left = expired[need:]
    for i, p in enumerate(left):
        if i < keep_expired:
            db.execute("""
                UPDATE t_package
                SET status='EXPIRED',
                    store_time=DATE_SUB(NOW(), INTERVAL 72 HOUR),
                    expire_time=DATE_SUB(NOW(), INTERVAL 24 HOUR),
                    pickup_time=NULL, overtime_fee=1.00, overtime_fee_paid=0
                WHERE package_id=%s""", (p["package_id"],))
            print(f"    ! 保持超时：{p['tracking_no']}  取件码 {p['pickup_code']}（待缴 ¥1.00）")

    if clean:
        n1 = db.execute("DELETE FROM t_sms_code WHERE created_at < DATE_SUB(NOW(), INTERVAL 1 DAY)")
        n2 = db.execute("DELETE FROM t_device_command WHERE created_at < DATE_SUB(NOW(), INTERVAL 1 DAY)")
        n3 = db.execute("DELETE FROM t_qr_ticket WHERE status IN ('EXPIRED','CANCELLED')")
        print(f"[*] 清理临时数据：验证码 {n1} 条、指令 {n2} 条、失效票据 {n3} 条")

    # 汇总输出，方便直接照着演示
    print("\n===== 演示数据就绪 =====")
    rows = db.query("""
        SELECT p.pickup_code, p.status, p.overtime_fee_paid, p.expire_time,
               cab.cabinet_code, cell.cell_code
        FROM t_package p
        JOIN t_cabinet cab ON cab.cabinet_id=p.cabinet_id
        JOIN t_cell cell   ON cell.cell_id=p.cell_id
        WHERE p.user_id=%s AND p.direction='RECEIVE' AND p.status IN ('STORED','EXPIRED')
        ORDER BY p.status, p.package_id""", (uid,))
    for r in rows:
        tag = "待取" if r["status"] == "STORED" else ("超时待缴费" if not r["overtime_fee_paid"] else "超时已缴费")
        print(f"  {r['cabinet_code']} {r['cell_code']}  取件码 {r['pickup_code']}  [{tag}]")
    print(f"\n共 {len(rows)} 件可演示。触屏端输入取件码，或手机扫码登录后点「立即取件」。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="准备快递柜演示数据")
    ap.add_argument("--phone", default="15800000001", help="演示账号手机号，默认 15800000001")
    ap.add_argument("--stored", type=int, default=2, help="希望保留的正常待取件数，默认 2")
    ap.add_argument("--keep-expired", type=int, default=1, help="希望保留的超时未缴费件数，默认 1")
    ap.add_argument("--clean", action="store_true", help="顺带清理验证码/指令/失效票据")
    args = ap.parse_args()
    sys.exit(reset(args.phone, args.stored, args.keep_expired, args.clean))


if __name__ == "__main__":
    main()
