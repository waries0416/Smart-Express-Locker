# 测试进程级互斥锁：保证同一时刻只有一个**测试进程**在写 smart_locker 库。
#
# ---------------------------------------------------------------------------
# 为什么必须有它（R9b flaky 实测 2026-11-19 01:0x；与 quality 交叉核实）
# ---------------------------------------------------------------------------
# 现象：同一条命令（cd backend && python -m unittest discover -s tests -p "test_*.py"）
#   单独跑 ~12s 全绿；但只要**还有别的进程/服务同时在写同一个库**，就会变成
#   60~160s、几十个用例随机报错，典型报错：
#       pymysql.err.OperationalError: (1213, 'Deadlock found when trying to get lock')
#   实测：两个测试进程并发跑 → A: 158.8s / 46 errors，B: 106.0s / 61 errors。
#
# 根因是同一类的**两个来源**（互相叠加，不矛盾）：
#
#   来源① 多个测试进程并发写库（SHOW ENGINE INNODB STATUS 死锁图逐字确认）：
#     · 进程 A 的 _fixtures.purge_residue() 执行
#           DELETE FROM t_cell WHERE cabinet_id IN (SELECT ... cabinet_code LIKE 'ZZT%')
#       删除父表 t_cell 时要对子表 t_package 做外键检查 → 持有 t_package 的 S 锁，
#       同时等待 t_cell 行的 X 锁；
#     · 进程 B 的 Fixture.make_expired_package() 正在
#           INSERT INTO t_package(... cell_id=<同一批 ZZT 格口> ...)
#       → 持有 t_cell 的 X 锁，同时等待 t_package 的插入意向锁（X）。
#     两个进程各持一把、各等一把 → 环形等待 → 1213；随后 50s 锁等待超时连环报错。
#     这条环**不可能发生在单进程内**（单进程里测试是串行的），所以它不是 R9b 的
#     CAS 逻辑问题，也不是用例依赖数据的问题，而是"多个进程共用一个库"。
#
#   来源② 库被外部进程污染/争用（quality 复测时确认）：R9b 复测期间起了 Flask
#     服务与测试同时写库；压测/录制脚本还泄漏了 1879 个孤儿用户
#     （t_user 120 → 2041），把全量测试从 12s 拖到 60~160s，并放大竞争。
#     环境清理后（t_user 回到 161）连跑 3 次均 11.5~12.2s，不再复现。
#
# 解法：用 MySQL 命名锁 GET_LOCK 做**跨测试进程**互斥（MySQL 官方推荐做法），
#   第二个进程排队等待而不是同时写库。锁由一条**独立连接**持有（不走连接池），
#   进程退出/连接断开时 MySQL 自动释放，不存在"崩溃后锁不释放"的风险。
#   数据库不可用时直接放行（此时用例本身会 skip，不该因为锁把整个套件搞红）。
#
# ⚠ 覆盖边界（务必知悉）：这把锁只约束**导入了本模块的测试进程**。
#   Flask 服务、quality 的压测/录制/造数脚本**不会**来抢这把锁，所以：
#     · 跑单元测试时不要同时开着写库的服务或压测脚本（否则会重新引入竞争）；
#     · 若将来要并行跑测试，正确做法是给每个进程独立 database/schema，
#       而不是把本锁去掉。
#
# 说明：可用环境变量 UNITTEST_LOCK_WAIT 调整等待上限（默认 600s）。
# ---------------------------------------------------------------------------
import atexit
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pymysql  # noqa: E402

from config import DB_CONFIG  # noqa: E402

LOCK_NAME = "smart_locker_unittest_suite"
WAIT_SECONDS = int(os.getenv("UNITTEST_LOCK_WAIT", "600"))

_conn = None


def _connect():
    return pymysql.connect(
        host=DB_CONFIG["host"], port=DB_CONFIG["port"], user=DB_CONFIG["user"],
        password=DB_CONFIG["password"], database=DB_CONFIG.get("database") or None,
        charset=DB_CONFIG["charset"], autocommit=True,
        cursorclass=pymysql.cursors.DictCursor)


def acquire():
    """获取进程级测试锁；可重复调用（幂等）。"""
    global _conn
    if _conn is not None:
        return
    try:
        conn = _connect()
    except Exception as exc:                       # 库不可用 → 放行，交给用例自己 skip
        print(f"[tests] DB unavailable, suite lock skipped ({exc})", file=sys.stderr)
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK(%s, 0) AS got", (LOCK_NAME,))
            if cur.fetchone()["got"] == 1:
                print(f"[tests] suite lock acquired: {LOCK_NAME}", file=sys.stderr)
            else:
                print(f"[tests] another test process is using the DB; waiting up to {WAIT_SECONDS}s"
                      f" (runs are serialized, not corrupted) ...", file=sys.stderr)
                cur.execute("SELECT GET_LOCK(%s, %s) AS got", (LOCK_NAME, WAIT_SECONDS))
                if cur.fetchone()["got"] != 1:
                    conn.close()
                    raise RuntimeError(
                        f"等待测试互斥锁 {LOCK_NAME} 超过 {WAIT_SECONDS}s：另一个测试进程"
                        f"长时间占用数据库。请稍后重试，或把 UNITTEST_LOCK_WAIT 调大。")
                print("[tests] suite lock acquired after waiting; running tests", file=sys.stderr)
    except RuntimeError:
        raise
    except Exception as exc:                       # 锁机制本身出错不该让套件红
        print(f"[tests] suite lock failed ({exc}), continue without it", file=sys.stderr)
        try:
            conn.close()
        except Exception:
            pass
        return
    _conn = conn
    atexit.register(release)


def release():
    global _conn
    if _conn is None:
        return
    try:
        with _conn.cursor() as cur:
            cur.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
    except Exception:
        pass
    try:
        _conn.close()
    except Exception:
        pass
    _conn = None


# 导入即加锁：所有 test_*.py 都在模块导入阶段（早于任何用例执行）import 本模块，
# 而 unittest discover 会先导入完全部模块再跑用例，因此锁在整个套件期间一直持有。
acquire()
