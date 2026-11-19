/* ===========================================================================
 * 手机端 H5 · 创新能力页面逻辑
 * ---------------------------------------------------------------------------
 * 三块内容：
 *   1) AI 智能助手：物品描述 → 禁寄/敏感提示 + 包装方式 + 格口规格 + 材料清单
 *   2) 地图找柜：高德 JS API 正常渲染；无 Key / 加载失败 → 列表 + 静态示意图降级
 *   3) 支付页：创建支付单 → 轮询服务端状态 → 成功/失败/重试
 *
 * 依赖 app.js 已声明的全局：state / show / toast / esc / fmtTime / $ / token
 * 依赖 api-core.js：ApiCore（超时、loading、错误归一化）、aiSourceMeta、payStatusMeta
 * 依赖 api-mobile.js：MApi（接口方法）
 *
 * 原则：
 *   · 任何接口不可用都要"降级 + 明确提示"，绝不白屏
 *   · 支付金额与状态一律以服务端返回为准，本地不判定成功
 *   · 敏感物品只做提示，不提供"一键确认可寄"
 * =========================================================================== */

/* ---------------- 小工具 ---------------- */
function aiEl(id) { return document.getElementById(id); }

/** 把可能是字符串 / {name,reason,detail} 的条目统一成 {name, reason, detail} */
function normalizeItem(it) {
  if (it == null) return { name: "", reason: "" };
  if (typeof it === "string") return { name: it, reason: "", detail: "" };
  const name = it.name || it.title || it.item || it.material || "";
  const reason = it.reason || it.desc || "";
  return {
    name: String(name),
    reason: String(reason),
    detail: String(it.detail || it.note || ""),
  };
}

/** 包装步骤：兼容 {step,title,detail} 与纯字符串 */
function normalizeStep(s, i) {
  if (typeof s === "string") return { step: i + 1, title: s, detail: "" };
  return {
    step: s.step != null ? s.step : i + 1,
    title: String(s.title || s.name || s.action || `步骤 ${i + 1}`),
    detail: String(s.detail || s.desc || s.note || ""),
  };
}

/* 展示"来源"徽章：AI 智能推荐 / 本地规则推荐 */
function renderSourceBadge(badgeEl, metaEl, source, extra) {
  const m = aiSourceMeta(source);
  if (badgeEl) {
    badgeEl.className = "src-badge " + m.cls;
    badgeEl.textContent = m.label;
  }
  if (metaEl) {
    metaEl.textContent = (extra || "") + (extra ? " · " : "") + m.desc;
  }
}
/* ===========================================================================
 * 一、AI 智能助手
 * =========================================================================== */
const aiState = {
  lastResult: null,   // 最近一次推荐结果（"一键用于寄件"要用）
  sessionId: null,    // AI 问答会话
  chatBusy: false,
  healthChecked: false,
};

/** 进入助手页时探一次 AI 能力状态，让用户知道当前是不是真的在走大模型 */
async function probeAiHealth() {
  if (aiState.healthChecked) return;
  aiState.healthChecked = true;
  const hint = aiEl("aiSourceHint");
  try {
    const h = await MApi.aiHealth();
    const mode = String(h && h.mode || "").toLowerCase();
    if (mode === "deepseek") {
      if (hint) hint.textContent = `AI 能力已就绪（${h.provider || "deepseek"}），描述物品即可获得推荐`;
    } else {
      if (hint) hint.textContent = "大模型暂不可用，将使用本地规则为你推荐包装";
    }
  } catch (e) {
    // 健康检查失败不阻塞主流程：真正推荐时还会再试，失败也会自动降级
    if (hint) hint.textContent = "描述你要寄的物品，我来判断能不能寄、怎么包";
  }
}

