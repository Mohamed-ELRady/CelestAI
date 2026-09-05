/* CelestAI — واجهة الويب */

import { STRINGS, detectLanguage } from "/static/i18n.js";
import { createPanZoom } from "/static/zoom.js";
import {
  initFeatures,
  renderAnalysis,
  setLang as setFeatureLang,
  startSession,
  updateAvailability as updateFeatureAvailability,
} from "/static/features.js";

const $ = (id) => document.getElementById(id);

let lang = detectLanguage();
let buildingType = "apartment";
let buildingTypes = [];
let lastResult = null;
let aiAvailable = false;
let aiProvider = null;  // "anthropic" | "openai" | null
let healthState = {};
let aiSettingsState = null;
let three = null;      // { dispose }
let planZoom = null;   // { zoomIn, zoomOut, fit }
let mode = "unit";     // "unit" | "building"
let floorUses = [];
let activeFloor = 0;
let ruleSeq = 0;

const t = (key) => STRINGS[lang][key] ?? key;

/* ------------------------------------------------------------------ */
/* اللغة                                                               */
/* ------------------------------------------------------------------ */

function applyLanguage() {
  const dict = STRINGS[lang];
  document.documentElement.lang = lang;
  document.documentElement.dir = dict.dir;
  localStorage.setItem("celestai-lang", lang);

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const value = dict[el.dataset.i18n];
    // القيم اللي مش نصوص (زي byWhom) بتتقرا بـ t() مش بتتحط في DOM
    if (typeof value === "string") el.textContent = value;
  });
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => {
    const value = dict[el.dataset.i18nPh];
    if (value !== undefined) el.placeholder = value;
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const value = dict[el.dataset.i18nTitle];
    if (value !== undefined) el.title = value;
  });

  document.title = dict.pageTitle;
  setFeatureLang(t, lang);

  $("langSwitch").querySelectorAll(".lang").forEach((b) => {
    b.classList.toggle("active", b.dataset.lang === lang);
  });

  renderBuildingTypes();
  renderAiBadge();
  renderFloorRules();

  // لو فيه نتيجة معروضة، نعيد بناء اللوحات بالنصوص الجديدة — كل وضع وشكله
  if (lastResult?.floors) renderBuilding(lastResult);
  else if (lastResult) renderStatic(lastResult);
}

function renderAiBadge() {
  const badge = $("aiBadge");
  const providerName = healthState[`ai_provider_name_${lang}`]
    || healthState.ai_provider_name || "";
  const onText = aiProvider === "anthropic"
    ? t("aiOn")
    : providerName ? `✦ ${providerName}` : t("aiOnGeneric");
  badge.textContent = aiAvailable ? onText : t("aiOff");
  badge.className = "ai-badge " + (aiAvailable ? "on" : "off");
  badge.title = aiAvailable ? "" : t("aiOffHint");
}

function renderBuildingTypes() {
  const host = $("buildingTypes");
  host.innerHTML = "";
  buildingTypes.forEach((type) => {
    const b = document.createElement("button");
    b.className = "chip" + (type.value === buildingType ? " active" : "");
    b.textContent = lang === "ar" ? type.label_ar : type.label_en;
    b.dataset.value = type.value;
    b.onclick = () => {
      buildingType = type.value;
      host.querySelectorAll(".chip").forEach((c) =>
        c.classList.toggle("active", c.dataset.value === buildingType)
      );
      // عدد غرف النوم مالوش لازمة في المكاتب والعيادات
      $("roomCounts").style.display =
        ["apartment", "villa_floor"].includes(buildingType) ? "flex" : "none";
    };
    host.appendChild(b);
  });
  $("roomCounts").style.display =
    ["apartment", "villa_floor"].includes(buildingType) ? "flex" : "none";
}

/* ------------------------------------------------------------------ */
/* التهيئة                                                             */
/* ------------------------------------------------------------------ */

