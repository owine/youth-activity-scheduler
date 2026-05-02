import { addDays, endOfMonth, format, startOfMonth, startOfWeek } from 'date-fns';
import type { View } from 'react-big-calendar';

export const BUFFER_DAYS = 3;

export function rangeFor(view: View, cursor: Date): { from: string; to: string } {
  if (view === 'month') {
    const monthStart = startOfMonth(cursor);
    const monthEnd = endOfMonth(cursor);
    const weekStart = startOfWeek(monthStart, { weekStartsOn: 0 });
    return {
      from: format(addDays(weekStart, -BUFFER_DAYS), 'yyyy-MM-dd'),
      to: format(addDays(monthEnd, 7 + BUFFER_DAYS), 'yyyy-MM-dd'),
    };
  }
  const weekStart = startOfWeek(cursor, { weekStartsOn: 0 });
  return {
    from: format(addDays(weekStart, -BUFFER_DAYS), 'yyyy-MM-dd'),
    to: format(addDays(weekStart, 7 + BUFFER_DAYS), 'yyyy-MM-dd'),
  };
}
