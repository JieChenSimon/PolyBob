import AltcoinDiscoveryWorkspace from '@/components/AltcoinDiscoveryWorkspace';
import WisdomSignalPanel from '@/components/WisdomSignalPanel';

export default function AltcoinDiscoveryPage() {
  return (
    <>
      <AltcoinDiscoveryWorkspace />
      <div className="mx-auto w-full max-w-shell px-5 pb-10 md:px-8">
        <WisdomSignalPanel symbol="SOL-USDT" domain="altcoin" />
      </div>
    </>
  );
}
