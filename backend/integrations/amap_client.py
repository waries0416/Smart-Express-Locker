"""高德地图客户端（Web 服务 API，**仅服务端**）。

Key 分级（docs/api-innovations.md §3.2，违反即安全事故）：
  · AMAP_JS_KEY / AMAP_JS_SECURITY_CODE —— 浏览器端 JS API 用，可以下发（需绑定域名白名单）；
  · AMAP_WEB_KEY —— 地理编码 / 逆地理编码，**永远只在服务端使用**，
                    禁止出现在任何响应、日志、前端代码里。本模块只读它、只用它，
                    对外（location.py）仅暴露布尔 web_service_available()。

容错：任何失败抛 IntegrationError，由 location.py 降级为 200 + degraded，绝不 500。
"""
import json
import logging
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

from .errors import IntegrationError

log = logging.getLogger("integrations.amap")

DEFAULT_TIMEOUT = 5.0
GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"

# 供单测替换的 HTTP 函数：签名 (url, params_dict, timeout) -> dict
_HTTP_GET = None


def _env_float(name, default):
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return v if v > 0 else default


def load_config():
    return {
        "js_key": (os.getenv("AMAP_JS_KEY") or "").strip(),
        "js_security_code": (os.getenv("AMAP_JS_SECURITY_CODE") or "").strip(),
        "web_key": (os.getenv("AMAP_WEB_KEY") or "").strip(),
        "timeout": _env_float("AMAP_TIMEOUT", DEFAULT_TIMEOUT),
    }


def web_service_available():
    """服务端是否配了 AMAP_WEB_KEY —— **只回布尔**，不泄漏 Key 本身。"""
    return bool(load_config()["web_key"])


def client_config():
    """可安全下发到浏览器的配置（GET /api/map/config 的唯一数据源）。

    只包含 JS API 客户端凭据；web_key 永不出现在返回值里。
    """
    cfg = load_config()
    js_key = cfg["js_key"] or None
    return {
        "provider": "amap",
        "js_key": js_key,
        "security_js_code": cfg["js_security_code"] or None,
        "configured": bool(js_key),
        "web_service_available": bool(cfg["web_key"]),
    }


def _http_get_json(url, params, timeout):
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    req = urllib.request.Request(full, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定域名)
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _get(url, params, timeout):
    fn = _HTTP_GET or _http_get_json
    return fn(url, params, timeout)


def _classify(exc):
    if isinstance(exc, urllib.error.HTTPError):
        code = int(getattr(exc, "code", 0) or 0)
        return f"高德错误 HTTP {code}", code
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "高德调用超时", None
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "高德调用超时", None
        return "高德网络不可达", None
    return "高德调用失败", None


def _call(url, params):
    """统一的请求 + 结果校验：status 非 '1' 一律视为失败（高德用 status 表示业务成败）。"""
    cfg = load_config()
    if not cfg["web_key"]:
        raise IntegrationError("未配置 AMAP_WEB_KEY")
    q = dict(params)
    q["key"] = cfg["web_key"]          # Key 只出现在请求参数里，不写日志
    q["output"] = "JSON"
    try:
        data = _get(url, q, cfg["timeout"])
    except Exception as exc:  # noqa: BLE001
        reason, status = _classify(exc)
        log.warning("amap 调用失败：%s", reason)
        raise IntegrationError(reason, status=status) from None
    if not isinstance(data, dict):
        raise IntegrationError("高德返回结构校验失败")
    if str(data.get("status")) != "1":
        # infocode 有定位价值，但**不含 Key**，可以安全记录
        info = data.get("info") or "未知错误"
        log.warning("amap 业务失败：info=%s infocode=%s", info, data.get("infocode"))
        raise IntegrationError(f"高德业务失败：{info}")
    return data


def geocode(address):
    """地址 → 经纬度。返回 dict(lng, lat, formatted_address, province, city, district)。"""
    data = _call(GEOCODE_URL, {"address": address})
    geos = data.get("geocodes")
    if not isinstance(geos, list) or not geos:
        raise IntegrationError("地址无法解析")
    item = geos[0] if isinstance(geos[0], dict) else {}
    lnglat = str(item.get("location") or "")
    if "," not in lnglat:
        raise IntegrationError("地址无法解析")
    lng_s, lat_s = lnglat.split(",", 1)
    try:
        lng, lat = float(lng_s), float(lat_s)
    except ValueError:
        raise IntegrationError("高德返回结构校验失败") from None
    return {
        "lng": lng,
        "lat": lat,
        "formatted_address": item.get("formatted_address") or address,
        "province": item.get("province") or None,
        "city": _city_of(item),
        "district": item.get("district") or None,
    }


def _city_of(item):
    """regeo 的 city 在直辖市级可能为空数组 []，统一归一成字符串或 None。"""
    city = item.get("city")
    if isinstance(city, list):
        city = city[0] if city else None
    if not city:
        # 直辖市：city 为空时用 province 兜底，避免前端出现空列
        prov = item.get("province")
        if isinstance(prov, list):
            prov = prov[0] if prov else None
        city = prov
    return city or None


def regeo(lng, lat):
    """经纬度 → 结构化地址。返回格式同 geocode()。"""
    data = _call(REGEO_URL, {"location": f"{lng:.6f},{lat:.6f}"})
    rg = data.get("regeocode")
    if not isinstance(rg, dict):
        raise IntegrationError("高德返回结构校验失败")
    comp = rg.get("addressComponent") or {}
    return {
        "lng": float(lng),
        "lat": float(lat),
        "formatted_address": rg.get("formatted_address") or None,
        "province": _first(comp.get("province")),
        "city": _city_of(comp),
        "district": _first(comp.get("district")),
    }


def _first(value):
    """高德在直辖市/新区把某些字段返回成空数组，统一归一。"""
    if isinstance(value, list):
        value = value[0] if value else None
    return (value or None) if not isinstance(value, list) else None