async function boot() {
  let health = {};
  try {
    health = await (await fetch("/api/health")).json();
    healthState = health;
    aiAvailable = !!health.ai_available;
    aiProvider = health.ai_provider || null;
    if (!aiAvailable) $("useAi").checked = false;
  } catch { /* الخدمة لسه بتقوم */ }

  try {
    buildingTypes = await (await fetch("/api/building-types")).json();
  } catch { buildingTypes = []; }

  try {
    floorUses = await (await fetch("/api/floor-uses")).json();
  } catch { floorUses = []; }
  if (!floorRules.length) {
    floorRules = [
      { id: ++ruleSeq, from: 0, to: 0, use: "retail", units: "" },
      { id: ++ruleSeq, from: 1, to: 4, use: "apartments", units: "" },
    ];
  }

  applyLanguage();

  initFeatures({
    t, lang, health,
    // الحوار بيغيّر المخطط في مكانه — نفس منطق العرض بالظبط
    onPlan: ({ svg, metrics, issues }) => {
      if (!lastResult) return;
      lastResult.svg = svg;
      lastResult.metrics = metrics;
      lastResult.issues = issues;
      $("svgHost").innerHTML = svg;
      planZoom?.fit();
      renderStats(lastResult);
      renderChecks(lastResult);
    },
  });

  $("langSwitch").querySelectorAll(".lang").forEach((b) => {
    b.onclick = () => {
      if (b.dataset.lang === lang) return;
      lang = b.dataset.lang;
      applyLanguage();
      // المخطط والتقرير نفسهم بيتولّدوا بلغة الطلب، فبنعيد التوليد
      if (lastResult) run();
    };
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      tab.classList.add("active");
      $("view-" + tab.dataset.tab).classList.add("active");
      if (tab.dataset.tab === "three" && lastResult && mode === "unit") renderThree(lastResult.model3d);
      // الحجم بيتحسب صح بس لما التبويب يبقى ظاهر فعليًا
      if (tab.dataset.tab === "plan") planZoom?.fit();
    };
  });

  planZoom = createPanZoom($("zoomViewport"), $("svgHost"), {
    onChange: (scale) => {
      $("zoomPct").textContent = Math.round(scale * 100) + "%";
    },
  });
  document.querySelectorAll(".zoom-btn").forEach((btn) => {
    btn.onclick = () => {
      const action = btn.dataset.zoom;
      if (action === "in") planZoom.zoomIn();
      else if (action === "out") planZoom.zoomOut();
      else if (action === "fit") planZoom.fit();
    };
  });
  addEventListener("resize", () => {
    if ($("view-plan").classList.contains("active")) planZoom?.fit();
  });

  $("modeSwitch").querySelectorAll(".mode").forEach((b) => {
    b.onclick = () => {
      if (b.dataset.mode === mode) return;
      mode = b.dataset.mode;
      applyMode();
    };
  });
  $("addRule").onclick = () => {
    const last = floorRules[floorRules.length - 1];
    const from = last ? Number(last.to) + 1 : 0;
    floorRules.push({ id: ++ruleSeq, from, to: from, use: "apartments", units: "" });
    renderFloorRules();
  };

  applyMode();
  $("run").onclick = run;

  $("aiBadge").onclick = openAiSettings;
  $("aiSettingsClose").onclick = closeAiSettings;
  $("aiSettingsCancel").onclick = closeAiSettings;
  $("aiSettingsModal").addEventListener("click", (e) => {
    if (e.target === $("aiSettingsModal")) closeAiSettings();
  });
  $("aiProviderSelect").onchange = () => renderProviderSettings(false);
  $("toggleApiKey").onclick = () => {
    const input = $("aiApiKey");
    input.classList.toggle("masked-secret");
  };
  $("aiSettingsForm").onsubmit = saveAiSettings;
  $("testAiConnection").onclick = testAiConnection;
  $("disconnectAi").onclick = disconnectAi;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("aiSettingsModal").hidden) closeAiSettings();
  });
}

/* ------------------------------------------------------------------ */
/* إعدادات مزوّد الذكاء الاصطناعي                                     */
/* ------------------------------------------------------------------ */

function providerById(id) {
  return aiSettingsState?.providers?.find((item) => item.id === id) || null;
}

