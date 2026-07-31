import BtcFiveMinuteWorkbenchClient from '@/components/BtcFiveMinuteWorkbenchClient';
import WisdomSignalPanel from '@/components/WisdomSignalPanel';
import SectionIntro from '@/components/SectionIntro';

export default function PolymarketPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '真实盘口', en: 'Real Order Books' }}
        title={{ zh: 'Polymarket', en: 'Polymarket' }}
        description={{
          zh: '集中管理 Polymarket 模块；当前先接入 BTC 5 分钟涨跌盘口，后续模块继续放在这里。',
          en: 'A dedicated Polymarket workspace. The BTC five-minute Up/Down order-book module is the first module here.',
        }}
      />

      <main className="mx-auto mt-6 grid w-full max-w-shell gap-5 px-5 pb-10 md:mt-8 md:px-8">
        <section className="panel px-5 py-4">
          <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">
                BTC 5m Up/Down
              </div>
              <h2 className="mt-1 text-xl font-bold text-stone-950">
                BTC 5分钟涨跌盘口
              </h2>
            </div>
            <p className="max-w-2xl text-sm leading-6 text-stone-600 md:text-right">
              按 3 秒轮询真实 CLOB 盘口；没有真实数据时直接 no-trade，不补假盘口。
            </p>
          </div>
        </section>

        <BtcFiveMinuteWorkbenchClient />
        <WisdomSignalPanel symbol="BTC-USDT" domain="altcoin" />
      </main>
    </>
  );
}
