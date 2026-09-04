/* مزايا الذكاء الاصطناعي في الواجهة — AI features UI.
 *
 * كل حاجة هنا **بتتخفي لو الميزة مش متاحة**. الواجهة بتسأل /api/health الأول
 * وبتعرض الزراير الشغّالة بس — أسوأ حاجة زرار بيوعد بحاجة وبيرجع خطأ.
 */

const $ = (id) => document.getElementById(id);

let T = () => "";
let LANG = "ar";
let sessionId = "";
let features = {};
let onPlanUpdate = null;

export function initFeatures({ t, lang, health, onPlan }) {
  T = t;
  LANG = lang;
  features = health.features || {};
  onPlanUpdate = onPlan;

  applyAvailability();
  wireChat();
  wireVoice();
  wireVision();
  wireToggles();
  fillCities();
}

export function setLang(t, lang) {
  T = t;
  LANG = lang;
}

export function updateAvailability(health) {
  features = health.features || {};
  applyAvailability();
}

/* ------------------------------------------------------------------ */
/* إظهار وإخفاء حسب المتاح                                             */
/* ------------------------------------------------------------------ */

function applyAvailability() {
  document.querySelectorAll("[data-feature]").forEach((el) => {
    const key = el.dataset.feature;
    el.hidden = features[key] === false;
    if (el.hidden) {
      const box = el.querySelector("input");
      if (box) box.checked = false;
    }
  });
  $("visionRow").hidden = !features.vision;
  $("micBtn").hidden = !features.voice;
}

function wireToggles() {
  $("optSolar").addEventListener("change", (e) => {
    $("cityField").hidden = !e.target.checked;
  });
  $("optFinishes").addEventListener("change", (e) => {
    $("tierField").hidden = !e.target.checked;
  });
}

const CITIES = [
  ["cairo", "القاهرة", "Cairo"], ["alex", "الإسكندرية", "Alexandria"],
  ["aswan", "أسوان", "Aswan"], ["hurghada", "الغردقة", "Hurghada"],
  ["riyadh", "الرياض", "Riyadh"], ["jeddah", "جدة", "Jeddah"],
  ["dubai", "دبي", "Dubai"], ["amman", "عمّان", "Amman"],
  ["casablanca", "الدار البيضاء", "Casablanca"], ["tunis", "تونس", "Tunis"],
];

function fillCities() {
  $("solarCity").innerHTML = CITIES
    .map(([id, ar, en]) => `<option value="${id}">${LANG === "ar" ? ar : en}</option>`)
    .join("");
}

/* ------------------------------------------------------------------ */
/* أ-2 · الحوار التصميمي                                               */
/* ------------------------------------------------------------------ */

export function startSession(result) {
  sessionId = result.session_id || "";
  const enabled = Boolean(sessionId) && features.chat;
  document.querySelector('[data-tab="chat"]').hidden = !enabled;
  $("chatLog").innerHTML = enabled
    ? `<p class="chat-empty">${esc(T("chatEmpty"))}</p>`
    : `<p class="chat-empty">${esc(T("chatNoAi"))}</p>`;
  $("chatUndo").disabled = true;
  $("chatRedo").disabled = true;
}

function wireChat() {
  $("chatSend").addEventListener("click", sendChat);
  $("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendChat();
  });
  $("chatUndo").addEventListener("click", () => chatAction("/api/chat/undo"));
  $("chatRedo").addEventListener("click", () => chatAction("/api/chat/redo"));
}

function bubble(role, text, cls = "") {
  const log = $("chatLog");
  log.querySelector(".chat-empty")?.remove();
  const el = document.createElement("div");
  el.className = `bubble ${role} ${cls}`;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

async function sendChat() {
  const input = $("chatInput");
  const message = input.value.trim();
  if (!message || !sessionId) return;

  input.value = "";
  bubble("user", message);
  const thinking = bubble("bot", T("chatThinking"), "thinking");
  $("chatSend").disabled = true;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    const data = await res.json();
    thinking.remove();

    if (!res.ok) {
      bubble("bot", data.detail || T("unknownError"), "err");
      return;
    }
    bubble("bot", data.reply, data.changed ? "ok" : "");
    applyChatState(data);
  } catch (e) {
    thinking.remove();
    bubble("bot", e.message, "err");
  } finally {
    $("chatSend").disabled = false;
  }
}

async function chatAction(url) {
  if (!sessionId) return;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: "" }),
    });
    const data = await res.json();
    if (!res.ok) return;
    bubble("bot", data.reply, "sys");
    applyChatState(data);
  } catch { /* تجاهل */ }
}