async function openAiSettings() {
  const status = $("aiConnectionStatus");
  status.hidden = true;
  $("aiSettingsModal").hidden = false;
  try {
    const res = await fetch("/api/ai/settings");
    if (!res.ok) throw new Error(t("unknownError"));
    aiSettingsState = await res.json();
    const select = $("aiProviderSelect");
    select.innerHTML = aiSettingsState.providers.map((provider) => {
      const name = lang === "ar" ? provider.name_ar : provider.name_en;
      const badge = provider.local ? ` · ${t("localProvider")}`
        : provider.free_tier ? ` · ${t("freeTier")}` : "";
      return `<option value="${escapeHtml(provider.id)}">${escapeHtml(name + badge)}</option>`;
    }).join("");
    select.value = aiSettingsState.provider_id === "offline"
      ? "groq" : aiSettingsState.provider_id;
    renderProviderSettings(true);
    $("aiApiKey").focus();
  } catch (e) {
    showAiStatus(e.message, false);
  }
}

function closeAiSettings() {
  $("aiSettingsModal").hidden = true;
  $("aiApiKey").value = "";
  $("aiApiKey").classList.add("masked-secret");
}

function renderProviderSettings(initial) {
  const provider = providerById($("aiProviderSelect").value);
  if (!provider) return;
  const isCurrent = aiSettingsState.provider_id === provider.id;
  const name = lang === "ar" ? provider.name_ar : provider.name_en;
  const description = lang === "ar" ? provider.description_ar : provider.description_en;
  const pills = [
    provider.free_tier && !provider.local ? `<span class="provider-pill">${t("freeTier")}</span>` : "",
    provider.local ? `<span class="provider-pill local">${t("localProvider")}</span>` : "",
  ].join("");
  $("providerSummary").innerHTML =
    `<div class="provider-summary-head">${escapeHtml(name)} ${pills}</div>${escapeHtml(description)}`;
  const savings = aiSettingsState.savings || {};
  $("aiSavingsStats").textContent = t("smartSavingsStats")
    .replace("{count}", savings.api_calls_saved || 0)
    .replace("{rate}", Math.round((savings.reuse_rate || 0) * 100));

  $("apiKeyField").hidden = !provider.requires_key;
  $("aiApiKey").value = "";
  requestAnimationFrame(() => { $("aiApiKey").value = ""; });
  $("apiKeyHint").textContent = isCurrent && aiSettingsState.has_api_key
    ? t("apiKeyConfigured") : t("apiKeyNotStored");

  const model = initial && isCurrent ? aiSettingsState.model : provider.default_model;
  $("aiModel").value = model || "";
  $("aiModelOptions").innerHTML = (provider.models || [])
    .map((item) => `<option value="${escapeHtml(item)}"></option>`).join("");

  $("baseUrlField").hidden = provider.adapter !== "openai";
  $("aiBaseUrl").readOnly = provider.id !== "custom";
  $("aiBaseUrl").value = initial && isCurrent
    ? aiSettingsState.base_url : provider.base_url;
  $("aiVision").checked = initial && isCurrent
    ? !!aiSettingsState.vision : !!provider.vision_default;

  const canRemember = !!aiSettingsState.secure_storage_available && provider.requires_key;
  $("rememberApiKey").disabled = !canRemember;
  $("rememberApiKey").checked = canRemember && initial && isCurrent
    ? !!aiSettingsState.remembered : false;
  $("rememberApiKey").closest("label").title = canRemember
    ? "" : t("secureStorageUnavailable");

  $("providerKeyLink").hidden = !provider.key_url || !provider.requires_key;
  $("providerKeyLink").href = provider.key_url || "#";
  $("providerDocsLink").hidden = !provider.docs_url;
  $("providerDocsLink").href = provider.docs_url || "#";
  $("aiConnectionStatus").hidden = true;
}

function aiSettingsPayload() {
  return {
    provider_id: $("aiProviderSelect").value,
    api_key: $("aiApiKey").value.trim(),
    model: $("aiModel").value.trim(),
    base_url: $("aiBaseUrl").value.trim(),
    vision: $("aiVision").checked,
    remember: $("rememberApiKey").checked,
  };
}

