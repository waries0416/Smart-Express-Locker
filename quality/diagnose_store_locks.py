# 取证：store 并发锁环形等待（只读快照）
#
# 背景：20 并发跑 /api/business/store 时，全部请求 30s 超时，
#       随后 MySQL 出现「同一批事务互为等待方」的环形等待。
#       本脚本把当时的现场（等待图 + 锁等待对数）定格成可复核的文本。
#
# 用法：python quality/diagnose_store_locks.py
import sys

sys.path.insert(0, r"D:\softwaretest")
sys.path.insert(0, r"D:\softwaretest\backend")
import db  # noqa: E402


def main():
    print("=" * 78)
    print(" store 并发锁诊断（只读）")
    print("=" * 78)

    # 1) 核心指标
    for name in ("Threads_connected", "Threads_running", "Max_used_connections",
                 "Innodb_row_lock_waits", "Innodb_row_lock_time_avg",
                 "Innodb_row_lock_current_waits", "Innodb_deadlocks"):
        try:
            r = db.query_one("SHOW STATUS LIKE %s", (name,))
            print(f"  {name:<32}: {r['Value'] if r else 'n/a'}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:<32}: ERR {exc}")

    # 2) 未提交事务
    print("\n--- 未提交事务（information_schema.innodb_trx）---")
    try:
        trx = db.query(
            "SELECT trx_id, trx_state, trx_mysql_thread_id AS thr, trx_started, "
            "TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS age_s, "
            "LEFT(trx_query, 90) AS q FROM information_schema.innodb_trx "
            "ORDER BY trx_started")
    except Exception as exc:  # noqa: BLE001
        print("  查询失败:", exc)
        trx = []
    for t in trx:
        print(f"  trx={t['trx_id']} state={t['trx_state']} thr={t['thr']} "
              f"age={t['age_s']}s")
    print(f"  合计 {len(trx)} 个未提交事务")

    # 3) 等待图：谁在等谁
    print("\n--- 等待图（谁等谁）---")
    try:
        waits = db.query(
            "SELECT w.REQUESTING_ENGINE_TRANSACTION_ID AS wait_trx, "
            "w.BLOCKING_ENGINE_TRANSACTION_ID AS block_trx "
            "FROM performance_schema.data_lock_waits w")
    except Exception as exc:  # noqa: BLE001
        print("  查询失败:", exc)
        waits = []
    edges = [(str(w["wait_trx"]), str(w["block_trx"])) for w in waits]
    for a, b in edges:
        print(f"  trx {a}  --等待-->  trx {b}")
    print(f"  合计 {len(edges)} 条等待边")

    # 4) 环检测（简单 DFS）
    graph = {}
    for a, b in edges:
        graph.setdefault(a, set()).add(b)

    cycles = []

    def dfs(node, path, seen):
        if node in seen:
            if node == path[0]:
                cycles.append(list(path))
            return
        seen.add(node)
        for nxt in graph.get(node, ()):
            dfs(nxt, path + [nxt], seen)
        seen.discard(node)

    for start in list(graph):
        dfs(start, [start], set())

    print("\n--- 环检测 ---")
    if cycles:
        uniq = {tuple(sorted(set(c))) for c in cycles}
        print(f"  检测到 {len(uniq)} 个等待环（任意两个事务互为对方的等待方）")
        for c in list(uniq)[:3]:
            print("   环成员事务:", " → ".join(c))
        print("\n  结论：这不是普通排队，而是**环形等待（死锁型）**：")
        print("        · 事务之间互相持有对方需要的行锁，没人能前进；")
        print("        · MySQL 未自动选牺牲者回滚（因为不是纯粹的单点死锁检测路径），")
        print("          现场表现为所有请求一起挂住，直到客户端 30s 超时。")
    else:
        print("  未检测到环（当前无等待或多条链不是环形）")

    print("\n--- 根因定位（对应 backend/business.py store()）---")
    print("  SQL: SELECT cell_id ... WHERE status='FREE' AND size_type IN (...) ")
    print("       ORDER BY cell_id LIMIT 1 FOR UPDATE")
    print("  问题：")
    print("    1) FOR UPDATE 锁的是**扫描到的全部 FREE 行**，不是最终选中的那 1 个格口；")
    print("    2) 无索引支撑该过滤（status/size_type 组合），扫描集合大、锁面大；")
    print("    3) 多个事务同时扫同一批行 → 各自持有一部分、又需要对方持有的部分 → 环形等待。")
    print("  建议（供 backend-engineer 参考，本次不修改代码）：")
    print("    · 用 SKIP LOCKED 或先按 cell_id 单行原子占用：")
    print("      UPDATE t_cell SET status='OCCUPIED' WHERE cell_id=(SELECT ... LIMIT 1) ")
    print("        AND status='FREE'; 再判断影响行数 ==1；")
    print("    · 或给 (status, size_type, cell_id) 建索引，把锁面收敛到索引区间；")
    print("    · 事务内禁止长时间持有行锁，把通知等旁路操作移到事务外。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
