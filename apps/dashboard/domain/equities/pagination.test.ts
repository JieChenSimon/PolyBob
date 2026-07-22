import { describe, expect, it } from 'vitest';

import {
  buildBatchQuoteSymbols,
  paginateEquities,
} from './pagination';

describe('equity pagination', () => {
  const observations = Array.from({ length: 75 }, (_, index) => ({
    symbol: `SYM${index + 1}`,
  }));

  it('returns at most 30 visible rows and clamps invalid pages', () => {
    expect(paginateEquities(observations, 1)).toMatchObject({
      page: 1,
      totalPages: 3,
      totalItems: 75,
    });
    expect(paginateEquities(observations, 1).items).toHaveLength(30);
    expect(paginateEquities(observations, 99)).toMatchObject({
      page: 3,
      items: observations.slice(60),
    });
    expect(paginateEquities([], 4)).toMatchObject({
      page: 1,
      totalPages: 1,
      totalItems: 0,
      items: [],
    });
  });

  it('quotes the visible page, selected symbol, and favorites without duplicates', () => {
    const symbols = buildBatchQuoteSymbols(
      observations.slice(30, 60),
      'SYM75',
      ['SYM2', 'SYM31', 'SYM75'],
    ).split(',');

    expect(symbols).toHaveLength(32);
    expect(symbols.slice(0, 30)).toEqual(observations.slice(30, 60).map((item) => item.symbol));
    expect(symbols).toEqual(expect.arrayContaining(['SYM2', 'SYM31', 'SYM75']));
  });
});
