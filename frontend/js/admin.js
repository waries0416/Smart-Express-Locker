// 后台管理看板逻辑

// ---- 视图切换 ----
function switchView(view) {
  document.querySelectorAll(".sidebar a").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === "view-" + view));
  if (view === "dashboard") loadDashboard();
  if (view === "notices") loadNotices(1);
  // 每次切到矩阵视图都重新拉取柜体列表：可能在其他视图刚做过柜体增删
  if (view === "matrix") loadMatrixInit(true);
  if (["companies","couriers","users","cabinets","cells","packages"].includes(view)) loadEntity(view);
  // 创新功能视图（定义在 admin-innovations.js）
  if (view === "coords" && typeof loadCoords === "function") loadCoords();
  if (view === "materials" && typeof loadMaterials === "function") loadMaterials();
  if (view === "payments" && typeof loadPayments === "function") loadPayments(1);
}

// ---- 数据看板 ----
const CHARTS = {};
async function loadDashboard() {
  try {
    const ov = await API.overview();
    renderKpis(ov);
    renderStatusChart(ov.package_status);
    renderThroughputChart(await API.cabinetThroughput());
    renderTrendChart(await API.dailyTrend(14));
    renderExcChart(await API.exceptionDist());
    // 公司排名表（来自存储过程）
    const rank = await API.companyRanking();
    const rows = rank.map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${r.company_name}</td>
        <td>${r.total_cnt}</td>
        <td>${r.picked_cnt}</td>
        <td>${r.expired_cnt}</td>
        <td>${r.returned_cnt}</td>
        <td>${r.timeout_rate}%</td>
      </tr>`).join("");
    document.getElementById("companyRankTable").innerHTML =
      `<table><thead><tr><th>#</th><th>快递公司</th><th>存件总量</th><th>已取</th><th>超时</th><th>退回</th><th>超时率</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch (e) {
    toast("看板加载失败：" + e.message, "error");
  }
}

function renderKpis(ov) {
  const ps = ov.package_status || {};
  const cs = ov.cell_status || {};
  const cards = [
    { label: "快递公司", value: ov.companies, sub: "家合作企业", icon: "🏢" },
    { label: "快递员", value: ov.couriers, sub: "注册配送员", icon: "🚚" },
    { label: "用户", value: ov.users, sub: "收件人", icon: "👤" },
    { label: "快递柜 / 格口", value: `${ov.cabinets} / ${ov.cells}`, sub: "柜体数与格口数", icon: "🗄️" },
    { label: "包裹总数", value: ov.packages, sub: `今日存 ${ov.today.stored_today} · 取 ${ov.today.picked_today}`, icon: "📦" },
    { label: "待取件(已存)", value: ps.stored_cnt || 0, sub: "格口中等待取出", icon: "⏳" },
    { label: "格口占用", value: cs.occupied || 0, sub: `空闲 ${cs.free || 0} · 故障 ${cs.fault || 0}`, icon: "🔲" },
    { label: "异常包裹", value: ps.exception_cnt || 0, sub: `超时 ${ps.expired_cnt || 0} · 退回 ${ps.returned_cnt || 0} · 异常 ${ps.exception_cnt || 0}（当前）`, icon: "⚠️" },
    { label: "待取件记录", value: ov.pending_receive || 0, sub: "收件方向 · 待取出", icon: "📥" },
    { label: "待送记录(待揽收)", value: ov.pending_send || 0, sub: "寄件方向 · 待揽收", icon: "📤" },
    { label: "已揽收", value: ov.send_collected || 0, sub: "寄件件已交快递员", icon: "📦" },
  ];
  document.getElementById("kpis").innerHTML = cards.map((c) => `
    <div class="kpi">
      <div class="icon">${c.icon}</div>
      <div class="label">${c.label}</div>
      <div class="value">${c.value}</div>
      <div class="sub">${c.sub}</div>
    </div>`).join("");
}

function renderStatusChart(ps) {
  destroyChart("chartStatus");
  // 完整状态分布：收件方向 5 态 + 寄件方向 2 态
  const labels = ["已存件","已取件","已超时","异常","已退回","待揽收","已揽收"];
  const keys = ["stored_cnt","picked_cnt","expired_cnt","exception_cnt","returned_cnt","send_wait_cnt","send_collected_cnt"];
  const colors = ["#f59e0b","#22c55e","#ef4444","#8b5cf6","#94a3b8","#06b6d4","#0ea5e9"];
  const data = keys.map((k) => ps[k] || 0);
  CHARTS.chartStatus = new Chart(document.getElementById("chartStatus"), {
    type: "doughnut",
    data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 2, borderColor: "#fff" }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right" } } },
  });
}

function renderThroughputChart(rows) {
  destroyChart("chartThroughput");
  const top = rows.slice(0, 10);
  CHARTS.chartThroughput = new Chart(document.getElementById("chartThroughput"), {
    type: "bar",
    data: {
      labels: top.map((r) => r.cabinet_code),
      datasets: [
        { label: "存件总量", data: top.map((r) => r.total_cnt), backgroundColor: "#3b82f6" },
        { label: "已取", data: top.map((r) => r.picked_cnt), backgroundColor: "#22c55e" },
        { label: "超时", data: top.map((r) => r.expired_cnt), backgroundColor: "#ef4444" },
      ],
    },
    options: { responsive: true, maintainAspectRatio: false, scales: { x: { stacked: false } } },
  });
}

function renderTrendChart(rows) {
  destroyChart("chartTrend");
  CHARTS.chartTrend = new Chart(document.getElementById("chartTrend"), {
    type: "line",
    data: {
      labels: rows.map((r) => fmtTime(r.stat_date)),
      datasets: [
        { label: "存件数", data: rows.map((r) => r.store_cnt), borderColor: "#2563eb", backgroundColor: "rgba(37,99,235,.15)", fill: true, tension: .3 },
        { label: "取件数", data: rows.map((r) => r.pickup_cnt), borderColor: "#16a34a", backgroundColor: "rgba(22,163,74,.15)", fill: true, tension: .3 },
      ],
    },
    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } },
  });
}

