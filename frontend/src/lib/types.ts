// Mirrors Pydantic schemas in src/yas/web/routes/. Hand-maintained.
// When backend types change, update both sides; tests/integration will
// fail loudly if shapes drift.

export type CloseReason = 'acknowledged' | 'dismissed';

export type AlertType =
  | 'watchlist_hit'
  | 'new_match'
  | 'reg_opens_24h'
  | 'reg_opens_1h'
  | 'reg_opens_now'
  | 'schedule_posted'
  | 'crawl_failed'
  | 'digest'
  | 'site_stagnant'
  | 'no_matches_for_kid'
  | 'push_cap';

// Mirrors src/yas/web/routes/matches_schemas.py::OfferingSummary AFTER Task 1's
// extension. Date/datetime are ISO strings over the wire.
export interface OfferingSummary {
  id: number;
  name: string;
  program_type: string;
  age_min: number | null;
  age_max: number | null;
  start_date: string | null;
  end_date: string | null;
  days_of_week: string[];
  time_start: string | null;
  time_end: string | null;
  price_cents: number | null;
  registration_url: string | null;
  site_id: number;
  // Added in Task 1:
  site_name: string;
  registration_opens_at: string | null;
}

export interface Match {
  kid_id: number;
  offering_id: number;
  score: number;
  reasons: Record<string, unknown>;
  computed_at: string;
  offering: OfferingSummary;
}

export interface InboxAlert {
  id: number;
  type: AlertType | string;
  kid_id: number | null;
  kid_name: string | null;
  offering_id: number | null;
  site_id: number | null;
  channels: string[];
  scheduled_for: string;
  sent_at: string | null;
  skipped: boolean;
  dedup_key: string;
  payload_json: Record<string, unknown>;
  summary_text: string;
  closed_at: string | null;
  close_reason: CloseReason | null;
}

export interface InboxKidMatchCount {
  kid_id: number;
  kid_name: string;
  total_new: number;
  opening_soon_count: number;
}

export interface InboxSiteActivity {
  refreshed_count: number;
  posted_new_count: number;
  stagnant_count: number;
}

export interface InboxSummary {
  window_start: string;
  window_end: string;
  alerts: InboxAlert[];
  new_matches_by_kid: InboxKidMatchCount[];
  site_activity: InboxSiteActivity;
}

export interface KidBrief {
  id: number;
  name: string;
  dob: string;
  interests: string[];
  active: boolean;
}

export interface WatchlistEntry {
  id: number;
  kid_id: number;
  site_id: number | null;
  pattern: string;
  priority: string;
  notes: string | null;
  active: boolean;
  ignore_hard_gates: boolean;
}

export interface KidDetail extends KidBrief {
  watchlist: WatchlistEntry[];
  // ... add the other embedded arrays the UI uses (matches, enrollments)
}

export interface Page {
  id: number;
  url: string;
  kind: string;
  content_hash: string | null;
  last_fetched: string | null;
  next_check_at: string | null;
}

export interface Site {
  id: number;
  name: string;
  base_url: string;
  adapter: string;
  needs_browser: boolean;
  active: boolean;
  default_cadence_s: number;
  muted_until: string | null;
  pages: Page[];
}

export interface CrawlRun {
  id: number;
  site_id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  pages_fetched: number;
  changes_detected: number;
  llm_calls: number;
  llm_cost_usd: number;
  error_text: string | null;
}

export interface AlertRouting {
  type: AlertType | string;
  channels: string[];
  enabled: boolean;
}

export interface Household {
  id: number;
  home_location_id: number | null;
  home_address: string | null;
  home_location_name: string | null;
  default_max_distance_mi: number | null;
  digest_time: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  daily_llm_cost_cap_usd: number;
}
