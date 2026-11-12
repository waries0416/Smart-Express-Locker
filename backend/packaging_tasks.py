# 创新点 2 · 包装准备协同（备包装任务 + 材料台账 + 快递员任务接口）
#
# 蓝图（docs/api-innovations.md §2）：
#   GET  /api/pack-materials                        COURIER 或 admin
#   PUT  /api/pack-materials/<id>                   COURIER 或 admin
#   GET  /api/courier/packaging-tasks               COURIER（本人）/ admin
#   POST /api/courier/packaging-tasks/<id>/done     COURIER（本人）/ admin
#
# 设计要点：
#   1) **材料名与数量在任务行内快照**（t_pack_task_item.name/qty/unit）。
#      台账后续改名或改单位，不会把历史任务里的"气泡膜 1 卷"变成别的东西。
#   2) 任务由寄件/存件时引用推荐结果自动生成；生成失败不得影响主流程，
#      因此 create_task_from_recommendation() 内部吞异常并返回 None。
#   3) 越权一律 403：快递员只能看/改 assignee_courier_id = 本人 的任务。
import logging

from flask import Blueprint, jsonify, request

import apiutil
import db

packaging_bp = Blueprint("packaging", __name__, url_prefix="/api")

log = logging.getLogger("packaging_tasks")

TASK_STATUSES = ("PENDING", "DONE", "CANCELED")
MAX_STOCK = 100000
MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# 材料台账
# ---------------------------------------------------------------------------
def _material_row(row):
    return {
        "material_id": row["material_id"],
        "name": row["name"],
        "spec": row.get("spec"),
        "stock": int(row["stock"] or 0),
        "threshold": int(row["threshold"] or 0),
        "unit": row["unit"],
    }


@packaging_bp.route("/pack-materials", methods=["GET"])
def list_pack_materials():
    """全量台账（量小，不做分页）；COURIER 或 admin。"""
    _ident, err = apiutil.require_admin_or_kiosk("COURIER")
    if err:
        return err
    rows = db.query(
        "SELECT material_id, name, spec, unit, stock, threshold "
        "FROM t_pack_material ORDER BY material_id")
    return jsonify({"data": [_material_row(r) for r in rows]})


@packaging_bp.route("/pack-materials/<int:material_id>", methods=["PUT"])
def update_pack_material(material_id):
    """只接受 stock / threshold；stock 必须是 0~100000 的整数。其余字段忽略。"""
    _ident, err = apiutil.require_admin_or_kiosk("COURIER")
    if err:
        return err

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return apiutil.bad_request("请求体必须是 JSON 对象")

    sets, params = [], []
    if "stock" in body:
        stock = _as_int(body.get("stock"))
        if stock is None:
            return apiutil.validation_failed("stock 必须是整数")
        if stock < 0 or stock > MAX_STOCK:
            return apiutil.validation_failed(
                f"stock 必须在 0~{MAX_STOCK} 之间（当前 {stock}）")
        sets.append("stock=%s")
        params.append(stock)
    if "threshold" in body:
        threshold = _as_int(body.get("threshold"))
        if threshold is None:
            return apiutil.validation_failed("threshold 必须是整数")
        if threshold < 0 or threshold > MAX_STOCK:
            return apiutil.validation_failed(
                f"threshold 必须在 0~{MAX_STOCK} 之间（当前 {threshold}）")
        sets.append("threshold=%s")
        params.append(threshold)

    if not sets:
        return apiutil.validation_failed("至少提供 stock 或 threshold 之一")

    exists = db.query_one(
        "SELECT material_id FROM t_pack_material WHERE material_id=%s", (material_id,))
    if not exists:
        return apiutil.not_found("材料不存在")

    try:
        db.execute(
            f"UPDATE t_pack_material SET {', '.join(sets)} WHERE material_id=%s",
            params + [material_id])
    except Exception:  # noqa: BLE001 —— 例如 CHECK 约束兜底
        log.exception("材料台账更新失败")
        return apiutil.validation_failed("库存更新失败，请检查取值是否合法")

    row = db.query_one(
        "SELECT material_id, name, spec, unit, stock, threshold "
        "FROM t_pack_material WHERE material_id=%s", (material_id,))
    return jsonify(_material_row(row))


