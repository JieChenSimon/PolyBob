'use client';

import { QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { createWorkbenchQueryClient } from './queryClient';

export function WorkbenchQueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createWorkbenchQueryClient);
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