/** 渲染推荐结果 */
function renderRecommend(rec) {
  aiState.lastResult = rec;

  // ---- 来源标识 ----
  const badge = aiEl("aiSrcBadge");
  const meta = aiEl("aiSrcMeta");
  const parts = [];
  if (rec.elapsed_ms != null) parts.push(`耗时 ${rec.elapsed_ms} ms`);
  // 降级时把后端给的中文原因直接展示（契约 §1.2 degraded_reason 可直接展示）
  if (rec.degraded && rec.degraded_reason) parts.push(`降级原因：${rec.degraded_reason}`);
  renderSourceBadge(badge, meta, rec.source, parts.join(" · "));

  // ---- 禁寄：红色醒目 ----
  const forbidden = (rec.forbidden || []).map(normalizeItem).filter((x) => x.name);
  const fCard = aiEl("aiForbiddenCard");
  if (forbidden.length) {
    fCard.hidden = false;
    aiEl("aiForbiddenList").innerHTML = forbidden.map((x) => `
      <li><b>${esc(x.name)}</b>${x.reason ? `<span>${esc(x.reason)}</span>` : ""}</li>`).join("");
  } else {
    fCard.hidden = true;
  }

  // ---- 敏感品 ----
  const sensitive = (rec.sensitive || []).map(normalizeItem).filter((x) => x.name);
  const sCard = aiEl("aiSensitiveCard");
  if (sensitive.length) {
    sCard.hidden = false;
    aiEl("aiSensitiveList").innerHTML = sensitive.map((x) => `
      <li><b>${esc(x.name)}</b>${x.reason ? `<span>${esc(x.reason)}</span>` : ""}</li>`).join("");
  } else {
    sCard.hidden = true;
  }

  // ---- 包装步骤 ----
  const steps = (rec.packaging || []).map(normalizeStep);
  aiEl("aiPackSteps").innerHTML = steps.length
    ? steps.map((s) => `
        <li>
          <span class="ps-idx">${esc(String(s.step))}</span>
          <div class="ps-body">
            <div class="ps-title">${esc(s.title)}</div>
            ${s.detail ? `<div class="ps-detail">${esc(s.detail)}</div>` : ""}
          </div>
        </li>`).join("")
    : `<li class="ps-empty">暂无具体包装步骤建议</li>`;

  // ---- 格口规格 ----
  aiEl("aiSizeType").textContent = rec.size_type ? sizeTypeCn(rec.size_type) : "待人工确认";
  aiEl("aiSizeReason").textContent = rec.size_reason || "";

  // ---- 材料清单 ----
  const mats = (rec.materials || []).map(normalizeItem).filter((x) => x.name);
  aiEl("aiMaterials").innerHTML = mats.length
    ? mats.map((x) => `<span class="material-chip">${esc(x.name)}` +
        (x.reason ? `<i>${esc(x.reason)}</i>` : "") + `</span>`).join("")
    : `<span class="muted">无需额外材料</span>`;

  // ---- 免责说明：必须有"以快递员/承运商审核为准" ----
  aiEl("aiNotice").innerHTML = rec.notice
    ? `${esc(rec.notice)}`
    : `以上为参考建议，<b>最终以快递员 / 承运商审核为准</b>。本页面不构成可寄承诺。`;

  aiEl("aiResultBox").hidden = false;
  // 滚到结果区，移动端体验更顺
  aiEl("aiResultBox").scrollIntoView({ behavior: "smooth", block: "start" });
}

/** 生成推荐 */
async function submitRecommend() {
  const desc = (aiEl("aiDesc").value || "").trim();
  const err = aiEl("aiErr");
  err.textContent = "";
  if (!desc) {
    err.textContent = "请先描述你要寄的物品";
    aiEl("aiDesc").focus();
    return;
  }
  if (desc.length < 2) {
    err.textContent = "描述太短了，例如：一个玻璃杯和两本书";
    return;
  }
  // 契约 §1.2：description 去空白后 1–500 字符，超出后端会 400，这里先挡一道
  if (desc.length > 500) {
    err.textContent = `描述太长（${desc.length}/500 字），请精简后再试`;
    return;
  }

  const btn = aiEl("btnAiRecommend");
  await ApiCore.withLoading(btn, "AI 分析中…", async () => {
    try {
      const rec = await MApi.aiRecommend(desc);
      renderRecommend(rec || {});
    } catch (e) {
      err.textContent = ApiCore.errText(e);
      // 服务端未就绪时给出更明确的引导，而不是只报一句"失败"
      if (e && e.unavailable) {
        err.textContent = "AI 推荐服务暂未就绪，可先用「寄件」页手动选择规格";
      }
    }
  });
}

