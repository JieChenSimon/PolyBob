'use client';

import { useEffect } from 'react';
import { useLanguage } from '@/lib/i18n';

/** Keep the document language aligned with the user's persisted workbench locale. */
export default function LanguageDocumentSync() {
  const { language } = useLanguage();

  useEffect(() => {
    document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  }, [language]);

  return null;
}
