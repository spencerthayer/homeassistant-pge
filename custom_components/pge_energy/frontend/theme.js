/**
 * Theme resolution for the PGE panel.
 *
 * HA theme tokens inherit into the panel shadow tree. PGE series tokens are
 * defined on `:host` in terms of those HA tokens so light/dark (and custom
 * themes) stay readable without hardcoded hex in chart options.
 */

/** Resolve a CSS custom property from an element (defaults to document root). */
export function cssVar(name, fallback = "", el = null) {
  const target = el || (typeof document !== "undefined" ? document.documentElement : null);
  if (!target || typeof getComputedStyle !== "function") return fallback;
  const v = getComputedStyle(target).getPropertyValue(name).trim();
  return v || fallback;
}

/** True when Home Assistant (or the document) is in a dark theme. */
export function isDarkTheme(hass = null, el = null) {
  if (hass?.themes && typeof hass.themes.darkMode === "boolean") {
    return hass.themes.darkMode;
  }
  const scheme = cssVar("color-scheme", "", el || document.documentElement);
  if (scheme.includes("dark") && !scheme.includes("only light")) return true;
  if (scheme.includes("light") && !scheme.includes("dark")) return false;
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ?? false;
  } catch (_e) {
    return false;
  }
}

/**
 * Sync host attributes used by CSS (`data-dark`, `color-scheme`) with HA.
 * Call whenever `hass` updates so theme switches reflow controls/charts.
 */
export function applyPanelTheme(host, hass) {
  if (!host) return false;
  const dark = isDarkTheme(hass, host);
  const themeName = hass?.themes?.theme || "";
  const prev = host.getAttribute("data-theme-key") || "";
  const next = `${themeName}|${dark ? "dark" : "light"}`;
  host.toggleAttribute("data-dark", dark);
  host.style.colorScheme = dark ? "dark" : "light";
  host.setAttribute("data-theme-key", next);
  return prev !== next;
}

/** Convert #rgb/#rrggbb/#rrggbbaa or rgb(a) into rgba(..., alpha). */
export function withAlpha(color, alpha) {
  const a = Math.max(0, Math.min(1, Number(alpha)));
  if (color == null || color === "") return `rgba(128, 128, 128, ${a})`;
  const c = String(color).trim();
  const rgbaMatch = c.match(/^rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)(?:\s*,\s*([0-9.]+))?\s*\)$/i);
  if (rgbaMatch) {
    return `rgba(${rgbaMatch[1]}, ${rgbaMatch[2]}, ${rgbaMatch[3]}, ${a})`;
  }
  if (c.startsWith("#")) {
    let h = c.slice(1);
    if (h.length === 3 || h.length === 4) {
      h = h
        .slice(0, 3)
        .split("")
        .map((ch) => ch + ch)
        .join("");
    } else if (h.length === 8) {
      h = h.slice(0, 6);
    }
    if (h.length === 6 && /^[0-9a-fA-F]+$/.test(h)) {
      const r = parseInt(h.slice(0, 2), 16);
      const g = parseInt(h.slice(2, 4), 16);
      const b = parseInt(h.slice(4, 6), 16);
      return `rgba(${r}, ${g}, ${b}, ${a})`;
    }
  }
  // Unparsed theme token — browsers ignore invalid fills; prefer a neutral.
  return `rgba(128, 128, 128, ${a})`;
}

/** Axis/label/surface colors from the active HA theme. */
export function chromeColors(el = null) {
  const root = el || document.documentElement;
  return {
    text: cssVar("--primary-text-color", "#212121", root),
    muted: cssVar("--secondary-text-color", "#727272", root),
    disabled: cssVar("--disabled-text-color", "#bdbdbd", root),
    grid: cssVar("--divider-color", "rgba(0, 0, 0, 0.12)", root),
    surface: cssVar(
      "--card-background-color",
      cssVar("--ha-card-background", cssVar("--primary-background-color", "#fff", root), root),
      root
    ),
    page: cssVar("--primary-background-color", "#fafafa", root),
    secondarySurface: cssVar("--secondary-background-color", "transparent", root),
    primary: cssVar("--primary-color", "#03a9f4", root),
    bg: "transparent",
  };
}

/** Series/status palette — HA semantic tokens with readable fallbacks. */
export function seriesColors(el = null) {
  const root = el || document.documentElement;
  return {
    kwh: cssVar("--pge-series-kwh", cssVar("--info-color", cssVar("--primary-color", "#2a78d6", root), root), root),
    export: cssVar(
      "--pge-series-export",
      cssVar("--purple-color", cssVar("--accent-color", "#7b61ff", root), root),
      root
    ),
    cost: cssVar(
      "--pge-series-cost",
      cssVar("--accent-color", cssVar("--warning-color", "#eb6834", root), root),
      root
    ),
    payment: cssVar("--pge-series-payment", cssVar("--success-color", "#1baf7a", root), root),
    savings: cssVar("--pge-series-savings", cssVar("--success-color", "#008300", root), root),
    tempCold: cssVar("--pge-temp-cold", cssVar("--info-color", cssVar("--primary-color", "#2a78d6", root), root), root),
    tempHot: cssVar("--pge-temp-hot", cssVar("--error-color", "#e34948", root), root),
    good: cssVar("--pge-status-good", cssVar("--success-color", "#1baf7a", root), root),
    warn: cssVar("--pge-status-warn", cssVar("--warning-color", "#eb6834", root), root),
    critical: cssVar("--pge-status-critical", cssVar("--error-color", "#e34948", root), root),
  };
}

/** Shared ECharts tooltip chrome that follows the active theme. */
export function tooltipTheme(el = null) {
  const t = chromeColors(el);
  return {
    backgroundColor: t.surface,
    borderColor: t.grid,
    textStyle: { color: t.text },
  };
}
