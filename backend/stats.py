# 统计分析与看板蓝图
# 提供 ≥3 个复杂聚合统计接口（柜体吞吐、公司排名、尺寸格口、每日趋势、异常分布）
# 并直接调用视图 / 存储过程。
from flask import Blueprint, request, jsonify

import db

stats_bp = Blueprint("stats", __name__, url_prefix="/api/stats")


@stats_bp.route("/overview", methods=["GET"])
def overview():
    res = {}
    res["companies"] = db.query_one("SELECT COUNT(*) c FROM t_express_company")["c"]
    res["couriers"] = db.query_one("SELECT COUNT(*) c FROM t_courier")["c"]
    res["users"] = db.query_one("SELECT COUNT(*) c FROM t_user")["c"]
    res["cabinets"] = db.query_one("SELECT COUNT(*) c FROM t_cabinet")["c"]
    res["cells"] = db.query_one("SELECT COUNT(*) c FROM t_cell")["c"]
    res["packages"] = db.query_one("SELECT COUNT(*) c FROM t_package")["c"]
    cell = db.query_one("""SELECT
        SUM(status='FREE') AS free,
        SUM(status='OCCUPIED') AS occupied,
        SUM(status='FAULT') AS fault FROM t_cell""")
    res["cell_status"] = {"free": cell["free"], "occupied": cell["occupied"], "fault": cell["fault"]}
    pkg = db.query_one("""SELECT
        SUM(status='STORED') AS stored_cnt,
        SUM(status='PICKED') AS picked_cnt,
        SUM(status='EXPIRED') AS expired_cnt,
        SUM(status='EXCEPTION') AS exception_cnt,
        SUM(status='RETURNED') AS returned_cnt,
        SUM(status='SEND_WAIT_PICKUP') AS send_wait_cnt,
        SUM(status='SEND_COLLECTED') AS send_collected_cnt FROM t_package""")
    res["package_status"] = pkg
    res["pending_receive"] = db.query_one(
        "SELECT COUNT(*) c FROM t_package WHERE direction='RECEIVE' AND status IN ('STORED','EXPIRED')")["c"]
    res["pending_send"] = db.query_one(
        "SELECT COUNT(*) c FROM t_package WHERE direction='SEND' AND status='SEND_WAIT_PICKUP'")["c"]
    res["send_collected"] = db.query_one(
        "SELECT COUNT(*) c FROM t_package WHERE direction='SEND' AND status='SEND_COLLECTED'")["c"]
    today = db.query_one("""SELECT
        SUM(DATE(store_time)=CURDATE()) AS stored_today,
        SUM(DATE(pickup_time)=CURDATE()) AS picked_today FROM t_package""")
    res["today"] = today
    return jsonify(res)


@stats_bp.route("/cabinet-throughput", methods=["GET"])
def cabinet_throughput():
    """统计1：各柜体吞吐量与占用率 + 平均滞留时长。"""
    sql = """
        SELECT cab.cabinet_code, cab.location, cab.status AS cabinet_status,
               COUNT(p.package_id)                                              AS total_cnt,
               SUM(CASE WHEN p.status='PICKED'    THEN 1 ELSE 0 END)            AS picked_cnt,
               SUM(CASE WHEN p.status='STORED'    THEN 1 ELSE 0 END)            AS stored_cnt,
               SUM(CASE WHEN p.status='EXPIRED'   THEN 1 ELSE 0 END)            AS expired_cnt,
               SUM(CASE WHEN p.status='EXCEPTION' THEN 1 ELSE 0 END)            AS exception_cnt,
               ROUND(AVG(TIMESTAMPDIFF(HOUR, p.store_time, p.pickup_time)), 1)   AS avg_hold_h
        FROM t_cabinet cab
        LEFT JOIN t_package p ON p.cabinet_id = cab.cabinet_id
        GROUP BY cab.cabinet_id, cab.cabinet_code, cab.location, cab.status
        ORDER BY total_cnt DESC
    """
    return jsonify(db.query(sql))


@stats_bp.route("/company-ranking", methods=["GET"])
def company_ranking():
    """统计2：各快递公司存件量与超时率排名（存储过程）。"""
    return jsonify(db.call_proc("sp_company_ranking"))


@stats_bp.route("/cell-size-usage", methods=["GET"])
def cell_size_usage():
    """统计3：各尺寸格口使用率与平均周转时长。"""
    sql = """
        SELECT cell.size_type,
               COUNT(DISTINCT cell.cell_id)                                   AS cell_cnt,
               SUM(CASE WHEN cell.status='OCCUPIED' THEN 1 ELSE 0 END)        AS occupied_cnt,
               ROUND(SUM(CASE WHEN cell.status='OCCUPIED' THEN 1 ELSE 0 END)
                     / COUNT(*), 3)                                           AS occ_rate,
               ROUND(AVG(TIMESTAMPDIFF(HOUR, p.store_time, p.pickup_time)), 1) AS avg_turn_h
        FROM t_cell cell
        LEFT JOIN t_package p ON p.cell_id = cell.cell_id AND p.status='PICKED'
        GROUP BY cell.size_type
        ORDER BY cell.size_type
    """
    return jsonify(db.query(sql))


@stats_bp.route("/daily-trend", methods=["GET"])
def daily_trend():
    """统计4：最近 N 天每日存取件趋势（存储过程）。"""
    try:
        days = max(1, min(60, int(request.args.get("days", 30))))
    except ValueError:
        days = 30
    return jsonify(db.call_proc("sp_daily_throughput", (days,)))


@stats_bp.route("/exception-distribution", methods=["GET"])
def exception_distribution():
    """统计5：异常类型与处理状态分布。"""
    by_type = db.query("""
        SELECT exception_type, COUNT(*) AS cnt
        FROM t_exception_log GROUP BY exception_type ORDER BY cnt DESC
    """)
    by_result = db.query("""
        SELECT handle_result, COUNT(*) AS cnt
        FROM t_exception_log GROUP BY handle_result ORDER BY cnt DESC
    """)
    return jsonify({"by_type": by_type, "by_result": by_result})


@stats_bp.route("/cabinet-occupancy/<int:cabinet_id>", methods=["GET"])
def cabinet_occupancy(cabinet_id):
    """单柜体占用详情（存储过程）。"""
    row = db.call_proc("sp_cabinet_occupancy", (cabinet_id,))
    return jsonify(row[0] if row else {})
