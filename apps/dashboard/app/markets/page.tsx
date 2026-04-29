import MarketsWorkspace from '@/components/MarketsWorkspace';
import SectionIntro from '@/components/SectionIntro';

export default function MarketsPage() {
  return (
    <>
      <SectionIntro
        eyebrow="Market Intelligence"
        title="Markets"
        description="市场观察页只负责 watchlist、盘口、特征和异常，不再承担策略控制和执行入口。"
      />

      <main className="mx-auto mt-6 w-full max-w-[1380px] px-5 pb-10 md:mt-8 md:px-8">
        <MarketsWorkspace />
      </main>
    </>
  );
}
