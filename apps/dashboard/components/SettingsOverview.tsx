export default function SettingsOverview() {
  const items = [
    {
      title: 'Data Sources',
      description: 'Polymarket realtime ingestor is the current primary market-data path.',
    },
    {
      title: 'Operating Model',
      description: 'PolyBob is scoped as a personal market workbench, not a public SaaS product.',
    },
    {
      title: 'Lab Boundary',
      description: 'BTC auto trader and RL modules stay in lab. Enable them explicitly instead of loading them in the core path.',
    },
    {
      title: 'Strategy Configuration',
      description: 'Strategy configs currently live in YAML files and are exposed read-only in phase one.',
    },
  ];

  return (
    <div className="grid gap-6 md:grid-cols-3">
      {items.map((item) => (
        <div key={item.title} className="panel p-6">
          <div className="text-lg font-bold tracking-[-0.04em] text-stone-900">{item.title}</div>
          <p className="mt-3 text-sm leading-6 text-stone-600">{item.description}</p>
        </div>
      ))}
    </div>
  );
}
