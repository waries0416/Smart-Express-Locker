/* ===========================================================================
 * 管理端 · 创新能力页面逻辑
 * ---------------------------------------------------------------------------
 * 三个新视图：
 *   1) 柜体坐标维护  —— 地图找柜依赖的 latitude / longitude，支持行内编辑
 *   2) 备包装材料台账 —— 库存查看与调整，低库存标红
 *   3) 支付流水      —— 订单、金额、渠道、状态，mock 订单明确标记
 *
 * 依赖：api-core.js（ApiCore / payStatusMeta / payIsSuccess）、api.js（API）、
 *       admin.js（switchView / escapeHtml / toast）
 *
 * 安全边界（硬性要求）：
 *   前端**绝不保存、也绝不请求**任何私钥或 API Key。
 *   支付金额与状态一律以服务端返回为准，前端不参与任何金额计算。
 * =========================================================================== */

/* ---------------- 通用小工具 ---------------- */
function admEl(id) { return document.getElementById(id); }

/** 统一渲染"接口不可用"提示条：既不空白也不报红，明确告诉管理员原因 */
function renderAdminWarn(elId, msg, kind) {
  const el = admEl(elId);
  if (!el) return;
  if (!msg) { el.hidden = true; el.textContent = ""; el.className = "admin-warn"; return; }
  el.hidden = false;
  el.className = "admin-warn" + (kind ? " " + kind : "");
  el.innerHTML = msg;
}

/** 金额展示：服务端给 number，前端只格式化不计算 */
function fmtAmount(v) {
  const n = Number(v);
  return Number.isFinite(n) ? "¥" + n.toFixed(2) : "--";
}

/** 坐标是否有效 */
function validLat(v) {
  const n = Number(v);
  return v !== "" && v != null && Number.isFinite(n) && n >= -90 && n <= 90;
}
function validLng(v) {
  const n = Number(v);
  return v !== "" && v != null && Number.isFinite(n) && n >= -180 && n <= 180;
}

/* ===========================================================================
 * 一、柜体坐标维护
 * =========================================================================== */
let coordRows = [];

/** 加载柜体列表（复用实体接口，读出 latitude/longitude） */
async function loadCoords() {
  const table = admEl("table-coords");
  if (!table) return;
  const q = (admEl("coordSearch") && admEl("coordSearch").value || "").trim();

  table.innerHTML = `<tbody><tr><td class="muted">加载中…</td></tr></tbody>`;
  try {
    const r = await API.list("cabinets", { size: 200, q });
    const rows = (r && (r.data || r.cabinets)) || [];
    coordRows = rows;
    renderCoords(rows);
  } catch (e) {
    table.innerHTML = `<tbody><tr><td class="muted">加载失败</td></tr></tbody>`;
    renderAdminWarn("coordWarn", "柜体数据加载失败：" + ApiCore.errText(e), "err");
  }
}

function renderCoords(rows) {
  const table = admEl("table-coords");
  const withCoord = rows.filter((c) => c.latitude != null && c.longitude != null).length;
  const missing = rows.length - withCoord;

  // KPI：让管理员一眼看到还有多少柜体没维护坐标
  const kpis = admEl("coordKpis");
  if (kpis) {
    kpis.innerHTML = `
      <div class="kpi"><div class="icon">🗄️</div>
        <div class="label">柜体总数</div><div class="value">${rows.length}</div>
        <div class="sub">参与地图展示的全部柜体</div></div>
      <div class="kpi"><div class="icon">📍</div>
        <div class="label">已维护坐标</div><div class="value">${withCoord}</div>
        <div class="sub">可用于距离排序与地图标注</div></div>
      <div class="kpi"><div class="icon">⚠️</div>
        <div class="label">未维护坐标</div>
        <div class="value" style="${missing ? "color:#dc2626" : ""}">${missing}</div>
        <div class="sub">手机端将提示"坐标未维护"</div></div>`;
  }

  if (missing > 0) {
    renderAdminWarn("coordWarn",
      `有 <b>${missing}</b> 个柜体尚未维护坐标，手机端「附近的柜」对这些柜体无法按距离排序。` +
      `请在下方表格中填写经纬度。`, "warn");
  } else if (rows.length) {
    renderAdminWarn("coordWarn", "全部柜体均已维护坐标。", "ok");
  } else {
    renderAdminWarn("coordWarn", "");
  }

  if (!rows.length) {
    table.innerHTML = `<tbody><tr><td class="muted">没有匹配的柜体</td></tr></tbody>`;
    return;
  }

  const body = rows.map((c) => {
    const has = c.latitude != null && c.longitude != null;
    const id = c.cabinet_id;
    return `
      <tr data-cid="${id}">
        <td>${id}</td>
        <td><b>${escapeHtml(c.cabinet_code || "")}</b></td>
        <td>${escapeHtml(c.location || "")}</td>
        <td><span class="badge ${has ? "NORMAL" : "EXPIRED"}">${has ? "已维护" : "坐标未维护"}</span></td>
        <td>
          <input class="coord-input" data-field="latitude" value="${c.latitude != null ? c.latitude : ""}"
                 placeholder="纬度" inputmode="decimal" />
        </td>
        <td>
          <input class="coord-input" data-field="longitude" value="${c.longitude != null ? c.longitude : ""}"
                 placeholder="经度" inputmode="decimal" />
        </td>
        <td>
          <button class="btn sm" onclick="saveCoord(${id})">保存</button>
        </td>
      </tr>`;
  }).join("");

  table.innerHTML = `
    <thead><tr>
      <th>ID</th><th>柜体编号</th><th>位置</th><th>坐标状态</th>
      <th>纬度 latitude</th><th>经度 longitude</th><th>操作</th>
    </tr></thead>
    <tbody>${body}</tbody>`;
}

