# 创新点 3 · 地图找柜与智能选柜（/api/map/*、/api/location/*、/api/cabinets/nearby 增补）
#
# 本模块做三件事：
#   1) 数学与排序：Haversine 距离、可用格口加权得分、排序与"首选柜"标记（纯函数，离线可测）；
#   2) 就近柜体查询：给 /api/cabinets/nearby 增补 latitude/longitude/distance_m/score/recommended；
#   3) 地址解析：/api/location/resolve，有 AMAP_WEB_KEY 走高德，否则本地降级。
#
# 关键设计约束：
#   · **保留原接口结构**：cabinets[] 元素原有键名一个都不改，只新增字段，
#     老页面/老书签/老测试依赖的 cabinet_id 升序在降级时完全不变（docs/08 §3.3）；
#   · AMAP_WEB_KEY 永不下发，/api/map/config 只给 JS API 的两个客户端凭据；
#   · 高德不可用一律 200 + degraded，绝不 500。
import logging
import math

from flask import Blueprint, jsonify, request

import apiutil
import db
from integrations import amap_client
from integrations.errors import IntegrationError

location_bp = Blueprint("location", __name__, url_prefix="/api")

log = logging.getLogger("location")

EARTH_RADIUS_M = 6371000.0

# 评分权重：空闲格口越多越优，距离越近越优。
# 之所以让"可用性"略高于"距离"：走 200m 到没格口的柜子，不如走 400m 到有空格的柜子。
_W_AVAILABILITY = 0.6
_W_DISTANCE = 0.4

# 距离衰减半径：超过这个距离视为"很远"，距离项趋近 0
_DISTANCE_DECAY_M = 3000.0

# /api/location/resolve 返回的最近柜体数量
_NEAREST_LIMIT = 5


# ---------------------------------------------------------------------------
# 数学（纯函数，离线可测）
# ---------------------------------------------------------------------------
def haversine_m(lat1, lng1, lat2, lng2):
    """两经纬度之间的球面直线距离（米）。参数非法返回 None。"""
    try:
        lat1, lng1, lat2, lng2 = float(lat1), float(lng1), float(lat2), float(lng2)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        return None
    if not (-180 <= lng1 <= 180 and -180 <= lng2 <= 180):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    a = min(1.0, max(0.0, a))
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(a))


def parse_coord(value, *, kind="lat"):
    """解析并校验坐标参数，返回 (float, None) 或 (None, 错误文案)。

    纬度 ±90、经度 ±180；非数字一律视为非法（契约 §3.1：400 BAD_REQUEST）。
    """
    if value is None or str(value).strip() == "":
        return None, f"缺少 {kind}"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, f"{kind} 必须是数字"
    if math.isnan(v) or math.isinf(v):
        return None, f"{kind} 必须是有限数字"
    limit = 90.0 if kind == "lat" else 180.0
    if not (-limit <= v <= limit):
        return None, f"{kind} 超出范围（-{limit:g} ~ {limit:g}）"
    return v, None


def availability_score(free_cnt, total, distance_m):
    """可用格口加权得分，0~1，越高越优。

    · 可用性项：free_cnt / total（无格口时按 0 处理，避免除零）；
    · 距离项：1 - min(distance/3000, 1)，线性衰减；
    · 缺距离（distance_m 为 None）时只用可用性项——不能把"未知距离"当成"最近"。

    **满柜直接 0 分**（而不是"距离近所以还有分"）：一个没有空闲格口的柜子，
    无论多近都装不下用户的包裹，给它任何正分都可能把它选成"首选柜"，
    这属于最严重的推荐错误（用户白跑一趟）。
    """
    try:
        total = float(total or 0)
        free = float(free_cnt or 0)
    except (TypeError, ValueError):
        return 0.0
    if total <= 0 or free <= 0:
        return 0.0
    avail = max(0.0, min(1.0, free / total))
    if distance_m is None:
        return round(avail * _W_AVAILABILITY / (_W_AVAILABILITY + _W_DISTANCE), 4)
    try:
        d = max(0.0, float(distance_m))
    except (TypeError, ValueError):
        d = _DISTANCE_DECAY_M
    dist_term = 1.0 - min(d / _DISTANCE_DECAY_M, 1.0)
    return round(avail * _W_AVAILABILITY + dist_term * _W_DISTANCE, 4)


