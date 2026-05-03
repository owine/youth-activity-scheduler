/**
 * Dedupe a list of TanStack Form errors by their rendered message.
 * onMount + onChange validators on the same schema both populate
 * `meta.errors`, producing visually-identical duplicates. We collapse
 * by message string so the user sees each problem once.
 */
export function uniqueFormErrors(errors: readonly unknown[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const err of errors) {
    const m = formErrorMessage(err);
    if (m && !seen.has(m)) {
      seen.add(m);
      out.push(m);
    }
  }
  return out;
}

/**
 * Extract a renderable string from a TanStack Form error entry.
 *
 * `field.state.meta.errors` is `Array<unknown>` — what's in there depends
 * on the validator. With Zod (via the standard schema adapter or direct
 * use), errors are Zod issue objects of shape `{ message, path, ... }`.
 * Plain strings happen too (custom validators). The bug we're fixing is
 * forms that called `String(err)` on Zod issues, producing the literal
 * "[object Object]".
 */
export function formErrorMessage(err: unknown): string {
  if (err == null) return '';
  if (typeof err === 'string') return err;
  if (typeof err === 'object' && 'message' in err) {
    const m = (err as { message: unknown }).message;
    if (typeof m === 'string') return m;
  }
  // Last-resort: try JSON, fall back to String() — at least we don't
  // silently render "[object Object]" with no diagnostic value.
  try {
    return JSON.stringify(err);
  } catch {
    return String(err);
  }
}
