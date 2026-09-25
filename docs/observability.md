# Observability

The app writes structured JSON logs to stderr (structlog) and reports errors to a
Sentry-protocol endpoint: in practice a self-hosted GlitchTip, through the official
`sentry-sdk` (backend) and `@sentry/react` (browser). Both are optional. With no DSN
set, nothing is initialised and behaviour is unchanged.

## Environment variables

### Runtime (the `yas` container)

All optional. These use the Sentry SDK's own unprefixed names rather than `YAS_`.

| Var | Purpose | Default |
|---|---|---|
| `SENTRY_DSN` | Backend DSN. Init is skipped when unset **or empty** (compose renders an unset `${VAR}` as empty). | unset |
| `SENTRY_BROWSER_DSN` | Browser DSN. Use a **separate GlitchTip project** from `SENTRY_DSN`: this value is rendered into public HTML. The backend puts it in a `<meta>` tag on `index.html` at request time, so it is a runtime value and one image serves any deployment. A DSN that isn't an http(s) URL, or that carries a password (a pasted wrong URL), is not rendered. | unset |
| `SENTRY_ENVIRONMENT` | `environment` on backend and browser events. | `production` |
| `YAS_GIT_SHA` | Baked into the image by CI. Used as the `release` on backend and browser events. | `unknown` (release omitted) |

### Build time (source-map upload)

Only needed if you want browser stack traces un-minified in GlitchTip. CI sets these
on pushes to `main` only; see `.github/workflows/ci.yml`.

| Var | Kind | Purpose |
|---|---|---|
| `SENTRY_AUTH_TOKEN` | **buildkit secret**, never a build arg | GlitchTip auth token. Without it the Vite plugin disables itself and the build output is unchanged. In CI: repo secret `SENTRY_AUTH_TOKEN`. |
| `SENTRY_URL` | build arg | GlitchTip base URL, e.g. `https://glitchtip.example.com/`. In CI: repo variable. |
| `SENTRY_ORG` | build arg | GlitchTip organization slug. In CI: repo variable. |
| `SENTRY_PROJECT` | build arg | Slug of the **browser** project. In CI: repo variable. |
| `VITE_SENTRY_DSN` | Vite env, dev only | Fallback browser DSN for `pnpm run dev`, where Vite serves its own `index.html` and there is no backend `<meta>` tag. Not used by the image. |

The token is passed as a buildkit secret because build args persist in image
history. The Dockerfile mounts it into the frontend build `RUN` only:

```bash
docker build --secret id=sentry_auth_token,src=/path/to/token \
  --build-arg SENTRY_URL=https://glitchtip.example.com/ \
  --build-arg SENTRY_ORG=my-org --build-arg SENTRY_PROJECT=yas-browser .
```

Source maps are matched by **debug ID** (GlitchTip 6 supports artifact bundles), so
the upload doesn't create a release and the frontend layer doesn't depend on the
commit SHA. Once uploaded, the maps are deleted from the image. A failed upload,
such as GlitchTip being down during the build, logs a warning and the build continues.

## What reaches GlitchTip

Reporting is **explicit**. structlog writes straight to stderr (`PrintLoggerFactory`)
and never passes through stdlib `logging`, so Sentry's logging integration can't
see `log.error(...)`. A new failure site that should page needs its own
`sentry_sdk.capture_exception(...)` or `capture_message(...)`. For crawl failures,
pass `**crawl_scope(site, page)` from `yas.observability` so the event carries the
`site`, `site_id` and `page_id` tags and a `crawl.page_url` context.

Tags let GlitchTip filter and break an issue down by site; they don't affect
grouping. Failures caused by one site's content also set a per-site `fingerprint`,
so each broken site becomes its own issue.

| Where | Reported? | Level | Grouping |
|---|---|---|---|
| Crawl: unexpected exception (reconcile/matcher bug, DB error, Anthropic error after SDK retries) | yes | error | stack trace, site-tagged |
| Crawl: exception escaping `crawl_page`, or the failure-backoff write failing | yes | error | stack trace, site-tagged |
| Crawl: `ExtractionError` (fetched fine, couldn't be read into offerings) | yes | warning | one issue per site |
| Crawl: page that listed offerings now extracts none (all withdrawn) | yes | warning | one issue per site |
| Crawl: `FetchError` (404, 5xx, transport) | no | | Expected per-site; backs off, and the third in a row sends the in-app `crawl_failed` alert |
| Delivery: a channel fails permanently (bad token, SMTP auth) | yes | warning | one issue per channel |
| Delivery: alert dropped after retries, or every channel failed | yes | error | one issue per alert type |
| Geocoder raised (enricher or household save) | yes | error | stack trace, tagged `location_id` (never the address) |
| Digest LLM summary failed (deterministic fallback used) | no | | Log warning; an Anthropic outage already shows up via crawl errors |
| `/readyz` returning 503 | no | | Probes poll constantly; the 503 is the signal. A readiness check that *raises* is still reported. |
| Unhandled API exception (500) | yes | error | FastAPI integration |
| Worker loop crash (exits the process) | yes | error | uncaught-exception hook, flushed at exit |
| Browser: route render error | yes | error | router `defaultOnCatch` |
| Browser: error outside routes | yes | error | app-level `ErrorBoundary`, which also renders a reload fallback |

## Privacy

- `send_default_pii=False` / `sendDefaultPii: false`; no tracing, profiling or session replay.
- `trace_propagation_targets=[]`: the FastAPI integration opens an (unsampled)
  transaction per request even at `traces_sample_rate=0`, and within one the httpx
  integration would otherwise add `sentry-trace` and `baggage` (which embeds the DSN
  public key) to every third-party request, e.g. the sites `/discover` fetches.
- httpx request breadcrumbs and stdlib-log breadcrumbs are dropped: Nominatim
  requests carry the household address in `q=`.
- Geocoding events are tagged by location id. The exception message can still
  contain an address; it only goes to your own GlitchTip.

## Setting up GlitchTip

1. Create two projects: one for the backend (platform Python) and one for the
   browser (platform JavaScript/React). Copy each DSN.
2. Set `SENTRY_DSN` and `SENTRY_BROWSER_DSN` on the `yas` container and recreate it.
3. (Optional, source maps) Create an auth token with `project:releases` (or
   `project:write`). In the GitHub repo, add the secret `SENTRY_AUTH_TOKEN` and the
   variables `SENTRY_URL`, `SENTRY_ORG` and `SENTRY_PROJECT` (the browser project's
   slug). The next push to `main` uploads maps for the image it publishes.
4. Check it's working: `docker logs yas 2>&1 | grep sentry.enabled` shows the backend
   initialised, and `index.html` should contain `<meta name="sentry-browser-dsn">`.

## Reading logs

```bash
docker logs yas                  # all logs (JSON, one event per line)
docker logs yas --since 1h
docker logs yas 2>&1 | jq 'select(.level == "error")'
```

Event names are dotted (`pipeline.unexpected`, `delivery.gave_up`), so a failure in
GlitchTip can be matched to its log line by name and timestamp.
