# 实体 CRUD 蓝图（快递公司/快递员/用户/快递柜/格口/包裹）
# 提供统一的 list / get / create / update / delete 接口。
#
# 删除前先查引用：存在 RESTRICT 外键引用时返回 409 和引用明细，由前端提示用户确认，
# 确认后带 ?force=1 走事务内级联清理。schema 上保留 ON DELETE RESTRICT，放开动作放在
# 应用层，既守住主数据安全，也让管理员有明确的处置路径。
#
# t_cabinet.total_cells 是冗余统计列，新增或修改柜体时自动增删 t_cell 记录使二者一致；
# 缩减时只清理空闲格口，占用或故障的格口拒绝删除并返回警告。
from flask import Blueprint, request, jsonify

import db
from auth import admin_session_valid

entities_bp = Blueprint("entities", __name__, url_prefix="/api")


@entities_bp.before_request
def _guard_mutations():
    """写操作必须带管理员会话。

    页面层已经用 before_request 拦住了 /admin/*，但接口层原先没有任何校验：
    任何人直接 POST/PUT/DELETE /api/packages/1 就能改库——页面门禁形同虚设。
    这里只拦写方法，读接口保持开放：触屏端「投递记录」按快递员查包裹、
    手机端下单要选公司与柜体，都依赖 GET，而它们手上没有管理员 Cookie。
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if admin_session_valid():
        return None
    return jsonify({"error": "未登录或登录已过期"}), 401

# 实体元数据：表名、主键、可写字段、列表默认排序、可选搜索列
ENTITY_META = {
    "companies": {
        "table": "t_express_company", "pk": "company_id",
        "fields": ["company_code", "company_name", "hotline"],
        "search": ["company_name", "company_code"], "order": "company_id",
    },
    "couriers": {
        "table": "t_courier", "pk": "courier_id",
        "fields": ["company_id", "employee_no", "name", "phone"],
        "search": ["name", "phone", "employee_no"], "order": "courier_id",
    },
    "users": {
        "table": "t_user", "pk": "user_id",
        "fields": ["name", "phone"],
        "search": ["name", "phone"], "order": "user_id",
    },
    "cabinets": {
        "table": "t_cabinet", "pk": "cabinet_id",
        "fields": ["cabinet_code", "location", "cabinet_type", "total_cells", "status"],
        "search": ["location", "cabinet_code"], "order": "cabinet_id",
    },
    "cells": {
        "table": "t_cell", "pk": "cell_id",
        "fields": ["cabinet_id", "cell_code", "size_type", "status"],
        "search": ["cell_code", "size_type", "status"], "order": "cell_id",
    },
    "packages": {
        "table": "t_package", "pk": "package_id",
        "fields": ["direction", "tracking_no", "courier_id", "user_id", "company_id",
                   "cabinet_id", "cell_id", "size_type", "weight", "status", "pickup_code",
                   "store_time", "expire_time", "pickup_time", "note"],
        "search": ["tracking_no", "pickup_code", "status", "direction"], "order": "package_id DESC",
        # 扩展过滤（S6-03 投递记录多条件检索）：
        #  like_fields  → 收件人手机号模糊匹配（快递员按收件人反查经手包裹）
        #  range_fields → 支持 {字段}_from / {字段}_to 区间（如 store_time_from/…_to）
        "like_fields": ["recipient_phone"],
        "range_fields": ["store_time"],
    },
}

# 实体中文名（用于删除确认等提示文案）
ENTITY_LABEL = {
    "companies": "快递公司", "couriers": "快递员", "users": "用户",
    "cabinets": "快递柜", "cells": "格口", "packages": "包裹",
}

# 引用关系：实体被哪些表引用。
#   blocking  = True  表示外键为 ON DELETE RESTRICT（会阻止删除），False 表示
#               ON DELETE CASCADE（随主表自动清除，仅作提示）
#   protected = True  表示这是**历史业务事实**，即使 force=1 也不允许删除。
#               典型：快递员经手的投递包裹、用户收过的包裹——人员可以离职/注销，
#               但其经手的业务记录必须留档以供追溯，绝不能跟着一起物理删除。
#               与设备的区别：柜体/格口是物理资产，拆除时其上包裹一并清归档尚可接受；
#               而"人走了就把他送过的快递记录抹掉"是错误的数据治理。
REF_CHECK = {
    "companies": [
        ("t_courier", "company_id", "快递员", True, False),
    ],
    "couriers": [
        ("t_package", "courier_id", "投递包裹", True, True),
    ],
    "users": [
        ("t_package", "user_id", "收件包裹", True, True),
    ],
    "cabinets": [
        ("t_cell", "cabinet_id", "格口", True, False),
        ("t_package", "cabinet_id", "包裹", True, False),
    ],
    "cells": [
        ("t_package", "cell_id", "包裹", True, False),
    ],
    "packages": [
        ("t_pickup_record", "package_id", "取件记录", False, False),
        ("t_exception_log", "package_id", "异常记录", False, False),
    ],
}

# 当前仍在柜内的包裹状态（这些才占用格口，删除时需要释放）
IN_CABINET_STATUS = ("STORED", "EXPIRED", "EXCEPTION", "SEND_WAIT_PICKUP")
VALID_CELL_SIZES = ("SMALL", "MEDIUM", "LARGE")


# ---- 工具：列表 / 引用计数 ----
def _build_list(meta, args):
    table = meta["table"]
    pk = meta["pk"]
    allowed = set(meta["fields"]) | {pk}
    wheres, params = [], []
    for k, v in args.items():
        if k in allowed and v not in (None, ""):
            wheres.append(f"{k}=%s")
            params.append(v)
    q = args.get("q")
    if q:
        ors = [f"{c} LIKE %s" for c in meta["search"]]
        wheres.append("(" + " OR ".join(ors) + ")")
        params.extend([f"%{q}%"] * len(meta["search"]))
    # 扩展过滤：like_fields 做模糊匹配（列名取自常量 meta，非用户输入）
    for f in meta.get("like_fields", []):
        v = args.get(f)
        if v not in (None, ""):
            wheres.append(f"{f} LIKE %s")
            params.append(f"%{v}%")
    # 扩展过滤：range_fields 支持 {字段}_from / {字段}_to 半开区间（含边界）
    for f in meta.get("range_fields", []):
        lo, hi = args.get(f + "_from"), args.get(f + "_to")
        if lo not in (None, ""):
            wheres.append(f"{f}>=%s")
            params.append(lo)
        if hi not in (None, ""):
            wheres.append(f"{f}<=%s")
            params.append(hi)
    where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    order = args.get("sort")
    order_sql = f" ORDER BY {meta['order']}"
    if order and order in allowed:
        direction = "DESC" if args.get("dir", "").upper() == "DESC" else "ASC"
        order_sql = f" ORDER BY {order} {direction}"

    try:
        page = max(1, int(args.get("page", 1)))
        size = min(200, max(1, int(args.get("size", 20))))
    except ValueError:
        page, size = 1, 20
    offset = (page - 1) * size

    total = db.query_one(f"SELECT COUNT(*) AS c FROM {table}{where_sql}", params)["c"]
    rows = db.query(
        f"SELECT * FROM {table}{where_sql}{order_sql} LIMIT %s OFFSET %s",
        params + [size, offset],
    )
    return {"total": total, "page": page, "size": size, "data": rows}


def _count_refs(entity, rid):
    """统计该记录被引用情况。

    返回 (detail, blocking_total, protected_total)
      blocking  : RESTRICT 引用，force=1 时允许级联清理（设备类）
      protected : 历史业务事实，**任何方式都不允许删除**（人员经手的包裹）
                  受保护的引用不计入 blocking，因为它不能被 force 覆盖
    """
    detail, blocking_total, protected_total = {}, 0, 0
    for tbl, col, label, blocking, protected in REF_CHECK.get(entity, []):
        n = db.query_one(f"SELECT COUNT(*) AS c FROM {tbl} WHERE {col}=%s", (rid,))["c"]
        if n:
            detail[label] = detail.get(label, 0) + n
            if protected:
                protected_total += n
            elif blocking:
                blocking_total += n
    # 快递公司：旗下快递员的投递记录同样是历史事实，需提前暴露给前端提示
    if entity == "companies":
        n = db.query_one(
            "SELECT COUNT(*) AS c FROM t_package WHERE courier_id IN "
            "(SELECT courier_id FROM t_courier WHERE company_id=%s)", (rid,))["c"]
        if n:
            detail["旗下快递员投递记录"] = n
            protected_total += n
    return detail, blocking_total, protected_total


# ---- 工具：级联删除（必须在 db.transaction() 内调用，保证原子性） ----
def _ids(conn, sql, args=()):
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return [list(r.values())[0] for r in cur.fetchall()]


def _free_cells_of_packages(conn, pkg_ids):
    """删除包裹前，把它们占用的格口释放为空闲"""
    if not pkg_ids:
        return 0
    ph = ",".join(["%s"] * len(pkg_ids))
    cell_ids = _ids(
        conn,
        f"SELECT cell_id FROM t_package WHERE package_id IN ({ph}) "
        f"AND status IN ({','.join(['%s'] * len(IN_CABINET_STATUS))})",
        tuple(pkg_ids) + IN_CABINET_STATUS,
    )
    if not cell_ids:
        return 0
    ph2 = ",".join(["%s"] * len(cell_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE t_cell SET status='FREE' WHERE cell_id IN ({ph2}) AND status='OCCUPIED'",
            tuple(cell_ids),
        )
        return cur.rowcount


def _delete_packages(conn, pkg_ids):
    """删除包裹并释放格口（取件记录/异常记录由 ON DELETE CASCADE 自动清除）"""
    if not pkg_ids:
        return 0
    _free_cells_of_packages(conn, pkg_ids)
    ph = ",".join(["%s"] * len(pkg_ids))
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM t_package WHERE package_id IN ({ph})", tuple(pkg_ids))
        return cur.rowcount


def _cascade_delete(conn, entity, rid):
    """按依赖顺序级联删除，返回清理统计 {类型: 条数}"""
    stats = {}

    if entity == "companies":
        # 公司 → 快递员 → 包裹
        for cid in _ids(conn, "SELECT courier_id FROM t_courier WHERE company_id=%s", (rid,)):
            for k, v in _cascade_delete(conn, "couriers", cid).items():
                stats[k] = stats.get(k, 0) + v
        with conn.cursor() as cur:
            cur.execute("DELETE FROM t_express_company WHERE company_id=%s", (rid,))
            stats["快递公司"] = cur.rowcount

    elif entity == "couriers":
        # 快递员离职≠抹掉他送过的快递：投递记录是历史业务事实，必须留档追溯。
        # 这里做兜底拦截——即便调用方绕过 refs 预检、直接带 force=1 也会被挡下。
        pkg_ids = _ids(conn, "SELECT package_id FROM t_package WHERE courier_id=%s", (rid,))
        if pkg_ids:
            raise ValueError(
                f"该快递员有 {len(pkg_ids)} 条投递记录，删除会导致历史包裹丢失，已阻止；"
                f"如需移除该快递员，请先处理其投递记录")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM t_courier WHERE courier_id=%s", (rid,))
            stats["快递员"] = cur.rowcount

    elif entity == "users":
        pkg_ids = _ids(conn, "SELECT package_id FROM t_package WHERE user_id=%s", (rid,))
        if pkg_ids:
            raise ValueError(
                f"该用户有 {len(pkg_ids)} 条收件记录，删除会导致历史包裹丢失，已阻止；"
                f"如需移除该用户，请先处理其收件记录")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM t_user WHERE user_id=%s", (rid,))
            stats["用户"] = cur.rowcount

    elif entity == "cells":
        stats["包裹"] = _delete_packages(
            conn, _ids(conn, "SELECT package_id FROM t_package WHERE cell_id=%s", (rid,)))
        # 必须在删除前取所属柜体，删完就查不到了
        cab_ids = _ids(conn, "SELECT cabinet_id FROM t_cell WHERE cell_id=%s", (rid,))
        with conn.cursor() as cur:
            cur.execute("DELETE FROM t_cell WHERE cell_id=%s", (rid,))
            stats["格口"] = cur.rowcount
        for cid in cab_ids:
            _recalc_cabinet_total(conn, cid)

    elif entity == "cabinets":
        cell_ids = _ids(conn, "SELECT cell_id FROM t_cell WHERE cabinet_id=%s", (rid,))
        # 直接挂在柜体上的包裹 + 挂在其格口上的包裹，取并集
        pkg_ids = set(_ids(conn, "SELECT package_id FROM t_package WHERE cabinet_id=%s", (rid,)))
        if cell_ids:
            ph = ",".join(["%s"] * len(cell_ids))
            pkg_ids |= set(_ids(conn, f"SELECT package_id FROM t_package WHERE cell_id IN ({ph})", tuple(cell_ids)))
        stats["包裹"] = _delete_packages(conn, sorted(pkg_ids))
        with conn.cursor() as cur:
            cur.execute("DELETE FROM t_cell WHERE cabinet_id=%s", (rid,))
            stats["格口"] = cur.rowcount
        with conn.cursor() as cur:
            cur.execute("DELETE FROM t_cabinet WHERE cabinet_id=%s", (rid,))
            stats["快递柜"] = cur.rowcount

    elif entity == "packages":
        stats["包裹"] = _delete_packages(conn, [rid])

    return stats


# ---- 工具：柜体格口数 ↔ t_cell 联动 ----
def _recalc_cabinet_total(conn, cabinet_id=None, fallback_cabinet=None):
    """把 t_cabinet.total_cells 校正为 t_cell 实际行数"""
    cid = cabinet_id or fallback_cabinet
    if not cid:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM t_cell WHERE cabinet_id=%s", (cid,))
        n = cur.fetchone()["c"]
        cur.execute("UPDATE t_cabinet SET total_cells=%s WHERE cabinet_id=%s", (n, cid))
    return n


def _next_cell_codes(conn, cabinet_id, count):
    """生成 count 个该柜体尚未占用的格口号（A01、A02… 跳过已存在编号）"""
    with conn.cursor() as cur:
        cur.execute("SELECT cell_code FROM t_cell WHERE cabinet_id=%s", (cabinet_id,))
        used = {r["cell_code"] for r in cur.fetchall()}
    codes, num, letter_idx, guard = [], 1, 0, 0
    limit = count * 200 + 1000
    while len(codes) < count and guard < limit:
        code = f"{chr(ord('A') + letter_idx)}{num:02d}"
        if code not in used:
            codes.append(code)
            used.add(code)
        num += 1
        if num > 99:
            num, letter_idx = 1, letter_idx + 1
        if letter_idx > 25:
            letter_idx = 0
        guard += 1
    return codes


def _plan_sizes(need, size_plan, default_size):
    """按 size_plan 生成新增格口的规格序列；未提供则全部用 default_size"""
    if size_plan and isinstance(size_plan, dict):
        plan = {k: int(v) for k, v in size_plan.items()
                if k in VALID_CELL_SIZES and str(v).isdigit() and int(v) > 0}
        total = sum(plan.values())
        if total == need:
            sizes = []
            for s, n in plan.items():
                sizes.extend([s] * n)
            return sizes
        if total > 0:
            sizes = []
            for s, n in plan.items():
                sizes.extend([s] * max(1, round(need * n / total)))
            sizes = sizes[:need]
            while len(sizes) < need:
                sizes.append(default_size)
            return sizes
    return [default_size] * need


def _cell_status_counts(conn, cabinet_id):
    """统计柜体格口状态分布，以及「空闲但仍被历史包裹引用」的数量。

    注意：包裹取件后触发器会把格口置为 FREE，但 t_package.cell_id 会保留
    用于追溯「曾从哪个格口取出」，因此存在 status='FREE' 却仍被包裹引用的格口。
    这类格口受 fk_pkg_cell (ON DELETE RESTRICT) 保护，删除时会直接报错，
    缩减格口数时必须排除，否则整个事务回滚、前端表现为「改了但没生效」。
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) AS c FROM t_cell WHERE cabinet_id=%s GROUP BY status",
            (cabinet_id,))
        rows = cur.fetchall()
    counts = {"FREE": 0, "OCCUPIED": 0, "FAULT": 0}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + r["c"]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM t_cell c WHERE c.cabinet_id=%s AND c.status='FREE' "
            "AND EXISTS (SELECT 1 FROM t_package p WHERE p.cell_id=c.cell_id)",
            (cabinet_id,))
        counts["FREE_REFERENCED"] = cur.fetchone()["c"]
    return counts


