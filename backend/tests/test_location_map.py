# 创新点 3 · 地图找柜与地址解析 · 离线单元测试
#
# 覆盖点：
#   1) Haversine 距离正确性（北京天安门 → 国贸约 8.5km 量级）与非法入参；
#   2) 评分权重、排序规则、recommended 唯一性；
#   3) /api/cabinets/nearby 保留原字段 + 新增字段，降级时顺序与改造前一致；
#   4) 坐标非法 → 400 BAD_REQUEST；
#   5) 所有柜体无坐标 → 200 + degraded + degraded_reason="柜体坐标未维护"；
#   6) /api/map/config 只下发 JS Key，**绝不泄漏 AMAP_WEB_KEY**；
#   7) /api/location/resolve 有 Key/无 Key/上游失败三种路径。
#
# 运行：cd backend && python -m unittest tests.test_location_map -v
# 数据库依赖：需要 smart_locker 库里有柜体数据；无库时相关类整类跳过。
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
for _k in ("AMAP_JS_KEY", "AMAP_JS_SECURITY_CODE", "AMAP_WEB_KEY"):
    os.environ.pop(_k, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module      # noqa: E402
import db                     # noqa: E402
import location               # noqa: E402
from integrations import amap_client  # noqa: E402
from integrations.errors import IntegrationError  # noqa: E402


def _db_ready():
    try:
        db.query_one("SELECT 1")
        return True
    except Exception:
        return False


# ===========================================================================
# 一、纯数学与排序（无需数据库）
# ===========================================================================
class HaversineTest(unittest.TestCase):
    def test_known_distance(self):
        # 天安门 (39.908722,116.397499) → 国贸 (39.908722,116.46) 约 5.3km
        d = location.haversine_m(39.908722, 116.397499, 39.908722, 116.46)
        self.assertIsNotNone(d)
        self.assertGreater(d, 5000)
        self.assertLess(d, 5600)

    def test_same_point_is_zero(self):
        self.assertAlmostEqual(
            location.haversine_m(39.9, 116.4, 39.9, 116.4), 0.0, places=3)

    def test_symmetry(self):
        a = location.haversine_m(39.9, 116.4, 31.23, 121.47)
        b = location.haversine_m(31.23, 121.47, 39.9, 116.4)
        self.assertAlmostEqual(a, b, places=3)

    def test_invalid_returns_none(self):
        self.assertIsNone(location.haversine_m(None, 116.4, 39.9, 116.4))
        self.assertIsNone(location.haversine_m("abc", 116.4, 39.9, 116.4))
        self.assertIsNone(location.haversine_m(100, 116.4, 39.9, 116.4))  # 纬度越界
        self.assertIsNone(location.haversine_m(39.9, 200, 39.9, 116.4))   # 经度越界


class ParseCoordTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(location.parse_coord("39.9", kind="lat")[0], 39.9)
        self.assertEqual(location.parse_coord("-180", kind="lng")[0], -180.0)

    def test_boundaries_valid(self):
        self.assertEqual(location.parse_coord("90", kind="lat")[0], 90.0)
        self.assertEqual(location.parse_coord("-90", kind="lat")[0], -90.0)
        self.assertEqual(location.parse_coord("180", kind="lng")[0], 180.0)

    def test_out_of_range(self):
        v, err = location.parse_coord("90.1", kind="lat")
        self.assertIsNone(v)
        self.assertIn("超出范围", err)

    def test_non_numeric(self):
        v, err = location.parse_coord("abc", kind="lat")
        self.assertIsNone(v)
        self.assertIn("数字", err)

    def test_empty(self):
        v, err = location.parse_coord("", kind="lat")
        self.assertIsNone(v)
        self.assertIn("缺少", err)

    def test_nan_inf(self):
        for bad in ("nan", "inf", "-inf"):
            v, _err = location.parse_coord(bad, kind="lat")
            self.assertIsNone(v, f"{bad} 应被拒绝")


class ScoreTest(unittest.TestCase):
    def test_free_ratio_dominates(self):
        # 同样的距离下，空闲格口多的得分更高
        a = location.availability_score(10, 10, 100)
        b = location.availability_score(1, 10, 100)
        self.assertGreater(a, b)

    def test_closer_is_better(self):
        near = location.availability_score(5, 10, 100)
        far = location.availability_score(5, 10, 2500)
        self.assertGreater(near, far)

    def test_zero_free_scores_zero(self):
        """满柜（free_cnt=0）得分必须为 0：推荐一个没有格口的柜子等于让用户白跑。"""
        self.assertEqual(location.availability_score(0, 10, 100), 0.0)
        self.assertEqual(location.availability_score(0, 0, 100), 0.0)

    def test_zero_total_no_division_error(self):
        self.assertEqual(location.availability_score(5, 0, 100), 0.0)

    def test_none_distance_does_not_fake_nearest(self):
        # 缺距离时只用可用性项（不得把"未知"当"最近"）
        s = location.availability_score(5, 5, None)
        self.assertGreater(s, 0)
        self.assertLess(s, 1.0)


class SortMarkTest(unittest.TestCase):
    def _rows(self):
        return [
            {"cabinet_id": 1, "latitude": 39.908722, "longitude": 116.397499,
             "total": 10, "free_cnt": 1},
            {"cabinet_id": 2, "latitude": 39.914512, "longitude": 116.403871,
             "total": 10, "free_cnt": 9},
            {"cabinet_id": 3, "latitude": None, "longitude": None,
             "total": 10, "free_cnt": 10},
        ]

    def test_no_coord_cabinet_goes_last(self):
        """契约：坐标缺失的柜体排在末尾（distance_m: null），不影响其它柜排序。"""
        rows, _ = location.sort_and_mark(self._rows(), 39.908722, 116.397499)
        self.assertEqual([r["cabinet_id"] for r in rows], [2, 1, 3])
        self.assertIsNone(rows[-1]["distance_m"])
        self.assertFalse(rows[-1]["recommended"])

    def test_no_coords_keeps_cabinet_id_order(self):
        rows, sorted_by = location.sort_and_mark(self._rows(), None, None)
        self.assertEqual(sorted_by, "cabinet_id")
        self.assertEqual([r["cabinet_id"] for r in rows], [1, 2, 3])
        for r in rows:
            self.assertIsNone(r["distance_m"])
            self.assertIsNone(r["score"])
            self.assertFalse(r["recommended"])

    def test_recommended_is_unique_and_available(self):
        rows, sorted_by = location.sort_and_mark(self._rows(), 39.908722, 116.397499)
        self.assertEqual(sorted_by, "distance+availability")
        rec = [r for r in rows if r["recommended"]]
        self.assertEqual(len(rec), 1, "recommended 必须唯一")
        self.assertGreater(rec[0]["score"], 0)
        self.assertIsNotNone(rec[0]["distance_m"])

    def test_all_full_cabinets_recommend_nothing(self):
        """所有柜体都满时不得推荐任何一个（recommended 全 false）。"""
        rows = [
            {"cabinet_id": 1, "latitude": 39.908722, "longitude": 116.397499,
             "total": 10, "free_cnt": 0},
            {"cabinet_id": 2, "latitude": 39.914512, "longitude": 116.403871,
             "total": 5, "free_cnt": 0},
        ]
        rows, _ = location.sort_and_mark(rows, 39.908722, 116.397499)
        self.assertFalse(any(r["recommended"] for r in rows))

    def test_distance_is_rounded_int(self):
        rows, _ = location.sort_and_mark(self._rows(), 39.908722, 116.397499)
        for r in rows:
            if r["distance_m"] is not None:
                self.assertIsInstance(r["distance_m"], int)


# ===========================================================================
# 二、map/config（无需数据库，且是安全红线）
# ===========================================================================
class MapConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self._saved = {k: os.environ.get(k) for k in
                       ("AMAP_JS_KEY", "AMAP_JS_SECURITY_CODE", "AMAP_WEB_KEY")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_unconfigured(self):
        body = self.client.get("/api/map/config").get_json()
        self.assertEqual(body["provider"], "amap")
        self.assertIsNone(body["js_key"])
        self.assertIsNone(body["security_js_code"])
        self.assertFalse(body["configured"])
        self.assertFalse(body["web_service_available"])

    def test_js_keys_are_downstreamed(self):
        os.environ["AMAP_JS_KEY"] = "js-key-public-123"
        os.environ["AMAP_JS_SECURITY_CODE"] = "sec-code-456"
        body = self.client.get("/api/map/config").get_json()
        self.assertEqual(body["js_key"], "js-key-public-123")
        self.assertEqual(body["security_js_code"], "sec-code-456")
        self.assertTrue(body["configured"])

    def test_web_key_never_downstreamed(self):
        """安全红线：AMAP_WEB_KEY 绝不能出现在响应里，只能回布尔。"""
        os.environ["AMAP_WEB_KEY"] = "web-key-MUST-NOT-LEAK"
        os.environ["AMAP_JS_KEY"] = "js-key-public-123"
        resp = self.client.get("/api/map/config")
        raw = resp.get_data(as_text=True)
        body = resp.get_json()
        self.assertNotIn("web-key-MUST-NOT-LEAK", raw)
        self.assertTrue(body["web_service_available"])
        self.assertNotIn("web_key", body)
        self.assertNotIn("web-key-MUST-NOT-LEAK", repr(body))

    def test_web_key_only_still_reports_availability(self):
        os.environ["AMAP_WEB_KEY"] = "web-only-key"
        body = self.client.get("/api/map/config").get_json()
        self.assertFalse(body["configured"])       # 无 JS Key → 前端地图降级
        self.assertTrue(body["web_service_available"])
        self.assertIsNone(body["js_key"])


# ===========================================================================
# 三、location/resolve（无需数据库也能验证 Key 缺失路径）
# ===========================================================================
class LocationResolveNoKeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self._saved = {k: os.environ.get(k) for k in
                       ("AMAP_JS_KEY", "AMAP_JS_SECURITY_CODE", "AMAP_WEB_KEY")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_missing_params_is_400(self):
        resp = self.client.get("/api/location/resolve")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "BAD_REQUEST")

    def test_invalid_coords_is_400(self):
        resp = self.client.get("/api/location/resolve?lat=999&lng=116.4")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.get("/api/location/resolve?lat=39.9&lng=abc")
        self.assertEqual(resp.status_code, 400)

    def test_overlong_address_is_400(self):
        resp = self.client.get("/api/location/resolve?address=" + "北" * 201)
        self.assertEqual(resp.status_code, 400)

    @unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
    def test_no_web_key_degrades_to_local(self):
        resp = self.client.get("/api/location/resolve?address=北京市东城区")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["provider"], "local")
        self.assertTrue(body["degraded"])
        self.assertIsNone(body["location"])
        self.assertEqual(body["degraded_reason"], "未配置 AMAP_WEB_KEY")
        self.assertIsInstance(body["nearest_cabinets"], list)

    @unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
    def test_coord_query_without_key_still_lists_nearest(self):
        body = self.client.get(
            "/api/location/resolve?lat=39.908722&lng=116.397499").get_json()
        self.assertEqual(body["provider"], "local")
        self.assertTrue(body["degraded"])
        self.assertIsNone(body["location"])
        # 无 Key 时 nearest_cabinets 仍按本地柜体坐标计算（契约 §3.3）
        self.assertIsInstance(body["nearest_cabinets"], list)


class LocationResolveWithAmapTest(unittest.TestCase):
    """有 AMAP_WEB_KEY 时用假 HTTP 层验证成功与失败两条路径（完全离线）。"""

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self._saved = {k: os.environ.get(k) for k in
                       ("AMAP_JS_KEY", "AMAP_JS_SECURITY_CODE", "AMAP_WEB_KEY")}
        self._saved_http = amap_client._HTTP_GET
        os.environ["AMAP_WEB_KEY"] = "web-key-for-test"

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        amap_client._HTTP_GET = self._saved_http

    def fake_amap(self, payload=None, *, exc=None):
        def _fn(url, params, timeout):
            if exc is not None:
                raise exc
            return payload
        amap_client._HTTP_GET = _fn

    def test_geocode_success(self):
        self.fake_amap({
            "status": "1", "info": "OK", "count": "1",
            "geocodes": [{
                "formatted_address": "北京市东城区东长安街",
                "province": "北京市", "city": [], "district": "东城区",
                "location": "116.397499,39.908722",
            }],
        })
        body = self.client.get("/api/location/resolve?address=天安门").get_json()
        self.assertEqual(body["provider"], "amap")
        self.assertFalse(body["degraded"])
        self.assertIsNone(body["degraded_reason"])
        self.assertAlmostEqual(body["location"]["lng"], 116.397499, places=5)
        self.assertAlmostEqual(body["location"]["lat"], 39.908722, places=5)
        self.assertEqual(body["location"]["district"], "东城区")
        # 直辖市的 city 为空数组 → 归一为 province
        self.assertEqual(body["location"]["city"], "北京市")

    def test_regeo_success(self):
        self.fake_amap({
            "status": "1", "info": "OK",
            "regeocode": {
                "formatted_address": "北京市东城区东长安街1号",
                "addressComponent": {"province": "北京市", "city": [], "district": "东城区"},
            },
        })
        body = self.client.get(
            "/api/location/resolve?lat=39.908722&lng=116.397499").get_json()
        self.assertEqual(body["provider"], "amap")
        self.assertFalse(body["degraded"])
        self.assertIn("东长安街", body["location"]["formatted_address"])

    def test_amap_status_zero_degrades(self):
        self.fake_amap({"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"})
        resp = self.client.get("/api/location/resolve?address=天安门")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["provider"], "local")
        self.assertTrue(body["degraded"])
        self.assertIsNone(body["location"])
        self.assertIn("高德", body["degraded_reason"])

    def test_amap_timeout_degrades(self):
        import socket
        self.fake_amap(exc=socket.timeout("timed out"))
        body = self.client.get("/api/location/resolve?address=天安门").get_json()
        self.assertEqual(body["provider"], "local")
        self.assertTrue(body["degraded"])
        self.assertIn("超时", body["degraded_reason"])

    def test_amap_no_geocode_result_degrades(self):
        self.fake_amap({"status": "1", "info": "OK", "count": "0", "geocodes": []})
        body = self.client.get("/api/location/resolve?address=不存在的地方").get_json()
        self.assertEqual(body["provider"], "local")
        self.assertTrue(body["degraded"])

    def test_web_key_not_in_response(self):
        self.fake_amap({"status": "0", "info": "INVALID_USER_KEY"})
        raw = self.client.get("/api/location/resolve?address=天安门").get_data(as_text=True)
        self.assertNotIn("web-key-for-test", raw)


