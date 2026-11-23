# 创新点 1 · AI 包装推荐与问答 · 离线单元测试
#
# 覆盖点（对应 R1 验收要求的每一类风险）：
#   1) 无 DEEPSEEK_API_KEY：source="rule"、degraded=true、结构完整、仍 200；
#   2) 有 Key 且模型正常：source="deepseek"、degraded=false；
#   3) 模型超时 / 5xx / 429：降级为规则，绝不 500，degraded_reason 明确；
#   4) 模型返回坏 JSON / 结构不合法：视为失败 → 降级；
#   5) 模型漏报禁运品：本地词表**强制补全**（安全事故代价不对称）；
#   6) 模型返回字典外枚举（XL）与过少/过多步骤：服务端强制纠偏；
#   7) notice 固定文案不可被模型改写；
#   8) Key 绝不出现在任何响应里；
#   9) 参数校验（缺失/超长/非字符串）与频控 429。
#
# 运行（无 Key、无网络也能全绿）：
#   cd backend && python -m unittest tests.test_ai_assistant -v
import json
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")  # 不启动通知线程
os.environ.pop("DEEPSEEK_API_KEY", None)     # 确保默认无 Key
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import _guard  # noqa: E402,F401  进程级测试互斥（见 tests/_guard.py）
import app as app_module            # noqa: E402
import assistant                    # noqa: E402
import packaging_rules              # noqa: E402
from integrations import deepseek_client  # noqa: E402
from integrations.errors import IntegrationError  # noqa: E402

NOTICE = "结果仅供参考，以快递员/承运商审核为准"


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self._saved_env = {k: os.environ.get(k) for k in
                           ("DEEPSEEK_API_KEY", "AI_ENABLED", "DEEPSEEK_MAX_RETRY")}
        self._saved_http = deepseek_client._HTTP_POST
        os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ["AI_ENABLED"] = "1"
        deepseek_client._HTTP_POST = None
        # 频控是进程级单例：每个用例前清空，避免相互影响
        import apiutil
        apiutil.AI_LIMITER.reset()

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        deepseek_client._HTTP_POST = self._saved_http

    # ---- 假 HTTP 层：完全离线 ----
    def fake_http(self, content=None, *, exc=None, payload=None):
        """替换 deepseek_client 的 HTTP 层。

        content —— 模型返回的 content 字符串；
        payload —— 完整的 chat/completions 响应 dict（优先于 content）；
        exc     —— 抛出该异常模拟上游故障。
        """
        def _fn(url, body, headers, timeout):
            if exc is not None:
                raise exc
            if payload is not None:
                return payload
            return {"choices": [{"message": {"content": content}}]}
        deepseek_client._HTTP_POST = _fn

    def use_key(self):
        os.environ["DEEPSEEK_API_KEY"] = "sk-unit-test-should-never-leak"
        # 重试会让"失败类"用例变慢/计数不符，这里显式归零
        os.environ["DEEPSEEK_MAX_RETRY"] = "0"


