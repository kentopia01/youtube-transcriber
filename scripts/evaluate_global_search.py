#!/usr/bin/env python3
"""Read-only quality and latency benchmark for the local global-search API."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUERY_FILE = PROJECT_ROOT / "benchmarks" / "global_search_queries.json"
DEFAULT_URL = "http://127.0.0.1:8000/api/global-search"


@dataclass(frozen=True)
class QueryCase:
    id: str
    category: str
    query: str
    expected_video_ids: tuple[str, ...]


@dataclass(frozen=True)
class Variant:
    name: str
    limit: int
    candidate_limit: int
    summary_limit: int
    per_video_limit: int
    rrf_k: int = 60


DEFAULT_VARIANTS = (
    Variant("baseline", 12, 100, 50, 3),
    Variant("lean", 12, 50, 25, 3),
    Variant("diverse", 12, 100, 50, 1),
    Variant("transcript_heavy", 12, 100, 0, 3),
    Variant("deep", 12, 200, 100, 3),
)


def load_query_cases(path: Path) -> list[QueryCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    seen_ids: set[str] = set()
    for item in raw.get("queries", []):
        case = QueryCase(
            id=str(item["id"]).strip(),
            category=str(item["category"]).strip(),
            query=str(item["query"]).strip(),
            expected_video_ids=tuple(str(value).strip() for value in item["expected_video_ids"]),
        )
        if not all((case.id, case.category, case.query)) or not case.expected_video_ids:
            raise ValueError("Every benchmark query needs an id, category, query, and expected video")
        if case.id in seen_ids:
            raise ValueError(f"Duplicate benchmark query id: {case.id}")
        seen_ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError("Benchmark query file contains no queries")
    return cases


def ranked_video_ids(results: Sequence[dict[str, Any]]) -> list[str]:
    """Return first-seen video IDs so multiple chunks cannot inflate metrics."""
    ranked = []
    seen: set[str] = set()
    for result in results:
        video_id = str(result.get("youtube_video_id") or "").strip()
        if video_id and video_id not in seen:
            seen.add(video_id)
            ranked.append(video_id)
    return ranked


def score_query(case: QueryCase, results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ranked = ranked_video_ids(results)
    expected = set(case.expected_video_ids)
    hits = expected.intersection(ranked)
    first_rank = next((index for index, value in enumerate(ranked, 1) if value in expected), None)
    return {
        "id": case.id,
        "category": case.category,
        "query": case.query,
        "expected_video_ids": list(case.expected_video_ids),
        "ranked_video_ids": ranked,
        "hit": bool(hits),
        "recall": len(hits) / len(expected),
        "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
        "first_relevant_rank": first_rank,
        "distinct_videos": len(ranked),
    }


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999)))
    return ordered[index]


def aggregate_variant(
    variant: Variant,
    query_scores: Sequence[dict[str, Any]],
    latencies_ms: Sequence[float],
) -> dict[str, Any]:
    count = len(query_scores)
    return {
        "variant": asdict(variant),
        "query_count": count,
        "hit_rate": sum(int(item["hit"]) for item in query_scores) / count,
        "mean_recall": statistics.fmean(item["recall"] for item in query_scores),
        "mrr": statistics.fmean(item["reciprocal_rank"] for item in query_scores),
        "mean_distinct_videos": statistics.fmean(item["distinct_videos"] for item in query_scores),
        "latency_ms": {
            "mean": statistics.fmean(latencies_ms),
            "median": statistics.median(latencies_ms),
            "p95": percentile(latencies_ms, 0.95),
            "samples": len(latencies_ms),
        },
        "queries": list(query_scores),
    }


SearchCall = Callable[[QueryCase, Variant], tuple[dict[str, Any], float]]


def run_benchmark(
    cases: Sequence[QueryCase],
    variants: Sequence[Variant],
    search: SearchCall,
    *,
    repeat: int = 3,
) -> list[dict[str, Any]]:
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    if len({variant.name for variant in variants}) != len(variants):
        raise ValueError("variant names must be unique")

    latencies: dict[str, list[float]] = {variant.name: [] for variant in variants}
    first_payloads: dict[tuple[str, str], dict[str, Any]] = {}
    variant_list = list(variants)
    for case_index, case in enumerate(cases):
        for repeat_index in range(repeat):
            # Rotate call order to distribute transient load fairly across variants.
            offset = (case_index + repeat_index) % len(variant_list)
            ordered = variant_list[offset:] + variant_list[:offset]
            for variant in ordered:
                payload, latency_ms = search(case, variant)
                first_payloads.setdefault((variant.name, case.id), payload)
                latencies[variant.name].append(latency_ms)

    reports = []
    for variant in variants:
        scores = [
            score_query(case, first_payloads[(variant.name, case.id)].get("results", []))
            for case in cases
        ]
        reports.append(aggregate_variant(variant, scores, latencies[variant.name]))
    return reports


def http_search(base_url: str, timeout: float) -> SearchCall:
    def search(case: QueryCase, variant: Variant) -> tuple[dict[str, Any], float]:
        options = asdict(variant)
        options.pop("name")
        body = json.dumps({"query": case.query, **options}).encode("utf-8")
        request = urllib.request.Request(
            base_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Global search request failed: {exc.reason}") from exc
        return payload, (time.perf_counter() - started) * 1000

    return search


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Global search benchmark",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Queries: {report['query_count']}",
        f"- Repetitions per query/variant: {report['repeat']}",
        "",
        "| Variant | Hit rate | MRR | Recall | Mean ms | p95 ms | Distinct videos |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["variants"]:
        latency = item["latency_ms"]
        lines.append(
            f"| {item['variant']['name']} | {item['hit_rate']:.1%} | {item['mrr']:.3f} | "
            f"{item['mean_recall']:.1%} | {latency['mean']:.1f} | {latency['p95']:.1f} | "
            f"{item['mean_distinct_videos']:.1f} |"
        )
    lines.extend(["", "## Misses", ""])
    misses = 0
    for item in report["variants"]:
        for query in item["queries"]:
            if not query["hit"]:
                misses += 1
                lines.append(
                    f"- `{item['variant']['name']}` / `{query['id']}` expected "
                    f"`{', '.join(query['expected_video_ids'])}`"
                )
    if not misses:
        lines.append("No misses in the labeled set.")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_FILE)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_query_cases(args.queries)
    search = http_search(args.url, args.timeout)
    # Warm each query once so one variant does not pay cold model/DB page costs.
    for case in cases:
        search(case, DEFAULT_VARIANTS[0])
    variants = run_benchmark(cases, DEFAULT_VARIANTS, search, repeat=args.repeat)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "query_file": str(args.queries),
        "query_count": len(cases),
        "warmup_requests": len(cases),
        "repeat": args.repeat,
        "variants": variants,
    }
    markdown = render_markdown(report)
    print(markdown, end="")
    if args.json_output:
        args.json_output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
