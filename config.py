# 智能快递柜管理系统 · 统一数据库配置
# 后端(backend/app.py) 与 数据生成脚本(scripts/*.py) 共用本文件。
# 可通过环境变量覆盖（便于在机房/服务器环境部署）。
import os
import threading

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "127.0.0.1"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "123456"),
    "database": os.getenv("DB_NAME", "smart_locker"),
    "charset":  "utf8mb4",
    "autocommit": True,
}

# ---- 数据库连接池（S9 性能实现手段） ----
# 引 DBUtils.PooledDB：默认库连接全部取自池，业务模块零改动（get_conn 签名不变）。
# 参数保守：上限 10、缓存 1~5、blocking=True（池满则排队而非报错）、ping=1（借出时
# 心跳探测，避免演示环境 MySQL wait_timeout 空闲断连；坏连接自动丢弃重建）。
# 附带收益：后台 notify worker 每轮轮询不再频繁新建/销毁连接。
POOL_CONFIG = {
    "maxconnections": int(os.getenv("DB_POOL_MAX", "10")),
    "mincached":      int(os.getenv("DB_POOL_MIN", "1")),
    "maxcached":      int(os.getenv("DB_POOL_CACHED", "5")),
    "blocking":       True,
    "ping":           1,
}

_pool = None
_pool_lock = threading.Lock()


def _new_conn(cfg):
    """直连新建一个 PyMySQL 连接（连接池 creator 与 override 直连共用）。"""
    import pymysql
    return pymysql.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=cfg["password"], database=cfg.get("database") or None,
        charset=cfg["charset"], autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from dbutils.pooled_db import PooledDB
                import pymysql
                cfg = dict(DB_CONFIG)
                _pool = PooledDB(
                    creator=pymysql,
                    host=cfg["host"], port=cfg["port"],
                    user=cfg["user"], password=cfg["password"],
                    database=cfg["database"], charset=cfg["charset"],
                    autocommit=True, cursorclass=pymysql.cursors.DictCursor,
                    **POOL_CONFIG,
                )
    return _pool


def get_conn(**override):
    """返回 PyMySQL 连接。

    - 不带 override：从 DBUtils 连接池借出（默认库 smart_locker），
      close() 归还池而非真正断开——这是 S9「PyMySQL 连接池」的落地实现。
    - 带 override（连其他库 / 不带库名的管理场景）：每次直连新建，不进池，
      避免池中连接指向被 DROP/CREATE 的库造成脏复用。
    """
    if override:
        cfg = dict(DB_CONFIG)
        cfg.update(override)
        return _new_conn(cfg)
    return _get_pool().connection()


def get_conn_no_db(**override):
    """连接时不指定 database（用于 CREATE DATABASE 阶段）。"""
    cfg = dict(DB_CONFIG)
    cfg.pop("database", None)
    cfg.update(override)
    return get_conn(**cfg)


# ---- 消息通知配置 ----
# 课程设计走模拟渠道：短信与推送写日志文件，站内消息直接落库（t_notice 记录本身即站内信）。
# 接入真实服务商时只改 sms_provider 并补对应分支，调用方无需改动。
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

NOTIFY_CONFIG = {
    # 总开关：置 0 后所有 enqueue 直接返回，业务主流程完全不受影响
    "enabled":             os.getenv("NOTIFY_ENABLED", "1") == "1",
    # 后台 worker 轮询间隔（秒）
    "worker_interval":     int(os.getenv("NOTIFY_WORKER_INTERVAL", "15")),
    "batch_size":          int(os.getenv("NOTIFY_BATCH_SIZE", "50")),
    "max_retry":           int(os.getenv("NOTIFY_MAX_RETRY", "3")),
    # 重试退避（秒）：第 n 次失败取第 n 项，超出取最后一项
    "retry_backoff":       [30, 120, 600],
    "channels":            [c.strip().upper()
                            for c in os.getenv("NOTIFY_CHANNELS", "SMS,INBOX,PUSH").split(",")
                            if c.strip()],
    "sms_provider":        os.getenv("NOTIFY_SMS_PROVIDER", "mock"),
    # 免费期到期前多少小时发出第一次提醒
    "remind_before_hours": int(os.getenv("NOTIFY_REMIND_BEFORE_HOURS", "6")),
    # 模拟发送失败的概率（0~1），用于演示失败重试；正常演示保持 0
    "fail_rate":           float(os.getenv("NOTIFY_FAIL_RATE", "0")),
    "log_path":            os.getenv("NOTIFY_LOG", os.path.join(_BASE_DIR, "logs", "notify.log")),
}
