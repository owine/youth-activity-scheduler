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
  muted_until: string | null;
  // Added in Task 2:
  location_lat: number | null;
  location_lon: number | null;
}

// Phase 7-2 types
export type SortKey = 'best_score' | 'soonest_start' | 'soonest_reg';

export type ChipKind = 'watchlist' | 'top_match' | 'opens_this_week' | 'near_home' | 'in_interests';

export interface Chip {
  kind: ChipKind;
  label: string; // emoji + text
  className: string; // Tailwind classes
}

export interface OfferingRow {
  offering: OfferingSummary;
  matches: Match[]; // sorted by score desc
}

export type RegTiming = 'any' | 'opens_this_week' | 'open_now' | 'closed';

export interface FilterState {
  // Primary
  selectedKidIds: number[];
  minScore: number;
  sort: SortKey;
  // Secondary
  hideMuted: boolean;
  programTypes: string[];
  days: ('mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun')[];
  regTiming: RegTiming;
  timeOfDayMin: string | null; // 'HH:MM'
  timeOfDayMax: string | null;
  maxDistanceMi: number | null;
  ageMin: number | null;
  ageMax: number | null;
  watchlistOnly: boolean;
  // Persistent UI
  moreFiltersOpen: boolean;
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
  created_at: string;
}

export interface KidDetail extends KidBrief {
  availability: Record<string, unknown>;
  max_distance_mi: number | null;
  alert_score_threshold: number;
  alert_on: Record<string, boolean>;
  school_weekdays: string[];
  school_time_start: string | null;
  school_time_end: string | null;
  school_year_ranges: Array<{ start: string; end: string }>;
  school_holidays: string[];
  notes: string | null;
  watchlist: WatchlistEntry[];
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

export type PageKind = 'schedule' | 'registration' | 'list' | 'other';

export interface Candidate {
  url: string;
  title: string;
  kind: 'html' | 'pdf';
  score: number;
  reason: string;
}

export interface DiscoveryStats {
  sitemap_urls: number;
  link_urls: number;
  filtered_junk: number;
  fetched_heads: number;
  classified: number;
  returned: number;
}

export interface DiscoveryResult {
  site_id: number;
  seed_url: string;
  stats: DiscoveryStats;
  candidates: Candidate[];
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
  home_lat: number | null;
  home_lon: number | null;
  default_max_distance_mi: number | null;
  digest_time: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  daily_llm_cost_cap_usd: number;
  email_configured: boolean;
  ntfy_configured: boolean;
  pushover_configured: boolean;
}

// Channel configuration types for Phase 7-1 Settings
export interface SmtpConfig {
  transport: 'smtp';
  host: string;
  port: number;
  use_tls: boolean;
  username?: string;
  password_env?: string;
  from_addr: string;
  to_addrs: string[];
}

export interface ForwardEmailConfig {
  transport: 'forwardemail';
  api_token_env: string;
  from_addr: string;
  to_addrs: string[];
}

export type EmailConfig = SmtpConfig | ForwardEmailConfig;

export interface NtfyConfig {
  base_url: string;
  topic: string;
  auth_token_env?: string;
}

export interface PushoverConfig {
  user_key_env: string;
  app_token_env: string;
  devices?: string[];
  emergency_retry_s?: number;
  emergency_expire_s?: number;
}

export interface TestSendResult {
  ok: boolean;
  detail: string;
}

export type CalendarEventKind = 'enrollment' | 'unavailability' | 'match' | 'holiday';

export interface CalendarEvent {
  id: string; // composite "kind:source-id:date"
  kind: CalendarEventKind;
  date: string; // YYYY-MM-DD
  time_start: string | null; // "HH:MM:SS" or null for all-day
  time_end: string | null;
  all_day: boolean;
  title: string;
  // enrollment-only:
  enrollment_id?: number | null;
  offering_id?: number | null;
  location_id?: number | null;
  status?: string | null;
  // unavailability-only:
  block_id?: number | null;
  source?: string | null;
  from_enrollment_id?: number | null;
  // match-only:
  score?: number | null;
  registration_url?: string | null;
  watchlist_hit?: boolean;
}

export interface KidCalendarResponse {
  kid_id: number;
  from: string; // YYYY-MM-DD
  to: string;
  events: CalendarEvent[];
}

export type EnrollmentStatus = 'interested' | 'enrolled' | 'waitlisted' | 'completed' | 'cancelled';

export interface Enrollment {
  id: number;
  kid_id: number;
  offering_id: number;
  status: EnrollmentStatus;
  enrolled_at: string | null;
  notes: string | null;
  created_at: string;
  offering: OfferingSummary;
}

// Phase 7-4 alerts page
export type AlertStatus = 'pending' | 'sent' | 'skipped';

export interface Alert {
  id: number;
  type: AlertType | string;
  kid_id: number | null;
  offering_id: number | null;
  site_id: number | null;
  channels: string[];
  scheduled_for: string;
  sent_at: string | null;
  skipped: boolean;
  dedup_key: string;
  payload_json: Record<string, unknown>;
  closed_at: string | null;
  close_reason: CloseReason | null;
  summary_text: string;
}

export interface AlertListResponse {
  items: Alert[];
  total: number;
  limit: number;
  offset: number;
}

export interface OutboxFilterState {
  kidId: number | null;
  type: string | null;
  status: AlertStatus | null;
  since: string | null;
  until: string | null;
  page: number;
}

export interface DigestPreviewResponse {
  subject: string;
  body_plain: string;
  body_html: string;
}

// Phase 8-1 combined calendar
export interface CombinedCalendarEvent extends CalendarEvent {
  /** Injected at merge time; not present in API response. */
  kid_id: number;
}

export interface CombinedCalendarFilterState {
  /** Selected kid ids; null means "all active". */
  kidIds: number[] | null;
  /** Selected event types; null means "all". */
  types: CalendarEventKind[] | null;
  /** Pull match events into the calendar (defaults false). */
  includeMatches: boolean;
}