# ===========================================================================
# 一、无 Key 的本地规则路径
# ===========================================================================
class NoKeyRuleTest(_Base):
    def test_health_reports_rule_mode_without_key(self):
        resp = self.client.get("/api/ai/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["provider"], "deepseek")
        self.assertFalse(body["configured"])
        self.assertEqual(body["mode"], "rule")
        # 安全：响应里绝不能出现任何 Key 形态
        self.assertNotIn("sk-", resp.get_data(as_text=True))

    def test_pack_recommend_degrades_to_rules(self):
        resp = self.client.post("/api/ai/pack-recommend",
                                json={"description": "一个玻璃杯和两本书"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["source"], "rule")
        self.assertTrue(body["degraded"])
        self.assertEqual(body["degraded_reason"], "未配置 DEEPSEEK_API_KEY")
        # 结构完整性：每类字段都在且类型正确
        self.assertIsInstance(body["forbidden"], list)
        self.assertIsInstance(body["sensitive"], list)
        self.assertIsInstance(body["packaging"], list)
        self.assertIn(body["size_type"], ("SMALL", "MEDIUM", "LARGE"))
        self.assertIsInstance(body["materials"], list)
        self.assertIsInstance(body["elapsed_ms"], int)
        self.assertEqual(body["notice"], NOTICE)
        self.assertIn("以快递员/承运商审核为准", body["notice"])
        # 玻璃杯必须被识别为敏感物（规则词表命中）
        names = [x["name"] for x in body["sensitive"]]
        self.assertIn("玻璃杯", names)
        # 步骤编号从 1 连续递增
        steps = [p["step"] for p in body["packaging"]]
        self.assertEqual(steps, list(range(1, len(steps) + 1)))
        self.assertGreaterEqual(len(steps), packaging_rules.MIN_STEPS)

    def test_pack_recommend_flags_forbidden_items(self):
        resp = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两节锂电池和一个充电宝"})
        body = resp.get_json()
        names = [x["name"] for x in body["forbidden"]]
        self.assertIn("锂电池", names)
        for item in body["forbidden"]:
            self.assertTrue(item["reason"])

    def test_chat_degrades_to_faq_rules(self):
        resp = self.client.post("/api/ai/chat", json={"message": "超时了怎么取件？"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["source"], "rule")
        self.assertTrue(body["degraded"])
        self.assertTrue(body["reply"])
        self.assertIn("超时", body["reply"])
        self.assertTrue(body["session_id"])
        self.assertLessEqual(len(body["session_id"]), 64)

    def test_chat_echoes_valid_session_id(self):
        resp = self.client.post("/api/ai/chat",
                                json={"message": "怎么寄件", "session_id": "s_fixed01"})
        self.assertEqual(resp.get_json()["session_id"], "s_fixed01")

    def test_chat_generates_session_when_missing(self):
        body = self.client.post("/api/ai/chat", json={"message": "你好"}).get_json()
        self.assertTrue(body["session_id"].startswith(assistant._SESSION_PREFIX))

    def test_chat_unknown_question_returns_guidance(self):
        # 用一个不命中任何 FAQ 关键词的问题，验证兜底引导文案
        body = self.client.post("/api/ai/chat",
                                json={"message": "量子纠缠是什么"}).get_json()
        self.assertEqual(body["source"], "rule")
        self.assertIn("建议", body["reply"])


# ===========================================================================
# 二、有 Key 且模型正常的路径
# ===========================================================================
class ModelSuccessTest(_Base):
    def test_health_reports_deepseek_mode_with_key(self):
        self.use_key()
        body = self.client.get("/api/ai/health").get_json()
        self.assertTrue(body["configured"])
        self.assertEqual(body["mode"], "deepseek")
        # 安全：绝不回传 Key 本身
        self.assertNotIn("sk-unit-test", json.dumps(body))

    def test_pack_recommend_uses_model_output(self):
        self.use_key()
        model_json = {
            "forbidden": [{"name": "锂电池", "reason": "航空禁运"}],
            "sensitive": [{"name": "玻璃杯", "reason": "易碎需缓冲"}],
            "packaging": [
                {"step": 1, "title": "气泡膜包裹", "detail": "玻璃杯至少包 3 层"},
                {"step": 2, "title": "装箱", "detail": "居中放置并填充"},
                {"step": 3, "title": "封箱贴标", "detail": "十字加固并贴易碎标签"},
            ],
            "size_type": "MEDIUM",
            "size_reason": "两本书+玻璃杯体积中等，需留缓冲空间",
            "materials": ["气泡膜", "5 号纸箱", "易碎标签"],
            "notice": "模型胡写的提示语",
        }
        self.fake_http(json.dumps(model_json, ensure_ascii=False))
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "一个玻璃杯和两本书"}).get_json()
        self.assertEqual(body["source"], "deepseek")
        self.assertFalse(body["degraded"])
        self.assertIsNone(body["degraded_reason"])
        self.assertEqual(body["size_type"], "MEDIUM")
        self.assertEqual(body["materials"], ["气泡膜", "5 号纸箱", "易碎标签"])
        self.assertEqual(len(body["packaging"]), 3)
        # notice 固定：模型改不动
        self.assertEqual(body["notice"], NOTICE)
        # 响应里不得出现测试用 Key
        self.assertNotIn("sk-unit-test", json.dumps(body, ensure_ascii=False))

    def test_chat_uses_model_reply(self):
        self.use_key()
        self.fake_http("超时后请先在手机端缴清保管费再取件。")
        body = self.client.post("/api/ai/chat",
                                json={"message": "超时了怎么办"}).get_json()
        self.assertEqual(body["source"], "deepseek")
        self.assertFalse(body["degraded"])
        self.assertIn("保管费", body["reply"])


# ===========================================================================
# 三、上游故障 → 一律降级，绝不 500
# ===========================================================================
class DegradeOnFailureTest(_Base):
    def _assert_degraded(self, body, expect_reason_part):
        self.assertEqual(body["source"], "rule")
        self.assertTrue(body["degraded"])
        self.assertIn(expect_reason_part, body["degraded_reason"])
        self.assertIn(body["size_type"], ("SMALL", "MEDIUM", "LARGE"))
        self.assertEqual(body["notice"], NOTICE)

    def test_timeout_degrades(self):
        self.use_key()
        import socket
        self.fake_http(exc=socket.timeout("timed out"))
        resp = self.client.post("/api/ai/pack-recommend", json={"description": "两本书"})
        self.assertEqual(resp.status_code, 200)
        self._assert_degraded(resp.get_json(), "调用超时")

    def test_http_500_degrades(self):
        self.use_key()
        import urllib.error
        err = urllib.error.HTTPError("https://api.deepseek.com", 500, "Server Error", {}, None)
        self.fake_http(exc=err)
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self._assert_degraded(body, "HTTP 500")

    def test_http_429_degrades(self):
        self.use_key()
        import urllib.error
        err = urllib.error.HTTPError("https://api.deepseek.com", 429, "Too Many Requests", {}, None)
        self.fake_http(exc=err)
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self._assert_degraded(body, "HTTP 429")

    def test_bad_json_degrades(self):
        self.use_key()
        self.fake_http("这不是 JSON {{{")
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self._assert_degraded(body, "返回结构校验失败")

    def test_missing_choices_degrades(self):
        self.use_key()
        self.fake_http(payload={"id": "x", "choices": []})
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self._assert_degraded(body, "返回结构校验失败")

    def test_network_unreachable_degrades(self):
        self.use_key()
        import urllib.error
        self.fake_http(exc=urllib.error.URLError("nodename nor servname provided"))
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self._assert_degraded(body, "网络不可达")

    def test_chat_degrades_on_failure(self):
        self.use_key()
        import socket
        self.fake_http(exc=socket.timeout("timed out"))
        resp = self.client.post("/api/ai/chat", json={"message": "怎么寄件"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["source"], "rule")
        self.assertTrue(body["degraded"])
        self.assertTrue(body["reply"])

    def test_ai_enabled_off_forces_rules(self):
        self.use_key()
        os.environ["AI_ENABLED"] = "0"
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self.assertEqual(body["source"], "rule")
        self.assertTrue(body["degraded"])
        self.assertIn("AI_ENABLED", body["degraded_reason"])

    def test_retry_counts_for_retryable_only(self):
        """429/5xx/超时可重试，4xx 立即降级（不为无意义的重试浪费用户等待）。"""
        self.use_key()
        os.environ["DEEPSEEK_MAX_RETRY"] = "2"
        calls = {"n": 0}

        def _fn(url, body, headers, timeout):
            calls["n"] += 1
            import socket
            raise socket.timeout("timed out")

        deepseek_client._HTTP_POST = _fn
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self.assertEqual(body["source"], "rule")
        self.assertEqual(calls["n"], 3, "超时应重试 2 次，共 3 次调用")

    def test_4xx_not_retried(self):
        self.use_key()
        os.environ["DEEPSEEK_MAX_RETRY"] = "2"
        calls = {"n": 0}

        def _fn(url, body, headers, timeout):
            calls["n"] += 1
            import urllib.error
            raise urllib.error.HTTPError("https://x", 400, "Bad Request", {}, None)

        deepseek_client._HTTP_POST = _fn
        self.client.post("/api/ai/pack-recommend", json={"description": "两本书"})
        self.assertEqual(calls["n"], 1, "4xx 不应重试")


# ===========================================================================
# 四、服务端二次校验（模型只建议、服务端说了算）
# ===========================================================================
class ValidationTest(_Base):
    def test_illegal_size_is_corrected(self):
        """模型返回 XL → 强制落回合法档位，否则格口分配会静默失败。"""
        self.use_key()
        self.fake_http(json.dumps({
            "forbidden": [], "sensitive": [],
            "packaging": [{"step": 1, "title": "a", "detail": "b"},
                          {"step": 2, "title": "c", "detail": "d"}],
            "size_type": "XL", "size_reason": "很大", "materials": ["气泡膜"],
            "notice": "x",
        }, ensure_ascii=False))
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "一个大件家电"}).get_json()
        self.assertIn(body["size_type"], ("SMALL", "MEDIUM", "LARGE"))
        self.assertEqual(body["size_type"], "LARGE", "XL 应归一为 LARGE 而不是丢回默认")

    def test_missing_forbidden_is_force_completed(self):
        """模型漏报锂电池 → 本地词表强制补全（安全事故代价不对称）。"""
        self.use_key()
        self.fake_http(json.dumps({
            "forbidden": [], "sensitive": [],
            "packaging": [{"step": 1, "title": "a", "detail": "b"},
                          {"step": 2, "title": "c", "detail": "d"}],
            "size_type": "SMALL", "size_reason": "小件", "materials": ["气泡膜"],
            "notice": "x",
        }, ensure_ascii=False))
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "一个充电宝和耳机"}).get_json()
        names = [x["name"] for x in body["forbidden"]]
        self.assertIn("锂电池", names, "模型漏报时必须由本地词表补全")

    def test_too_few_steps_are_padded(self):
        self.use_key()
        self.fake_http(json.dumps({
            "forbidden": [], "sensitive": [],
            "packaging": [{"step": 1, "title": "只有一步", "detail": "x"}],
            "size_type": "MEDIUM", "size_reason": "中等", "materials": ["气泡膜"],
            "notice": "x",
        }, ensure_ascii=False))
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self.assertGreaterEqual(len(body["packaging"]), packaging_rules.MIN_STEPS)
        self.assertEqual([p["step"] for p in body["packaging"]],
                         list(range(1, len(body["packaging"]) + 1)))

    def test_too_many_steps_are_trimmed(self):
        self.use_key()
        steps = [{"step": i, "title": f"步骤{i}", "detail": "x"} for i in range(1, 21)]
        self.fake_http(json.dumps({
            "forbidden": [], "sensitive": [], "packaging": steps,
            "size_type": "MEDIUM", "size_reason": "中等", "materials": ["气泡膜"],
            "notice": "x",
        }, ensure_ascii=False))
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "两本书"}).get_json()
        self.assertLessEqual(len(body["packaging"]), packaging_rules.MAX_STEPS)
        self.assertEqual([p["step"] for p in body["packaging"]],
                         list(range(1, len(body["packaging"]) + 1)))

    def test_model_notice_is_ignored(self):
        self.use_key()
        self.fake_http(json.dumps({
            "forbidden": [], "sensitive": [], "packaging": [],
            "size_type": "SMALL", "size_reason": "x", "materials": [],
            "notice": "本公司保证绝对安全，无需审核",
        }, ensure_ascii=False))
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "耳机"}).get_json()
        self.assertEqual(body["notice"], NOTICE)