/** 保存单个柜体坐标：前端先做范围校验，再交给后端 */
async function saveCoord(cabinetId) {
  const row = document.querySelector(`#table-coords tr[data-cid="${cabinetId}"]`);
  if (!row) return;
  const latEl = row.querySelector('.coord-input[data-field="latitude"]');
  const lngEl = row.querySelector('.coord-input[data-field="longitude"]');
  const latRaw = (latEl.value || "").trim();
  const lngRaw = (lngEl.value || "").trim();

  // 两个都清空 = 主动清除坐标，允许（后端接受 null）
  const clearing = latRaw === "" && lngRaw === "";
  if (!clearing) {
    if (latRaw === "" || lngRaw === "") {
      toast("纬度和经度需要成对填写（或都留空表示未维护）", "warn");
      return;
    }
    if (!validLat(latRaw)) { toast("纬度需为 −90 ~ 90 之间的数字", "warn"); return; }
    if (!validLng(lngRaw)) { toast("经度需为 −180 ~ 180 之间的数字", "warn"); return; }
  }

  const payload = {
    latitude: clearing ? null : Number(latRaw),
    longitude: clearing ? null : Number(lngRaw),
  };
  const btn = row.querySelector("button");
  await ApiCore.withLoading(btn, "保存中…", async () => {
    try {
      await API.update("cabinets", cabinetId, payload);
      // 服务端必须回写成功才算保存成功：通用实体接口只写白名单字段，
      // 若后端尚未把 latitude/longitude 纳入可写字段，请求会 200 但值没变。
      // 这里回读一次校验，绝不"假成功"，避免管理员以为坐标已维护。
      const fresh = await API.getOne("cabinets", cabinetId);
      const gotLat = fresh && fresh.latitude != null ? Number(fresh.latitude) : null;
      const gotLng = fresh && fresh.longitude != null ? Number(fresh.longitude) : null;
      const wantLat = payload.latitude;
      const wantLng = payload.longitude;
      const same = (a, b) => (a == null && b == null) || (a != null && b != null && Math.abs(a - b) < 1e-6);

      if (!same(gotLat, wantLat) || !same(gotLng, wantLng)) {
        renderAdminWarn("coordWarn",
          `保存未生效：服务端读回来的经纬度与提交值不一致，说明该字段当前没有真正写库。` +
          `请把此问题转给后端，确认 <code>PUT /api/cabinets/{id}</code> 是否接受 ` +
          `<code>latitude</code>/<code>longitude</code>；在此之前手机端「附近的柜」仍按柜号排序。`, "err");
        toast("坐标未真正保存（服务端未写入该字段）", "error", 5000);
        return;
      }
      toast(clearing ? "已清除坐标" : "坐标已保存", "success");
      await loadCoords();
    } catch (e) {
      toast("保存失败：" + ApiCore.errText(e), "error");
    }
  });
}

/* ===========================================================================
 * 二、备包装材料台账
 * =========================================================================== */