/** 一键把推荐规格 / 材料带进寄件表单 */
function useForSend() {
  const rec = aiState.lastResult;
  if (!rec) { toast("请先生成推荐", "err"); return; }

  // 1) 规格
  if (rec.size_type) {
    const sel = aiEl("sendSize");
    const val = String(rec.size_type).toUpperCase();
    if (sel && [...sel.options].some((o) => o.value === val)) {
      sel.value = val;
    }
  }

  // 2) 材料清单 + 提示写进备注，快递员能直接看到要带什么
  const mats = (rec.materials || []).map(normalizeItem).map((x) => x.name).filter(Boolean);
  const steps = (rec.packaging || []).map(normalizeStep);
  const noteParts = [];
  if (mats.length) noteParts.push("需备材料：" + mats.join("、"));
  if (steps.length) noteParts.push("包装：" + steps.map((s) => s.title).join(" → "));

  const noteEl = aiEl("sendNote");
  if (noteEl) {
    const tagline = noteParts.join("；");
    const base = (noteEl.value || "").trim();
    // 避免重复点击不断叠加同一段文字
    if (tagline && base.indexOf(noteParts[0]) === -1) {
      noteEl.value = base ? `${base} ${tagline}` : tagline;
    }
  }

  // 3) 在寄件页顶部给一条可见的"已带入"提示，让用户明白发生了什么
  const tipCard = aiEl("sendAiTipCard");
  const tip = aiEl("sendAiTip");
  if (tip && tipCard) {
    tipCard.hidden = false;
    tip.innerHTML =
      `已带入 AI 推荐的 <b>${esc(sizeTypeCn(rec.size_type))}</b>` +
      (mats.length ? `，材料：${esc(mats.join("、"))}` : "") +
      `。<span class="muted">最终以快递员 / 承运商审核为准。</span>`;
  }

  toast("已带入寄件表单", "ok");
  show("send");
}

/* ---------------- AI 问答 ---------------- */
function appendChat(role, text, source) {
  const log = aiEl("chatLog");
  const wrap = document.createElement("div");
  wrap.className = "chat-msg " + (role === "user" ? "user" : "bot");
  const bubble = document.createElement("div");
  bubble.className = "cm-bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);
  // 机器人回复带来源小标：让用户知道这句是 AI 还是本地规则
  if (role !== "user" && source) {
    const m = aiSourceMeta(source);
    const tag = document.createElement("span");
    tag.className = "cm-src " + m.cls;
    tag.textContent = m.short;
    wrap.appendChild(tag);
  }
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

async function sendChat() {
  const input = aiEl("chatInput");
  const msg = (input.value || "").trim();
  if (!msg || aiState.chatBusy) return;

  appendChat("user", msg);
  input.value = "";
  aiState.chatBusy = true;

  const btn = aiEl("btnChatSend");
  const hint = aiEl("chatSrcHint");
  if (btn) btn.disabled = true;
  if (hint) hint.textContent = "思考中…";

  try {
    const r = await MApi.aiChat(msg, aiState.sessionId);
    if (r && r.session_id) aiState.sessionId = r.session_id;
    appendChat("bot", (r && r.reply) || "暂时没有得到回复，请换个说法试试。", r && r.source);
    if (hint) {
      const m = aiSourceMeta(r && r.source);
      hint.textContent = `本条回复来源：${m.label}`;
    }
  } catch (e) {
    appendChat("bot", "抱歉，" + ApiCore.errText(e));
    if (hint) hint.textContent = "";
  } finally {
    aiState.chatBusy = false;
    if (btn) btn.disabled = false;
  }
}

/* ===========================================================================
 * 二、地图找柜
 * =========================================================================== */
const mapState = {
  cabinets: [],
  sort: "distance",
  coords: null,       // {lat, lng} 浏览器定位结果
  amap: null,         // AMap.Map 实例
  amapReady: false,
  amapTried: false,
  markers: [],
  loading: false,
  keyword: "",
  degraded: false,        // 后端整体降级（坐标缺失等）
  degradedReason: "",
};

/** 取浏览器定位；失败/超时返回 null，不阻塞列表展示 */
function getPosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) { resolve(null); return; }
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    // 定位权限弹窗可能一直不响应，这里 6 秒兜底
    const t = setTimeout(() => finish(null), 6000);
    navigator.geolocation.getCurrentPosition(
      (pos) => { clearTimeout(t); finish({ lat: pos.coords.latitude, lng: pos.coords.longitude }); },
      () => { clearTimeout(t); finish(null); },
      { timeout: 6000, maximumAge: 60000, enableHighAccuracy: false }
    );
  });
}

