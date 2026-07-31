import VerdictBanner from '@/components/VerdictBanner';
import AltcoinDiscoveryWorkspace from '@/components/AltcoinDiscoveryWorkspace';
import WisdomSignalPanel from '@/components/WisdomSignalPanel';

export default function AltcoinDiscoveryPage() {
  return (
    <>
      <div className="mx-auto w-full max-w-shell px-5 pt-6 md:px-8">
        <VerdictBanner symbol="SOL-USDT" domain="altcoin" />
      </div>
      <AltcoinDiscoveryWorkspace />
      <div className="mx-auto w-full max-w-shell px-5 pb-10 md:px-8">
        <WisdomSignalPanel symbol="SOL-USDT" domain="altcoin" />
      </div>
    </>
  );
}
