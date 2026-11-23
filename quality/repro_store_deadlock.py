# 复现：并发存件在全局选格口时的行锁死锁（只读观测 + 受控复现）
#
# 目的：把"20 并发 store 全部 30s 超时"这件事，从"我观察到慢"
#       升级成"可复现、可归因"的结论。
#
# 复现思路：
#   后端的 store 事务里执行
#       SELECT ... WHERE status='FREE' AND size_type IN (...) ORDER BY cell_id LIMIT 1 FOR UPDATE
#   这是一个**无索引扫描 + 排他锁**：InnoDB 会对扫描过的 FREE 行加锁。
#   多个并发事务同时扫同一批 FREE 行时，彼此持有 A 行、等待 B 行 → 死锁/长等待。
#   本脚本用两个独立连接精确复现该锁冲突，并用 innodb_lock_wait_timeout 限时，
#   避免再次把连接池占满。
import sys
import threading
import time

sys.path.insert(0, r"D:\softwaretest")
sys.path.insert(0, r"D:\softwaretest\backend")
from config import get_conn  # noqa: E402  直连，不进池

SQL = ("SELECT cell_id, cabinet_id, cell_code, size_type FROM t_cell "
       "WHERE status='FREE' AND size_type IN (%s) "
       "ORDER BY cell_id LIMIT 1 FOR UPDATE")

results = {}


def worker(name, delay):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION innodb_lock_wait_timeout=5")
            cur.execute("SET AUTOCOMMIT=0")
            t0 = time.perf_counter()
            try:
                cur.execute(SQL, ("SMALL",))
                row = cur.fetchone()
                results[name] = {"locked_cell": row["cell_id"] if row else None,
                                 "waited_ms": round((time.perf_counter() - t0) * 1000, 1),
                                 "status": "acquired"}
                time.sleep(delay)          # 持锁不退，制造重叠
                conn.commit()
                results[name]["committed"] = True
            except Exception as exc:  # noqa: BLE001
                results[name] = {"status": "failed",
                                 "error": f"{type(exc).__name__}: {exc}",
                                 "waited_ms": round((time.perf_counter() - t0) * 1000, 1)}
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("SET AUTOCOMMIT=1")
        except Exception:  # noqa: BLE001
            pass
        conn.close()


print("=== 复现：两个并发事务对同一批 FREE 格口做 SELECT ... FOR UPDATE ===")
print(f"SQL: {SQL}\n")

t1 = threading.Thread(target=worker, args=("T1", 2.0))
t2 = threading.Thread(target=worker, args=("T2", 0.0))
t1.start()
time.sleep(0.3)      # 让 T1 先拿到锁
t2.start()
t1.join()
t2.join()

for k in ("T1", "T2"):
    print(f"  {k}: {results.get(k)}")

print("\n=== 解读 ===")
ok1 = results.get("T1", {}).get("status") == "acquired"
t2info = results.get("T2", {})
if ok1 and t2info.get("status") == "failed":
    print("  T2 在 T1 持锁期间无法获得同一批 FREE 行的排他锁 → 等待超时。")
    print(f"  这正是 store 在高并发下集体卡住的机制：")
    print(f"    · 锁粒度 = 扫描到的全部 FREE 行（不是只锁最终选中的那 1 个格口）")
    print(f"    · 无索引支撑 → 扫描集合随 FREE 行数变大，锁冲突面随之变大")
    print(f"    · 并发越高，事务互相等待链越长 → 请求全部堵在 SELECT ... FOR UPDATE")
elif ok1 and t2info.get("status") == "acquired":
    print("  两次都拿到了锁（T1 已提交后 T2 才进入）→ 本次未复现锁冲突，")
    print("  说明该争用依赖真实并发时序，需以压测原始数据为准。")
else:
    print("  复现未按预期完成，结果见上。")