function renderExcChart(dist) {
  destroyChart("chartExc");
  const byType = dist.by_type || [];
  const palette = ["#ef4444","#f59e0b","#8b5cf6","#3b82f6","#14b8a6","#ec4899"];
  CHARTS.chartExc = new Chart(document.getElementById("chartExc"), {
    type: "pie",
    data: {
      labels: byType.map((r) => r.exception_type),
      datasets: [{ data: byType.map((r) => r.cnt), backgroundColor: palette, borderWidth: 2, borderColor: "#fff" }],
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right" } } },
  });
}

function destroyChart(id) {
  if (CHARTS[id]) { CHARTS[id].destroy(); delete CHARTS[id]; }
}

// ---- 业务操作 ----
// 存件/取件/寄件/揽收等日常业务已归口触屏端（kiosk.html 按角色分流），
// 后台仅保留包裹流转干预；此处初始化只填充「揽收快递员」下拉。
async function initBizSelects() {
  try {
    const couriers = await API.list("couriers", { size: 200 });
    const pkgCourierEl = document.getElementById("pkgCourier");
    if (pkgCourierEl) {
      pkgCourierEl.innerHTML =
        `<option value="">揽收快递员(未选)</option>` +
        couriers.data.map((c) => `<option value="${c.courier_id}">${c.name}（${c.employee_no}）</option>`).join("");
    }
  } catch (e) {
    toast("初始化失败：" + e.message, "error");
  }
}

async function bizForceExpire() {
  const id = Number(document.getElementById("bizPkgId").value);
  if (!id) return toast("请输入包裹 ID", "warn");
  try { await API.forceExpire(id); document.getElementById("bizFlowResult").innerHTML = `✅ 包裹 #${id} 已标记超时`; toast("已超时", "success"); }
  catch (e) { toast(e.message, "error"); }
}
async function bizReturn() {
  const id = Number(document.getElementById("bizPkgId").value);
  if (!id) return toast("请输入包裹 ID", "warn");
  try { await API.returnPkg(id); document.getElementById("bizFlowResult").innerHTML = `✅ 包裹 #${id} 已退回快递员`; toast("已退回", "success"); }
  catch (e) { toast(e.message, "error"); }
}
async function bizException() {
  const id = Number(document.getElementById("bizPkgId").value);
  if (!id) return toast("请输入包裹 ID", "warn");
  const payload = {
    exception_type: document.getElementById("bizExcType").value,
    remark: document.getElementById("bizExcRemark").value.trim(),
  };
  try { await API.exception(id, payload); document.getElementById("bizFlowResult").innerHTML = `✅ 包裹 #${id} 已登记异常`; toast("已登记异常", "success"); }
  catch (e) { toast(e.message, "error"); }
}

// ---- 实体 CRUD ----
const ENTITY_COLS = {
  companies: ["company_id","company_code","company_name","hotline"],
  couriers: ["courier_id","company_id","employee_no","name","phone"],
  users: ["user_id","name","phone","register_time"],
  cabinets: ["cabinet_id","cabinet_code","location","cabinet_type","total_cells","status"],
  cells: ["cell_id","cabinet_id","cell_code","size_type","status"],
  packages: ["package_id","direction","tracking_no","courier_id","user_id","company_id","cabinet_id","cell_id","size_type","weight","status","pickup_code","store_time","expire_time","pickup_time","note"],
};
const ENTITY_TITLE = {
  companies:"快递公司", couriers:"快递员", users:"用户", cabinets:"快递柜", cells:"格口", packages:"包裹",
};
// 表单字段定义：type=text/number/select/date ；options 为异步获取的选择项
const FORM_FIELDS = {
  companies: [
    { name:"company_code", label:"公司编码", type:"text", required:true },
    { name:"company_name", label:"公司名称", type:"text", required:true },
    { name:"hotline", label:"客服热线", type:"text" },
  ],
  couriers: [
    { name:"company_id", label:"所属公司", type:"select", source:"companies", required:true },
    { name:"employee_no", label:"工号", type:"text", required:true },
    { name:"name", label:"姓名", type:"text", required:true },
    // 与数据库 chk_courier_phone 保持一致：1 开头、第二位 3-9、共 11 位
    { name:"phone", label:"手机号（1 开头，共 11 位）", type:"text", required:true,
      pattern:"^1[3-9]\\d{9}$", patternMsg:"手机号格式不正确：需为 1 开头、第二位 3-9、共 11 位数字" },
  ],
  users: [
    { name:"name", label:"姓名", type:"text" },
    { name:"phone", label:"手机号（1 开头，共 11 位）", type:"text", required:true,
      pattern:"^1[3-9]\\d{9}$", patternMsg:"手机号格式不正确：需为 1 开头、第二位 3-9、共 11 位数字" },
  ],
  cabinets: [
    { name:"cabinet_code", label:"柜体编码", type:"text", required:true },
    { name:"location", label:"安装位置", type:"text", required:true },
    // 数据库 chk_cabinet_type 仅允许这四类，用下拉避免自由输入撞 CHECK 约束
    { name:"cabinet_type", label:"柜体类型", type:"select",
      options:[["社区柜","社区柜"],["校园柜","校园柜"],["商圈柜","商圈柜"],["园区柜","园区柜"]] },
    { name:"total_cells", label:"格口总数（修改后自动增删实际格口）", type:"number", required:true, min:0 },
    // 规格分配：新增柜体时即整个柜体的分布；编辑扩容时仅指「新增部分」的分布
    { name:"plan_small", label:"其中小件格口", type:"number", min:0, plan:"SMALL" },
    { name:"plan_medium", label:"其中中件格口", type:"number", min:0, plan:"MEDIUM" },
    { name:"plan_large", label:"其中大件格口", type:"number", min:0, plan:"LARGE" },
    { name:"new_cell_size", label:"未指定规格分配时，新增格口统一用", type:"select", options:[["SMALL","小件"],["MEDIUM","中件"],["LARGE","大件"]] },
    // chk_cabinet_status 允许 NORMAL / OFFLINE / MAINTENANCE
    { name:"status", label:"状态", type:"select",
      options:[["NORMAL","正常"],["OFFLINE","离线"],["MAINTENANCE","维护中"]] },
  ],
  cells: [
    { name:"cabinet_id", label:"所属柜体", type:"select", source:"cabinets", required:true },
    { name:"cell_code", label:"格口号", type:"text", required:true },
    { name:"size_type", label:"规格", type:"select", options:[["SMALL","小件"],["MEDIUM","中件"],["LARGE","大件"]], required:true },
    // OCCUPIED 由存件业务流控制，手工设置会造成「格口占用但无包裹」的脏数据
    { name:"status", label:"状态", type:"select", options:[["FREE","空闲"],["FAULT","故障"]] },
  ],
  packages: [
    { name:"direction", label:"业务方向", type:"select", options:[["RECEIVE","收件"],["SEND","寄件"]] },
    { name:"tracking_no", label:"运单号", type:"text" },
    { name:"courier_id", label:"快递员", type:"select", source:"couriers" },
    { name:"user_id", label:"用户", type:"select", source:"users" },
    { name:"company_id", label:"寄送公司", type:"select", source:"companies" },
    { name:"cabinet_id", label:"柜体", type:"select", source:"cabinets" },
    { name:"cell_id", label:"格口", type:"select", source:"cells" },
    { name:"size_type", label:"规格", type:"select", options:[["SMALL","小件"],["MEDIUM","中件"],["LARGE","大件"]] },
    { name:"weight", label:"重量(kg)", type:"number" },
    { name:"status", label:"状态", type:"select", options:[["STORED","已存件"],["PICKED","已取件"],["EXPIRED","已超时"],["EXCEPTION","异常"],["RETURNED","已退回"],["SEND_WAIT_PICKUP","待揽收"],["SEND_COLLECTED","已揽收"]] },
    // 与 chk_pkg_code 一致：必须是 6 位纯数字
    { name:"pickup_code", label:"取件码（6 位数字）", type:"text",
      pattern:"^$|^[0-9]{6}$", patternMsg:"取件码必须为 6 位纯数字" },
    { name:"store_time", label:"存入时间", type:"text" },
    { name:"expire_time", label:"超时时间", type:"text" },
    { name:"pickup_time", label:"取件时间", type:"text" },
    { name:"note", label:"备注", type:"text" },
  ],
};

const PAGE = {}; // 每实体分页状态
let formState = { entity: null, id: null, data: {} };

async function loadEntity(entity) {
  PAGE[entity] = PAGE[entity] || 1;
  const searchEl = document.getElementById("search-" + entity);
  const q = searchEl ? searchEl.value.trim() : "";
  // 包裹：联动「方向 / 状态」筛选，支持两类记录的精准查询
  const params = { q, page: PAGE[entity], size: 12 };
  if (entity === "packages") {
    const dirEl = document.getElementById("pkgDirection");
    const stEl = document.getElementById("pkgStatus");
    if (dirEl && dirEl.value) params.direction = dirEl.value;
    if (stEl && stEl.value) params.status = stEl.value;
  }
  const res = await API.list(entity, params);
  const cols = ENTITY_COLS[entity];
  const rows = res.data.map((row) => {
    const tds = cols.map((c) => {
      let v = row[c];
      if (v === null || v === undefined) v = "";
      // 业务方向单独用徽标渲染（收件 / 寄件）
      if (c === "direction") v = `<span class="badge ${v}">${directionCn(v)}</span>`;
      else if (c === "created_at" || c.endsWith("_time")) v = fmtTime(v);   // 时间列统一可读格式
      else if (["status","size_type","cabinet_status"].includes(c)) v = `<span class="badge ${v}">${statusCn(v)}</span>`;
      else if (typeof v === "string" && v.length > 22) v = v.slice(0, 22) + "…";
      return `<td>${v}</td>`;
    }).join("");
    // 包裹：依据状态追加业务操作按钮（揽收 / 强制开柜）
    let extra = "";
    if (entity === "packages") {
      if (row.status === "SEND_WAIT_PICKUP") {
        extra = `<button class="btn sm green" onclick="collectOne(${row.package_id})">揽收</button>`;
      } else if (["STORED","EXPIRED"].includes(row.status)) {
        const cid = row.cell_id != null ? row.cell_id : "null";
        extra = `<button class="btn sm ghost" onclick="forceUnlockPkg(${row.package_id}, ${cid})">强制开柜</button>`;
      }
    }
    return `<tr>${tds}
      <td class="nowrap">
        ${extra}
        <button class="btn sm" onclick="openForm('${entity}',${row[cols[0]]})">编辑</button>
        <button class="btn sm danger" onclick="delEntity('${entity}',${row[cols[0]]})">删除</button>
      </td></tr>`;
  }).join("");
  const head = "<thead><tr>" + cols.map((c) => `<th>${c}</th>`).join("") +
    "<th>操作</th></tr></thead>";
  document.getElementById("table-" + entity).innerHTML = head +
    (rows ? `<tbody>${rows}</tbody>` : `<tbody><tr><td colspan="${cols.length+1}" class="empty">暂无数据</td></tr></tbody>`);

  // 分页
  const totalPages = Math.max(1, Math.ceil(res.total / res.size));
  const pager = document.getElementById("pager-" + entity);
  let p = `<button ${PAGE[entity]<=1?"disabled":""} onclick="gotoPage('${entity}',${PAGE[entity]-1})">上一页</button>`;
  for (let i = 1; i <= totalPages; i++) {
    if (totalPages > 8 && Math.abs(i - PAGE[entity]) > 3 && i !== 1 && i !== totalPages) {
      if (i === 2 || i === totalPages-1) p += `<span>…</span>`;
      continue;
    }
    p += `<button class="${i===PAGE[entity]?"active":""}" onclick="gotoPage('${entity}',${i})">${i}</button>`;
  }
  p += `<button ${PAGE[entity]>=totalPages?"disabled":""} onclick="gotoPage('${entity}',${PAGE[entity]+1})">下一页</button>`;
  p += `<span class="info">共 ${res.total} 条 · 第 ${PAGE[entity]}/${totalPages} 页</span>`;
  pager.innerHTML = p;
}

function gotoPage(entity, page) { PAGE[entity] = page; loadEntity(entity); }

// 包裹快捷筛选：待取件记录 / 待送记录(待揽收) / 已揽收
function pkgQuick(dir, st) {
  const dirEl = document.getElementById("pkgDirection");
  const stEl = document.getElementById("pkgStatus");
  if (dirEl) dirEl.value = dir || "";
  if (stEl) stEl.value = st || "";
  loadEntity("packages");
}

// 包裹行内「揽收」：将待寄件交给指定快递员（SEND_WAIT_PICKUP → SEND_COLLECTED）
async function collectOne(pid) {
  const cid = Number(document.getElementById("pkgCourier").value);
  if (!cid) { toast("请先在上方选择「揽收快递员」", "warn"); return; }
  if (!confirm("确认由该快递员揽收此寄件？揽收后包裹状态将变为「已揽收」。")) return;
  try {
    await API.collect({ package_id: pid, courier_id: cid });
    toast("揽收成功，包裹已交快递员", "success");
    loadEntity("packages");
  } catch (e) { toast("揽收失败：" + e.message, "error"); }
}

// 包裹行内「强制开柜」：管理员远程开锁并释放格口（STORED/EXPIRED 走此路径）
async function forceUnlockPkg(pid, cellId) {
  if (cellId == null || cellId === "null") { toast("该包裹无关联格口，无法远程开锁", "warn"); return; }
  if (!confirm(`确认对包裹 #${pid} 执行远程强制开柜？`)) return;
  try {
    const r = await API.forceUnlockCell(cellId);
    toast("已远程开柜：" + (r.detail.cleared ? "故障/空闲格口已重置" : "包裹已取出，格口释放"), "success");
    loadEntity("packages");
  } catch (e) { toast("强制开柜失败：" + e.message, "error"); }
}

// ---- 通知中心 ----
const NOTICE_TYPE_CN = {
  STORE_ARRIVAL: "投递成功", SEND_ORDER_CREATED: "寄件下单", SEND_COLLECTED: "快递员揽收",
  PICKUP_REMIND: "到期前提醒", EXPIRE_URGE: "超时催取", EXCEPTION_ALERT: "异常告警",
  PICKUP_RECEIPT: "取件回执",
};
const NOTICE_STATUS_CN = {
  PENDING: "待发送", SENT: "已发送", FAILED: "发送失败", DEAD: "已放弃",
};
let noticePage = 1;

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function loadNotices(page) {
  if (page) noticePage = page;
  const val = (id) => (document.getElementById(id) || {}).value || "";
  try {
    const res = await API.notices({
      type: val("noticeType"), status: val("noticeStatus"),
      channel: val("noticeChannel"), phone: val("noticePhone").trim(),
      page: noticePage, size: 12,
    });
    const rows = res.data.map((n) => `
      <tr>
        <td>${n.notice_id}</td>
        <td><span class="badge ${n.notice_type}">${NOTICE_TYPE_CN[n.notice_type] || n.notice_type}</span></td>
        <td>${n.channel_cn}</td>
        <td>${escapeHtml(n.recipient_name) || "-"}
            <div class="pi-sub">${n.recipient_phone ? maskPhone(n.recipient_phone) : "无手机号"}</div></td>
        <td title="${escapeHtml(n.content)}">${escapeHtml(n.title)}</td>
        <td><span class="badge s-${n.status}">${NOTICE_STATUS_CN[n.status] || n.status}</span></td>
        <td>${n.retry_count}${n.next_retry_at ? `<div class="pi-sub">${fmtTime(n.next_retry_at)}</div>` : ""}</td>
        <td>${fmtTime(n.sent_at || n.created_at)}</td>
        <td class="nowrap">
          <button class="btn sm" onclick="retryNotice(${n.notice_id})">重投</button>
          <button class="btn sm ghost" onclick="showNoticeDetail(${n.notice_id})">详情</button>
        </td>
      </tr>`).join("");
    document.getElementById("table-notices").innerHTML =
      `<thead><tr><th>ID</th><th>类型</th><th>渠道</th><th>接收人</th><th>标题</th>
       <th>状态</th><th>重试</th><th>时间</th><th>操作</th></tr></thead>` +
      (rows ? `<tbody>${rows}</tbody>`
            : `<tbody><tr><td colspan="9" class="empty">暂无通知</td></tr></tbody>`);

    const totalPages = Math.max(1, Math.ceil(res.total / res.size));
    let p = `<button ${noticePage <= 1 ? "disabled" : ""} onclick="loadNotices(${noticePage - 1})">上一页</button>`;
    p += `<button ${noticePage >= totalPages ? "disabled" : ""} onclick="loadNotices(${noticePage + 1})">下一页</button>`;
    p += `<span class="info">共 ${res.total} 条 · 第 ${noticePage}/${totalPages} 页</span>`;
    document.getElementById("pager-notices").innerHTML = p;
  } catch (e) {
    toast("通知加载失败：" + e.message, "error");
  }
  loadNoticeStats();
}

async function loadNoticeStats() {
  try {
    const st = await API.notifyStats();
    const pick = (s) => st.by_status[s] || 0;
    const items = [
      ["🔔", "通知总量", st.total, "var(--primary)"],
      ["✅", "已发送", pick("SENT"), "var(--ok)"],
      ["⏳", "待发送", st.pending, "var(--warn)"],
      ["☠️", "死信", pick("DEAD"), "var(--err)"],
    ];
    document.getElementById("noticeKpis").innerHTML = items.map(([icon, label, v, color]) => `
      <div class="kpi"><div class="icon">${icon}</div>
        <div><div class="value" style="color:${color};">${v}</div><div class="label">${label}</div></div>
      </div>`).join("") +
      `<div class="kpi"><div class="icon">🧵</div><div>
        <div class="value" style="font-size:18px;color:${st.worker_alive ? "var(--ok)" : "var(--ink-3)"};">
          ${st.worker_alive ? "运行中" : "未运行"}</div>
        <div class="label">后台投递线程</div></div></div>`;
  } catch (e) { /* 统计卡片失败不打断列表加载 */ }
}

async function retryNotice(id) {
  try {
    await API.retryNotice(id);
    toast("已重投通知 #" + id, "success");
    loadNotices();
  } catch (e) { toast("重投失败：" + e.message, "error"); }
}

function showNoticeDetail(id) {
  API.notices({ page: 1, size: 200 }).then((res) => {
    const row = res.data.find((x) => x.notice_id === id);
    if (!row) { toast("未找到该通知", "warn"); return; }
    alert(
      `通知 #${row.notice_id}\n` +
      `类型：${row.notice_type_cn}（${row.notice_type}）\n` +
      `渠道：${row.channel_cn}　状态：${row.status_cn}\n` +
      `接收人：${row.recipient_name || "-"} ${row.recipient_phone || ""}\n` +
      `重试：${row.retry_count} 次　入队：${fmtTime(row.created_at)}\n` +
      `发送：${row.sent_at ? fmtTime(row.sent_at) : "-"}\n` +
      (row.last_error ? `最近错误：${row.last_error}\n` : "") +
      `\n标题：${row.title}\n正文：${row.content}`
    );
  });
}

async function scanNotices() {
  try {
    const r = await API.scanNotices();
    toast(`扫描完成：自动超时 ${r.auto_expired ?? 0} 件，到期提醒 ${r.remind} 条，超时催取 ${r.urge} 条`, "success");
    loadNotices(1);
  } catch (e) { toast("扫描失败：" + e.message, "error"); }
}

async function dispatchNotices() {
  try {
    const r = await API.dispatchNotices();
    toast(`投递完成：成功 ${r.sent}，失败 ${r.failed}，转死信 ${r.dead}`, "success");
    loadNotices(1);
  } catch (e) { toast("投递失败：" + e.message, "error"); }
}

async function openTestNotice() {
  const channel = (prompt("发送测试通知到哪个渠道？\nSMS = 短信　INBOX = 站内消息　PUSH = 外部推送", "SMS") || "")
    .trim().toUpperCase();
  if (!["SMS", "INBOX", "PUSH"].includes(channel)) {
    if (channel !== "") toast("渠道必须为 SMS / INBOX / PUSH", "warn");
    return;
  }
  const phone = channel === "PUSH" ? "" : (prompt("接收人手机号（11 位）", "") || "").trim();
  try {
    const r = await API.testNotice({ channel, phone, name: "测试用户" });
    toast(`测试通知已发送（#${r.notice_id}）`, "success");
    loadNotices(1);
  } catch (e) { toast("发送失败：" + e.message, "error"); }
}

// 打开表单（新增/编辑）
async function openForm(entity, id) {
  formState = { entity, id: id || null, data: {} };
  document.getElementById("formTitle").textContent =
    (id ? "编辑" : "新增") + ENTITY_TITLE[entity];
  const fields = FORM_FIELDS[entity];
  const html = [];
  for (const f of fields) {
    let controlHtml = "";
    if (f.type === "select") {
      let options = "";
      if (f.source) {
        const list = await API.list(f.source, { size: 300 });
        const LABEL_PRIORITY = ["name","company_name","employee_no","phone","company_code","location","cell_code","cabinet_code"];
        options = list.data.map((o) => {
          const idk = Object.keys(o).find((k) => k.endsWith("_id"));
          const namek = LABEL_PRIORITY.find((k) => o[k] !== undefined && o[k] !== null) || Object.keys(o)[1];
          return `<option value="${o[idk]}">${o[namek]}</option>`;
        }).join("");
      } else if (f.options) {
        options = f.options.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
      }
      controlHtml = `<select data-field="${f.name}"><option value="">-- 请选择 --</option>${options}</select>`;
    } else if (f.type === "number") {
      controlHtml = `<input type="number" step="any" data-field="${f.name}" />`;
    } else {
      controlHtml = `<input type="text" data-field="${f.name}" />`;
    }
    html.push(`<label>${f.label}${f.required?" *":""}</label>${controlHtml}`);
  }
  document.getElementById("formFields").innerHTML = html.join("");

  if (id) {
    const row = await API.getOne(entity, id);
    formState.data = row;
    document.querySelectorAll("#formFields [data-field]").forEach((el) => {
      const v = row[el.dataset.field];
      if (v === null || v === undefined) return;
      // 下拉框：若数据库当前值不在预设选项中（例如历史数据的 OFFLINE），
      // 先把它补进选项再回填，否则 el.value 会失效并被静默清空成空值
      if (el.tagName === "SELECT" && !Array.from(el.options).some((o) => o.value === String(v))) {
        const opt = document.createElement("option");
        opt.value = v; opt.textContent = `${v}（当前值）`;
        el.insertBefore(opt, el.options[1] || null);
      }
      el.value = v;
    });
  }

  // 柜体：编辑时先拉取格口概况；新增与编辑都要挂上规格分配的实时校验
  if (entity === "cabinets") {
    if (id) await showCabinetCellHint(id);
    else formState.actualCells = 0;
    updateSizePlanHint();
    ["total_cells", "plan_small", "plan_medium", "plan_large"].forEach((n) => {
      const el = document.querySelector(`#formFields [data-field="${n}"]`);
      if (el) el.addEventListener("input", updateSizePlanHint);
    });
  }

  document.getElementById("formModal").classList.add("show");
}

// 柜体格口概况提示条：说明当前真实格口数、可缩减下限，以及规格分配的实时校验
async function showCabinetCellHint(cabinetId) {
  const box = document.getElementById("formFields");
  let hint = document.getElementById("cabinetCellHint");
  if (hint) hint.remove();
  try {
    const s = await API.cabinetCellSummary(cabinetId);
    formState.actualCells = s.actual;   // 供规格分配校验计算「需新增数」
    const parts = [
      `当前实际格口 <b>${s.actual}</b> 个`,
      `空闲 ${s.free}`,
      `占用 ${s.occupied}`,
      `故障 ${s.fault}`,
    ];
    if (s.referenced > 0) parts.push(`带历史取件记录 ${s.referenced}`);

    let tip;
    if (s.min_reducible > 0) {
      const reasons = [];
      if (s.occupied) reasons.push(`占用中 ${s.occupied} 个`);
      if (s.fault) reasons.push(`故障 ${s.fault} 个`);
      if (s.referenced) reasons.push(`带历史取件记录 ${s.referenced} 个（受外键保护需保留）`);
      tip = `以下格口不会被删除：${reasons.join("、")}，`
          + `因此<b>最少只能缩到 ${s.min_reducible} 个</b>；`
          + `如需继续缩减，请先取出包裹或修复故障格口。`;
    } else {
      tip = `全部格口空闲且无历史记录，可自由增减数量。`;
    }
    if (s.declared_total !== s.actual) {
      parts.push(`<span style="color:#d97706;">登记的 total_cells=${s.declared_total} 与实际不一致，保存后会自动校正</span>`);
    }
    hint = document.createElement("div");
    hint.id = "cabinetCellHint";
    hint.style.cssText = "grid-column:1/-1;background:#fffbeb;border:1px solid #fcd34d;"
      + "border-radius:8px;padding:10px 12px;font-size:12.5px;line-height:1.7;color:#78350f;margin-bottom:4px;";
    hint.innerHTML = `${parts.join(" · ")}<br/>${tip}`;
    box.appendChild(hint);
  } catch (e) {
    /* 概况拉取失败不阻塞表单 */
  }
}

// 规格分配实时提示：告诉用户「小+中+大」应该等于多少
function updateSizePlanHint() {
  let el = document.getElementById("sizePlanHint");
  const fields = document.getElementById("formFields");
  if (!fields) return;
  if (!el) {
    el = document.createElement("div");
    el.id = "sizePlanHint";
    el.style.cssText = "grid-column:1/-1;background:#eff6ff;border:1px solid #93c5fd;"
      + "border-radius:8px;padding:9px 12px;font-size:12.5px;line-height:1.7;color:#1e3a8a;";
    fields.appendChild(el);
  }
  const totalEl = document.querySelector('#formFields [data-field="total_cells"]');
  if (!totalEl) { el.remove(); return; }

  const target = Number(totalEl.value || 0);
  const current = formState.id ? (formState.actualCells || 0) : 0;
  const need = Math.max(0, target - current);
  const get = (n) => Number((document.querySelector(`#formFields [data-field="${n}"]`) || {}).value || 0);
  const sum = get("plan_small") + get("plan_medium") + get("plan_large");

  let text, color = "#1e3a8a";
  if (need === 0) {
    text = formState.id
      ? `目标 ${target} 个、当前 ${current} 个 —— 不新增也不删除格口，规格分配仅在新增时生效。`
      : `将新增 <b>${target}</b> 个格口；请在上方填写小 / 中 / 大件数量，三者合计需等于 <b>${target}</b>。`;
  } else {
    text = `目标 ${target} 个、当前 ${current} 个 —— 需<b>新增 ${need} 个</b>；`
         + `小 / 中 / 大件合计需等于 <b>${need}</b>（当前合计 ${sum}）。`;
    if (sum > 0 && sum !== need) { color = "#b45309"; }
    if (sum === need) { color = "#166534"; text += " ✔ 分配已匹配"; }
  }
  el.style.color = color;
  el.innerHTML = text;
}
function closeForm() { document.getElementById("formModal").classList.remove("show"); }

async function saveForm() {
  const { entity, id } = formState;
  const payload = {};
  const fields = FORM_FIELDS[entity];

  // 逐字段校验：必填 + 正则 + 数值下限，避免把非法值打到数据库撞 CHECK 约束
  for (const f of fields) {
    const el = document.querySelector(`#formFields [data-field="${f.name}"]`);
    if (!el) continue;
    const v = (el.value || "").trim();
    if (!v) {
      if (f.required) { toast(`请填写「${f.label}」`, "warn"); el.focus(); return; }
      continue;
    }
    if (f.pattern && !new RegExp(f.pattern).test(v)) {
      toast(f.patternMsg || `「${f.label}」格式不正确`, "warn"); el.focus(); return;
    }
    if (f.type === "number") {
      const n = Number(v);
      if (Number.isNaN(n)) { toast(`「${f.label}」必须是数字`, "warn"); el.focus(); return; }
      if (f.min !== undefined && n < f.min) {
        toast(`「${f.label}」不能小于 ${f.min}`, "warn"); el.focus(); return;
      }
    }
    payload[f.name] = (f.type === "number") ? Number(v) : v;
  }

  // 柜体：把「小/中/大件数量」组装成后端约定的 size_plan
  if (entity === "cabinets") {
    const target = Number(payload.total_cells || 0);
    const current = id ? (formState.actualCells || 0) : 0;
    const need = Math.max(0, target - current);
    const plan = {};
    for (const f of fields) {
      if (!f.plan) continue;
      const v = payload[f.name];
      if (v) plan[f.plan] = Number(v);
      delete payload[f.name];      // plan_* 是前端专用字段，不进 body
    }
    const sum = Object.values(plan).reduce((a, b) => a + b, 0);
    if (sum > 0) {
      if (need === 0) {
        toast("当前不新增格口，规格分配不生效；如需调整请先把格口总数调大", "warn");
        return;
      }
      if (sum !== need) {
        toast(`规格分配合计 ${sum} 与需新增的 ${need} 个不一致，请调整后再保存`, "warn");
        return;
      }
      payload.size_plan = plan;
    }
    // 未指定分配时，new_cell_size 作为统一规格兜底
    if (!payload.new_cell_size) delete payload.new_cell_size;
  }

  try {
    // 格口增减会影响所属柜体统计，先在提交前记录受影响的柜体
    const res = id ? await API.update(entity, id, payload) : await API.create(entity, payload);
    toast("保存成功", "success");
    closeForm();
    loadEntity(entity);

    // 柜体格口联动结果反馈：只要返回了同步结果就明确告知实际数量，
    // 尤其是「填了更小的数却因占用/故障删不掉」时，要说清为什么没到目标值
    const syn = res && res.cells_synced;
    if (syn) {
      setTimeout(() => {
        if (syn.blocked > 0) {
          toast(`格口数未完全生效：目标 ${syn.requested} 个，实际为 ${syn.actual} 个`
              + `（${syn.blocked} 个格口因占用/故障未删除）`, "warn");
        } else {
          toast(`格口已同步：新增 ${syn.added} 个，删除 ${syn.removed} 个，当前共 ${syn.actual} 个`, "success");
        }
      }, 200);
      if (syn.warnings && syn.warnings.length) {
        setTimeout(() => toast(syn.warnings.join("；"), "warn", 8000), 1200);
      }
    }
    if (entity === "cabinets" || entity === "cells") loadMatrixInit(true);
  } catch (e) { toast("保存失败：" + e.message, "error"); }
}

async function delEntity(entity, id) {
  const title = ENTITY_TITLE[entity];

  // 先预检引用，把后果一次讲清楚，只弹一次确认框
  // （旧实现是「先删一次 → 拿到 409 → 再弹第二个框」，
  //   第二句措辞是「无法直接删除」，很容易让人误以为功能坏了）
  let info = null;
  try {
    info = await API.refs(entity, id);
  } catch (e) {
    // 预检失败不阻断，退回直接删除
  }

  const refs = (info && info.refs) || {};
  const refDesc = Object.entries(refs).map(([k, v]) => `${k} ${v} 条`).join("，");
  const needForce = info ? info.need_force : false;
  const canDelete = info ? info.can_delete !== false : true;

  // 受保护的历史业务记录（快递员经手的投递包裹、用户收过的包裹）：
  // 人员可以离职/注销，但其经手的业务记录必须留档追溯，不允许删除。
  // 这里直接讲清原因并中止，不弹「确认强制删除」——否则会让人误以为功能坏了。
  if (!canDelete) {
    alert(
      `无法删除该${title}（ID=${id}）\n\n` +
      (info && info.message ? info.message : `该记录关联：${refDesc}`) +
      `\n\n如需移除，请先处理上述业务记录。`
    );
    return;
  }

  let msg;
  if (needForce) {
    msg = `确认删除该${title}（ID=${id}）？\n\n`
        + `该记录仍关联：${refDesc}。\n`
        + `删除时将一并清理这些关联记录，并释放被占用的格口。\n\n`
        + `此操作不可撤销。`;
  } else {
    msg = `确认删除该${title}（ID=${id}）？` + (refDesc ? `\n\n（关联记录：${refDesc}，将一并清理）` : "");
  }
  if (!confirm(msg)) return;

  try {
    // 需要级联时直接带 force，避免后端再返回 409 让界面看起来「删不掉」
    const res = await API.remove(entity, id, needForce || Boolean(refDesc));
    toast(res.message || "已删除", "success");
    loadEntity(entity);
    if (entity === "cabinets" || entity === "cells") loadMatrixInit(true);
  } catch (e) {
    // 兜底：预检与实际删除之间存在并发写入时，仍可能收到 409
    if (e.status === 409 && e.data && e.data.conflict) {
      // 受保护的历史业务记录：即使强制也不允许清理，直接说明原因
      if (e.data.protected) {
        toast("无法删除：" + e.message, "error", 6000);
        return;
      }
      const d = Object.entries(e.data.refs || {}).map(([k, v]) => `${k} ${v} 条`).join("，");
      if (confirm(`删除前发现新的关联记录（${d}）。\n\n是否一并清理并删除？`)) {
        try {
          const res = await API.remove(entity, id, true);
          toast(res.message || "已删除", "success");
          loadEntity(entity);
          if (entity === "cabinets" || entity === "cells") loadMatrixInit(true);
        } catch (e2) { toast("删除失败：" + e2.message, "error"); }
      }
      return;
    }
    toast("删除失败：" + e.message, "error");
  }
}

// ---- 格子矩阵图：柜体物理视图 + 下钻抽屉 + 远程强制开锁 ----
let matrixCabinetLoaded = false;
// forceRefresh=true 时重新拉取柜体列表：柜体增删改后必须调用，
// 否则下拉框会残留已删除的柜体（选中后显示"不存在"），或看不到新增的柜体
async function loadMatrixInit(forceRefresh = false) {
  const sel = document.getElementById("matrixCabinet");
  const prev = sel.value;
  if (forceRefresh || !matrixCabinetLoaded || !sel.options.length) {
    const cabs = await API.list("cabinets", { size: 200 });
    sel.innerHTML = cabs.data.map((c) =>
      `<option value="${c.cabinet_id}">${c.cabinet_code} · ${c.location}</option>`).join("");
    matrixCabinetLoaded = true;
    // 尽量保留用户当前选中项；若该柜体已被删除则自动回退到第一个
    if (prev && Array.from(sel.options).some((o) => o.value === prev)) sel.value = prev;
  }
  loadMatrix();
}

const CELL_CLASS = {
  FREE: "free",
  FAULT: "fault",
  STORED: "stored",
  EXPIRED: "expired",
  EXCEPTION: "stored",
};

async function loadMatrix() {
  const box = document.getElementById("matrixBox");
  const cabId = document.getElementById("matrixCabinet").value;
  if (!cabId) { box.innerHTML = `<div class="empty">请选择柜体</div>`; return; }
  box.innerHTML = `<div class="empty">加载中…</div>`;
  try {
    const r = await API.cabinetCells(Number(cabId));
    const cells = r.cells;
    if (!cells.length) { box.innerHTML = `<div class="empty">该柜体暂无格口</div>`; return; }
    const groups = { SMALL: [], MEDIUM: [], LARGE: [] };
    cells.forEach((c) => groups[c.size_type].push(c));
    const statusOf = (c) => {
      if (c.cell_status === "FAULT") return "FAULT";
      if (c.cell_status === "FREE") return "FREE";
      return c.pkg_status || "STORED"; // OCCUPIED + 包裹状态
    };
    const html = Object.keys(groups).map((size) => {
      const blocks = groups[size].map((c) => {
        const st = statusOf(c);
        const cls = CELL_CLASS[st] || "free";
        const title = `${c.cell_code} · ${st}`;
        return `<div class="cell-block ${cls}" data-cell='${JSON.stringify(c).replace(/'/g, "&apos;")}' title="${title}">
                  <span class="cb-code">${c.cell_code}</span>
                  ${c.need_pay ? '<span class="cb-dot">¥</span>' : ""}
                </div>`;
      }).join("");
      return `<div class="matrix-group">
                <div class="mg-title">${size === "SMALL" ? "小件" : size === "MEDIUM" ? "中件" : "大件"}（${groups[size].length}）</div>
                <div class="cell-grid">${blocks}</div>
              </div>`;
    }).join("");
    box.innerHTML = html;
    box.querySelectorAll(".cell-block").forEach((el) => {
      el.addEventListener("click", () => openDrawer(JSON.parse(el.dataset.cell.replace(/&apos;/g, "'"))));
    });
  } catch (e) {
    // 柜体已被删除：自动刷新下拉列表，避免残留一个"不存在"的选项
    if (e.status === 404) {
      await loadMatrixInit(true);
      return;
    }
    box.innerHTML = `<div class="empty">加载失败：${e.message}</div>`;
  }
}

function openDrawer(cell) {
  currentCell = cell;
  const stLabel = {
    FREE: "空闲", FAULT: "故障", STORED: "待取(已存件)", EXPIRED: "超期未取", EXCEPTION: "异常",
  };
  const st = cell.cell_status === "FAULT" ? "FAULT"
    : cell.cell_status === "FREE" ? "FREE" : (cell.pkg_status || "STORED");
  let body = `
    <div class="drawer-row"><span>格口号</span><b>${cell.cell_code}</b></div>
    <div class="drawer-row"><span>规格</span><b>${cell.size_type === "SMALL" ? "小件" : cell.size_type === "MEDIUM" ? "中件" : "大件"}</b></div>
    <div class="drawer-row"><span>格口状态</span><b class="badge ${st}">${stLabel[st] || st}</b></div>`;
  if (cell.package_id) {
    body += `
    <hr/>
    <div class="drawer-row"><span>运单号</span><b>${cell.tracking_no}</b></div>
    <div class="drawer-row"><span>包裹状态</span><b>${stLabel[cell.pkg_status] || cell.pkg_status}</b></div>
    <div class="drawer-row"><span>存入时间</span><b>${fmtTime(cell.store_time)}</b></div>
    <div class="drawer-row"><span>已存放</span><b>${cell.stored_hours != null ? cell.stored_hours + " 小时" : "-"}</b></div>`;
    if (cell.need_pay) {
      body += `<div class="drawer-row"><span>超时保管费</span><b style="color:#dc2626;">待付 ¥${cell.overtime_fee || 1}</b></div>`;
    }
  } else {
    body += `<hr/><div class="drawer-row"><span>当前占用</span><b>无包裹</b></div>`;
  }
  document.getElementById("drawerTitle").textContent = `格口 ${cell.cell_code} 详情`;
  document.getElementById("drawerBody").innerHTML = body;
  document.getElementById("drawerForce").textContent =
    cell.package_id ? "🛠 远程强制开锁" : "🛠 解除故障 / 置为空闲";
  document.getElementById("cellDrawer").classList.add("show");
}
function closeDrawer() { document.getElementById("cellDrawer").classList.remove("show"); }

let currentCell = null;
async function drawerForceUnlock() {
  if (!currentCell) return;
  if (!confirm(`确认对格口 ${currentCell.cell_code} 执行远程强制开锁？`)) return;
  try {
    const r = await API.forceUnlockCell(currentCell.cell_id);
    toast("已远程开锁：" + (r.detail.cleared ? "故障/空闲格口已重置" : "包裹已取出，格口释放"), "success");
    closeDrawer();
    loadMatrix();
  } catch (e) {
    toast("强制开锁失败：" + e.message, "error");
  }
}

// 初始化
(async function init() {
  await initBizSelects();
  loadDashboard();
  // 通知类型下拉：与后端 NOTICE_TEMPLATES 保持一致的中文名
  const typeSel = document.getElementById("noticeType");
  if (typeSel) {
    Object.entries(NOTICE_TYPE_CN).forEach(([k, cn]) => {
      const opt = document.createElement("option");
      opt.value = k; opt.textContent = cn;
      typeSel.appendChild(opt);
    });
  }
})();
