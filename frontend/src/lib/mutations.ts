import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { api } from './api';
import type { CloseReason, InboxAlert, InboxSummary, KidCalendarResponse } from './types';

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

interface CancelEnrollmentInput {
  kidId: number;
  enrollmentId: number;
}

export function useCancelEnrollment() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, CancelEnrollmentInput, Ctx>({
    mutationFn: ({ enrollmentId }) =>
      api.patch(`/api/enrollments/${enrollmentId}`, { status: 'cancelled' }),

    onMutate: async ({ kidId, enrollmentId }) => {
      await qc.cancelQueries({ queryKey: ['kids', kidId, 'calendar'] });
      const snapshots = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids', kidId, 'calendar'],
      });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const filtered = data.events.filter(
          (e) =>
            e.enrollment_id !== enrollmentId &&
            e.from_enrollment_id !== enrollmentId,
        );
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async (_data, _err, { kidId }) => {
      await qc.invalidateQueries({ queryKey: ['kids', kidId, 'calendar'] });
    },
  });
}

interface EnrollOfferingInput {
  kidId: number;
  offeringId: number;
}

export function useEnrollOffering() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, EnrollOfferingInput, Ctx>({
    mutationFn: ({ kidId, offeringId }) =>
      api.post('/api/enrollments', {
        kid_id: kidId,
        offering_id: offeringId,
        status: 'enrolled',
      }),

    onMutate: async ({ kidId, offeringId }) => {
      await qc.cancelQueries({ queryKey: ['kids', kidId, 'calendar'] });
      const snapshots = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids', kidId, 'calendar'],
      });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const filtered = data.events.filter(
          (e) => !(e.kind === 'match' && e.offering_id === offeringId),
        );
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async (_data, _err, { kidId }) => {
      await qc.invalidateQueries({ queryKey: ['kids', kidId, 'calendar'] });
    },
  });
}

interface UpdateSiteMuteInput {
  siteId: number;
  mutedUntil: string | null;
}

export function useUpdateSiteMute() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, UpdateSiteMuteInput>({
    mutationFn: ({ siteId, mutedUntil }) =>
      api.patch(`/api/sites/${siteId}`, { muted_until: mutedUntil }),

    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ['sites'] });
    },

    onSettled: async (_d, _e, { siteId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['sites'] }),
        qc.invalidateQueries({ queryKey: ['sites', siteId] }),
        qc.invalidateQueries({ queryKey: ['kids'] }),
      ]);
    },
  });
}

interface UpdateOfferingMuteInput {
  offeringId: number;
  mutedUntil: string | null;
}

export function useUpdateOfferingMute() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, UpdateOfferingMuteInput, Ctx>({
    mutationFn: ({ offeringId, mutedUntil }) =>
      api.patch(`/api/offerings/${offeringId}`, { muted_until: mutedUntil }),

    onMutate: async ({ offeringId, mutedUntil }) => {
      // Always cancel to flush state; optimistic surgery only when muting.
      await qc.cancelQueries({ queryKey: ['kids'] });
      if (mutedUntil == null) return { snapshots: [] };

      await qc.cancelQueries({ queryKey: ['kids'] });
      const allKidsQueries = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids'],
      });
      const calendarSnapshots = allKidsQueries.filter(
        ([key]) => key.length >= 3 && key[2] === 'calendar',
      );

      for (const [key, data] of calendarSnapshots) {
        if (!data) continue;
        const filtered = data.events.filter(
          (e) => !(e.kind === 'match' && e.offering_id === offeringId),
        );
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots: calendarSnapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['matches'] }),
        qc.invalidateQueries({ queryKey: ['kids'] }),
      ]);
    },
  });
}

interface DeleteUnavailabilityInput {
  kidId: number;
  blockId: number;
}

export function useDeleteUnavailability() {
  const qc = useQueryClient();
  type Ctx = {
    snapshots: ReadonlyArray<readonly [QueryKey, KidCalendarResponse | undefined]>;
  };
  return useMutation<unknown, Error, DeleteUnavailabilityInput, Ctx>({
    mutationFn: ({ blockId }) => api.delete(`/api/unavailability/${blockId}`),

    onMutate: async ({ kidId, blockId }) => {
      await qc.cancelQueries({ queryKey: ['kids', kidId, 'calendar'] });
      const snapshots = qc.getQueriesData<KidCalendarResponse>({
        queryKey: ['kids', kidId, 'calendar'],
      });

      for (const [key, data] of snapshots) {
        if (!data) continue;
        const filtered = data.events.filter((e) => e.block_id !== blockId);
        qc.setQueryData<KidCalendarResponse>(key, { ...data, events: filtered });
      }
      return { snapshots };
    },

    onError: (_err, _vars, ctx) => {
      ctx?.snapshots.forEach(([key, data]) => qc.setQueryData(key, data));
    },

    onSettled: async (_data, _err, { kidId }) => {
      await qc.invalidateQueries({ queryKey: ['kids', kidId, 'calendar'] });
    },
  });
}
