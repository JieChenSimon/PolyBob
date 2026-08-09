import { Suspense } from 'react';
import InstrumentDetail from '@/components/InstrumentDetail';

/**
 * One instrument, one route. The verdict is an instrument-level judgement, so it
 * lives on the instrument's own page instead of at the top of the A-share tab —
 * where it used to render for whichever symbol happened to be the default.
 */
export default async function AshareInstrumentPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  return (
    <Suspense fallback={<div className="mx-auto mt-6 h-32 w-full max-w-shell px-5 md:px-8" />}>
      <InstrumentDetail symbol={decodeURIComponent(symbol).toUpperCase()} domain="a_share" />
    </Suspense>
  );
}