/** 动态加载高德 JS API 2.0（含安全密钥），超时/失败都只能 resolve(false) */
function loadAMapScript(jsKey, securityCode) {
  return new Promise((resolve) => {
    if (window.AMap) { resolve(true); return; }
    // 官方要求：安全密钥必须在脚本加载前挂到 window._AMapSecurityConfig
    if (securityCode) {
      window._AMapSecurityConfig = { securityJsCode: securityCode };
    }
    const s = document.createElement("script");
    let settled = false;
    const done = (ok) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(ok);
    };
    const timer = setTimeout(() => done(false), 10000);
    s.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(jsKey)}`;
    s.async = true;
    s.onload = () => done(!!window.AMap);
    s.onerror = () => done(false);
    document.head.appendChild(s);
  });
}

/** 极简静态示意图：把柜体按经纬度相对位置排布成点位，不代表真实地图 */
function renderSketch(list) {
  const box = aiEl("mfSketch");
  const pts = list.filter((c) => c.latitude != null && c.longitude != null);
  if (!pts.length) {
    // 没有坐标就明确说"暂无示意图"，不要留一个空网格让人以为是坏掉的地图
    box.innerHTML = `<div class="mf-sketch-empty">柜体坐标未维护，暂无示意图</div>`;
    box.classList.add("is-empty");
    return;
  }
  box.classList.remove("is-empty");  const lats = pts.map((c) => Number(c.latitude));
  const lngs = pts.map((c) => Number(c.longitude));
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const spanLat = maxLat - minLat || 1e-6;
  const spanLng = maxLng - minLng || 1e-6;

  box.innerHTML = pts.slice(0, 40).map((c) => {
    // y 轴翻转：纬度越大越靠上
    const x = ((Number(c.longitude) - minLng) / spanLng) * 100;
    const y = 100 - ((Number(c.latitude) - minLat) / spanLat) * 100;
    return `<span class="sk-dot" style="left:${x.toFixed(2)}%;top:${y.toFixed(2)}%;"
              title="${esc(c.cabinet_code)} ${esc(c.location || "")}"></span>`;
  }).join("");
}

/** 初始化高德地图；任何异常都返回 false 交给降级分支 */
async function initAMap(list) {
  try {
    const cfg = await MApi.mapConfig();
    const key = cfg && cfg.js_key;
    const sec = cfg && cfg.security_js_code;
    const configured = !!(cfg && cfg.configured) && !!key && !!sec;
    if (!configured) {
      return { ok: false, why: !cfg || !cfg.configured ? "服务端未配置地图 Key" : "地图 Key 或安全密钥缺失" };
    }
    const loaded = await loadAMapScript(key, sec);
    if (!loaded) return { ok: false, why: "高德地图脚本加载失败" };

    const box = aiEl("amapBox");
    box.hidden = false;
    aiEl("mapFallback").hidden = true;
    aiEl("mapLoading").hidden = true;

    if (!mapState.amap) {
      mapState.amap = new window.AMap.Map(box, {
        zoom: 13,
        // 默认以第一个有坐标的柜体为中心，没有坐标时用全国视野
        center: list.some((c) => c.latitude != null)
          ? [Number(list.find((c) => c.latitude != null).longitude),
             Number(list.find((c) => c.latitude != null).latitude)]
          : [116.397428, 39.90923],
        resizeEnable: true,
      });
    }
    drawMarkers(list);
    mapState.amapReady = true;
    return { ok: true };
  } catch (e) {
    // 配置接口本身 404（后端未上线）也走降级
    return { ok: false, why: e && e.unavailable ? "服务端未提供地图配置接口" : "地图初始化异常" };
  }
}

/** 把柜体画到地图上（只画有坐标的） */
function drawMarkers(list) {
  if (!mapState.amap || !window.AMap) return;
  mapState.amap.remove(mapState.markers || []);
  const pts = list.filter((c) => c.latitude != null && c.longitude != null);
  mapState.markers = pts.map((c) => {
    const marker = new window.AMap.Marker({
      position: [Number(c.longitude), Number(c.latitude)],
      title: c.cabinet_code,
      // 用纯 DOM 内容做标注，避免额外依赖默认图标资源
      content: `<div class="amap-pin">📦<b>${esc(c.cabinet_code)}</b></div>`,
      offset: new window.AMap.Pixel(-16, -32),
    });
    marker.on("click", () => {
      const info = new window.AMap.InfoWindow({
        content: `<div style="padding:6px 4px;font-size:13px;line-height:1.6;">
          <b>${esc(c.cabinet_code)}</b><br/>${esc(c.location || "")}<br/>
          空闲格口：<b>${c.free_cnt != null ? c.free_cnt : "--"}</b></div>`,
        offset: new window.AMap.Pixel(0, -30),
      });
      info.open(mapState.amap, marker.getPosition());
    });
    return marker;
  });
  if (mapState.markers.length) {
    mapState.amap.add(mapState.markers);
    try { mapState.amap.setFitView(mapState.markers); } catch (e) { /* 视野自适应失败不影响标注 */ }
  }
}

/** 导航链接：优先用坐标精确导航，无坐标时退化为按地址搜索 */
function navUrl(c) {
  if (c.latitude != null && c.longitude != null) {
    return `https://uri.amap.com/marker?position=${c.longitude},${c.latitude}` +
      `&name=${encodeURIComponent(c.cabinet_code + " " + (c.location || ""))}&src=smartlocker&coordinate=gaode&callnative=1`;
  }
  return `https://uri.amap.com/search?keyword=${encodeURIComponent(
    (c.cabinet_code || "") + " " + (c.location || ""))}&src=smartlocker`;
}

