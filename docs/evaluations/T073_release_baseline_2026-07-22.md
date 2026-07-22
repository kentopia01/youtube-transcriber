# T073 Reader/Operations release baseline - 2026-07-22

## Result

The T063-T072 Reader/Operations worktree is release-ready and reproducible.

| Gate | Result |
|---|---:|
| Secret and oversized-file audit | pass |
| `git diff --check` | pass |
| Python compilation | pass |
| Migration/dependency contracts | 30 passed |
| Default test suite | 1350 passed, 11 skipped |
| Live HTTP feature areas | 33/33 passed |
| Chromium desktop/mobile workflows | 30/30 passed |

The first live Search API request exceeded the QA client's timeout while the
embedding model cold-loaded. The immediate repeat passed both Search APIs; no
steady-state error or service restart was present.
