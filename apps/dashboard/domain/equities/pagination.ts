export const equityPageSize = 30;

interface SymbolItem {
  symbol: string;
}

export function paginateEquities<T>(
  items: readonly T[],
  requestedPage: number,
  pageSize = equityPageSize,
) {
  const safePageSize = Math.max(1, Math.floor(pageSize));
  const totalPages = Math.max(1, Math.ceil(items.length / safePageSize));
  const normalizedPage = Number.isFinite(requestedPage) ? Math.floor(requestedPage) : 1;
  const page = Math.min(totalPages, Math.max(1, normalizedPage));
  const start = (page - 1) * safePageSize;

  return {
    items: items.slice(start, start + safePageSize),
    page,
    totalItems: items.length,
    totalPages,
  };
}

export function buildBatchQuoteSymbols(
  visibleItems: readonly SymbolItem[],
  selectedSymbol: string,
  favorites: readonly string[],
) {
  const symbols = new Set(visibleItems.map((item) => item.symbol));
  if (selectedSymbol) {
    symbols.add(selectedSymbol);
  }
  for (const symbol of favorites) {
    if (symbol) {
      symbols.add(symbol);
    }
  }
  return Array.from(symbols).join(',');
}
