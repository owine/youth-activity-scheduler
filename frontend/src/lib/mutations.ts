import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { api } from './api';
import type { CloseReason, InboxAlert, InboxSummary } from './types';

const keyIncludesClosed = (key: QueryKey): boolean =>
  key.length >= 4 && key[3] === 'with-closed';

type Snapshot = ReadonlyArray<readonly [QueryKey, InboxSummary | undefined]>;

interface CloseInput {
  alertId: number;
  reason: CloseReason;
}

export function useCloseAlert() {
  const qc = useQueryClient();
  return useMutation<InboxAlert, Error, CloseInput, { snapshots: Snapshot }>({
    mutationFn: ({ alertId, reason }) =>
      api.post<InboxAlert>(`/api/alerts/${alertId}/close`, { reason }),

    onMutate: async ({ alertId, reason }) => {
      await qc.cancelQueries({ queryKey: ['inbox', 'summary'] });
      const snapshots = qc.getQueriesData<InboxSummary>({ queryKey: ['inbox', 'summary'] });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const closedAt = new Date().toISOString();
        const updated = data.alerts.map((a) =>
          a.id === alertId ? { ...a, closed_at: closedAt, close_reason: reason } : a,
        );
        const filtered = keyIncludesClosed(key)
          ? updated
          : updated.filter((a) => a.closed_at == null);
        qc.setQueryData<InboxSummary>(key, { ...data, alerts: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: ['inbox', 'summary'] });
    },
  });
}

export function useReopenAlert() {
  const qc = useQueryClient();
  return useMutation<InboxAlert, Error, { alertId: number }, { snapshots: Snapshot }>({
    mutationFn: ({ alertId }) => api.post<InboxAlert>(`/api/alerts/${alertId}/reopen`),

    onMutate: async ({ alertId }) => {
      await qc.cancelQueries({ queryKey: ['inbox', 'summary'] });
      const snapshots = qc.getQueriesData<InboxSummary>({ queryKey: ['inbox', 'summary'] });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const updated = data.alerts.map((a) =>
          a.id === alertId ? { ...a, closed_at: null, close_reason: null } : a,
        );
        qc.setQueryData<InboxSummary>(key, { ...data, alerts: updated });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: ['inbox', 'summary'] });
    },
  });
}