def sort_and_mark(rows, user_lat=None, user_lng=None):
    """给每行补 distance_m / score / recommended，并按契约排序。

    rows 元素须已含 latitude / longitude / free_cnt / total / cabinet_id（可为 None 坐标）。
    返回 (rows, sorted_by)。
    """
    with_coord = False
    for r in rows:
        cab_lat, cab_lng = r.get("latitude"), r.get("longitude")
        dist = None
        if user_lat is not None and user_lng is not None and cab_lat is not None and cab_lng is not None:
            d = haversine_m(user_lat, user_lng, cab_lat, cab_lng)
            if d is not None:
                dist = int(round(d))
                with_coord = True
        r["distance_m"] = dist
        r["score"] = (availability_score(r.get("free_cnt"), r.get("total"), dist)
                      if user_lat is not None and user_lng is not None else None)
        r["recommended"] = False

    if user_lat is not None and user_lng is not None and with_coord:
        # 契约 §3.1 排序规则：
        #   ① 坐标缺失的柜体**排在末尾**（distance_m: null），且不影响其它柜的相对顺序；
        #   ② 其余按 score 降序 → distance_m 升序 → cabinet_id 升序。
        # 用布尔位做第一排序键，比拿 10^12 塞进 distance 更直白，也不会在极端距离下出错。
        rows.sort(key=lambda x: (
            x["distance_m"] is None,
            -(x["score"] if x["score"] is not None else 0.0),
            x["distance_m"] if x["distance_m"] is not None else 0,
            x.get("cabinet_id") or 0,
        ))
        # 首选柜：得分最高且**确实可用**者，仅 1 个为 true。
        # 若第一名得分为 0（全部满柜），则不推荐任何柜体——"推荐一个满柜"毫无意义。
        best = rows[0]
        if (best.get("score") or 0) > 0 and best.get("distance_m") is not None:
            best["recommended"] = True
        return rows, "distance+availability"

    # 无坐标 / 全部缺坐标：维持 cabinet_id 升序（与改造前完全一致的顺序）
    rows.sort(key=lambda x: x.get("cabinet_id") or 0)
    return rows, "cabinet_id"


# ---------------------------------------------------------------------------
# 柜体查询
# ---------------------------------------------------------------------------
_CABINET_SQL = """
    SELECT cab.cabinet_id, cab.cabinet_code, cab.location, cab.cabinet_type, cab.status,
           cab.latitude, cab.longitude,
           COUNT(cell.cell_id) AS total,
           COALESCE(SUM(cell.status='FREE'), 0) AS free_cnt,
           COALESCE(SUM(cell.status='FREE' AND cell.size_type='SMALL'), 0)  AS free_small,
           COALESCE(SUM(cell.status='FREE' AND cell.size_type='MEDIUM'), 0) AS free_medium,
           COALESCE(SUM(cell.status='FREE' AND cell.size_type='LARGE'), 0)  AS free_large
    FROM t_cabinet cab
    LEFT JOIN t_cell cell ON cell.cabinet_id = cab.cabinet_id
    WHERE (%s IS NULL OR cab.location LIKE %s OR cab.cabinet_code LIKE %s)
    GROUP BY cab.cabinet_id, cab.cabinet_code, cab.location, cab.cabinet_type, cab.status,
             cab.latitude, cab.longitude
    ORDER BY cab.cabinet_id
"""


