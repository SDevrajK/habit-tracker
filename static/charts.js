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
 * undefined/null/0 → no data (#ebedf0), >0..0.33 → light green, 0.33..0.66 → mid, 1 → dark green
 */
function fractionToColor(fraction) {
  if (fraction === undefined || fraction === null || fraction === 0) return COLORS.none;
  if (fraction < 0.34) return "#f08a83";
  if (fraction < 0.67) return "#ecd240";
  if (fraction == 1.0) return "#32db78";

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

      const tipText = isFuture
        ? dateStr
        : fraction !== undefined
          ? `${dateStr}: ${Math.round(fraction * 100)}% completed`
          : `${dateStr}: no data`;
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

// ---- Challenge Grid -------------------------------------------------------

/**
 * Render a 10-column grid of N challenge days.
 * @param {string} containerId
 * @param {Object} dayStatuses   — { "1": "clean"|"failed"|"future", ... } (string keys from JSON)
 * @param {number} duration      — total days in challenge (e.g. 100)
 * @param {string} startDateStr  — "YYYY-MM-DD" of day 1
 * @param {number} currentDay    — 1-indexed current day number (for today highlight)
 */
function renderChallengeGrid(containerId, dayStatuses, duration, startDateStr, currentDay) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const CELL = 30, GAP = 4, STEP = CELL + GAP;
  const COLS = 10;
  const ROWS = Math.ceil(duration / COLS);
  const PAD = 6;
  const WIDTH  = COLS * STEP + PAD;
  const HEIGHT = ROWS * STEP + PAD;

  const svg = svgEl("svg", { width: WIDTH, height: HEIGHT });

  const STATUS_FILL = {
    clean:   "#2da44e",
    failed:  "#cf222e",
    future:  "#ebedf0",
  };

  const startDate = parseDate(startDateStr);

  for (let i = 0; i < duration; i++) {
    const dayNum   = i + 1;
    const col      = i % COLS;
    const row      = Math.floor(i / COLS);
    const x        = PAD / 2 + col * STEP;
    const y        = PAD / 2 + row * STEP;
    const status   = dayStatuses[String(dayNum)] || "future";
    const isToday  = (dayNum === currentDay);
    const fill     = STATUS_FILL[status] || STATUS_FILL.future;

    const rect = svgEl("rect", {
      x, y, width: CELL, height: CELL, rx: 4,
      fill,
      stroke:         isToday ? "#0969da" : "rgba(27,31,35,0.1)",
      "stroke-width": isToday ? "2.5" : "0.5",
      "class": "challenge-cell",
    });

    // Day number label inside cell
    const label = svgEl("text", {
      x: x + CELL / 2, y: y + CELL / 2 + 4,
      "font-size": 9, "text-anchor": "middle", "font-weight": "bold",
      fill: status === "future" ? "#adb5bd" : "white",
    });
    label.textContent = dayNum;

    // Tooltip: day number + date + status
    const d = new Date(startDate);
    d.setDate(d.getDate() + i);
    const dateStr = fmtDate(d);
    const tipLabel = status === "future" ? "upcoming" : status;
    addTooltip(rect, `Day ${dayNum} — ${dateStr} — ${tipLabel}`);

    svg.appendChild(rect);
    svg.appendChild(label);
  }

  container.appendChild(svg);
}


// ---- Sparkline -----------------------------------------------------------

/**
 * Render a minimal sparkline (120x36 SVG, no axes, no labels).
 * @param {string} containerId
 * @param {Array}  data   — [{date, value}, ...]
 * @param {string} color  — stroke color
 */
function renderSparkline(containerId, data, color) {
  const container = document.getElementById(containerId);
  if (!container || !data || data.length < 2) return;

  const W = 120, H = 36, PAD = 2;
  const svg = svgEl("svg", { width: W, height: H });

  const values = data.map(function(d) { return d.value; });
  const minV = Math.min.apply(null, values);
  const maxV = Math.max.apply(null, values);
  const range = maxV - minV || 1;

  var points = data.map(function(d, i) {
    var x = PAD + (i / (data.length - 1)) * (W - 2 * PAD);
    var y = H - PAD - ((d.value - minV) / range) * (H - 2 * PAD);
    return x + "," + y;
  }).join(" ");

  var polyline = svgEl("polyline", {
    points: points,
    fill: "none",
    stroke: color || "#0969da",
    "stroke-width": "1.5",
    "stroke-linejoin": "round",
    "stroke-linecap": "round",
  });
  svg.appendChild(polyline);
  container.appendChild(svg);
}


// ---- Line Chart ----------------------------------------------------------

/**
 * Render a multi-series line chart with optional moving average overlay.
 * @param {string} containerId
 * @param {Array}  series  — [{label, color, data: [{date, value}], unit, movingAvg, dashed}, ...]
 * @param {Object} options — {width, height, yLabel, movingAvgDays}
 */
function renderLineChart(containerId, series, options) {
  var container = document.getElementById(containerId);
  if (!container) return;

  options = options || {};
  var WIDTH  = options.width  || container.offsetWidth || 680;
  var HEIGHT = options.height || 280;
  var MA_DAYS = options.movingAvgDays || 7;
  var Y_LABEL = options.yLabel || "";

  var LEFT = 56, RIGHT = 20, TOP = 30, BOTTOM = 36;
  var plotW = WIDTH - LEFT - RIGHT;
  var plotH = HEIGHT - TOP - BOTTOM;

  // Collect all dates and value range across all series
  var allDates = [];
  var allValues = [];
  series.forEach(function(s) {
    if (!s.data) return;
    s.data.forEach(function(d) {
      allDates.push(d.date);
      allValues.push(d.value);
    });
  });

  if (allValues.length === 0) return;

  // Sort unique dates for x-axis
  var uniqueDates = allDates.filter(function(v, i, a) { return a.indexOf(v) === i; }).sort();
  var dateIndex = {};
  uniqueDates.forEach(function(d, i) { dateIndex[d] = i; });

  var minV = Math.min.apply(null, allValues);
  var maxV = Math.max.apply(null, allValues);
  var vRange = maxV - minV;
  if (vRange === 0) { vRange = 1; minV -= 0.5; maxV += 0.5; }
  // Add 5% padding
  var vPad = vRange * 0.05;
  minV -= vPad;
  maxV += vPad;
  vRange = maxV - minV;

  function xPos(dateStr) {
    var idx = dateIndex[dateStr];
    if (uniqueDates.length === 1) return LEFT + plotW / 2;
    return LEFT + (idx / (uniqueDates.length - 1)) * plotW;
  }

  function yPos(val) {
    return TOP + plotH - ((val - minV) / vRange) * plotH;
  }

  var svg = svgEl("svg", { width: WIDTH, height: HEIGHT });

  // Y-axis gridlines and labels (5 lines)
  for (var i = 0; i <= 4; i++) {
    var yVal = minV + (i / 4) * vRange;
    var y = yPos(yVal);
    var gridline = svgEl("line", {
      x1: LEFT, y1: y, x2: LEFT + plotW, y2: y,
      stroke: "#e1e4e8", "stroke-width": "1",
    });
    svg.appendChild(gridline);
    var label = svgEl("text", {
      x: LEFT - 6, y: y + 4,
      "font-size": 10, fill: "#57606a", "text-anchor": "end",
    });
    label.textContent = yVal.toFixed(1);
    svg.appendChild(label);
  }

  // X-axis: show month/year label at first occurrence of each month
  var lastMonth = "";
  uniqueDates.forEach(function(dateStr) {
    var parts = dateStr.split("-");
    var monthKey = parts[0] + "-" + parts[1];
    if (monthKey !== lastMonth) {
      lastMonth = monthKey;
      var MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      var mIdx = parseInt(parts[1], 10) - 1;
      var xLabel = svgEl("text", {
        x: xPos(dateStr), y: HEIGHT - 6,
        "font-size": 10, fill: "#57606a", "text-anchor": "middle",
      });
      xLabel.textContent = MONTHS[mIdx] + " " + parts[0].slice(2);
      svg.appendChild(xLabel);
    }
  });

  // Compute moving average for a data array
  function computeMA(data, days) {
    var sorted = data.slice().sort(function(a, b) { return a.date < b.date ? -1 : 1; });
    return sorted.map(function(d, i) {
      var start = Math.max(0, i - days + 1);
      var slice = sorted.slice(start, i + 1);
      var sum = slice.reduce(function(acc, v) { return acc + v.value; }, 0);
      return { date: d.date, value: sum / slice.length };
    });
  }

  // Draw each series
  series.forEach(function(s) {
    if (!s.data || s.data.length === 0) return;
    var sorted = s.data.slice().sort(function(a, b) { return a.date < b.date ? -1 : 1; });

    // Main line
    var pathParts = sorted.map(function(d, i) {
      var cmd = i === 0 ? "M" : "L";
      return cmd + xPos(d.date) + "," + yPos(d.value);
    });
    var path = svgEl("path", {
      d: pathParts.join(" "),
      fill: "none",
      stroke: s.color || "#0969da",
      "stroke-width": s.dashed ? "1.5" : "2",
      "stroke-dasharray": s.dashed ? "4,3" : "none",
      "stroke-linejoin": "round",
    });
    svg.appendChild(path);

    // Data point circles with tooltips
    sorted.forEach(function(d) {
      var cx = xPos(d.date);
      var cy = yPos(d.value);
      var circle = svgEl("circle", {
        cx: cx, cy: cy, r: 3,
        fill: s.color || "#0969da",
        stroke: "white", "stroke-width": "1",
      });
      var tipUnit = s.unit ? " " + s.unit : "";
      addTooltip(circle, d.date + ": " + d.value + tipUnit);
      svg.appendChild(circle);
    });

    // Moving average overlay
    if (s.movingAvg && sorted.length >= 2) {
      var maData = computeMA(sorted, MA_DAYS);
      var maParts = maData.map(function(d, i) {
        var cmd = i === 0 ? "M" : "L";
        return cmd + xPos(d.date) + "," + yPos(d.value);
      });
      var maPath = svgEl("path", {
        d: maParts.join(" "),
        fill: "none",
        stroke: s.color || "#0969da",
        "stroke-width": "1.5",
        "stroke-dasharray": "4,3",
        "stroke-linejoin": "round",
        opacity: "0.6",
      });
      svg.appendChild(maPath);
    }
  });

  // Legend at top-right
  var legendX = LEFT + plotW;
  series.forEach(function(s, i) {
    if (!s.label) return;
    var ly = 14 + i * 16;
    var rect = svgEl("rect", {
      x: legendX - 80, y: ly - 8, width: 10, height: 10, rx: 2,
      fill: s.color || "#0969da",
    });
    var text = svgEl("text", {
      x: legendX - 66, y: ly,
      "font-size": 10, fill: "#24292f",
    });
    text.textContent = s.label;
    if (s.movingAvg) {
      var maText = svgEl("text", {
        x: legendX - 80, y: ly + 12,
        "font-size": 9, fill: "#57606a",
      });
      maText.textContent = MA_DAYS + "-day avg (dashed)";
      svg.appendChild(maText);
    }
    svg.appendChild(rect);
    svg.appendChild(text);
  });

  container.appendChild(svg);
}
