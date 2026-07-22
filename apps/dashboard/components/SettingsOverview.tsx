'use client';

import { useLanguage } from '@/lib/i18n';

export default function SettingsOverview() {
  const { language } = useLanguage();
  const items = language === 'zh'
    ? [
        {
          title: '数据源',
          description: 'Polymarket 实时采集为主，美股观察使用免费行情源补充报价和均线。',
        },
        {
          title: '运行模式',
          description: '核心路径只服务个人研究、判断、paper 执行与复盘。',
        },
        {
          title: '实验边界',
          description: 'BTC 自动交易和 RL 模块留在 lab，默认不进入首页判断流。',
        },
        {
          title: '策略配置',
          description: '策略模板从 YAML 暴露为只读目录，运行实例单独跟踪。',
        },
      ]
    : [
        {
          title: 'Data Sources',
          description: 'Polymarket realtime ingestion is primary; US equities add free quotes and moving averages.',
        },
        {
          title: 'Operating Model',
          description: 'The core path serves personal research, judgment, paper execution, and review.',
        },
        {
          title: 'Lab Boundary',
          description: 'BTC auto trader and RL modules stay in lab and out of the daily brief by default.',
        },
        {
          title: 'Strategy Configuration',
          description: 'YAML templates are exposed read-only; runtime instances are tracked separately.',
        },
      ];

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div key={item.title} className="panel p-5">
          <div className="text-base font-bold tracking-[-0.03em] text-stone-900">{item.title}</div>
          <p className="mt-2 text-sm leading-6 text-stone-600">{item.description}</p>
        </div>
      ))}
    </div>
  );
}
