export default function AltcoinDiscoveryLoading() {
  return (
    <main className="panel mx-auto mt-5 min-h-[720px] w-[calc(100%-24px)] max-w-shell overflow-hidden md:mt-6 md:w-full" aria-busy="true">
      <header className="h-24 animate-pulse border-b border-stone-200 bg-stone-50" />
      <section className="grid h-24 grid-cols-2 border-b border-stone-200 lg:grid-cols-6">
        {Array.from({ length: 6 }, (_, index) => <div key={index} className="border-r border-stone-200 bg-white" />)}
      </section>
      <section className="h-[560px] bg-white" />
    </main>
  );
}