def _as_int(value):
    """严格整数解析：拒绝 True/False、小数、字符串数字以外的类型。

    为什么不用 int(value)：int(True)==1、int("1.5") 抛错、int(1.5)==1，
    这些"看起来能用"的行为会让前端把 1.5 传成 1 而无人察觉。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# 快递员备包装任务
# ---------------------------------------------------------------------------
def create_task_from_recommendation(package_id, recommendation_id=None,
                                    courier_id=None, note=None):
    """按推荐结果生成一条备包装任务 + 材料快照。

    刻意"尽力而为"：任何异常都吞掉并返回 None —— 备包装任务是协同增强，
    不能因为生成失败而让存件/寄件主流程报错（向后兼容是硬要求）。

    返回 task_id 或 None。
    """
    if not recommendation_id:
        return None
    try:
        rec = db.query_one(
            "SELECT recommendation_id, size_type FROM t_pack_recommendation "
            "WHERE recommendation_id=%s", (int(recommendation_id),))
        if not rec:
            return None

        mats = db.query(
            "SELECT name, qty, unit FROM t_pack_recommend_item "
            "WHERE recommendation_id=%s AND kind='MATERIAL' ORDER BY item_id",
            (int(recommendation_id),))
        cab = db.query_one(
            "SELECT cabinet_id FROM t_package WHERE package_id=%s", (int(package_id),))

        with db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO t_pack_task
                       (package_id, recommendation_id, assignee_courier_id, cabinet_id,
                        size_type, status, note)
                   VALUES (%s,%s,%s,%s,%s,'PENDING',%s)""",
                (int(package_id), int(recommendation_id), courier_id,
                 (cab or {}).get("cabinet_id"), rec["size_type"],
                 (note or "AI 推荐生成的备包装任务")[:200]))
            task_id = cur.lastrowid

            rows = []
            for m in mats:
                # 材料名/数量在此**快照**，台账后续改名不影响历史任务
                unit = m.get("unit") or _default_unit(m.get("name"))
                rows.append((task_id, _material_id_of(m.get("name")),
                             str(m.get("name"))[:50], max(1, int(m.get("qty") or 1)),
                             str(unit)[:20]))
            if rows:
                cur.executemany(
                    """INSERT INTO t_pack_task_item (task_id, material_id, name, qty, unit)
                       VALUES (%s,%s,%s,%s,%s)""", rows)
        return task_id
    except Exception as e:  # noqa: BLE001
        log.warning("备包装任务生成失败（不影响主流程）：%s", type(e).__name__)
        return None


def _material_id_of(name):
    """按名称匹配台账，匹配不到返回 None（外键可空，快照仍然有效）。"""
    if not name:
        return None
    row = db.query_one("SELECT material_id FROM t_pack_material WHERE name=%s", (name,))
    return row["material_id"] if row else None


def _default_unit(name):
    """材料默认单位：与 t_pack_material 种子数据保持一致。"""
    n = str(name or "")
    if "纸箱" in n:
        return "个"
    if "标签" in n:
        return "张"
    if "泡沫板" in n:
        return "块"
    return "卷"


