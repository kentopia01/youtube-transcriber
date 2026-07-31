# T080 Reader, Ask, and embedding review — 2026-07-31

## Method

- Inspected the live tailnet-only deployment at desktop (1440x900), tablet
  (768x1024), and mobile (390x844).
- Covered Reader Home, Library, a real document, Highlights, scoped Search, and
  scoped Ask at every viewport.
- Traced the Reader/Ask routes, templates, browser code, retrieval services,
  chunking, embedding tasks, schema, and indexes.
- Ran read-only database coverage and chunk-distribution queries.
- Validated the shipped fixes with the repository suite plus live HTTP and
  Chromium gates through the Tailscale HTTPS URL.

## Reader and responsive findings

| Area | Before | Disposition |
|---|---|---|
| Document hierarchy | `/read/{video_id}` opened the raw transcript; the summary lived on a secondary details page. | Summary is now the default reading surface. The full timestamped transcript is an explicit disclosure with direct progress resume. |
| Mobile scanability | Library card summaries were hidden below 768px. | Summary previews remain visible with a three-line clamp. |
| Tailnet Search/Ask | Real browser POSTs over Tailscale HTTPS returned 403 because the app compared the public `https` Origin with the proxy's internal `http` request URL. | The same-host guard now honors the trusted forwarded scheme. Cross-site requests remain blocked. |
| 768px Library | The six-column filter row pushed Apply beyond the viewport. | Tablet filters reflow to three columns and Apply spans the row. |
| Mobile Ask composer | Scope controls compressed the question field and the whole composer sat below the viewport. | Disabled channel scope is hidden, the question field gets its own row, and chat height includes the Research tabs. |
| Source confidence | Ask displayed RRF fusion scores such as 4% as if they were semantic similarity. | Source badges now say Summary or Transcript. |

All six audited surfaces fit their viewports after the changes. The representative
mobile document opened with the summary and exposed the 121-minute transcript only
on request. Its stored summary was still 2,382 words (about 11 minutes), which is
materially better than the full transcript but suggests a future product choice:
keep At-a-Glance and Executive Summary expanded while collapsing the Detailed Brief.
That should be designed against the variability of the existing summary corpus, not
inferred from a single document.

## Ask: current flow and product gap

Current Ask flow:

1. `/chat?video_id=...` sets a current-video retrieval option in the page.
2. Sending a message retrieves ten candidates through hybrid global search, with
   semantic fallback.
3. The LLM receives recent chat history plus grounded chunks and returns prose with
   source cards.

The central product bug is session scope. Opening a current-video Ask link loads the
most recent web chat session, even when that session was created for another topic.
Scope is a per-request UI choice rather than persisted session identity. The result
is visually and semantically confusing: old history can appear under a new
“Current transcript” scope, and a session can silently change retrieval domains.

Recommended Ask follow-on:

1. Persist retrieval scope (`library`, `channel`, or `video` plus its target) on the
   chat session.
2. Treat scope as immutable for a session. Opening Ask from a Reader document should
   create a fresh video-scoped session or reopen a session already scoped to that
   exact video.
3. Show the scope target by name in the header and empty state.
4. Keep source type and timestamp explicit; make transcript timestamp badges link
   back to the Reader passage.
5. Add simple answer feedback and query logging so real questions become the
   retrieval evaluation set.

This changes session semantics and stored data, so it was not implemented as a
straightforward UI patch.

## Embedding and retrieval audit

### Current strengths

- 643 completed videos have embedding chunks; no completed video is wholly missing
  chunks.
- 57,881 chunks cover the corpus, including 5,576 summary chunks across 642 videos.
- The configured encoder is `nomic-ai/nomic-embed-text-v1.5`, 768 dimensions, with
  the correct `search_document:` and `search_query:` prefixes and normalized vectors.
- PostgreSQL has a cosine HNSW vector index and a GIN full-text index; both are used.
- No duplicate `(video_id, chunk_index)` rows or wrong-dimensional vectors were found.
- The existing 12-query benchmark records 91.7% video hit rate, MRR 0.792, mean
  64.3ms, and p95 81.5ms. Removing the summary lane reduced hit rate to 83.3%.

### Gaps and risks

- Chunk provenance is implicit. `speaker="__SUMMARY__"` doubles as source type, and
  chunks do not record embedding model/revision, chunker version, or source
  fingerprint.
- The nominal maximum is 400 tokens, but 290 chunks exceed it. The longest is 4,069
  tokens; transcript and summary chunks both have outliers. Long markdown bullets or
  sentences bypass the intended cap.
- Chunking has no overlap, reducing boundary recall.
- Full-text search is hard-coded to English despite a small multilingual corpus.
- The embedding task deletes existing chunks before the replacement set is safely
  installed. A failed embedding run can therefore leave a video's retrieval coverage
  degraded.
- There is no database uniqueness constraint protecting chunk identity.
- Two existing summaries have no summary chunks; one belongs to a completed video.
- The global ranker has vector, keyword, and summary-vector lanes. Because summary
  chunks also participate in the all-source vector lane, summary evidence can receive
  two boosts. This may be intentional, but it needs evaluation rather than guesswork.

## Proposed embedding follow-on

1. **Build the evaluation gate first.** Collect and manually label at least 30 real
   Ask/Search questions with relevant videos and passages; score hit rate, MRR,
   passage recall, answer support, latency, and failures by scope.
2. **Add explicit provenance.** Store source type, embedding model/revision/dimension,
   chunker version, and source fingerprint; add a safe uniqueness contract.
3. **Make chunking strict and format-aware.** Enforce the hard maximum, split long
   markdown/list items, add modest overlap, and preserve timestamp boundaries.
4. **Make re-embedding atomic.** Compute/version a replacement set before swapping it
   into active retrieval; never delete the last good set on an encoder failure.
5. **Reconcile coverage.** Backfill the one completed summary missing summary chunks
   and add a periodic coverage check.
6. **Tune ranking only against the evaluation set.** Test summary-lane weighting,
   multilingual FTS behavior, and optionally a reranker. Ship a ranker/model change
   only if it produces a measured improvement without unacceptable latency.

The current embeddings are usable and already deliver a reasonable baseline. The
right next move is provenance, atomicity, strict chunking, and a real-query evaluation
set—not an unmeasured model swap.

## Verification

- Repository tests: `1382 passed, 11 skipped`.
- Live HTTP gate: `33/33 passed`.
- Live Chromium gate through Tailscale HTTPS: `30/30 passed`.
- Visual matrix: 18 page/viewport combinations, plus a focused post-fix mobile Ask
  recheck with no horizontal or vertical page overflow.
