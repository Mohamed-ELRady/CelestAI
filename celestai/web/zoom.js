/* تكبير وتصغير وتحريك المخطط باللمس أو الماوس — pan & zoom for the plan viewer.
 *
 * بيستخدم Pointer Events عشان نفس الكود يشتغل باللمس (سحب بإصبع، تكبير بإصبعين)
 * والماوس (سحب بالكليك، عجلة الماوس أو pinch على التراك باد) من غير تكرار منطق.
 */

const MIN_SCALE = 0.08;
const MAX_SCALE = 8;
const WHEEL_SENSITIVITY = 0.0032;

export function createPanZoom(viewport, content, { onChange } = {}) {
  let scale = 1;
  let tx = 0;
  let ty = 0;
  const pointers = new Map();
  let mode = null;          // "pan" | "pinch"
  let start = null;

  const clamp = (s) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));

  function apply() {
    content.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    onChange?.(scale);
  }

  function naturalSize() {
    const svg = content.querySelector("svg");
    if (!svg) return null;
    const w = svg.width?.baseVal?.value;
    const h = svg.height?.baseVal?.value;
    return w && h ? { w, h } : null;
  }

  function zoomAt(clientX, clientY, factor) {
    const rect = viewport.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const next = clamp(scale * factor);
    if (next === scale) return;
    tx = x - (x - tx) * (next / scale);
    ty = y - (y - ty) * (next / scale);
    scale = next;
    apply();
  }

  function zoomAtCenter(factor) {
    const rect = viewport.getBoundingClientRect();
    zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
  }

  /** يعرض المخطط كامل جوه الإطار المتاح، ويتوسّطه — الحالة الافتراضية. */
  function fit() {
    const size = naturalSize();
    const vw = viewport.clientWidth;
    const vh = viewport.clientHeight;
    if (!size || vw <= 0 || vh <= 0) return;
    const pad = 28;
    const fitScale = Math.min((vw - pad * 2) / size.w, (vh - pad * 2) / size.h, 1.4);
    scale = clamp(fitScale > 0 ? fitScale : 1);
    tx = (vw - size.w * scale) / 2;
    ty = (vh - size.h * scale) / 2;
    apply();
  }

  viewport.addEventListener(
    "wheel",
    (e) => {
      if (!naturalSize()) return;
      e.preventDefault();
      const factor = Math.exp(-e.deltaY * WHEEL_SENSITIVITY);
      zoomAt(e.clientX, e.clientY, factor);
    },
    { passive: false }
  );

  viewport.addEventListener("pointerdown", (e) => {
    if (!naturalSize()) return;
    // ممكن يفشل لو المتصفح مش متتبّع الـ pointer ده فعليًا (نادر) — مش لازم نوقف التتبع بسببه
    try {
      viewport.setPointerCapture(e.pointerId);
    } catch {
      /* تجاهل — التتبع هيفضل شغال طول ما الإصبع/الماوس فوق العنصر */
    }
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (pointers.size === 1) {
      mode = "pan";
      start = { x: e.clientX, y: e.clientY, tx, ty };
    } else if (pointers.size === 2) {
      mode = "pinch";
      const [a, b] = [...pointers.values()];
      start = {
        dist: Math.hypot(a.x - b.x, a.y - b.y),
        midX: (a.x + b.x) / 2,
        midY: (a.y + b.y) / 2,
        scale,
        tx,
        ty,
      };
    }
  });

  viewport.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (mode === "pan" && pointers.size === 1) {
      tx = start.tx + (e.clientX - start.x);
      ty = start.ty + (e.clientY - start.y);
      apply();
    } else if (mode === "pinch" && pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const next = clamp(start.scale * (dist / start.dist));
      const rect = viewport.getBoundingClientRect();
      const midX = start.midX - rect.left;
      const midY = start.midY - rect.top;
      tx = midX - (midX - start.tx) * (next / start.scale);
      ty = midY - (midY - start.ty) * (next / start.scale);
      scale = next;
      apply();
    }
  });

  function release(e) {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (pointers.size === 1) {
      const [p] = pointers.values();
      mode = "pan";
      start = { x: p.x, y: p.y, tx, ty };
    } else {
      mode = null;
    }
  }
  viewport.addEventListener("pointerup", release);
  viewport.addEventListener("pointercancel", release);
  viewport.addEventListener("pointerleave", release);

  viewport.addEventListener("dblclick", (e) => {
    e.preventDefault();
    fit();
  });

  return {
    zoomIn: () => zoomAtCenter(1.3),
    zoomOut: () => zoomAtCenter(1 / 1.3),
    fit,
    get scale() {
      return scale;
    },
  };
}