function showAiStatus(message, ok = null) {
  const status = $("aiConnectionStatus");
  status.textContent = message;
  status.className = "connection-status" + (ok === true ? " ok" : ok === false ? " bad" : "");
  status.hidden = false;
}

async function testAiConnection() {
  const button = $("testAiConnection");
  button.disabled = true;
  showAiStatus(t("testingConnection"));
  try {
    const res = await fetch("/api/ai/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(aiSettingsPayload()),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || t("unknownError"));
    if (data.models?.length) {
      $("aiModelOptions").innerHTML = data.models
        .map((item) => `<option value="${escapeHtml(item)}"></option>`).join("");
    }
    const suffix = data.model_found || !data.models?.length
      ? "" : ` · ${t("modelsAvailable").replace("{count}", data.models.length)}`;
    showAiStatus(t("connectionOk") + suffix, true);
  } catch (e) {
    showAiStatus(e.message, false);
  } finally {
    button.disabled = false;
  }
}

async function saveAiSettings(e) {
  e.preventDefault();
  const button = $("saveAiSettings");
  button.disabled = true;
  try {
    const res = await fetch("/api/ai/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(aiSettingsPayload()),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || t("unknownError"));
    aiSettingsState = data;
    await refreshAiHealth();
    $("useAi").checked = true;
    showAiStatus(t("settingsSaved"), true);
    setTimeout(closeAiSettings, 450);
  } catch (error) {
    showAiStatus(error.message, false);
  } finally {
    button.disabled = false;
  }
}

async function disconnectAi() {
  const button = $("disconnectAi");
  button.disabled = true;
  try {
    const res = await fetch("/api/ai/settings", { method: "DELETE" });
    if (!res.ok) throw new Error(t("unknownError"));
    await refreshAiHealth();
    $("useAi").checked = false;
    closeAiSettings();
  } catch (e) {
    showAiStatus(e.message, false);
  } finally {
    button.disabled = false;
  }
}

async function refreshAiHealth() {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error(t("unknownError"));
  healthState = await res.json();
  aiAvailable = !!healthState.ai_available;
  aiProvider = healthState.ai_provider || null;
  renderAiBadge();
  updateFeatureAvailability(healthState);
}

/* ------------------------------------------------------------------ */
/* وضع المبنى                                                          */
/* ------------------------------------------------------------------ */

let floorRules = [];

function applyMode() {
  const building = mode === "building";
  $("modeSwitch").querySelectorAll(".mode").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode)
  );
  $("typeStep").hidden = building;
  $("floorsStep").hidden = !building;
  $("roomsStep").hidden = building;
  // في وضع المبنى المساحة بتبقى مساحة الدور مش الوحدة
  const areaLabel = $("area").closest(".field").querySelector("span");
  areaLabel.textContent = building ? t("floorAreaLabel") : t("totalArea");
  // مساحة وحدة واحدة صغيرة أوي على دور كامل — نرفعها لقيمة معقولة
  if (building && Number($("area").value) < 200) $("area").value = 400;
  // البدائل والمجسّم مش متاحين لسه في وضع المبنى
  document.querySelector('[data-tab="alts"]').hidden = building;
  // شريط تنقّل الأدوار خاص بوضع المبنى بس — لو رجعنا لوحدة واحدة بعد ما
  // ولّدنا مبنى، لازم نخفيه فورًا مش نستنى توليد جديد
  if (!building) $("floorNav").hidden = true;
  renderFloorRules();
}

