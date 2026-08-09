import { Suspense } from 'react';
import BestOpportunity from '@/components/BestOpportunity';
import AltcoinDiscoveryWorkspace from '@/components/AltcoinDiscoveryWorkspace';

export default function AltcoinDiscoveryPage() {
  return (
    <>
      <div className="mx-auto w-full max-w-shell px-5 pt-6 md:px-8">
        {/* The crowding edge fires on eight majors; discovery below scans a much
            wider, unvalidated universe. Leading with the validated one keeps the
            page honest about which part has evidence behind it. */}
        <Suspense fallback={<div className="mb-6 h-28 rounded-xl border-l-4 border-stone-200 bg-stone-50" />}>
          <BestOpportunity
            domain="altcoin"
            title={{ zh: '山寨币今天该看哪一个', en: 'Which coin to look at today' }}
          />
        </Suspense>
      </div>
      <AltcoinDiscoveryWorkspace />
    </>
  );
}