/** 渲染柜体列表 */
function renderCabinetList() {
  const list = mapState.cabinets;
  const empty = aiEl("cabinetEmpty");
  const wrap = aiEl("cabinetList");
  empty.hidden = list.length > 0;
  wrap.innerHTML = list.map((c) => {
    const dist = c.distance_m != null
      ? (Number(c.distance_m) >= 1000
          ? (Number(c.distance_m) / 1000).toFixed(1) + " km"
          : Math.round(Number(c.distance_m)) + " m")
      : "距离未知";
    const free = c.free_cnt != null ? c.free_cnt : 0;
    const hasCoord = c.latitude != null && c.longitude != null;
    return `
      <div class="cab-card">
        <div class="cab-top">
          <div class="cab-main">
            <div class="cab-code">${esc(c.cabinet_code || "--")}</div>
            <div class="cab-loc">${esc(c.location || "位置未填写")}</div>
          </div>
          <span class="cab-free ${free > 0 ? "ok" : "none"}">空闲 ${free}</span>
        </div>
        <div class="cab-meta">
          <span class="cab-dist">📍 ${esc(dist)}</span>
          <span class="cab-sizes">小 ${c.free_small ?? "-"} · 中 ${c.free_medium ?? "-"} · 大 ${c.free_large ?? "-"}</span>
        </div>
        <div class="cab-foot">
          <span class="cab-coord ${hasCoord ? "" : "none"}">
            ${hasCoord ? "坐标已维护" : "坐标未维护"}
          </span>
          <a class="btn primary sm cab-nav" href="${navUrl(c)}" target="_blank" rel="noopener">🧭 导航</a>
        </div>
      </div>`;
  }).join("");
}

/** 排序 + 渲染 */
function applySort() {
  const list = [...mapState.cabinets];
  if (mapState.sort === "free") {
    // 空闲格口多的排前面；相同则距离近的优先
    list.sort((a, b) => (Number(b.free_cnt || 0) - Number(a.free_cnt || 0))
      || ((a.distance_m ?? 1e12) - (b.distance_m ?? 1e12)));
  } else {
    // 距离最近的排前面；没有距离数据的排到最后，再按空闲数兜底
    list.sort((a, b) => ((a.distance_m ?? 1e12) - (b.distance_m ?? 1e12))
      || (Number(b.free_cnt || 0) - Number(a.free_cnt || 0)));
  }
  mapState.cabinets = list;
  renderCabinetList();
  if (mapState.amapReady) drawMarkers(list);
}

/** 加载柜体列表 + 地图 */
async function loadCabinets() {
  if (mapState.loading) return;
  mapState.loading = true;
  const err = aiEl("mapErr");
  err.textContent = "";
  aiEl("mapFallback").hidden = true;
  aiEl("mapLoading").hidden = false;
  aiEl("mapLoading").textContent = "正在获取位置与柜体…";

  try {
    if (!mapState.coords) mapState.coords = await getPosition();

    const params = {};
    if (mapState.coords) {
      params.lat = mapState.coords.lat;
      params.lng = mapState.coords.lng;
    }
    if (mapState.keyword) params.q = mapState.keyword;

    const r = await MApi.nearbyCabinets(params);
    // 后端返回 {count, cabinets:[...], degraded, degraded_reason, sorted_by}
    // 兼容直接返回数组的情况
    const list = Array.isArray(r) ? r : ((r && r.cabinets) || []);
    mapState.cabinets = list;
    mapState.degraded = !!(r && r.degraded);
    mapState.degradedReason = (r && r.degraded_reason) || "";
    applySort();

    aiEl("mapLoading").hidden = true;

    // 后端整体降级（如所有柜体都没维护坐标）：即使地图能画，也要说明距离不可用
    if (mapState.degraded) {
      aiEl("mapErr").textContent = mapState.degradedReason
        ? `提示：${mapState.degradedReason}，距离与排序结果可能不准确`
        : "提示：坐标数据不完整，距离与排序结果可能不准确";
    }
    if (!mapState.amapTried || mapState.amapReady) {
      mapState.amapTried = true;
      const res = await initAMap(list);
      if (!res.ok) {
        // 降级：列表 + 静态示意图 + 明确提示，绝不白屏
        aiEl("amapBox").hidden = true;
        aiEl("mapFallback").hidden = false;
        aiEl("mapFallbackWhy").textContent =
          `（原因：${res.why}）柜体名称、地址、空闲格口与导航仍然可用。`;
        renderSketch(list);
      }
    } else {
      // 已确定走降级：保持降级视图，只更新示意图
      aiEl("mapFallback").hidden = false;
      renderSketch(list);
    }

    if (!mapState.coords) {
      toast("未能获取定位，距离信息可能不准确", "err");
    }
  } catch (e) {
    aiEl("mapLoading").hidden = true;
    aiEl("amapBox").hidden = true;
    aiEl("mapFallback").hidden = false;
    // 原因已经在降级卡片里说清楚了，红字就不再重复一遍同样的话
    aiEl("mapFallbackWhy").textContent = `（原因：${ApiCore.errText(e)}）暂无可用柜体数据。`;
    mapState.cabinets = [];
    aiEl("mfSketch").innerHTML =
      `<div class="mf-sketch-empty">柜体数据加载失败，暂无示意图</div>`;
    aiEl("mfSketch").classList.add("is-empty");
    renderCabinetList();
    err.textContent = "";
  } finally {
    mapState.loading = false;
  }
}