function renderFloorRules() {
  const host = $("floorRules");
  if (!host) return;
  host.innerHTML = "";
  const useOptions = floorUses
    .map((u) => `<option value="${u.value}">${lang === "ar" ? u.label_ar : u.label_en}</option>`)
    .join("");

  floorRules.forEach((rule) => {
    const row = document.createElement("div");
    row.className = "floor-rule";
    row.innerHTML = `
      <input type="number" min="-3" max="60" value="${rule.from}" title="${t("ruleFrom")}">
      <input type="number" min="-3" max="60" value="${rule.to}" title="${t("ruleTo")}">
      <select title="${t("ruleUse")}">${useOptions}</select>
      <input type="number" min="1" max="8" value="${rule.units}"
             placeholder="${t("ruleAuto")}" title="${t("ruleUnits")}">
      <button type="button" class="rule-del" title="${t("removeRule")}">×</button>`;

    const [from, to, use, units, del] = [
      row.children[0], row.children[1], row.children[2], row.children[3], row.children[4],
    ];
    use.value = rule.use;
    from.onchange = () => { rule.from = Number(from.value); };
    to.onchange = () => { rule.to = Number(to.value); };
    use.onchange = () => { rule.use = use.value; };
    units.onchange = () => { rule.units = units.value; };
    del.onclick = () => {
      floorRules = floorRules.filter((r) => r.id !== rule.id);
      renderFloorRules();
    };
    host.appendChild(row);
  });
}

/** يحوّل مجموعات الأدوار لقائمة أدوار صريحة زي ما الـ API بيتوقّعها. */
function buildFloorSpecs() {
  const count = Math.max(1, Number($("floorCount").value) || 1);
  const overrides = new Map();
  for (const r of floorRules) {
    const lo = Math.min(Number(r.from), Number(r.to));
    const hi = Math.max(Number(r.from), Number(r.to));
    for (let lv = lo; lv <= hi; lv++) {
      overrides.set(lv, { use: r.use, units: r.units ? Number(r.units) : null });
    }
  }
  const levels = [...overrides.keys()];
  const bottom = Math.min(0, ...levels);
  const top = Math.max(count - 1, ...levels);

  const specs = [];
  for (let lv = bottom; lv <= top; lv++) {
    const o = overrides.get(lv) || { use: "apartments", units: null };
    specs.push({ level: lv, use: o.use, units: o.units });
  }
  return specs;
}

/* ------------------------------------------------------------------ */
/* التوليد                                                             */
/* ------------------------------------------------------------------ */

const num = (id) => {
  const v = $(id).value.trim();
  return v === "" ? null : Number(v);
};

