'use client';

import { useEffect, useState } from 'react';

export type Language = 'zh' | 'en';

const storageKey = 'polybob-language';
const languageEvent = 'polybob-language-change';

function readLanguage(): Language {
  if (typeof window === 'undefined') {
    return 'zh';
  }

  return window.localStorage.getItem(storageKey) === 'en' ? 'en' : 'zh';
}

export function useLanguage() {
  const [language, setLanguageState] = useState<Language>('zh');

  useEffect(() => {
    setLanguageState(readLanguage());

    const handleLanguageChange = () => setLanguageState(readLanguage());
    window.addEventListener(languageEvent, handleLanguageChange);
    window.addEventListener('storage', handleLanguageChange);

    return () => {
      window.removeEventListener(languageEvent, handleLanguageChange);
      window.removeEventListener('storage', handleLanguageChange);
    };
  }, []);

  const setLanguage = (nextLanguage: Language) => {
    window.localStorage.setItem(storageKey, nextLanguage);
    setLanguageState(nextLanguage);
    window.dispatchEvent(new Event(languageEvent));
  };

  return { language, setLanguage };
}