/* ===========================================================================
 * 三、支付页
 * =========================================================================== */
const payState = {
  bizType: null,
  bizId: null,
  desc: "",
  provider: "mock",
  payId: null,
  status: null,
  amount: null,
  mock: false,
  providerLabel: "",
  pollTimer: null,
  pollCount: 0,
  onSuccess: null,
  busy: false,
};

const PAY_MAX_POLL = 120;     // 最多轮询 120 次
const PAY_POLL_MS = 1500;     // 每 1.5s 查一次

/** 停止轮询（离开页面 / 已出结果时必须调用，避免定时器泄漏） */
function stopPayPoll() {
  if (payState.pollTimer) {
    clearInterval(payState.pollTimer);
    payState.pollTimer = null;
  }
}

/** 按服务端返回渲染支付卡片 */
function renderPay(p) {
  const status = payStatusMeta(p.status);
  payState.status = p.status;

  // 金额与提供方一律用服务端返回值，前端不自己算
  if (p.amount != null) {
    payState.amount = p.amount;
    aiEl("payAmount").textContent = "¥" + Number(p.amount).toFixed(2);
  }
  if (p.mock != null) {
    payState.mock = !!p.mock;
    aiEl("payMockBanner").hidden = !payState.mock;
  }
  // provider_label 由后端下发中文文案，前端直接展示，不重复维护一套
  const label = p.provider_label || p.provider || "--";
  payState.providerLabel = label;
  aiEl("payProvider").textContent =
    label + (p.mock ? " · 不会真实扣款" : "");

  // 状态点
  const dot = aiEl("payDot");
  dot.className = "pay-status-dot " + status.cls;
  aiEl("payStatusText").textContent = status.cn;

  if (p.pay_no) aiEl("payNo").textContent = p.pay_no;
  if (p.paid_at) {
    aiEl("payTimeRow").hidden = false;
    aiEl("payTime").textContent = fmtTime(p.paid_at);
  }

  const ok = payIsSuccess(p.status);
  const failed = status.cls === "failed" || status.cls === "closed";

  // 按钮态：成功/失败/处理中 三态互斥
  const btnConfirm = aiEl("btnPayConfirm");
  const btnRetry = aiEl("btnPayRetry");
  const btnMockOk = aiEl("btnPayMockOk");

  btnConfirm.hidden = ok || failed;
  btnRetry.hidden = !failed;

  if (ok) {
    stopPayPoll();
    btnMockOk.hidden = true;
    btnConfirm.hidden = true;
    btnRetry.hidden = true;
    aiEl("payErr").textContent = "";
    aiEl("payHint").textContent = "支付成功，正在返回…";
    if (payState.onSuccess) {
      const cb = payState.onSuccess;
      payState.onSuccess = null;
      setTimeout(() => cb(p), 700);
    }
    return;
  }

  if (failed) {
    stopPayPoll();
    btnMockOk.hidden = true;
    aiEl("payHint").textContent = "支付未成功，可点「重试支付」重新发起";
    aiEl("payErr").textContent = p.fail_reason || "";
    return;
  }

  // PENDING：mock 模式下提供"模拟支付成功"，真实沙箱不提供
  btnMockOk.hidden = !payState.mock;
  aiEl("payHint").textContent = payState.mock
    ? "模拟支付环境下，点下方按钮可直接把支付单置为成功（演示用）"
    : "支付状态以服务端为准，本页会自动刷新";

  if (!payState.pollTimer && payState.pollCount < PAY_MAX_POLL) {
    payState.pollTimer = setInterval(pollPay, PAY_POLL_MS);
  }
}