async function run() {
  const outputs = ["svg"];
  document.querySelectorAll(".outputs input:checked").forEach((c) => {
    if (c.value !== "svg") outputs.push(c.value);
  });

  if (mode === "building") return runBuilding(outputs);

  const request = {
    building_type: buildingType,
    area: Number($("area").value),
    width: num("width"),
    depth: num("depth"),
    bedrooms: num("bedrooms"),
    bathrooms: num("bathrooms"),
    receptions: num("receptions"),
    entry_side: $("entrySide").value,
    brief: $("brief").value,
    outputs,
    use_ai: $("useAi").checked,
    language: lang,
    want_boq: $("optBoq").checked,
  };

  const options = {
    repair: $("optRepair").checked,
    explain: $("optExplain").checked,
    solar_city: $("optSolar").checked ? $("solarCity").value : "",
    finishes_tier: $("optFinishes").checked ? $("finishTier").value : "",
    furnish: $("optFurnish").checked,
    intent_options: $("optIntent").checked ? 3 : 0,
  };

  $("error").hidden = true;
  $("run").disabled = true;
  $("loading").hidden = false;
  $("loadingText").textContent = request.use_ai ? t("loadingAi") : t("loadingRules");

  const tick = setTimeout(() => {
    $("loadingText").textContent = t("loadingDraw");
  }, 2500);

  try {
    const res = await fetch("/api/design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, options }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t("unknownError"));
    }
    lastResult = await res.json();
    renderStatic(lastResult);
    if ($("view-three").classList.contains("active")) renderThree(lastResult.model3d);
  } catch (e) {
    $("error").textContent = e.message;
    $("error").hidden = false;
  } finally {
    clearTimeout(tick);
    $("loading").hidden = true;
    $("run").disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/* العرض                                                               */
/* ------------------------------------------------------------------ */

/** الأرقام. مفصولة عشان الحوار بيحدّثها من غير ما يعيد بناء الصفحة كلها. */
function renderStats(r) {
  const m = r.metrics;
  const errs = m.errors | 0;
  const warns = m.warnings | 0;
  const unit = lang === "ar" ? "م²" : "m²";
  const unitM = lang === "ar" ? "م" : "m";

  $("stats").hidden = false;
  $("stats").innerHTML = [
    stat(`${m.gross_area.toFixed(1)} ${unit}`, t("statGross")),
    stat(`${m.net_area.toFixed(1)} ${unit}`, t("statNet")),
    stat(`${(m.efficiency * 100).toFixed(1)}%`, t("statEfficiency"),
         m.efficiency > 0.85 ? "good" : "mid"),
    stat(`${(m.circulation_share * 100).toFixed(1)}%`, t("statCirculation")),
    stat(`${m.plot_width} × ${m.plot_depth} ${unitM}`, t("statPlot")),
    stat(`${m.rooms | 0}`, t("statRooms")),
    stat(`${errs}`, t("statErrors"), errs ? "bad" : "good"),
    stat(`${warns}`, t("statWarnings"), warns ? "mid" : "good"),
    stat(r.ai_used
      ? (healthState[`ai_provider_name_${lang}`] || healthState.ai_provider_name || t("sourceAi"))
      : t("sourceRules"), t("statSource")),
  ].join("");
}

function renderChecks(r) {
  $("checksHost").innerHTML = r.issues.length
    ? r.issues
        .map(
          (i) => `<div class="check ${i.severity}">
            <span class="icon">${i.severity === "error" ? "❌" : "⚠️"}</span>
            <div><div>${escapeHtml(i.message)}</div>
                 <div class="code">${i.code}</div></div></div>`
        )
        .join("")
    : `<div class="all-good"><span class="big">✅</span>${t("allGood")}</div>`;
}

function renderStatic(r) {
  $("placeholder").style.display = "none";
  $("floorNav").hidden = true;   // نتيجة وحدة واحدة — مفيش أدوار نتنقّل بينها
  $("svgHost").innerHTML = r.svg;
  planZoom?.fit();

  $("altHost").innerHTML = r.alternatives.length
    ? r.alternatives
        .map(
          (svg, i) =>
            `<figure><figcaption>${t("option")} ${i + 1}</figcaption>${svg}</figure>`
        )
        .join("")
    : `<div class="placeholder"><p>${t("noAlternatives")}</p></div>`;

  $("reportHost").innerHTML = markdown(r.report_md);

  renderStats(r);
  renderChecks(r);
  renderAnalysis(r);
  startSession(r);

  const labels = {
    svg: t("dlSvg"), pdf: t("dlPdf"), dxf: t("dlDxf"),
    json3d: t("dlJson3d"), report: t("dlReport"),
    rationale: t("dlRationale"), boq: t("dlBoq"),
  };
  const dl = $("downloads");
  dl.hidden = false;
  dl.innerHTML = Object.entries(r.downloads)
    .map(([fmt, url]) => `<a class="dl" href="${url}" download>⬇ ${labels[fmt] || fmt}</a>`)
    .join("");
}

async function runBuilding(outputs) {
  const payload = {
    area: Number($("area").value),
    width: num("width"),
    depth: num("depth"),
    floors: buildFloorSpecs(),
    entry_side: $("entrySide").value,
    brief: $("brief").value,
    outputs,
    use_ai: $("useAi").checked,
    language: lang,
  };

  $("error").hidden = true;
  $("run").disabled = true;
  $("loading").hidden = false;
  $("loadingText").textContent = t("loadingRules");

  try {
    const res = await fetch("/api/building", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || t("unknownError"));
    }
    lastResult = await res.json();
    activeFloor = lastResult.floors.length - 1;   // نبدأ من دور متكرر مش الأرضي
    renderBuilding(lastResult);
  } catch (e) {
    $("error").textContent = e.message;
    $("error").hidden = false;
  } finally {
    $("loading").hidden = true;
    $("run").disabled = false;
  }
}

function renderBuilding(r) {
  $("placeholder").style.display = "none";
  renderFloorNav(r);
  showFloor(r, activeFloor);

  $("reportHost").innerHTML = markdown(r.report_md);

  const m = r.metrics;
  const unit = lang === "ar" ? "م²" : "m²";
  const unitM = lang === "ar" ? "م" : "m";
  $("stats").hidden = false;
  $("stats").innerHTML = [
    stat(`${m.floors | 0}`, t("statFloors")),
    stat(`${m.units | 0}`, t("statTotalUnits")),
    stat(`${m.floor_area.toFixed(0)} ${unit}`, t("statGross")),
    stat(`${m.total_built_area.toFixed(0)} ${unit}`, t("statBuiltArea")),
    stat(`${m.plot_width} × ${m.plot_depth} ${unitM}`, t("statFootprint")),
    stat(`${(m.avg_efficiency * 100).toFixed(1)}%`, t("statEfficiency"),
         m.avg_efficiency > 0.8 ? "good" : "mid"),
    stat(`${m.errors | 0}`, t("statErrors"), (m.errors | 0) ? "bad" : "good"),
    stat(`${m.warnings | 0}`, t("statWarnings"), (m.warnings | 0) ? "mid" : "good"),
  ].join("");

  const labels = {
    pdf: t("dlPdf"), json3d: t("dlJson3d"), report: t("dlReport"),
  };
  const dl = $("downloads");
  dl.hidden = false;
  dl.innerHTML = Object.entries(r.downloads)
    .map(([fmt, url]) => {
      const m2 = fmt.match(/^(svg|dxf)_L(-?\d+)$/);
      const name = m2
        ? `${m2[1].toUpperCase()} · ${r.floors.find((f) => f.level === Number(m2[2]))?.label ?? m2[2]}`
        : labels[fmt] || fmt;
      return `<a class="dl" href="${url}" download>⬇ ${name}</a>`;
    })
    .join("");
}

function renderFloorNav(r) {
  const nav = $("floorNav");
  if (!r.floors) { nav.hidden = true; return; }
  nav.hidden = false;
  nav.innerHTML = "";
  // من فوق لتحت زي ما المهندس بيقرا قطاع المبنى
  [...r.floors].reverse().forEach((f) => {
    const idx = r.floors.indexOf(f);
    const b = document.createElement("button");
    const errs = f.metrics.errors | 0;
    b.className = "floor-btn" + (idx === activeFloor ? " active" : "")
                + (errs ? " has-errors" : "");
    b.innerHTML = `<span>${escapeHtml(f.label)}</span>`
      + `<span class="badge">${f.units}</span>`;
    b.onclick = () => { activeFloor = idx; renderFloorNav(r); showFloor(r, idx); };
    nav.appendChild(b);
  });
}

function showFloor(r, idx) {
  const floor = r.floors[idx];
  if (!floor) return;
  $("svgHost").innerHTML = floor.svg;
  planZoom?.fit();

  $("checksHost").innerHTML = floor.issues.length
    ? floor.issues
        .map((i) => `<div class="check ${i.severity}">
            <span class="icon">${i.severity === "error" ? "❌" : "⚠️"}</span>
            <div><div>${escapeHtml(i.message)}</div>
                 <div class="code">${i.code}</div></div></div>`)
        .join("")
    : `<div class="all-good"><span class="big">✅</span>${t("allGood")}</div>`;
}

const stat = (value, label, cls = "") =>
  `<div class="stat ${cls}"><b>${value}</b><span>${label}</span></div>`;

const escapeHtml = (s) =>
  String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ------------------------------------------------------------------ */
/* Markdown خفيف (عناوين، جداول، قوائم)                                */
/* ------------------------------------------------------------------ */

function markdown(md) {
  const lines = md.split("\n");
  const out = [];
  let inTable = false, inList = false;

  const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
  const closeTable = () => { if (inTable) { out.push("</tbody></table>"); inTable = false; } };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { closeList(); closeTable(); continue; }

    if (line.startsWith("|")) {
      if (/^\|[\s:|-]+\|$/.test(line)) continue;          // سطر الفاصل
      const cells = line.split("|").slice(1, -1).map((c) => c.trim());
      if (!inTable) {
        closeList();
        out.push("<table><thead><tr>" +
          cells.map((c) => `<th>${inline(c)}</th>`).join("") +
          "</tr></thead><tbody>");
        inTable = true;
      } else {
        out.push("<tr>" + cells.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>");
      }
      continue;
    }
    closeTable();

    if (line.startsWith("### ")) { closeList(); out.push(`<h3>${inline(line.slice(4))}</h3>`); }
    else if (line.startsWith("## ")) { closeList(); out.push(`<h2>${inline(line.slice(3))}</h2>`); }
    else if (line.startsWith("# ")) { closeList(); out.push(`<h1>${inline(line.slice(2))}</h1>`); }
    else if (line.startsWith("> ")) { closeList(); out.push(`<blockquote>${inline(line.slice(2))}</blockquote>`); }
    else if (line === "---") { closeList(); out.push("<hr>"); }
    else if (line.startsWith("- ")) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${inline(line.slice(2))}</li>`);
    } else { closeList(); out.push(`<p>${inline(line)}</p>`); }
  }
  closeList(); closeTable();
  return out.join("");
}

const inline = (s) =>
  escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");

/* ------------------------------------------------------------------ */
/* المجسّم ثلاثي الأبعاد                                                */
/* ------------------------------------------------------------------ */

async function renderThree(model) {
  const host = $("threeHost");
  if (!model || !model.walls) return;

  let THREE, OrbitControls;
  try {
    THREE = await import("three");
    ({ OrbitControls } = await import("three/addons/controls/OrbitControls.js"));
  } catch {
    host.innerHTML = `<div class="placeholder"><p>${t("threeOffline")}</p></div>`;
    return;
  }

  if (three) { three.dispose(); host.innerHTML = ""; }

  const w = host.clientWidth || 900, h = host.clientHeight || 600;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b1017);

  const P = model.plot;
  const span = Math.max(P.w, P.h);
  const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 500);
  camera.position.set(P.w / 2 + span * 0.85, span * 0.95, P.h / 2 + span * 0.95);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(w, h);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  host.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(P.x + P.w / 2, 1.2, P.y + P.h / 2);
  controls.enableDamping = true;

  scene.add(new THREE.HemisphereLight(0xdfe9f5, 0x2a3242, 1.5));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(span, span * 1.4, span * 0.6);
  scene.add(sun);

  for (const f of model.floors) {
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(f.w, f.h),
      new THREE.MeshLambertMaterial({
        color: new THREE.Color(f.colour),
        transparent: f.unroofed, opacity: f.unroofed ? 0.55 : 1,
      })
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(f.x + f.w / 2, 0.015, f.y + f.h / 2);
    scene.add(mesh);
  }

  const wallMat = new THREE.MeshLambertMaterial({ color: 0xf1f3f6 });
  const extMat = new THREE.MeshLambertMaterial({ color: 0xd9dee6 });
  for (const b of model.walls) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(b.sx, b.sz, b.sy),
      b.exterior ? extMat : wallMat
    );
    mesh.position.set(b.cx, b.cz, b.cy);
    scene.add(mesh);
  }

  const grid = new THREE.GridHelper(span * 2.2, Math.round(span * 2.2), 0x1e2735, 0x161e2b);
  grid.position.set(P.x + P.w / 2, 0, P.y + P.h / 2);
  scene.add(grid);

  let alive = true;
  (function loop() {
    if (!alive) return;
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  })();

  const onResize = () => {
    const W = host.clientWidth, H = host.clientHeight;
    if (!W || !H) return;
    camera.aspect = W / H; camera.updateProjectionMatrix(); renderer.setSize(W, H);
  };
  addEventListener("resize", onResize);

  three = {
    dispose() {
      alive = false;
      removeEventListener("resize", onResize);
      controls.dispose();
      renderer.dispose();
    },
  };
}

boot();