# ===========================================================================
# 四、/api/cabinets/nearby（需要数据库）
# ===========================================================================
@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
class NearbyTest(unittest.TestCase):
    """用自建夹具（带坐标的柜体 + 格口）验证增补字段与排序，不依赖演示数据。"""

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        from tests import _fixtures
        self.client = app_module.app.test_client()
        # 夹具自带 1 个柜体（39.908722/116.397499）+ 3 个格口（全 FREE）
        self.fx = _fixtures.Fixture().setup(with_package=False)
        self.cabinet_id = self.fx.cabinet_id

    def tearDown(self):
        self.fx.teardown()

    def test_legacy_fields_preserved(self):
        """契约核心：原有键名与含义一个都不改（老前端/老用例不能假失败）。"""
        resp = self.client.get("/api/cabinets/nearby")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("count", body)
        self.assertIn("cabinets", body)
        self.assertIsInstance(body["cabinets"], list)
        self.assertGreaterEqual(body["count"], 1)
        legacy = ("cabinet_id", "cabinet_code", "location", "cabinet_type", "status",
                  "total", "free_cnt", "free_small", "free_medium", "free_large")
        for cab in body["cabinets"]:
            for key in legacy:
                self.assertIn(key, cab, f"原有字段 {key} 丢失")
            for key in ("latitude", "longitude", "distance_m", "score", "recommended"):
                self.assertIn(key, cab, f"新增字段 {key} 缺失")

    def test_top_level_new_fields(self):
        body = self.client.get("/api/cabinets/nearby").get_json()
        for key in ("degraded", "degraded_reason", "sorted_by"):
            self.assertIn(key, body)
        self.assertEqual(body["sorted_by"], "cabinet_id")

    def test_without_coords_order_is_cabinet_id(self):
        body = self.client.get("/api/cabinets/nearby").get_json()
        ids = [c["cabinet_id"] for c in body["cabinets"]]
        self.assertEqual(ids, sorted(ids), "无坐标时顺序必须与改造前一致")

    def test_free_counts_are_correct(self):
        """夹具里 3 个格口全 FREE：total=3、free_cnt=3、分规格各 1。"""
        body = self.client.get("/api/cabinets/nearby").get_json()
        cab = next(c for c in body["cabinets"] if c["cabinet_id"] == self.cabinet_id)
        self.assertEqual(cab["total"], 3)
        self.assertEqual(cab["free_cnt"], 3)
        self.assertEqual(cab["free_small"], 1)
        self.assertEqual(cab["free_medium"], 1)
        self.assertEqual(cab["free_large"], 1)

    def test_with_coords_sorts_and_marks_one(self):
        body = self.client.get(
            "/api/cabinets/nearby?lat=39.908722&lng=116.397499").get_json()
        self.assertEqual(body["sorted_by"], "distance+availability")
        rec = [c for c in body["cabinets"] if c["recommended"]]
        self.assertLessEqual(len(rec), 1, "recommended 最多 1 个")
        # 有坐标的柜体必须算出 distance_m，且自己到自己是 0
        for cab in body["cabinets"]:
            if cab["latitude"] is not None and cab["longitude"] is not None:
                self.assertIsNotNone(cab["distance_m"])
        mine = next(c for c in body["cabinets"] if c["cabinet_id"] == self.cabinet_id)
        self.assertEqual(mine["distance_m"], 0)
        self.assertGreater(mine["score"], 0)

    def test_invalid_coords_is_400(self):
        for qs in ("lat=91&lng=116.4", "lat=39.9&lng=181", "lat=abc&lng=116.4"):
            resp = self.client.get(f"/api/cabinets/nearby?{qs}")
            self.assertEqual(resp.status_code, 400, qs)
            self.assertEqual(resp.get_json()["code"], "BAD_REQUEST")

    def test_only_one_coord_param_is_ignored(self):
        """契约：与 lng 同时给出才生效；只给 lat 不报错，按未提供处理。"""
        resp = self.client.get("/api/cabinets/nearby?lat=39.9")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["sorted_by"], "cabinet_id")

    def test_q_filter_still_works(self):
        cab = db.query_one("SELECT cabinet_code FROM t_cabinet WHERE cabinet_id=%s",
                           (self.cabinet_id,))
        body = self.client.get(
            f"/api/cabinets/nearby?q={cab['cabinet_code']}").get_json()
        self.assertGreaterEqual(body["count"], 1)

    def test_mobile_alias_matches(self):
        """/api/m/cabinets/nearby 必须与新接口结构一致（共用同一实现）。"""
        a = self.client.get("/api/cabinets/nearby").get_json()
        b = self.client.get("/api/m/cabinets/nearby").get_json()
        self.assertEqual(a["sorted_by"], b["sorted_by"])
        self.assertEqual(len(a["cabinets"]), len(b["cabinets"]))

    def test_all_coords_missing_degrades(self):
        """所有柜体都没坐标时：200 + degraded + reason（契约 §3.1）。"""
        rows = db.query(
            "SELECT cabinet_id, latitude, longitude FROM t_cabinet "
            "WHERE latitude IS NOT NULL OR longitude IS NOT NULL LIMIT 200")
        if not rows:
            body = self.client.get(
                "/api/cabinets/nearby?lat=39.908722&lng=116.397499").get_json()
            self.assertTrue(body["degraded"])
            self.assertEqual(body["degraded_reason"], "柜体坐标未维护")
            self.assertEqual(body["sorted_by"], "cabinet_id")
            return
        # 临时把坐标清空 → 断言 → 还原（不 DROP、不删数据）
        saved = [(r["cabinet_id"], r["latitude"], r["longitude"]) for r in rows]
        try:
            db.execute("UPDATE t_cabinet SET latitude=NULL, longitude=NULL "
                       "WHERE cabinet_id IN (%s)"
                       % ",".join(["%s"] * len(saved)), [x[0] for x in saved])
            body = self.client.get(
                "/api/cabinets/nearby?lat=39.908722&lng=116.397499").get_json()
            self.assertTrue(body["degraded"])
            self.assertEqual(body["degraded_reason"], "柜体坐标未维护")
            self.assertEqual(body["sorted_by"], "cabinet_id")
        finally:
            for cid, lat, lng in saved:
                db.execute("UPDATE t_cabinet SET latitude=%s, longitude=%s "
                           "WHERE cabinet_id=%s", (lat, lng, cid))

    def test_full_cabinet_gets_zero_score(self):
        """满柜（无空闲格口）得分必须为 0，且不会被标成推荐。"""
        db.execute("UPDATE t_cell SET status='OCCUPIED' WHERE cabinet_id=%s",
                   (self.cabinet_id,))
        try:
            body = self.client.get(
                "/api/cabinets/nearby?lat=39.908722&lng=116.397499").get_json()
            mine = next(c for c in body["cabinets"]
                        if c["cabinet_id"] == self.cabinet_id)
            self.assertEqual(mine["free_cnt"], 0)
            self.assertEqual(mine["score"], 0.0)
            self.assertFalse(mine["recommended"])
        finally:
            db.execute("UPDATE t_cell SET status='FREE' WHERE cabinet_id=%s",
                       (self.cabinet_id,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