def _sync_cabinet_cells(conn, cabinet_id, target, size_plan=None, default_size="SMALL"):
    """把柜体 t_cell 数量调整到 target，返回同步结果明细 dict

    - target > 现有：新增格口，自动生成编号与规格
    - target < 现有：仅删除 FREE 格口；占用/故障格口保留，并回写真实数量
      被阻塞时给出可读的原因（占用 X 个、故障 Y 个）与可达下限
    - 最后统一把 t_cabinet.total_cells 校正为实际行数
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM t_cell WHERE cabinet_id=%s", (cabinet_id,))
        cur_n = cur.fetchone()["c"]
    warnings, added, removed = [], 0, 0
    occupied = fault = blocked = 0

    if target > cur_n:
        need = target - cur_n
        codes = _next_cell_codes(conn, cabinet_id, need)
        if len(codes) < need:
            warnings.append(f"格口号生成空间不足，仅新增 {len(codes)} 个")
        sizes = _plan_sizes(len(codes), size_plan, default_size)
        with conn.cursor() as cur:
            for code, size in zip(codes, sizes):
                cur.execute(
                    "INSERT INTO t_cell (cabinet_id, cell_code, size_type, status) "
                    "VALUES (%s,%s,%s,'FREE')", (cabinet_id, code, size))
        added = len(codes)

    elif target < cur_n:
        excess = cur_n - target
        # 只能删除「空闲且无任何包裹引用」的格口：
        #  - 占用/故障格口：业务上不能删
        #  - 空闲但仍被历史包裹引用的格口：受 fk_pkg_cell RESTRICT 保护，删会报错
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cell_id FROM t_cell c WHERE c.cabinet_id=%s AND c.status='FREE' "
                "AND NOT EXISTS (SELECT 1 FROM t_package p WHERE p.cell_id=c.cell_id) "
                "ORDER BY c.cell_id DESC LIMIT %s", (cabinet_id, excess))
            free_ids = [r["cell_id"] for r in cur.fetchall()]
        if free_ids:
            ph = ",".join(["%s"] * len(free_ids))
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM t_cell WHERE cell_id IN ({ph})", tuple(free_ids))
                removed = cur.rowcount
        blocked = excess - len(free_ids)
        if blocked > 0:
            # 分别说明为什么删不掉，让用户知道下一步该做什么
            counts = _cell_status_counts(conn, cabinet_id)
            occupied = counts.get("OCCUPIED", 0)
            fault = counts.get("FAULT", 0)
            referenced = counts.get("FREE_REFERENCED", 0)
            reasons = []
            if occupied:
                reasons.append(f"占用中 {occupied} 个")
            if fault:
                reasons.append(f"故障 {fault} 个")
            if referenced:
                reasons.append(f"空闲但有历史取件记录 {referenced} 个")
            detail = "、".join(reasons) if reasons else "受关联数据保护"
            warnings.append(
                f"目标 {target} 个未能达成：还有 {blocked} 个格口无法删除（{detail}）。"
                f"占用中的请先取出包裹、故障的请先修复；"
                f"带历史取件记录的格口受外键保护需保留。"
                f"当前最少只能缩减到 {cur_n - removed} 个。")

    actual = cur_n + added - removed
    with conn.cursor() as cur:
        cur.execute("UPDATE t_cabinet SET total_cells=%s WHERE cabinet_id=%s",
                    (actual, cabinet_id))
    return {
        "requested": target, "added": added, "removed": removed, "actual": actual,
        "blocked": blocked, "occupied": occupied, "fault": fault, "warnings": warnings,
    }


# ---- 路由 ----
@entities_bp.route("/<entity>", methods=["GET"])
def list_entity(entity):
    meta = ENTITY_META.get(entity)
    if not meta:
        return jsonify({"error": "未知实体"}), 404
    return jsonify(_build_list(meta, request.args))


@entities_bp.route("/<entity>/<int:rid>", methods=["GET"])
def get_entity(entity, rid):
    meta = ENTITY_META.get(entity)
    if not meta:
        return jsonify({"error": "未知实体"}), 404
    row = db.query_one(f"SELECT * FROM {meta['table']} WHERE {meta['pk']}=%s", (rid,))
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify(row)


@entities_bp.route("/<entity>", methods=["POST"])
def create_entity(entity):
    meta = ENTITY_META.get(entity)
    if not meta:
        return jsonify({"error": "未知实体"}), 404
    body = request.get_json(silent=True) or {}
    cols, vals, params = [], [], []
    for f in meta["fields"]:
        if f in body and body[f] is not None:
            cols.append(f)
            vals.append("%s")
            params.append(body[f])
    if not cols:
        return jsonify({"error": "无任何可写入字段"}), 400

    # 柜体：建柜体 + 生成格口 必须原子完成
    if entity == "cabinets":
        try:
            with db.transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO {meta['table']} ({','.join(cols)}) "
                        f"VALUES ({','.join(vals)})", tuple(params))
                    new_id = cur.lastrowid
                if int(body.get("total_cells") or 0) > 0:
                    sync = _sync_cabinet_cells(
                        conn, new_id, int(body["total_cells"]),
                        body.get("size_plan"), body.get("new_cell_size") or "SMALL")
                else:
                    sync = {"added": 0, "removed": 0,
                            "actual": _recalc_cabinet_total(conn, new_id) or 0,
                            "blocked": 0, "occupied": 0, "fault": 0, "warnings": []}
        except Exception as e:
            return jsonify({"error": f"新增失败: {e}"}), 400
        row = db.query_one(f"SELECT * FROM {meta['table']} WHERE {meta['pk']}=%s", (new_id,))
        return jsonify({"id": new_id, "data": row, "cells_synced": sync}), 201

    sql = f"INSERT INTO {meta['table']} ({','.join(cols)}) VALUES ({','.join(vals)})"
    try:
        new_id = db.insert(sql, params)
    except Exception as e:
        return jsonify({"error": f"插入失败: {e}"}), 400

    # 单个格口的新增/删除会让所属柜体 total_cells 失准，这里回写校正
    if entity == "cells" and body.get("cabinet_id"):
        try:
            with db.transaction() as conn:
                _recalc_cabinet_total(conn, int(body["cabinet_id"]))
        except Exception:
            pass

    row = db.query_one(f"SELECT * FROM {meta['table']} WHERE {meta['pk']}=%s", (new_id,))
    return jsonify({"id": new_id, "data": row}), 201


@entities_bp.route("/<entity>/<int:rid>", methods=["PUT"])
def update_entity(entity, rid):
    meta = ENTITY_META.get(entity)
    if not meta:
        return jsonify({"error": "未知实体"}), 404
    body = request.get_json(silent=True) or {}

    exists = db.query_one(f"SELECT * FROM {meta['table']} WHERE {meta['pk']}=%s", (rid,))
    if not exists:
        return jsonify({"error": "记录不存在"}), 404

    # 柜体：字段更新 + 格口数量联动 必须原子完成
    if entity == "cabinets":
        sync = None
        try:
            with db.transaction() as conn:
                sets, params = [], []
                for f in meta["fields"]:
                    if f == "total_cells":
                        continue  # 由 _sync_cabinet_cells 统一写回真实值
                    if f in body and body[f] is not None:
                        sets.append(f"{f}=%s")
                        params.append(body[f])
                if sets:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE {meta['table']} SET {','.join(sets)} "
                            f"WHERE {meta['pk']}=%s", tuple(params) + (rid,))
                if body.get("total_cells") is not None:
                    try:
                        target = int(body["total_cells"])
                    except (TypeError, ValueError):
                        return jsonify({"error": "格口总数必须为整数"}), 400
                    if target < 0:
                        return jsonify({"error": "格口总数不能为负数"}), 400
                    sync = _sync_cabinet_cells(
                        conn, rid, target,
                        body.get("size_plan"), body.get("new_cell_size") or "SMALL")
        except Exception as e:
            return jsonify({"error": f"更新失败: {e}"}), 400
        row = db.query_one(f"SELECT * FROM {meta['table']} WHERE {meta['pk']}=%s", (rid,))
        return jsonify({"id": rid, "data": row, "cells_synced": sync})

    sets, params = [], []
    for f in meta["fields"]:
        if f in body and body[f] is not None:
            sets.append(f"{f}=%s")
            params.append(body[f])
    if not sets:
        return jsonify({"error": "无任何可更新字段"}), 400
    params.append(rid)
    sql = f"UPDATE {meta['table']} SET {','.join(sets)} WHERE {meta['pk']}=%s"
    try:
        # 格口换了所属柜体，两个柜体的 total_cells 都要校正
        old_cab = exists.get("cabinet_id") if entity == "cells" else None
        db.execute(sql, params)
        if entity == "cells":
            try:
                with db.transaction() as conn:
                    _recalc_cabinet_total(conn, old_cab)
                    new_cab = body.get("cabinet_id")
                    if new_cab and int(new_cab) != old_cab:
                        _recalc_cabinet_total(conn, int(new_cab))
            except Exception:
                pass
    except Exception as e:
        return jsonify({"error": f"更新失败: {e}"}), 400
    row = db.query_one(f"SELECT * FROM {meta['table']} WHERE {meta['pk']}=%s", (rid,))
    return jsonify({"id": rid, "data": row})


@entities_bp.route("/<entity>/<int:rid>", methods=["DELETE"])
def delete_entity(entity, rid):
    meta = ENTITY_META.get(entity)
    if not meta:
        return jsonify({"error": "未知实体"}), 404

    exists = db.query_one(f"SELECT * FROM {meta['table']} WHERE {meta['pk']}=%s", (rid,))
    if not exists:
        return jsonify({"error": "记录不存在"}), 404

    detail, blocking_total, protected_total = _count_refs(entity, rid)
    force = str(request.args.get("force", "")).lower() in ("1", "true", "yes")

    # 受保护的历史业务记录：即使 force=1 也拒绝删除（人员离职 ≠ 抹掉业务记录）
    if protected_total:
        desc = "、".join(f"{k} {v} 条" for k, v in detail.items())
        return jsonify({
            "error": f"该记录含不可删除的历史业务记录（{desc}），"
                     f"删除会导致业务追溯信息丢失，已阻止",
            "conflict": True,
            "protected": True,
            "refs": detail,
            "protected_total": protected_total,
        }), 409

    # 存在 RESTRICT 引用且未确认强制删除 → 返回 409，让前端给出明确提示
    if blocking_total and not force:
        desc = "、".join(f"{k} {v} 条" for k, v in detail.items())
        return jsonify({
            "error": f"该记录仍被引用（{desc}），无法直接删除",
            "conflict": True,
            "refs": detail,
            "blocking": blocking_total,
        }), 409

    try:
        with db.transaction() as conn:
            if blocking_total:
                stats = _cascade_delete(conn, entity, rid)
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {meta['table']} WHERE {meta['pk']}=%s", (rid,))
                    stats = {}
            # 删除格口后校正所属柜体的格口总数
            if entity == "cells" and exists.get("cabinet_id"):
                _recalc_cabinet_total(conn, int(exists["cabinet_id"]))
    except Exception as e:
        return jsonify({"error": f"删除失败: {e}"}), 400

    msg = "已删除" + (f"（并清理 {sum(stats.values())} 条关联记录）" if stats else "")
    return jsonify({"deleted": rid, "cascade": stats, "message": msg})


# 包裹明细视图（多表 JOIN）
@entities_bp.route("/packages/<int:pid>/detail", methods=["GET"])
def package_detail(pid):
    row = db.query_one("SELECT * FROM v_package_detail WHERE package_id=%s", (pid,))
    if not row:
        return jsonify({"error": "包裹不存在"}), 404
    return jsonify(row)


# ----------------------------------------------------------------------------
# 删除前的引用预检：让前端能在唯一一次确认框里把后果讲清楚，
# 避免「先删一次拿到 409 再二次确认」造成的「删不掉」观感。
# ----------------------------------------------------------------------------
@entities_bp.route("/<entity>/<int:rid>/refs", methods=["GET"])
def entity_refs(entity, rid):
    if entity not in ENTITY_META:
        return jsonify({"error": "未知实体"}), 404
    meta = ENTITY_META[entity]
    row = db.query_one(f"SELECT * FROM {meta['table']} WHERE {meta['pk']}=%s", (rid,))
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    detail, blocking, protected = _count_refs(entity, rid)
    refs_desc = "、".join(f"{k} {v} 条" for k, v in detail.items())
    if protected:
        message = (f"该{ENTITY_LABEL.get(entity, entity)}有 {refs_desc}，"
                   f"属历史业务记录，删除会导致业务追溯信息丢失，不可删除")
    elif blocking:
        message = f"该记录仍被引用（{refs_desc}），删除将一并清理"
    else:
        message = ""
    return jsonify({
        "entity": entity, "id": rid,
        "title": ENTITY_LABEL.get(entity, entity),
        "refs": detail, "blocking": blocking, "protected": protected,
        "has_refs": bool(detail),
        "need_force": protected == 0 and blocking > 0,
        # 前端据此决定：False 时直接提示原因，不再弹「确认强制删除」
        "can_delete": protected == 0,
        "message": message,
    })


# ----------------------------------------------------------------------------
# 柜体格口概况：供编辑表单在用户改数字「之前」就展示可缩减下限，
# 避免填了小数却因占用/故障格口缩不下去、看起来像没生效。
# ----------------------------------------------------------------------------
@entities_bp.route("/cabinets/<int:rid>/cell-summary", methods=["GET"])
def cabinet_cell_summary(rid):
    row = db.query_one("SELECT * FROM t_cabinet WHERE cabinet_id=%s", (rid,))
    if not row:
        return jsonify({"error": "柜体不存在"}), 404
    counts = {"FREE": 0, "OCCUPIED": 0, "FAULT": 0, "FREE_REFERENCED": 0}
    with db.transaction() as conn:
        counts.update(_cell_status_counts(conn, rid))
    actual = counts["FREE"] + counts["OCCUPIED"] + counts["FAULT"]
    return jsonify({
        "cabinet_id": rid,
        "declared_total": row.get("total_cells"),
        "actual": actual,
        "free": counts["FREE"],
        "occupied": counts["OCCUPIED"],
        "fault": counts["FAULT"],
        # 空闲但被历史包裹引用的格口受外键保护，同样删不掉
        "referenced": counts["FREE_REFERENCED"],
        # 占用 + 故障 + 带历史记录 = 当前能缩减到的下限
        "min_reducible": counts["OCCUPIED"] + counts["FAULT"] + counts["FREE_REFERENCED"],
    })
