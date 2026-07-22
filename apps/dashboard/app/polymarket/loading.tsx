export default function PolymarketLoading() {
  return (
    <main className="mx-auto mt-6 grid min-h-[620px] w-full max-w-shell gap-5 px-5 pb-10 md:mt-8 md:px-8" aria-busy="true">
      <section className="panel h-24 animate-pulse bg-stone-100" />
      <section className="h-[500px] border border-stone-200 bg-white" />
    </main>
  );
}