/** 轮询支付状态 */
async function pollPay() {
  if (!payState.payId) return;
  if (payState.pollCount >= PAY_MAX_POLL) {
    stopPayPoll();
    aiEl("payErr").textContent = "查询支付状态超时，请稍后在「我的」中查看结果";
    aiEl("btnPayRetry").hidden = false;
    return;
  }
  payState.pollCount += 1;
  try {
    const p = await MApi.payStatus(payState.payId);
    renderPay(p);
  } catch (e) {
    // 单次轮询失败不立刻报错（网络抖动），连续失败才提示
    if (payState.pollCount % 5 === 0) {
      aiEl("payErr").textContent = ApiCore.errText(e);
    }
  }
}

/** 打开支付页并创建支付单 */
async function openPay({ bizType, bizId, desc, provider, onSuccess }) {
  // 上一次的轮询必须先停掉，否则会把旧状态写到新页面
  stopPayPoll();
  payState.bizType = bizType;
  payState.bizId = bizId;
  payState.desc = desc || "";
  payState.provider = provider || payState.provider || "mock";
  payState.payId = null;
  payState.status = null;
  payState.pollCount = 0;
  payState.onSuccess = onSuccess || null;

  // 先切页面再请求：让用户看到"处理中"而不是原地卡住
  aiEl("payErr").textContent = "";
  aiEl("payHint").textContent = "正在创建支付单…";
  aiEl("payAmount").textContent = "¥--";
  aiEl("payProvider").textContent = "--";
  aiEl("payNo").textContent = "--";
  aiEl("payDesc").textContent = payState.desc || "--";
  aiEl("payTimeRow").hidden = true;
  aiEl("payMockBanner").hidden = true;
  aiEl("btnPayConfirm").hidden = false;
  aiEl("btnPayRetry").hidden = true;
  aiEl("btnPayMockOk").hidden = true;
  aiEl("payDot").className = "pay-status-dot pending";
  aiEl("payStatusText").textContent = "处理中";
  show("pay");

  try {
    const p = await MApi.payCreate(bizType, bizId, payState.provider);
    payState.payId = p.pay_id;
    if (p.pay_no) aiEl("payNo").textContent = p.pay_no;
    // 后端可能返回专属描述，优先用后端的
    if (p.desc) aiEl("payDesc").textContent = p.desc;
    renderPay(p);
  } catch (e) {
    aiEl("payErr").textContent = ApiCore.errText(e);
    aiEl("payHint").textContent = "支付单创建失败";
    aiEl("btnPayConfirm").hidden = true;
    aiEl("btnPayRetry").hidden = false;
  }
}

/** 确认支付：mock 走"置成功"，真实沙箱则等轮询 */
async function confirmPay() {
  if (!payState.payId || payState.busy) return;
  payState.busy = true;
  const btn = aiEl("btnPayConfirm");
  aiEl("payErr").textContent = "";

  await ApiCore.withLoading(btn, "支付处理中…", async () => {
    try {
      if (payState.mock) {
        // 模拟支付：直接让服务端把单子置成功，再以查询结果为准渲染
        await MApi.payMockSucceed(payState.payId);
        const p = await MApi.payStatus(payState.payId);
        renderPay(p);
      } else {
        // 真实沙箱：没有前端可控的"成功"，只能等轮询
        aiEl("payHint").textContent = "已提交，正在等待支付结果…";
        await pollPay();
      }
    } catch (e) {
      // 契约 §4.3：非 mock 模式调用 mock-succeed 会 403 MOCK_NOT_ALLOWED
      const code = e && e.data && e.data.code;
      if (code === "MOCK_NOT_ALLOWED") {
        aiEl("payErr").textContent = "当前为真实支付模式，请按提示完成支付";
        aiEl("btnPayMockOk").hidden = true;
      } else {
        aiEl("payErr").textContent = ApiCore.errText(e);
      }
    }
  });
  payState.busy = false;
}

