import { z } from 'zod';

export const kidSchema = z
  .object({
    name: z.string().trim().min(1, 'Name is required').max(80),
    dob: z.string().refine((s) => {
      const d = new Date(s + 'T00:00:00Z');
      const now = new Date();
      const minBound = new Date(now.getFullYear() - 100, now.getMonth(), now.getDate());
      return !isNaN(d.getTime()) && d <= now && d >= minBound;
    }, 'DOB must be a valid date in the past 100 years'),
    interests: z.array(z.string().trim().min(1)).max(20),
    school_weekdays: z.array(z.enum(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])),
    school_time_start: z.string().nullable(),
    school_time_end: z.string().nullable(),
    school_year_ranges: z.array(z.object({ start: z.string(), end: z.string() })),
    school_holidays: z.array(z.string()),
    max_distance_mi: z.number().min(1).max(50).nullable(),
    max_drive_minutes: z.number().int().min(1).max(180).nullable(),
    alert_score_threshold: z.number().min(0).max(1),
    alert_on: z.record(z.string(), z.boolean()),
    notes: z.string().max(2000).nullable(),
    active: z.boolean(),
  })
  .refine(
    (data) => {
      if (data.school_time_start && data.school_time_end) {
        return data.school_time_start < data.school_time_end;
      }
      return true;
    },
    { message: 'School day start must be before end', path: ['school_time_end'] },
  );

export type KidFormValues = z.infer<typeof kidSchema>;
