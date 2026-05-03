import type { CredentialStatus } from '@/lib/types';

interface Props {
  /** Stable form-field id used by the <label htmlFor>. */
  id: string;
  /** Visible label, e.g. "User Key". */
  label: string;
  /** Current form value (the password override). Empty string when not set. */
  value: string;
  onChange: (next: string) => void;
  onBlur?: () => void;
  /** Server-resolved status: where the credential currently comes from. May
   *  be undefined when no config row exists yet (channel pristine). */
  status?: CredentialStatus;
  /** Form-field validation errors (already resolved to strings). */
  errors?: string[];
  /** Optional inline helper text above the input. */
  hint?: string;
}

/**
 * One credential field with a masked password input and a status badge
 * showing whether the credential is currently resolving via the form
 * override (this DB row), the conventional env var, or is unset.
 *
 * The placeholder reads "•••••• (set via env)" when an env value is in
 * effect — the user can leave the box empty to keep using env, or type
 * a new value to override.
 */
export function CredentialField({
  id,
  label,
  value,
  onChange,
  onBlur,
  status,
  errors,
  hint,
}: Props) {
  const via = status?.via ?? null;
  const envVar = status?.env_var;

  const placeholder =
    via === 'env'
      ? `•••••• (set via ${envVar})`
      : via === 'form'
        ? '•••••• (saved value — type to replace)'
        : envVar
          ? `Paste value, or set ${envVar} env var`
          : 'Paste value';

  const badge =
    via === 'env' ? (
      <span
        className="inline-flex items-center rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-200"
        title={`Resolves from ${envVar}`}
      >
        ✓ env
      </span>
    ) : via === 'form' ? (
      <span
        className="inline-flex items-center rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-900 dark:bg-blue-900/30 dark:text-blue-200"
        title="Stored in DB; overrides any env var"
      >
        ✓ form
      </span>
    ) : (
      <span
        className="inline-flex items-center rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900 dark:bg-amber-900/30 dark:text-amber-200"
        title={envVar ? `Set ${envVar} or paste a value above` : 'Unconfigured'}
      >
        ✗ not set
      </span>
    );

  return (
    <div>
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="block text-sm font-medium">
          {label}
        </label>
        {badge}
      </div>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      <input
        id={id}
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        aria-invalid={Boolean(errors?.length)}
        className="mt-1 block w-full rounded border border-input px-3 py-2 font-mono text-sm"
        placeholder={placeholder}
      />
      {errors?.map((err, i) => (
        <p key={i} className="mt-1 text-xs text-destructive">
          {err}
        </p>
      ))}
      {via === 'env' && (
        <p className="mt-1 text-xs text-muted-foreground">
          Currently using <code>{envVar}</code>. Leave blank to keep, or paste a value to override.
        </p>
      )}
    </div>
  );
}
