'use client';

import { Language, useLanguage } from '@/lib/i18n';

type LocalizedText = string | Record<Language, string>;

interface SectionIntroProps {
  eyebrow: LocalizedText;
  title: LocalizedText;
  description: LocalizedText;
}

function localize(value: LocalizedText, language: Language) {
  return typeof value === 'string' ? value : value[language];
}

/**
 * Compact page header: eyebrow, page title, and the page's purpose as a
 * one-line subtitle. Shared by every route for consistent hierarchy.
 */
export default function SectionIntro({
  eyebrow,
  title,
  description,
}: SectionIntroProps) {
  const { language } = useLanguage();

  return (
    <header className="mx-auto w-full max-w-shell px-5 pt-6 md:px-8 md:pt-8">
      <div className="eyebrow">{localize(eyebrow, language)}</div>
      <h1 className="mt-1 text-2xl font-bold tracking-[-0.03em] text-stone-900 md:text-3xl">
        {localize(title, language)}
      </h1>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-stone-500">
        {localize(description, language)}
      </p>
    </header>
  );
}