def _norm_row(r):
    """把数据库行整理成接口元素：原有字段保持原样，数值列转 int，坐标转 float。"""
    return {
        "cabinet_id": r["cabinet_id"],
        "cabinet_code": r["cabinet_code"],
        "location": r["location"],
        "cabinet_type": r["cabinet_type"],
        "status": r["status"],
        "total": int(r["total"]),
        "free_cnt": int(r["free_cnt"]),
        "free_small": int(r["free_small"]),
        "free_medium": int(r["free_medium"]),
        "free_large": int(r["free_large"]),
        # 新增字段（契约 §3.1）
        "latitude": float(r["latitude"]) if r.get("latitude") is not None else None,
        "longitude": float(r["longitude"]) if r.get("longitude") is not None else None,
    }


def nearby_cabinets(q=None, lat=None, lng=None):
    """供 /api/cabinets/nearby 复用的实现，返回接口响应 dict。

    注意：这个函数**不**返回 Flask 响应，便于单测直接断言结构。
    坐标非法时抛 ValueError(文案)，由调用方转成 400。
    """
    like = f"%{q}%" if q else None
    rows = db.query(_CABINET_SQL, (like, like, like))
    cabs = [_norm_row(r) for r in rows]

    degraded, degraded_reason = False, None
    if (lat is None) != (lng is None):
        # 只给了一个：契约要求"与 lng 同时给出才生效"，因此按未提供处理（不 400）
        lat = lng = None
    if lat is not None and lng is not None:
        cabs, sorted_by = sort_and_mark(cabs, lat, lng)
        if cabs and all(c["distance_m"] is None for c in cabs):
            # 坐标合法但所有柜体都没维护坐标 → 降级但仍 200
            degraded, degraded_reason = True, "柜体坐标未维护"
            sorted_by = "cabinet_id"
    else:
        cabs, sorted_by = sort_and_mark(cabs, None, None)

    return {
        "count": len(cabs),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "sorted_by": sorted_by,
        "cabinets": cabs,
    }


def cabinets_with_coord():
    """全部维护了坐标的柜体（供地址解析算最近柜体）。"""
    return db.query(
        "SELECT cabinet_id, cabinet_code, location, latitude, longitude "
        "FROM t_cabinet WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
        "ORDER BY cabinet_id")


def nearest_cabinets(lat, lng, limit=_NEAREST_LIMIT):
    """按距离升序返回最近的若干柜体：[{cabinet_id, distance_m}]。"""
    out = []
    for c in cabinets_with_coord():
        d = haversine_m(lat, lng, c["latitude"], c["longitude"])
        if d is None:
            continue
        out.append({"cabinet_id": c["cabinet_id"], "distance_m": int(round(d)),
                    "cabinet_code": c["cabinet_code"], "location": c["location"]})
    out.sort(key=lambda x: (x["distance_m"], x["cabinet_id"]))
    return out[:limit]


def read_coord_params(args):
    """从查询参数读取 lat/lng，返回 (lat, lng, error_response)。

    契约 §3.1："与 lng 同时给出才生效" —— 因此：
      · 两个都没给      → (None, None, None)，走 cabinet_id 排序；
      · **只给了一个**  → 视为未提供（不报错），避免前端只拿到部分定位参数时整页失败；
      · 两个都给但非法  → 400 BAD_REQUEST（例如纬度 91、经度 abc）。
    这个区分很关键：前者是"客户端能力不足"，后者才是"参数错误"。
    """
    raw_lat = args.get("lat")
    raw_lng = args.get("lng")
    has_lat = raw_lat not in (None, "")
    has_lng = raw_lng not in (None, "")
    if not has_lat and not has_lng:
        return None, None, None
    if not (has_lat and has_lng):
        return None, None, None
    lat, err = parse_coord(raw_lat, kind="lat")
    if err:
        return None, None, apiutil.bad_request(err)
    lng, err = parse_coord(raw_lng, kind="lng")
    if err:
        return None, None, apiutil.bad_request(err)
    return lat, lng, None


