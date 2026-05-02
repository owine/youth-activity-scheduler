import { differenceInCalendarDays, format, isSameDay, parseISO } from 'date-fns';

export function price(value: number | null | undefined): string {
  if (value == null || value < 0) return '';
  if (value === 0) return 'Free';
  return `$${value.toFixed(2)}`;
}

export function relDate(value: string | Date | null | undefined, now: Date = new Date()): string {
  if (value == null) return '';
  const d = typeof value === 'string' ? parseISO(value) : value;
  const diff = differenceInCalendarDays(d, now);
  if (isSameDay(d, now)) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff > 1 && diff <= 6) return `in ${diff} days`;
  // Within ~3 months: short day + month + day
  if (Math.abs(diff) <= 90) return format(d, 'EEE MMM d');
  return format(d, 'PP');
}

export function fmt(value: string | Date, fmtStr = 'EEE h:mm a · MMM d'): string {
  const d = typeof value === 'string' ? parseISO(value) : value;
  return format(d, fmtStr);
}