function applyChatState(data) {
  $("chatUndo").disabled = !data.can_undo;
  $("chatRedo").disabled = !data.can_redo;
  if (data.changed && data.svg) {
    onPlanUpdate?.({ svg: data.svg, metrics: data.metrics, issues: data.issues });
  }
}

/* ------------------------------------------------------------------ */
/* ب-3 · الصوت                                                         */
/* ------------------------------------------------------------------ */

let recorder = null;
let chunks = [];

function wireVoice() {
  $("micBtn").addEventListener("click", async () => {
    if (recorder && recorder.state === "recording") {
      recorder.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(stream);
      chunks = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop());
        await transcribe(new Blob(chunks, { type: recorder.mimeType }));
      };
      recorder.start();
      $("micBtn").classList.add("recording");
      showHint(T("recording"));
    } catch {
      showHint(T("chatNoAi"));
    }
  });
}

function showHint(text) {
  const el = $("micHint");
  el.textContent = text;
  el.hidden = !text;
}

async function transcribe(blob) {
  $("micBtn").classList.remove("recording");
  showHint(T("transcribing"));

  const reader = new FileReader();
  reader.onloadend = async () => {
    try {
      const res = await fetch("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio: reader.result, language: LANG }),
      });
      const data = await res.json();
      if (res.ok && data.text) {
        const brief = $("brief");
        brief.value = brief.value ? `${brief.value} ${data.text}` : data.text;
        showHint("");
      } else {
        showHint(data.detail || T("unknownError"));
      }
    } catch (e) {
      showHint(e.message);
    }
  };
  reader.readAsDataURL(blob);
}

/* ------------------------------------------------------------------ */
/* ب-1/ب-2 · الرؤية — مع تأكيد إجباري                                  */
/* ------------------------------------------------------------------ */

let visionKind = "sketch";
let visionReading = null;

function wireVision() {
  $("sketchBtn").addEventListener("click", () => pickImage("sketch"));
  $("siteBtn").addEventListener("click", () => pickImage("site"));
  $("visionFile").addEventListener("change", readImage);
  $("visionCancel").addEventListener("click", closeVision);
  $("visionApply").addEventListener("click", applyVision);
}

function pickImage(kind) {
  visionKind = kind;
  $("visionFile").value = "";
  $("visionFile").click();
}

async function readImage(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    showHint("الصورة أكبر من 5 ميجابايت");
    return;
  }

  $("loading").hidden = false;
  $("loadingText").textContent = T("visionReading");

  const reader = new FileReader();
  reader.onloadend = async () => {
    const url = visionKind === "sketch" ? "/api/read-sketch" : "/api/read-site";
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ images: [reader.result], language: LANG }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || T("unknownError"));
      visionReading = data.reading;
      showVision();
    } catch (err) {
      $("error").textContent = err.message;
      $("error").hidden = false;
    } finally {
      $("loading").hidden = true;
    }
  };
  reader.readAsDataURL(file);
}

const CONF = { low: "confLow", medium: "confMedium", high: "confHigh" };

function showVision() {
  const r = visionReading;
  $("visionTitle").textContent =
    T(visionKind === "sketch" ? "visionSketchTitle" : "visionSiteTitle");

  const rows = [];
  rows.push(
    `<p class="conf conf-${r.confidence}">${esc(T("confidence"))}: ` +
    `${esc(T(CONF[r.confidence] || "confLow"))}</p>`
  );

  const readBack = LANG === "ar" ? r.read_back_ar : r.read_back_en || r.read_back_ar;
  if (readBack) rows.push(`<p class="read-back">${esc(readBack)}</p>`);

  if (visionKind === "sketch" && r.rooms?.length) {
    rows.push("<ul class='vision-list'>" + r.rooms.map((room) => {
      const name = LANG === "ar" ? room.name_ar : room.name_en || room.name_ar;
      const size = room.approx_area
        ? `${room.approx_area} ${LANG === "ar" ? "م²" : "m²"}`
        : room.relative_size;
      return `<li>${esc(name || room.kind)} <em>${esc(size)}</em></li>`;
    }).join("") + "</ul>");
  }

  if (visionKind === "site") {
    const fields = [
      ["plot_width", LANG === "ar" ? "العرض" : "Width", "m"],
      ["plot_depth", LANG === "ar" ? "العمق" : "Depth", "m"],
      ["plot_area", LANG === "ar" ? "المساحة" : "Area", "m²"],
      ["setback_front", LANG === "ar" ? "ردّ أمامي" : "Front setback", "m"],
      ["setback_back", LANG === "ar" ? "ردّ خلفي" : "Rear setback", "m"],
      ["setback_sides", LANG === "ar" ? "ردّ جانبي" : "Side setback", "m"],
      ["max_floors", LANG === "ar" ? "أقصى أدوار" : "Max floors", ""],
    ].filter(([k]) => r[k] != null);

    if (fields.length) {
      rows.push("<ul class='vision-list'>" + fields.map(
        ([k, label, unit]) => `<li>${esc(label)} <em>${r[k]} ${unit}</em></li>`
      ).join("") + "</ul>");
    }
    if (r.street_sides?.length) {
      rows.push(`<p>${LANG === "ar" ? "شوارع" : "Streets"}: ` +
                `${esc(r.street_sides.join("، "))}</p>`);
    }
  }

  const unreadable = LANG === "ar" ? r.unreadable_ar
                                   : r.unreadable_en || r.unreadable_ar;
  if (unreadable) {
    rows.push(`<p class="unreadable"><strong>${esc(T("visionUnreadable"))}:</strong> ` +
              `${esc(unreadable)}</p>`);
  }

  $("visionBody").innerHTML = rows.join("");
  $("visionModal").hidden = false;
}

