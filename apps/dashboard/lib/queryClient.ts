import { QueryClient, type DefaultOptions } from '@tanstack/react-query';

export const workbenchQueryDefaults: DefaultOptions = {
  queries: {
    gcTime: 5 * 60_000,
    refetchIntervalInBackground: false,
    refetchOnReconnect: true,
    refetchOnWindowFocus: true,
    retry: 1,
    staleTime: 5_000,
  },
  mutations: {
    retry: 0,
  },
};

export function createWorkbenchQueryClient() {
  return new QueryClient({ defaultOptions: workbenchQueryDefaults });
}
