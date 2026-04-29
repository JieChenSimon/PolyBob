import SectionIntro from '@/components/SectionIntro';
import SettingsOverview from '@/components/SettingsOverview';

export default function SettingsPage() {
  return (
    <>
      <SectionIntro
        eyebrow="Workbench Settings"
        title="Settings"
        description="这里记录个人工作台的运行边界：核心路径保持稳定，lab 模块显式开启，后续再补数据源、账户、环境和密钥管理。"
      />

      <main className="mx-auto mt-6 w-full max-w-[1380px] px-5 pb-10 md:mt-8 md:px-8">
        <SettingsOverview />
      </main>
    </>
  );
}
