/**
 * charts.js — Vanilla JS / SVG heatmap and calendar rendering.
 * No external dependencies. No build step required.
 *
 * Exports (called from template <script> blocks):
 *   renderHeatmap(containerId, data, today)
 *   renderCalendar(containerId, data, today)
 */

// ---- Color helpers --------------------------------------------------------

const COLORS = {
  completed: "#2da44e",
  partial:   "#d1a726",
  failed:    "#cf222e",
  skipped:   "#8c959f",
  na:        "#ffffff",
  none:      "#ebedf0",
};

/**
 * Map a fraction [0,1] to a green gradient color for the annual heatmap.
 * 0 → no data (#ebedf0), >0..0.33 → light green, 0.33..0.66 → mid, 1 → dark green
 */
function fractionToColor(fraction) {
  if (fraction === undefined || fraction === null) return COLORS.none;
  if (fraction === 0) return "#9be9a8";   // at least something attempted
  if (fraction < 0.34) return "#9be9a8";
  if (fraction < 0.67) return "#40c463";
  return COLORS.completed;
}

function statusToColor(status) {
  return COLORS[status] || COLORS.none;
}

// ---- SVG helpers ----------------------------------------------------------

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function addTooltip(cell, text) {
  let tip = null;
  cell.addEventListener("mouseenter", (e) => {
    tip = document.createElement("div");
    tip.className = "hm-tooltip";
    tip.textContent = text;
    document.body.appendChild(tip);
    positionTip(e, tip);
  });
  cell.addEventListener("mousemove", (e) => tip && positionTip(e, tip));
  cell.addEventListener("mouseleave", () => { if (tip) { tip.remove(); tip = null; } });
}

function positionTip(e, tip) {
  tip.style.left = (e.clientX + 12) + "px";
  tip.style.top  = (e.clientY - 28) + "px";
}

// ---- Date helpers ---------------------------------------------------------

/** Parse "YYYY-MM-DD" without timezone shift. */
function parseDate(str) {
  const [y, m, d] = str.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Format Date as "YYYY-MM-DD". */
function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

// ---- Annual Heatmap -------------------------------------------------------

/**
 * Render a GitHub-style 52-week heatmap into containerId.
 * @param {string} containerId
 * @param {Object} data   — { "YYYY-MM-DD": fraction, ... }
 * @param {string} today  — "YYYY-MM-DD"
 */
function renderHeatmap(containerId, data, today) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const CELL = 13, GAP = 2, STEP = CELL + GAP;
  const LEFT_PAD = 28, TOP_PAD = 22;
  const WEEKS = 53;
  const WIDTH  = LEFT_PAD + WEEKS * STEP;
  const HEIGHT = TOP_PAD + 7 * STEP;

  const svg = svgEl("svg", { width: WIDTH, height: HEIGHT });

  // Month labels
  const todayDate = parseDate(today);
  const startDate = new Date(todayDate);
  startDate.setDate(startDate.getDate() - 364);
  // Align to Sunday start
  startDate.setDate(startDate.getDate() - startDate.getDay());

  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  let lastMonth = -1;
  for (let w = 0; w < WEEKS; w++) {
    const d = new Date(startDate);
    d.setDate(d.getDate() + w * 7);
    if (d.getMonth() !== lastMonth) {
      lastMonth = d.getMonth();
      const label = svgEl("text", {
        x: LEFT_PAD + w * STEP, y: 14,
        "font-size": 10, fill: "#57606a",
      });
      label.textContent = MONTHS[d.getMonth()];
      svg.appendChild(label);
    }
  }

  // Day labels (Mon, Wed, Fri)
  const DAY_LABELS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  [1, 3, 5].forEach((dow) => {
    const label = svgEl("text", {
      x: LEFT_PAD - 4, y: TOP_PAD + dow * STEP + CELL - 3,
      "font-size": 9, fill: "#57606a", "text-anchor": "end",
    });
    label.textContent = DAY_LABELS[dow];
    svg.appendChild(label);
  });

  // Cells
  for (let w = 0; w < WEEKS; w++) {
    for (let dow = 0; dow < 7; dow++) {
      const d = new Date(startDate);
      d.setDate(d.getDate() + w * 7 + dow);
      const dateStr = fmtDate(d);
      const isFuture = d > todayDate;
      const fraction = data[dateStr];
      let color = isFuture ? COLORS.na : (fraction !== undefined ? fractionToColor(fraction) : COLORS.none);

      const rect = svgEl("rect", {
        x: LEFT_PAD + w * STEP,
        y: TOP_PAD + dow * STEP,
        width: CELL, height: CELL, rx: 2,
        fill: color,
        "stroke": "rgba(27,31,35,0.06)", "stroke-width": "0.5",
        "class": "hm-cell",
      });

      const pct = fraction !== undefined ? Math.round(fraction * 100) : 0;
      const tipText = isFuture
        ? dateStr
        : `${dateStr}: ${pct}% completed`;
      addTooltip(rect, tipText);
      svg.appendChild(rect);
    }
  }

  container.appendChild(svg);
}

