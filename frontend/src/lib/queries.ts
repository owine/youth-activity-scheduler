import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import type {
  AlertRouting,
  CrawlRun,
  Household,
  InboxSummary,
  KidBrief,
  KidCalendarResponse,
  KidDetail,
  Match,
  Site,
} from './types';

const minus = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
};

export function useInboxSummary(opts?: { days?: number; includeClosed?: boolean }) {
  const days = opts?.days ?? 7;
  const includeClosed = opts?.includeClosed ?? false;
  return useQuery({
    queryKey: ['inbox', 'summary', days, includeClosed ? 'with-closed' : 'open-only'],
    queryFn: () => {
      const since = minus(days);
      const until = new Date().toISOString();
      const url = `/api/inbox/summary?since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}${
        includeClosed ? '&include_closed=true' : ''
      }`;
      return api.get<InboxSummary>(url);
    },
    refetchInterval: 60_000,
  });
}

export function useKids() {
  return useQuery({
    queryKey: ['kids'],
    queryFn: () => api.get<KidBrief[]>('/api/kids'),
  });
}

export function useKid(id: number) {
  return useQuery({
    queryKey: ['kids', id],
    queryFn: () => api.get<KidDetail>(`/api/kids/${id}`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useKidMatches(kidId: number) {
  return useQuery({
    queryKey: ['matches', kidId],
    queryFn: () => api.get<Match[]>(`/api/matches?kid_id=${kidId}&limit=200`),
    enabled: Number.isFinite(kidId) && kidId > 0,
  });
}

export function useAllMatches({ minScore, limit = 500 }: { minScore: number; limit?: number }) {
  return useQuery({
    queryKey: ['matches', 'all', { minScore, limit }],
    queryFn: () => api.get<Match[]>(`/api/matches?min_score=${minScore}&limit=${limit}`),
  });
}

export function useSites() {
  return useQuery({
    queryKey: ['sites'],
    queryFn: () => api.get<Site[]>('/api/sites'),
  });
}

export function useSite(id: number) {
  return useQuery({
    queryKey: ['sites', id],
    queryFn: () => api.get<Site>(`/api/sites/${id}`),
    enabled: Number.isFinite(id),
  });
}

export function useSiteCrawls(id: number, limit = 10) {
  return useQuery({
    queryKey: ['sites', id, 'crawls', limit],
    queryFn: () => api.get<CrawlRun[]>(`/api/sites/${id}/crawls?limit=${limit}`),
    enabled: Number.isFinite(id),
  });
}

export function useHousehold() {
  return useQuery({
    queryKey: ['household'],
    queryFn: () => api.get<Household>('/api/household'),
  });
}

export function useAlertRouting() {
  return useQuery({
    queryKey: ['alert_routing'],
    queryFn: () => api.get<AlertRouting[]>('/api/alert_routing'),
  });
}

export function useKidCalendar({
  kidId,
  from,
  to,
  includeMatches = false,
}: {
  kidId: number;
  from: string;
  to: string;
  includeMatches?: boolean;
}) {
  return useQuery({
    queryKey: ['kids', kidId, 'calendar', from, to, includeMatches ? 'with-matches' : 'no-matches'],
    queryFn: () =>
      api.get<KidCalendarResponse>(
        `/api/kids/${kidId}/calendar?from=${from}&to=${to}${includeMatches ? '&include_matches=true' : ''}`,
      ),
    enabled: Number.isFinite(kidId) && !!from && !!to,
  });
}