async function loadMaterials() {
  const table = admEl("table-materials");
  if (!table) return;
  table.innerHTML = `<tbody><tr><td class="muted">加载中…</td></tr></tbody>`;

  try {
    const r = await API.packMaterials();
    const rows = (r && r.data) || [];
    renderMaterials(rows);
  } catch (e) {
    table.innerHTML = `<tbody><tr><td class="muted">加载失败</td></tr></tbody>`;
    // 401/403 要明确提示，不能静默
    if (e && (e.authRequired || e.forbidden)) {
      renderAdminWarn("matWarn",
        `${ApiCore.errText(e)}（该接口需要快递员或管理员身份）`, "err");
    } else if (e && e.unavailable) {
      renderAdminWarn("matWarn", "备包装材料接口暂未上线，请稍后再试。", "warn");
    } else {
      renderAdminWarn("matWarn", "加载失败：" + ApiCore.errText(e), "err");
    }
  }
}

function renderMaterials(rows) {
  const table = admEl("table-materials");
  const low = rows.filter((m) => Number(m.stock) <= Number(m.threshold));

  if (low.length) {
    renderAdminWarn("matWarn",
      `以下材料库存已到或低于阈值，请及时补充：<b>${low.map((m) =>
        escapeHtml(m.name) + "（" + m.stock + (m.unit || "") + "）").join("、")}</b>`,
      "warn");
  } else if (rows.length) {
    renderAdminWarn("matWarn", "全部材料库存充足。", "ok");
  } else {
    renderAdminWarn("matWarn", "台账为空。", "warn");
  }

  const hint = admEl("matHint");
  if (hint) hint.textContent = `共 ${rows.length} 种材料，${low.length} 种需补货`;

  if (!rows.length) {
    table.innerHTML = `<tbody><tr><td class="muted">暂无材料记录</td></tr></tbody>`;
    return;
  }

  const body = rows.map((m) => {
    const isLow = Number(m.stock) <= Number(m.threshold);
    return `
      <tr data-mid="${m.material_id}">
        <td>${m.material_id}</td>
        <td><b>${escapeHtml(m.name || "")}</b></td>
        <td>${escapeHtml(m.spec || "-")}</td>
        <td class="${isLow ? "stock-low" : "stock-ok"}">${m.stock} ${escapeHtml(m.unit || "")}</td>
        <td>${m.threshold} ${escapeHtml(m.unit || "")}</td>
        <td>
          <input class="stock-input" type="number" min="0" max="100000" step="1"
                 value="${m.stock}" style="width:110px;" />
          <button class="btn sm" onclick="saveMaterial(${m.material_id})">更新</button>
        </td>
      </tr>`;
  }).join("");

  table.innerHTML = `
    <thead><tr>
      <th>ID</th><th>材料名称</th><th>规格</th><th>当前库存</th><th>补货阈值</th><th>调整库存</th>
    </tr></thead>
    <tbody>${body}</tbody>`;
}

/** 更新库存 */
async function saveMaterial(mid) {
  const row = document.querySelector(`#table-materials tr[data-mid="${mid}"]`);
  if (!row) return;
  const input = row.querySelector(".stock-input");
  const raw = (input.value || "").trim();
  const n = Number(raw);

  // 契约 §2.1：stock 必须是整数且 0 <= stock <= 100000
  if (raw === "" || !Number.isInteger(n) || n < 0 || n > 100000) {
    toast("库存需为 0 ~ 100000 的整数", "warn");
    return;
  }

  const btn = row.querySelector("button");
  await ApiCore.withLoading(btn, "更新中…", async () => {
    try {
      await API.updatePackMaterial(mid, { stock: n });
      toast("库存已更新", "success");
      await loadMaterials();
    } catch (e) {
      toast("更新失败：" + ApiCore.errText(e), "error");
    }
  });
}

/* ===========================================================================
 * 三、支付流水
 * =========================================================================== */
const PAY_PAGE = { page: 1, size: 20 };

async function loadPayments(page) {
  const table = admEl("table-payments");
  if (!table) return;
  if (page) PAY_PAGE.page = page;

  const params = {
    page: PAY_PAGE.page,
    size: PAY_PAGE.size,
    status: (admEl("payFilterStatus") || {}).value || "",
    provider: (admEl("payFilterProvider") || {}).value || "",
    biz_type: (admEl("payFilterBiz") || {}).value || "",
  };

  table.innerHTML = `<tbody><tr><td class="muted">加载中…</td></tr></tbody>`;
  try {
    const r = await API.payRecords(params);
    const rows = (r && r.data) || [];
    renderPayments(rows, (r && r.count) || 0);
  } catch (e) {
    table.innerHTML = `<tbody><tr><td class="muted">加载失败</td></tr></tbody>`;
    if (e && (e.authRequired || e.forbidden)) {
      renderAdminWarn("payWarn", `${ApiCore.errText(e)}（支付流水仅管理员可见）`, "err");
    } else if (e && e.unavailable) {
      renderAdminWarn("payWarn", "支付流水接口暂未上线。", "warn");
    } else {
      renderAdminWarn("payWarn", "加载失败：" + ApiCore.errText(e), "err");
    }
  }
}