// ---- Per-habit Monthly Calendar ------------------------------------------

/**
 * Render a 12-month calendar grid for a single habit.
 * @param {string} containerId
 * @param {Object} data   — { "YYYY-MM-DD": { status, value }, ... }
 * @param {string} today  — "YYYY-MM-DD"
 */
function renderCalendar(containerId, data, today) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const todayDate = parseDate(today);
  const CELL = 24, GAP = 3, STEP = CELL + GAP;
  const MONTHS_PER_ROW = 4;
  const MONTH_W = 7 * STEP + 10;
  const MONTH_H = 7 * STEP + 24;  // 6 rows + header
  const ROWS = 3;
  const WIDTH  = MONTHS_PER_ROW * MONTH_W;
  const HEIGHT = ROWS * MONTH_H;

  const svg = svgEl("svg", { width: WIDTH, height: HEIGHT });

  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const DOW_LABELS = ["Mo","Tu","We","Th","Fr","Sa","Su"];

  // Render 12 months ending with the current month
  const endYear  = todayDate.getFullYear();
  const endMonth = todayDate.getMonth();  // 0-indexed

  for (let i = 0; i < 12; i++) {
    // Month index going back from current: i=0 → 11 months ago, i=11 → current month
    let monthOffset = endMonth - (11 - i);
    let year = endYear;
    if (monthOffset < 0) { year--; monthOffset += 12; }

    const col = i % MONTHS_PER_ROW;
    const row = Math.floor(i / MONTHS_PER_ROW);
    const ox = col * MONTH_W;
    const oy = row * MONTH_H;

    // Month label
    const label = svgEl("text", {
      x: ox + 2, y: oy + 12,
      "font-size": 11, "font-weight": "bold", fill: "#24292f",
    });
    label.textContent = `${MONTHS[monthOffset]} ${year}`;
    svg.appendChild(label);

    // Day-of-week header
    DOW_LABELS.forEach((dl, j) => {
      const t = svgEl("text", {
        x: ox + j * STEP + CELL / 2, y: oy + 24,
        "font-size": 8, fill: "#57606a", "text-anchor": "middle",
      });
      t.textContent = dl;
      svg.appendChild(t);
    });

    // Cells — week starts Monday (ISO)
    const firstDay = new Date(year, monthOffset, 1);
    const daysInMonth = new Date(year, monthOffset + 1, 0).getDate();
    // ISO weekday: Mon=0 … Sun=6
    const startDow = (firstDay.getDay() + 6) % 7;

    for (let day = 1; day <= daysInMonth; day++) {
      const d = new Date(year, monthOffset, day);
      const dateStr = fmtDate(d);
      const isFuture = d > todayDate;
      const entry = data[dateStr];
      const status = entry ? entry.status : null;
      const value  = entry ? entry.value  : null;

      const cellIdx = startDow + day - 1;
      const cx = ox + (cellIdx % 7) * STEP;
      const cy = oy + 28 + Math.floor(cellIdx / 7) * STEP;

      let color;
      if (isFuture || status === "not_applicable" || !status) {
        color = COLORS.na;
      } else {
        color = statusToColor(status);
      }

      const rect = svgEl("rect", {
        x: cx, y: cy, width: CELL, height: CELL, rx: 2,
        fill: color,
        "stroke": "rgba(27,31,35,0.08)", "stroke-width": "0.5",
        "class": "cal-cell",
      });
      svg.appendChild(rect);

      // Show numeric value as text inside cell
      if (value !== null && value !== undefined && !isFuture) {
        const t = svgEl("text", {
          x: cx + CELL / 2, y: cy + CELL / 2 + 4,
          "font-size": 7, fill: "white", "text-anchor": "middle",
          "font-weight": "bold",
        });
        t.textContent = value % 1 === 0 ? value : value.toFixed(1);
        svg.appendChild(t);
      }

      // Day number
      const dayLabel = svgEl("text", {
        x: cx + 2, y: cy + 9,
        "font-size": 7, fill: isFuture ? "#ccc" : "rgba(0,0,0,0.4)",
      });
      dayLabel.textContent = day;
      svg.appendChild(dayLabel);

      const tipStatus = status ? ` — ${status}${value !== null ? ` (${value})` : ""}` : "";
      addTooltip(rect, `${dateStr}${tipStatus}`);
    }
  }

  container.appendChild(svg);
}
