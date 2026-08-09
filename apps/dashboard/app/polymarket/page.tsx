import BtcCalibrationPanel from '@/components/BtcCalibrationPanel';
import BtcFiveMinuteWorkbenchClient from '@/components/BtcFiveMinuteWorkbenchClient';
import VerdictBanner from '@/components/VerdictBanner';
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
        {/*
          This page trades a five-minute Polymarket binary, not spot BTC. The
          banner used to judge BTC-USDT daily bars here — a different
          instrument on a different timeframe with a different payoff — so it
          now says the framework does not apply rather than lending a
          borrowed conclusion this page's authority.
        */}
        <VerdictBanner
          symbol="BTC-USDT"
          domain="altcoin"
          notApplicable={{
            zh: '本页是 5 分钟二元合约,不是现货。投资准则判定基于日线趋势、量价与事件型优势,时间尺度和赔付结构都对不上——BTC-5m 目前也没有任何通过门禁的优势(t=3.45 < 门槛 3.77)。这里不拿现货日线的结论冒充本标的的判定。',
            en: 'This page trades a five-minute binary, not spot. The verdict framework reads daily trend, volume and event edges — a different timeframe and payoff — and BTC-5m has no gate-approved edge either (t=3.45 vs a 3.77 hurdle). A spot daily conclusion will not be presented as this instrument’s verdict.',
          }}
        />
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

        {/* The calibration panel goes above the workbench: while the edge is
            ungated, growing n from 95 towards 200 is the module's actual job,
            and the order-book view below is the instrument for doing it rather
            than a desk to trade from. */}
        <BtcCalibrationPanel />
        <BtcFiveMinuteWorkbenchClient />
        {/* WisdomSignalPanel used to sit here with symbol="BTC-USDT". The banner
            at the top of this page explains that a daily-bar verdict does not
            describe a five-minute binary — and then a panel of BTC *spot* daily
            buy signals, stops and position sizes appeared underneath it, which
            cancelled the disclaimer it had just made. Spot BTC has its own page. */}
      </main>
    </>
  );
}
