# 后端数据库访问助手
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_conn  # noqa: E402


@contextmanager
def transaction():
    """在同一连接上开启**真正**的事务，供 SELECT ... FOR UPDATE 等需要
    行级排他锁 + 后续写操作在同一事务内的场景使用（防止并发争用）。

    注意：config.get_conn() 的连接默认 autocommit=True，若不显式关闭，
    每条语句都会立即提交，导致「FOR UPDATE 取锁 → 后续 UPDATE」被拆成
    两个独立事务，行锁提前释放；级联删除也会失去原子性。

    A2 引入 DBUtils 连接池后，池返回的是 SteadyDB 包装连接，不暴露
    PyMySQL 的 conn.autocommit() 方法，故这里用标准 SQL SET AUTOCOMMIT=0/1
    开关事务，对直连与池化连接均有效；退出时恢复 autocommit 并归还连接。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET AUTOCOMMIT=0")  # 同 conn.autocommit(False)，真正开启事务
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("SET AUTOCOMMIT=1")
        except Exception:
            pass
        conn.close()


def query(sql, args=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args or ())
            return cur.fetchall()
    finally:
        conn.close()


def query_one(sql, args=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchone()
    finally:
        conn.close()


def execute(sql, args=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args or ())
            return cur.rowcount
    finally:
        conn.close()


def insert(sql, args=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args or ())
            return cur.lastrowid
    finally:
        conn.close()


def call_proc(proc_name, args=None):
    """调用存储过程并返回结果集（适用于 SELECT 型过程）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.callproc(proc_name, args or ())
            # callproc 后第一个结果集
            result = cur.fetchall()
            return result
    finally:
        conn.close()
