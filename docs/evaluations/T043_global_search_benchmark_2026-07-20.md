# T043 Global Search Benchmark — 2026-07-20

## Decision

Do not ship a reranker or query-expansion dependency yet. The current hybrid search
reached a 91.7% video-level hit rate on the corpus-grounded seed set. Its only
consistent miss was an ambiguous multi-model landscape query that returned several
closely related OpenAI/Anthropic videos instead of the specifically labeled video.

Keep the summary lane. Its removal caused an additional vague-question miss and
reduced hit rate to 83.3%. Do not change the default candidate or per-video limits
until the set includes at least 30 anonymized real operator queries; the current
labels cannot measure whether reducing per-video evidence harms answer quality.

## Corpus and method

- Corpus at run time: 605 videos and 55,159 embedding chunks, including 5,052 summary chunks.
- Query set: 12 corpus-grounded operator-style seeds across names, technical terms, broad themes, vague questions, and summary-style questions.
- Relevance unit: expected YouTube video ID. Multiple chunks from the same video are deduplicated before scoring.
- Timing: every query warmed once, then every query/variant repeated three times. Variant order rotates per query/repetition to distribute transient load.
- Writes: none. The harness only calls the loopback API and reads search results.
- Caveat: these are plausible seed queries based on the real corpus, not captured user telemetry.

## Results

| Variant | Candidate / summary / per-video | Hit rate | MRR | Recall | Mean ms | p95 ms | Mean distinct videos |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 100 / 50 / 3 | 91.7% | 0.792 | 91.7% | 64.3 | 81.5 | 8.2 |
| lean | 50 / 25 / 3 | 91.7% | 0.792 | 91.7% | 64.1 | 78.3 | 8.2 |
| diverse | 100 / 50 / 1 | 91.7% | 0.792 | 91.7% | 65.6 | 79.8 | 11.7 |
| transcript-heavy | 100 / 0 / 3 | 83.3% | 0.688 | 83.3% | 62.7 | 76.8 | 8.2 |
| deep | 200 / 100 / 3 | 91.7% | 0.792 | 91.7% | 63.7 | 80.0 | 8.2 |

All variants use result limit 12 and RRF k=60. Latency has normal local-run noise;
the interleaved results show no practically meaningful difference among variants
other than the quality loss when summaries are removed.

## Misses and interpretation

- All variants missed `summary-model-landscape`, labeled to `lgo_QbgV198`. The query asks broadly about OpenAI, Anthropic, open source, and ROI; the baseline instead returned multiple highly related videos. This is a useful ambiguity case, not yet proof that a reranker would select the desired result.
- `transcript-heavy` also missed `vague-coding-solved`, showing that summary candidates help bridge vague wording to the intended video.

## Reopen criteria for T042

Run the reranker/query-expansion experiment only after one of these gates is met:

- the fixed set contains at least 30 manually reviewed, anonymized real queries;
- baseline video hit rate is repeatedly below 90%; or
- at least three recurring miss patterns suggest a specific reranking or expansion hypothesis.

At that point, compare bounded variants over only the top 30–50 candidates and keep
advanced inference optional and off by default.