/** 失败重试：重新创建一笔支付单 */
async function retryPay() {
  if (!payState.bizType || payState.bizId == null) return;
  const keepCb = payState.lastOnSuccess || null;
  await openPay({
    bizType: payState.bizType,
    bizId: payState.bizId,
    desc: payState.desc,
    provider: payState.provider,
    onSuccess: keepCb,
  });
}

/** 切换支付方式：重建支付单（演示 mock 与支付宝沙箱两条路径） */
async function changeProvider(provider) {
  if (!payState.bizType || payState.bizId == null) return;
  payState.provider = provider;
  const cb = payState.onSuccess;   // 保留原回调
  await openPay({
    bizType: payState.bizType,
    bizId: payState.bizId,
    desc: payState.desc,
    provider,
    onSuccess: cb,
  });
}

/* ===========================================================================
 * 事件绑定与进入钩子
 * =========================================================================== */
function bindInnovationEvents() {
  // ---- AI 助手 ----
  aiEl("btnAiRecommend").addEventListener("click", submitRecommend);
  aiEl("aiDesc").addEventListener("keydown", (e) => {
    // Ctrl/Cmd + Enter 快速提交，避免移动端回车换行误触
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submitRecommend();
  });
  aiEl("aiChips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    aiEl("aiDesc").value = chip.dataset.text || chip.textContent;
    aiEl("aiErr").textContent = "";
  });
  aiEl("btnAiUseForSend").addEventListener("click", useForSend);
  aiEl("btnAiReset").addEventListener("click", () => {
    aiEl("aiDesc").value = "";
    aiEl("aiErr").textContent = "";
    aiEl("aiResultBox").hidden = true;
    aiState.lastResult = null;
    aiEl("aiDesc").focus();
  });
  aiEl("btnChatSend").addEventListener("click", sendChat);
  aiEl("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendChat();
  });

  // ---- 地图 ----
  document.querySelectorAll(".chip.sort").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".chip.sort").forEach((x) =>
        x.classList.toggle("active", x === b));
      mapState.sort = b.dataset.sort;
      applySort();
    });
  });
  let searchTimer = null;
  aiEl("mapSearch").addEventListener("input", () => {
    clearTimeout(searchTimer);
    // 输入防抖：每敲一个字就请求会打爆后端
    searchTimer = setTimeout(() => {
      mapState.keyword = aiEl("mapSearch").value.trim();
      loadCabinets();
    }, 400);
  });

  // ---- 支付 ----
  aiEl("btnPayConfirm").addEventListener("click", confirmPay);
  aiEl("btnPayRetry").addEventListener("click", retryPay);
  aiEl("btnPayMockOk").addEventListener("click", async () => {
    if (!payState.payId) return;
    const btn = aiEl("btnPayMockOk");
    await ApiCore.withLoading(btn, "处理中…", async () => {
      try {
        await MApi.payMockSucceed(payState.payId);
        const p = await MApi.payStatus(payState.payId);
        renderPay(p);
      } catch (e) {
        aiEl("payErr").textContent = ApiCore.errText(e);
      }
    });
  });
  aiEl("btnBackPay").addEventListener("click", () => {
    stopPayPoll();
    show("send");
  });

  // 支付方式切换（mock / 支付宝沙箱），动态插入到支付卡片顶部
  const payCard = document.querySelector("#screen-pay .pay-card");
  if (payCard) {
    const sel = document.createElement("div");
    sel.className = "pay-provider-pick";
    sel.innerHTML = `
      <button type="button" class="chip prov active" data-provider="mock">🧪 模拟支付</button>
      <button type="button" class="chip prov" data-provider="alipay_sandbox">💳 支付宝沙箱</button>`;
    payCard.insertBefore(sel, payCard.firstChild);
    sel.addEventListener("click", (e) => {
      const b = e.target.closest(".chip.prov");
      if (!b) return;
      if (payState.busy) return;
      sel.querySelectorAll(".chip.prov").forEach((x) =>
        x.classList.toggle("active", x === b));
      changeProvider(b.dataset.provider);
    });
  }

  // 离开支付页（切 tab）时停轮询，避免后台空转
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.dataset.tab !== "send") stopPayPoll();
    });
  });
}

/** 进入某个 tab 时的数据加载钩子（由 app.js 的 tab 处理逻辑调用） */
function onInnovationTabEnter(name) {
  if (name === "ai") probeAiHealth();
  if (name === "map") {
    // 每次进入都刷新柜体（其他用户可能刚存满格口），首次进入立即加载
    if (!mapState.cabinets.length) loadCabinets();
  }
}

document.addEventListener("DOMContentLoaded", bindInnovationEvents);
