import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { api } from './api';
import type {
  CloseReason,
  InboxAlert,
  InboxSummary,
  KidCalendarResponse,
  KidDetail,
  Site,
  WatchlistEntry,
} from './types';

const keyIncludesClosed = (key: QueryKey): boolean => key.length >= 4 && key[3] === 'with-closed';

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
          (e) => e.enrollment_id !== enrollmentId && e.from_enrollment_id !== enrollmentId,
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

// ---------------------------------------------------------------------------
// Phase 6 Task 2 — kid + watchlist + site mutation hooks
// ---------------------------------------------------------------------------

interface CreateKidInput {
  name: string;
  dob: string;
  interests?: string[];
  school_weekdays?: string[];
  school_time_start?: string | null;
  school_time_end?: string | null;
  school_year_ranges?: { start: string; end: string }[];
  school_holidays?: string[];
  max_distance_mi?: number | null;
  alert_score_threshold?: number;
  alert_on?: Record<string, boolean>;
  notes?: string | null;
}

export function useCreateKid() {
  const qc = useQueryClient();
  return useMutation<KidDetail, Error, CreateKidInput>({
    mutationFn: (input) => api.post<KidDetail>('/api/kids', input),
    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: ['kids'] });
    },
  });
}

interface UpdateKidInput {
  id: number;
  patch: Partial<CreateKidInput> & { active?: boolean };
}

export function useUpdateKid() {
  const qc = useQueryClient();
  type Ctx = { snapshot: KidDetail | undefined };
  return useMutation<KidDetail, Error, UpdateKidInput, Ctx>({
    mutationFn: ({ id, patch }) => api.patch<KidDetail>(`/api/kids/${id}`, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: ['kids', id] });
      const snapshot = qc.getQueryData<KidDetail>(['kids', id]);
      if (snapshot) {
        qc.setQueryData<KidDetail>(['kids', id], { ...snapshot, ...patch });
      }
      return { snapshot };
    },
    onError: (_err, { id }, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['kids', id], ctx.snapshot);
    },
    onSettled: async (_d, _e, { id }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['kids'] }),
        qc.invalidateQueries({ queryKey: ['kids', id] }),
        qc.invalidateQueries({ queryKey: ['matches'] }),
      ]);
    },
  });
}

interface CreateWatchlistEntryInput {
  kidId: number;
  pattern: string;
  priority?: 'low' | 'normal' | 'high';
  site_id?: number | null;
  ignore_hard_gates?: boolean;
  notes?: string | null;
}

export function useCreateWatchlistEntry() {
  const qc = useQueryClient();
  return useMutation<WatchlistEntry, Error, CreateWatchlistEntryInput>({
    mutationFn: ({ kidId, ...body }) =>
      api.post<WatchlistEntry>(`/api/kids/${kidId}/watchlist`, body),
    onSettled: async (_d, _e, { kidId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['kids', kidId, 'watchlist'] }),
        qc.invalidateQueries({ queryKey: ['matches'] }),
      ]);
    },
  });
}

interface UpdateWatchlistEntryInput {
  kidId: number;
  entryId: number;
  patch: Partial<Omit<WatchlistEntry, 'id' | 'kid_id' | 'created_at'>>;
}

export function useUpdateWatchlistEntry() {
  const qc = useQueryClient();
  type Ctx = { snapshot: WatchlistEntry[] | undefined };
  return useMutation<WatchlistEntry, Error, UpdateWatchlistEntryInput, Ctx>({
    mutationFn: ({ entryId, patch }) =>
      api.patch<WatchlistEntry>(`/api/watchlist/${entryId}`, patch),
    onMutate: async ({ kidId, entryId, patch }) => {
      const key = ['kids', kidId, 'watchlist'];
      await qc.cancelQueries({ queryKey: key });
      const snapshot = qc.getQueryData<WatchlistEntry[]>(key);
      if (snapshot) {
        qc.setQueryData<WatchlistEntry[]>(
          key,
          snapshot.map((e) => (e.id === entryId ? { ...e, ...patch } : e)),
        );
      }
      return { snapshot };
    },
    onError: (_err, { kidId }, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['kids', kidId, 'watchlist'], ctx.snapshot);
    },
    onSettled: async (_d, _e, { kidId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['kids', kidId, 'watchlist'] }),
        qc.invalidateQueries({ queryKey: ['matches'] }),
      ]);
    },
  });
}

interface DeleteWatchlistEntryInput {
  kidId: number;
  entryId: number;
}

export function useDeleteWatchlistEntry() {
  const qc = useQueryClient();
  type Ctx = { snapshot: WatchlistEntry[] | undefined };
  return useMutation<unknown, Error, DeleteWatchlistEntryInput, Ctx>({
    mutationFn: ({ entryId }) => api.delete(`/api/watchlist/${entryId}`),
    onMutate: async ({ kidId, entryId }) => {
      const key = ['kids', kidId, 'watchlist'];
      await qc.cancelQueries({ queryKey: key });
      const snapshot = qc.getQueryData<WatchlistEntry[]>(key);
      if (snapshot) {
        qc.setQueryData<WatchlistEntry[]>(
          key,
          snapshot.filter((e) => e.id !== entryId),
        );
      }
      return { snapshot };
    },
    onError: (_err, { kidId }, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['kids', kidId, 'watchlist'], ctx.snapshot);
    },
    onSettled: async (_d, _e, { kidId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['kids', kidId, 'watchlist'] }),
        qc.invalidateQueries({ queryKey: ['matches'] }),
      ]);
    },
  });
}

export function useCrawlNow() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { siteId: number }>({
    mutationFn: ({ siteId }) => api.post(`/api/sites/${siteId}/crawl-now`),
    onSettled: async (_d, _e, { siteId }) => {
      await qc.invalidateQueries({ queryKey: ['sites', siteId] });
    },
  });
}

interface ToggleSiteActiveInput {
  siteId: number;
  active: boolean;
}

export function useToggleSiteActive() {
  const qc = useQueryClient();
  type Ctx = { snapshot: Site | undefined };
  return useMutation<Site, Error, ToggleSiteActiveInput, Ctx>({
    mutationFn: ({ siteId, active }) => api.patch<Site>(`/api/sites/${siteId}`, { active }),
    onMutate: async ({ siteId, active }) => {
      await qc.cancelQueries({ queryKey: ['sites', siteId] });
      const snapshot = qc.getQueryData<Site>(['sites', siteId]);
      if (snapshot) {
        qc.setQueryData<Site>(['sites', siteId], { ...snapshot, active });
      }
      return { snapshot };
    },
    onError: (_err, { siteId }, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(['sites', siteId], ctx.snapshot);
    },
    onSettled: async (_d, _e, { siteId }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['sites'] }),
        qc.invalidateQueries({ queryKey: ['sites', siteId] }),
      ]);
    },
  });
}