def _task_row(task):
    """把任务行 + 材料明细组装成契约 §2.2 的元素结构。"""
    items = db.query(
        "SELECT name, qty, unit FROM t_pack_task_item WHERE task_id=%s "
        "ORDER BY task_item_id", (task["task_id"],))
    return {
        "task_id": task["task_id"],
        "package_id": task.get("package_id"),
        "tracking_no": task.get("tracking_no"),
        "cabinet_id": task.get("cabinet_id"),
        "cabinet_code": task.get("cabinet_code"),
        "cell_code": task.get("cell_code"),
        "recommendation_id": task.get("recommendation_id"),
        "size_type": task.get("size_type"),
        "status": task["status"],
        "created_at": task["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(task.get("created_at"), "strftime") else task.get("created_at"),
        "materials": [
            {"name": it["name"], "qty": int(it["qty"] or 0), "unit": it["unit"]}
            for it in items
        ],
    }


_TASK_SELECT = """
    SELECT t.task_id, t.package_id, t.recommendation_id, t.assignee_courier_id,
           t.cabinet_id, t.size_type, t.status, t.created_at, t.done_at,
           p.tracking_no, cab.cabinet_code, cell.cell_code
    FROM t_pack_task t
    LEFT JOIN t_package p  ON p.package_id = t.package_id
    LEFT JOIN t_cabinet cab ON cab.cabinet_id = t.cabinet_id
    LEFT JOIN t_cell    cell ON cell.cell_id = p.cell_id
"""


@packaging_bp.route("/courier/packaging-tasks", methods=["GET"])
def list_packaging_tasks():
    """COURIER 只返回 assignee_courier_id = 本人；admin 可查全部（可传 courier_id 过滤）。"""
    ident, err = apiutil.require_admin_or_kiosk("COURIER")
    if err:
        return err

    status = (request.args.get("status") or "").strip().upper()
    if status and status not in TASK_STATUSES:
        return apiutil.bad_request(
            f"status 非法（只能是 {'/'.join(TASK_STATUSES)}）：{status}")

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        return apiutil.bad_request("page 必须是整数")
    try:
        size = int(request.args.get("size", 20))
    except ValueError:
        return apiutil.bad_request("size 必须是整数")
    if not (1 <= size <= MAX_PAGE_SIZE):
        return apiutil.bad_request(f"size 必须在 1~{MAX_PAGE_SIZE} 之间")

    wheres, params = [], []
    if apiutil.is_admin(ident):
        only = request.args.get("courier_id")
        if only not in (None, ""):
            try:
                wheres.append("t.assignee_courier_id=%s")
                params.append(int(only))
            except ValueError:
                return apiutil.bad_request("courier_id 必须是整数")
    else:
        _role, cid = ident
        wheres.append("t.assignee_courier_id=%s")
        params.append(cid)
    if status:
        wheres.append("t.status=%s")
        params.append(status)
    where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    total = db.query_one(
        f"SELECT COUNT(*) AS c FROM t_pack_task t{where_sql}", params)["c"]
    rows = db.query(
        f"{_TASK_SELECT}{where_sql} ORDER BY t.task_id DESC LIMIT %s OFFSET %s",
        params + [size, (page - 1) * size])

    return jsonify({
        "count": int(total),
        "page": page,
        "size": size,
        "data": [_task_row(r) for r in rows],
    })


@packaging_bp.route("/courier/packaging-tasks/<int:task_id>/done", methods=["POST"])
def finish_packaging_task(task_id):
    """COURIER 本人任务或 admin；已完成/已取消 409。"""
    ident, err = apiutil.require_admin_or_kiosk("COURIER")
    if err:
        return err

    task = db.query_one("SELECT * FROM t_pack_task WHERE task_id=%s", (task_id,))
    if not task:
        return apiutil.not_found("备包装任务不存在")

    if not apiutil.is_admin(ident):
        _role, cid = ident
        if task.get("assignee_courier_id") != cid:
            return apiutil.forbidden("只能完成指派给本人的备包装任务")

    if task["status"] == "DONE":
        return apiutil.conflict("该任务已完成，请勿重复提交")
    if task["status"] == "CANCELED":
        return apiutil.conflict("该任务已取消，无法完成")

    body = request.get_json(silent=True) or {}
    note = body.get("note")
    if note is not None:
        if not isinstance(note, str):
            return apiutil.bad_request("note 必须是字符串")
        note = note.strip()
        if len(note) > 200:
            return apiutil.bad_request("note 超长（最多 200 字符）")

    # 条件更新：并发下只有一个能改成 DONE（防止重复记账）
    affected = db.execute(
        "UPDATE t_pack_task SET status='DONE', done_at=NOW(), note=COALESCE(%s, note) "
        "WHERE task_id=%s AND status='PENDING'", (note or None, task_id))
    if affected != 1:
        return apiutil.conflict("任务状态已变化，请刷新后重试")

    row = db.query_one(
        "SELECT task_id, status, done_at FROM t_pack_task WHERE task_id=%s", (task_id,))
    done_at = row["done_at"]
    return jsonify({
        "task_id": row["task_id"],
        "status": row["status"],
        "done_at": done_at.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(done_at, "strftime") else done_at,
    })
