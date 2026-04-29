interface SectionIntroProps {
  eyebrow: string;
  title: string;
  description: string;
}

export default function SectionIntro({
  eyebrow,
  title,
  description,
}: SectionIntroProps) {
  return (
    <section className="mx-auto w-full max-w-[1380px] px-5 pt-6 md:px-8 md:pt-8">
      <div className="panel overflow-hidden px-6 py-6 md:px-8 md:py-8">
        <span className="eyebrow">{eyebrow}</span>
        <h1 className="mt-4 text-4xl font-bold tracking-[-0.06em] text-stone-900 md:text-5xl">
          {title}
        </h1>
        <p className="mt-4 max-w-3xl text-sm leading-6 text-stone-600 md:text-base">
          {description}
        </p>
      </div>
    </section>
  );
}
