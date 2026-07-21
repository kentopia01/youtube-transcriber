# T061 Historical Stale-Download Recovery — 2026-07-21

## Cohort and method

The recovery cohort is the 22 unresolved April attempts identified during T059,
not every historical `stale_reaped` row in the database. The read-only evaluator
queried that state, then used yt-dlp metadata extraction with `skip_download=true`.
No authenticated cookies, media downloads, or database mutations were used during
classification.

Metadata result:

- 11 public long-form candidates at or above the 600-second autonomous-ingest floor.
- 11 short-form items below the floor.
- No private, unavailable, scheduled/live, duration-limit, or probe-error results.
- `6M1Z_V3WgOk` is the older copy of the fixed-audio Dante re-upload
  `4EZUrGPgAos`, so only the fixed re-upload was approved.

## Disposition

| YouTube ID | Duration | Disposition | Recovery attempt |
|---|---:|---|---|
| `pZqVAvFg0UQ` | 58s | Intentionally skipped — short-form | — |
| `m6B95EUX7-0` | 33s | Intentionally skipped — short-form | — |
| `Z_AoFoWkROg` | 66s | Intentionally skipped — short-form | — |
| `sriQqkfM1C4` | 57s | Intentionally skipped — short-form | — |
| `hj1OxZky_qA` | 57s | Intentionally skipped — short-form | — |
| `TRLfSFXXSKA` | 67s | Intentionally skipped — short-form | — |
| `3MjtdKgaBy4` | 26s | Intentionally skipped — short-form | — |
| `2WjVuzy6diM` | 44s | Intentionally skipped — short-form | — |
| `VYbAOAHqUi4` | 26s | Intentionally skipped — short-form | — |
| `zXqKYa-3y_w` | 69s | Intentionally skipped — short-form | — |
| `52_uGJehKFc` | 38s | Intentionally skipped — short-form | — |
| `6M1Z_V3WgOk` | 2863s | Intentionally skipped — duplicate/older audio copy | — |
| `am_oeAoUhew` | 2780s | Recovered | `f918f667-44bc-459a-98c9-4009d8e30369` |
| `Mjc7vwys1vY` | 2000s | Recovered | `b869485e-5809-4eba-b9a8-1bcf544f7e65` |
| `IZDJ3jcO5UY` | 1730s | Recovered | `3b08bc1b-08ff-4726-83ad-c46f1afb9e75` |
| `yiJOTCRVWjc` | 3242s | Recovered | `9e2c3cb8-cb49-4477-aa81-d472aa813435` |
| `dvEwb1Ajkwo` | 3305s | Recovered | `c99769c2-75e5-469f-a7eb-6361fa3ec65e` |
| `oM1d9Tau27w` | 2711s | Recovered | `99434166-a9db-4d99-ba28-53f013a96a45` |
| `W--hvgRLmJM` | 6831s | Final batch running | `7778a396-d03c-4dd6-bb91-d38bcc652ef1` |
| `Es4sU4H4TYg` | 877s | Final batch running | `13eb30ea-08d8-4682-a259-b6c6844431e3` |
| `ue8y5e3HnHE` | 4986s | Final batch running | `1ee04939-eafc-4649-81db-43f5fc5df12b` |
| `4EZUrGPgAos` | 2817s | Final batch running | `31fee972-ba82-4f81-a8d4-85900e6dc5f9` |

## Batch evidence

- Batch 1: three AI/product videos, 3/3 completed.
- Batch 2: three AI/design videos, all downloads passed and recovery completed.
- Batch 3: four remaining approved long-form videos, all downloads passed before
  heavy processing began.
- Every retry created attempt 2 with stale-recovery lineage; historical failed
  attempts remain preserved and superseded.
- Cookie-backed media requests returned the known public-video 403 in several
  cases, and the existing one-time cookie-free fallback downloaded successfully.
  T034's authenticated-cookie evidence gate remains closed.

The short-form and duplicate videos were already reversibly dismissed by the April
legacy-backfill cleanup. T061 leaves those historical audit rows intact and records
the more specific policy disposition here.