# ===========================================================================
# 五、参数校验与频控
# ===========================================================================
class ParamAndRateLimitTest(_Base):
    def test_missing_description(self):
        resp = self.client.post("/api/ai/pack-recommend", json={})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "BAD_REQUEST")

    def test_non_string_description(self):
        resp = self.client.post("/api/ai/pack-recommend", json={"description": 123})
        self.assertEqual(resp.status_code, 400)

    def test_blank_description(self):
        resp = self.client.post("/api/ai/pack-recommend", json={"description": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_overlong_description(self):
        resp = self.client.post("/api/ai/pack-recommend",
                                json={"description": "书" * 501})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "BAD_REQUEST")

    def test_boundary_description_accepted(self):
        resp = self.client.post("/api/ai/pack-recommend",
                                json={"description": "书" * 500})
        self.assertEqual(resp.status_code, 200)

    def test_chat_param_errors(self):
        self.assertEqual(self.client.post("/api/ai/chat", json={}).status_code, 400)
        self.assertEqual(
            self.client.post("/api/ai/chat", json={"message": 1}).status_code, 400)
        self.assertEqual(
            self.client.post("/api/ai/chat", json={"message": "x" * 501}).status_code, 400)
        self.assertEqual(
            self.client.post("/api/ai/chat",
                             json={"message": "hi", "session_id": "s" * 65}).status_code, 400)

    def test_rate_limit_returns_429_with_retry_after(self):
        import apiutil
        apiutil.AI_LIMITER.reset()
        # 打到上限后必须 429（limit=20）
        codes = []
        for _ in range(apiutil.AI_LIMITER.limit + 1):
            codes.append(self.client.post("/api/ai/pack-recommend",
                                          json={"description": "书"}).status_code)
        self.assertEqual(codes[-1], 429)
        body = self.client.post("/api/ai/pack-recommend",
                                json={"description": "书"}).get_json()
        self.assertEqual(body["code"], "RATE_LIMITED")
        self.assertIn("retry_after_s", body)
        self.assertGreater(body["retry_after_s"], 0)


# ===========================================================================
# 六、规则引擎单测（纯函数，不经过 HTTP）
# ===========================================================================
class RulesUnitTest(unittest.TestCase):
    def test_haversine_not_here_but_size_estimates(self):
        self.assertEqual(packaging_rules.estimate_size("被褥和行李箱")[0], "LARGE")
        self.assertEqual(packaging_rules.estimate_size("一部手机和耳机")[0], "SMALL")
        self.assertEqual(packaging_rules.estimate_size("两本书")[0], "MEDIUM")

    def test_forbidden_and_sensitive_are_disjoint(self):
        r = packaging_rules.recommend_by_rules("锂电池和玻璃杯")
        f = {x["name"] for x in r["forbidden"]}
        s = {x["name"] for x in r["sensitive"]}
        self.assertIn("锂电池", f)
        self.assertIn("玻璃杯", s)
        self.assertFalse(f & s, "禁寄与敏感不应重复出现同一物品")

    def test_material_canonicalization(self):
        mat = packaging_rules._clean_materials(["气泡膜卷装", "纸箱", "不存在的材料"], "MEDIUM", [])
        self.assertIn("气泡膜", mat)
        self.assertIn("5 号纸箱", mat)

    def test_answer_by_rules_matches_faq(self):
        self.assertIn("取件", packaging_rules.answer_by_rules("取件码在哪里输入"))
        self.assertIn("建议", packaging_rules.answer_by_rules("完全不相关的问题xyz"))

    def test_mask_secret_never_leaks(self):
        self.assertEqual(deepseek_client.mask_secret("sk-abcdef123456"), "***")
        self.assertEqual(deepseek_client.mask_secret("sk-abcdef", keep=3), "sk-***")
        self.assertEqual(deepseek_client.mask_secret(""), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