# ---------------------------------------------------------------------------
# 路由：附近柜机（在既有接口上增补，保留旧结构）
# ---------------------------------------------------------------------------
@location_bp.route("/cabinets/nearby", methods=["GET"])
def cabinets_nearby():
    """公开：附近柜机查询，带距离与可用性加权排序。

    兼容性契约（docs/08 §3.2）：cabinets[] 元素**原有字段一个都不改**，
    只新增 latitude / longitude / distance_m / score / recommended；
    顶层新增 degraded / degraded_reason / sorted_by。
    降级（无坐标）时顺序与改造前**完全一致**（cabinet_id 升序），老用例不会假失败。
    """
    q = (request.args.get("q") or "").strip()
    lat, lng, err = read_coord_params(request.args)
    if err:
        return err
    return jsonify(nearby_cabinets(q or None, lat, lng))


# ---------------------------------------------------------------------------
# 路由：地图配置
# ---------------------------------------------------------------------------
@location_bp.route("/map/config", methods=["GET"])
def map_config():
    """公开：下发浏览器端需要的 JS API 凭据。

    安全红线：只回 AMAP_JS_KEY / AMAP_JS_SECURITY_CODE；
    AMAP_WEB_KEY **只回布尔** web_service_available，永不下发（docs/08 §3.6）。
    """
    return jsonify(amap_client.client_config())


# ---------------------------------------------------------------------------
# 路由：地址解析
# ---------------------------------------------------------------------------
@location_bp.route("/location/resolve", methods=["GET"])
def location_resolve():
    """公开：地址 → 坐标（地理编码）或 坐标 → 地址（逆地理编码）。

    降级：无 AMAP_WEB_KEY / 无网络 / 解析失败 → provider: "local", degraded: true,
    location: null；nearest_cabinets 仍按本地柜体坐标计算（有坐标时）。
    """
    address = (request.args.get("address") or "").strip()
    raw_lat = request.args.get("lat")
    raw_lng = request.args.get("lng")

    has_coord = (raw_lat not in (None, "") or raw_lng not in (None, ""))
    if not address and not has_coord:
        return apiutil.bad_request("请提供 address（地址）或 lat+lng（坐标）")

    lat = lng = None
    if has_coord:
        lat, err = parse_coord(raw_lat, kind="lat")
        if err:
            return apiutil.bad_request(err)
        lng, err = parse_coord(raw_lng, kind="lng")
        if err:
            return apiutil.bad_request(err)

    if address and len(address) > 200:
        return apiutil.bad_request("address 超长（最多 200 字符）")

    loc, provider, degraded, reason = None, "local", True, None

    if amap_client.web_service_available():
        try:
            if address:
                loc = amap_client.geocode(address)
            else:
                loc = amap_client.regeo(lng, lat)
            provider, degraded = "amap", False
        except IntegrationError as e:
            reason = e.reason
            log.info("location/resolve 降级：%s", reason)
            loc = None
    else:
        reason = "未配置 AMAP_WEB_KEY"

    # 本地降级时仍尽可能给出就近柜体（地址模式没有坐标则无法计算）
    near = []
    if loc and loc.get("lat") is not None and loc.get("lng") is not None:
        near = nearest_cabinets(loc["lat"], loc["lng"])
    elif lat is not None and lng is not None:
        near = nearest_cabinets(lat, lng)

    # nearest_cabinets 只暴露契约要求的两个字段 + 便于前端展示的两个附加字段
    nearest = [{"cabinet_id": x["cabinet_id"], "distance_m": x["distance_m"],
                "cabinet_code": x.get("cabinet_code"), "location": x.get("location")}
               for x in near]

    return jsonify({
        "provider": provider,
        "degraded": degraded,
        "degraded_reason": reason,
        "location": loc,
        "nearest_cabinets": nearest,
    })