function renderPayments(rows, count) {
  const table = admEl("table-payments");
  const pager = admEl("pager-payments");

  // KPI：按状态汇总本次查询结果
  const byStatus = {};
  rows.forEach((p) => { byStatus[p.status] = (byStatus[p.status] || 0) + 1; });
  const totalAmount = rows
    .filter((p) => payIsSuccess(p.status))
    .reduce((s, p) => s + Number(p.amount || 0), 0);

  const kpis = admEl("payKpis");
  if (kpis) {
    kpis.innerHTML = `
      <div class="kpi"><div class="icon">🧾</div>
        <div class="label">记录总数</div><div class="value">${count}</div>
        <div class="sub">当前筛选条件</div></div>
      <div class="kpi"><div class="icon">✅</div>
        <div class="label">本页成功笔数</div><div class="value">${byStatus.SUCCESS || 0}</div>
        <div class="sub">状态 SUCCESS</div></div>
      <div class="kpi"><div class="icon">💰</div>
        <div class="label">本页成功金额</div><div class="value">${fmtAmount(totalAmount)}</div>
        <div class="sub">仅统计已成功订单</div></div>
      <div class="kpi"><div class="icon">⏳</div>
        <div class="label">处理中</div><div class="value">${byStatus.PENDING || 0}</div>
        <div class="sub">状态 PENDING</div></div>`;
  }

  // 异常提示：失败单 / 长期未完成的 PENDING 单
  const failed = rows.filter((p) => p.status === "FAILED");
  const pending = rows.filter((p) => p.status === "PENDING");
  if (failed.length) {
    renderAdminWarn("payWarn",
      `本页有 <b>${failed.length}</b> 笔支付失败，建议核对渠道配置或联系用户重试。`, "err");
  } else if (pending.length) {
    renderAdminWarn("payWarn",
      `本页有 <b>${pending.length}</b> 笔支付仍在处理中，用户未完成付款前请勿手动确认。`, "warn");
  } else if (rows.length) {
    renderAdminWarn("payWarn", "本页支付状态均正常。", "ok");
  } else {
    renderAdminWarn("payWarn", "");
  }

  if (!rows.length) {
    table.innerHTML = `<tbody><tr><td class="muted">暂无支付记录</td></tr></tbody>`;
    if (pager) pager.innerHTML = "";
    return;
  }

  const body = rows.map((p) => {
    const meta = payStatusMeta(p.status);
    // 模拟支付必须显式标记，避免管理员误以为账上有真实收入
    const mockTag = p.mock
      ? `<span class="mock-tag">模拟</span>`
      : "";
    return `
      <tr class="${p.status === "FAILED" ? "row-failed" : ""}">
        <td>${p.pay_id}</td>
        <td class="mono">${escapeHtml(p.pay_no || "-")}</td>
        <td>${p.biz_type === "OVERTIME" ? "超时保管费" : p.biz_type === "SEND" ? "寄件费" : escapeHtml(p.biz_type || "-")}
            <span class="muted">#${p.biz_id != null ? p.biz_id : "-"}</span></td>
        <td class="amt">${fmtAmount(p.amount)}</td>
        <td>${escapeHtml(p.provider_label || p.provider || "-")} ${mockTag}</td>
        <td><span class="pay-badge ${meta.cls}">${meta.cn}</span></td>
        <td>${fmtTime(p.created_at)}</td>
        <td>${p.paid_at ? fmtTime(p.paid_at) : "-"}</td>
      </tr>`;
  }).join("");

  table.innerHTML = `
    <thead><tr>
      <th>ID</th><th>支付单号</th><th>业务</th><th>金额</th>
      <th>渠道</th><th>状态</th><th>创建时间</th><th>支付时间</th>
    </tr></thead>
    <tbody>${body}</tbody>`;

  // 分页
  if (pager) {
    const totalPages = Math.max(1, Math.ceil(count / PAY_PAGE.size));
    pager.innerHTML = `
      <button class="btn sm ghost" ${PAY_PAGE.page <= 1 ? "disabled" : ""}
              onclick="loadPayments(${PAY_PAGE.page - 1})">上一页</button>
      <span class="muted">第 ${PAY_PAGE.page} / ${totalPages} 页</span>
      <button class="btn sm ghost" ${PAY_PAGE.page >= totalPages ? "disabled" : ""}
              onclick="loadPayments(${PAY_PAGE.page + 1})">下一页</button>`;
  }
}