function closeVision() {
  $("visionModal").hidden = true;
  visionReading = null;
}

function applyVision() {
  const r = visionReading;
  if (!r) return closeVision();

  if (visionKind === "site") {
    // الردود بتتخصم — المحرك بيبني على المساحة الصافية
    const sides = r.setback_sides || 0;
    const front = r.setback_front || 0;
    const back = r.setback_back || 0;
    if (r.plot_width && r.plot_depth) {
      const w = Math.max(r.plot_width - 2 * sides, 2.5);
      const d = Math.max(r.plot_depth - front - back, 2.5);
      $("width").value = w.toFixed(2);
      $("depth").value = d.toFixed(2);
      $("area").value = (w * d).toFixed(0);
    } else if (r.plot_area) {
      $("area").value = Math.round(r.plot_area);
    }
    if (r.street_sides?.length) $("entrySide").value = r.street_sides[0];
  } else {
    if (r.total_area) $("area").value = Math.round(r.total_area);
    if (r.entry_side && r.entry_side !== "auto") $("entrySide").value = r.entry_side;

    const beds = r.rooms.filter((x) => String(x.kind).includes("bedroom")).length;
    const baths = r.rooms.filter(
      (x) => x.kind === "bath" || x.kind === "wc"
    ).length;
    if (beds) $("bedrooms").value = beds;
    if (baths) $("bathrooms").value = baths;

    const names = r.rooms
      .map((x) => (LANG === "ar" ? x.name_ar : x.name_en) || x.kind)
      .join("، ");
    const readBack = LANG === "ar" ? r.read_back_ar : r.read_back_en;
    const brief = $("brief");
    const line = readBack || names;
    if (line) brief.value = brief.value ? `${brief.value}\n${line}` : line;
  }
  closeVision();
}

/* ------------------------------------------------------------------ */
/* د-1 · الكميات  ·  د-2 · التوجيه  ·  و-2 · دفتر التصميم              */
/* ------------------------------------------------------------------ */

export function renderAnalysis(r) {
  renderBoq(r.boq);
  renderSolar(r.solar);
  renderLog(r.rationale);
}

function tab(name, on) {
  const el = document.querySelector(`[data-tab="${name}"]`);
  if (el) el.hidden = !on;
}

function renderBoq(boq) {
  const on = Boolean(boq && boq.items && boq.items.length);
  tab("cost", on);
  if (!on) return;

  const ar = LANG === "ar";
  const head = boq.priced
    ? [T("boqItem"), T("boqUnit"), T("boqQty"), T("boqRate"), T("boqTotal")]
    : [T("boqItem"), T("boqUnit"), T("boqQty")];

  const rows = boq.items.map((i) => {
    const cells = [
      esc(ar ? i.name_ar : i.name_en),
      esc(ar ? i.unit_ar : i.unit_en),
      fmt(i.quantity),
    ];
    if (boq.priced) {
      cells.push(i.unit_rate == null ? "—" : fmt(i.unit_rate));
      cells.push(i.total == null ? "—" : fmt(i.total));
    }
    return `<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`;
  }).join("");

  const total = boq.priced
    ? `<p class="boq-total">${esc(T("boqEstimate"))}: <strong>` +
      `${fmt(boq.low)} – ${fmt(boq.high)} ${esc(boq.currency)}</strong></p>`
    : `<p class="note">${esc(T("boqNoPrices"))}</p>`;

  $("costHost").innerHTML =
    `<table class="boq"><thead><tr>` +
    head.map((h) => `<th>${esc(h)}</th>`).join("") +
    `</tr></thead><tbody>${rows}</tbody></table>${total}`;
}

