import JournalWorkspace from '@/components/JournalWorkspace';
import SectionIntro from '@/components/SectionIntro';

export default function JournalPage() {
  return (
    <>
      <SectionIntro
        eyebrow={{ zh: '核心路径', en: 'Core Path' }}
        title={{ zh: '交易日志', en: 'Trade Journal' }}
        description={{
          zh: '记分牌上的胜率来自历史研究；这里是你自己交出来的。没有成交记录就没有实测胜率,北极星「持续提高胜率」也就无从验证。',
          en: 'The scoreboard reports a historical study; this records what you actually did. Without fills and exits there is no measured win rate, and the north star cannot be checked.',
        }}
      />
      <JournalWorkspace />
    </>
  );
}
