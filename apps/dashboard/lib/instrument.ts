/**
 * Where an instrument's own page lives.
 *
 * Each instrument has a real route rather than a query parameter on a category
 * page. The distinction matters because the two surfaces answer different
 * questions: a category tab says *which* instrument to look at, an instrument
 * page says what to do about that one. Putting the verdict on the category page
 * conflated them — it rendered an instrument-level judgement in the slot where a
 * selection belongs, for whichever symbol happened to be default.
 */
export type InstrumentDomain = 'us_equity' | 'a_share' | 'altcoin' | string;

export function instrumentHref(domain: InstrumentDomain, symbol: string): string {
  const encoded = encodeURIComponent(symbol.trim().toUpperCase());
  if (domain === 'altcoin') return `/crypto/${encoded}`;
  if (domain === 'a_share') return `/markets/${encoded}`;
  return `/us-equities/${encoded}`;
}

/** A-share codes are six digits; everything else is treated as a US listing. */
export function domainForSymbol(symbol: string): InstrumentDomain {
  const clean = symbol.trim().toUpperCase();
  if (clean.endsWith('-USDT') || clean.endsWith('-USD')) return 'altcoin';
  if (/^\d{6}/.test(clean.split('.')[0])) return 'a_share';
  return 'us_equity';
}