const FACADES = {
  north: ["شمالية", "North"], south: ["جنوبية", "South"],
  east: ["شرقية", "East"], west: ["غربية", "West"],
};

function renderSolar(solar) {
  const on = Boolean(solar && solar.windows);
  tab("solar", on);
  if (!on) return;

  const ar = LANG === "ar";
  const idx = solar.summer_load_index || 0;
  const verdict = idx < 0.35 ? "solarGood" : idx < 0.6 ? "solarOk" : "solarBad";
  const cls = idx < 0.35 ? "good" : idx < 0.6 ? "mid" : "bad";

  const byFacade = Object.entries(solar.by_facade || {})
    .sort((a, b) => b[1] - a[1])
    .map(([f, area]) => {
      const label = FACADES[f] ? (ar ? FACADES[f][0] : FACADES[f][1]) : f;
      return `<tr><td>${esc(label)}</td><td>${fmt(area)} ${ar ? "م²" : "m²"}</td></tr>`;
    }).join("");

  const hot = (solar.windows || []).filter((w) => w.severity === "hot");
  const hotList = hot.length
    ? `<h4>${ar ? "محتاج انتباه" : "Needs attention"}</h4><ul>` +
      hot.map((w) => {
        const name = ar ? w.room_name_ar : w.room_name_en;
        const f = FACADES[w.facade] ? (ar ? FACADES[w.facade][0] : FACADES[w.facade][1])
                                    : w.facade;
        return `<li><strong>${esc(name)}</strong> — ${esc(f)}، ` +
               `${fmt(w.area)} ${ar ? "م² زجاج" : "m² glazing"}</li>`;
      }).join("") + "</ul>"
    : "";

  $("solarHost").innerHTML =
    `<p class="solar-index ${cls}">${esc(T("solarIndex"))}: ` +
    `<strong>${idx.toFixed(2)}</strong> — ${esc(T(verdict))}</p>` +
    `<p class="note">${ar ? "محسوب لخط عرض" : "Computed for"} ` +
    `${esc(ar ? solar.city_ar : solar.city_en)} (${solar.latitude}°) — ` +
    `${ar ? "هندسة شمسية حتمية، مش تقدير." : "deterministic solar geometry."}</p>` +
    `<table class="boq"><thead><tr><th>${esc(T("facade"))}</th>` +
    `<th>${esc(T("glazing"))}</th></tr></thead><tbody>${byFacade}</tbody></table>` +
    hotList;
}

const STAGES = {
  program: ["البرنامج المعماري", "Programme"],
  plot: ["أبعاد القطعة", "Plot"],
  layout: ["التوزيع", "Layout"],
  repair: ["الإصلاح الذاتي", "Self-repair"],
  trim: ["التقليم", "Trimming"],
  edit: ["تعديلاتك", "Your edits"],
  analysis: ["التحليل", "Analysis"],
  openings: ["الفتحات", "Openings"],
  building: ["تركيب المبنى", "Building"],
};

function renderLog(rationale) {
  const on = Boolean(rationale && rationale.length);
  tab("log", on);
  if (!on) return;

  const ar = LANG === "ar";
  const who = T("byWhom") || {};
  const groups = {};
  rationale.forEach((d) => (groups[d.stage] ||= []).push(d));

  $("logHost").innerHTML = Object.entries(groups).map(([stage, items]) => {
    const label = STAGES[stage] ? (ar ? STAGES[stage][0] : STAGES[stage][1]) : stage;
    const rows = items.map((d) => {
      const what = ar ? d.what_ar : d.what_en || d.what_ar;
      const why = ar ? d.why_ar : d.why_en || d.why_ar;
      return `<li><span class="by by-${d.by}">${esc(who[d.by] || d.by)}</span>` +
             `<strong>${esc(what)}</strong>` +
             (why ? `<em>${esc(why)}</em>` : "") + `</li>`;
    }).join("");
    return `<section><h4>${esc(label)}</h4><ul class="log-list">${rows}</ul></section>`;
  }).join("");
}

/* ------------------------------------------------------------------ */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmt(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString(LANG === "ar" ? "ar-EG" : "en-US", {
    maximumFractionDigits: 2,
  });
}
