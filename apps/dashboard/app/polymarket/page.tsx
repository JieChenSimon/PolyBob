import BtcCalibrationPanel from '@/components/BtcCalibrationPanel';
import BtcFiveMinuteWorkbenchClient from '@/components/BtcFiveMinuteWorkbenchClient';
import VerdictBanner from '@/components/VerdictBanner';
import AssetTerminalFrame from '@/components/AssetTerminalFrame';
import { Suspense } from 'react';

export default function PolymarketPage() {
  return (
    <>
      <main className="asset-terminal-page">
        <Suspense fallback={<div className="terminal-loading" />}>
        <AssetTerminalFrame asset="PREDICTION MARKET" title="BTC 5m Up / Down" subtitle="Five-minute binary market context, calibration and real CLOB state; not spot BTC." symbol="BTC-5M" source="Polymarket CLOB" links={[{ href: '/btc-5m', label: 'BTC 5m', meta: 'Up / Down binary' }, { href: '/markets', label: 'Prediction Markets', meta: 'Event instruments' }]}>
        <div className="grid gap-5">
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
            zh: '本页是 5 分钟二元合约，不是现货。现货日线趋势、量价与事件型优势不适用于本合约；当前 5m 研究状态以校准台返回的最新证据为准，未通过门禁时不会生成交易结论。',
            en: 'This page trades a five-minute binary, not spot. Spot daily trend, volume and event edges do not apply here; the calibration panel is the source of truth for the latest 5m research state, and no trade conclusion is generated before the gate clears.',
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
        </div>
        </AssetTerminalFrame>
        </Suspense>
      </main>
    </>
  );
}
