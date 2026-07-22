/**
 * Shared number formatting for the dashboard.
 *
 * Every numeric surface should use these helpers so prices, percentages,
 * and quantities render consistently (and honestly: missing data is
 * always "--", never a fake zero).
 */

const EMPTY = '--';

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Fixed-digit number, or "--" when the value is missing. */
export function formatNumber(value: number | null | undefined, digits = 2): string {
  return isNumber(value) ? value.toFixed(digits) : EMPTY;
}

/** Price with 2-4 decimals depending on magnitude. */
export function formatPrice(value: number | null | undefined, digits = 4): string {
  return isNumber(value) ? value.toFixed(digits) : EMPTY;
}

/** "+1.23" / "-0.45" with explicit sign, or "--". */
export function formatSigned(value: number | null | undefined, digits = 2): string {
  if (!isNumber(value)) {
    return EMPTY;
  }
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;
}

/** "12.34%" from a 0-100 value, or "--". */
export function formatPercent(value: number | null | undefined, digits = 2): string {
  return isNumber(value) ? `${value.toFixed(digits)}%` : EMPTY;
}

/** "12.34%" from a 0-1 ratio, or "--". */
export function formatRatioAsPercent(value: number | null | undefined, digits = 2): string {
  return isNumber(value) ? `${(value * 100).toFixed(digits)}%` : EMPTY;
}

/** Compact notation: 1.2K, 3.4M ... */
export function formatCompact(value: number | null | undefined, digits = 1): string {
  if (!isNumber(value)) {
    return EMPTY;
  }
  return new Intl.NumberFormat('en', {
    notation: 'compact',
    maximumFractionDigits: digits,
  }).format(value);
}

/** "$12,345" (whole dollars). */
export function formatUsd(value: number | null | undefined, digits = 0): string {
  if (!isNumber(value)) {
    return EMPTY;
  }
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: digits })}`;
}

/**
 * Semantic text color for a signed value: green up, red down,
 * neutral gray for zero/unknown. Matches the design tokens.
 */
export function signToneClass(value: number | null | undefined): string {
  if (!isNumber(value) || value === 0) {
    return 'text-stone-500';
  }
  return value > 0 ? 'text-emerald-600' : 'text-rose-600';
}
