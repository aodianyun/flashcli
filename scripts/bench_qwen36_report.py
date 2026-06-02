#!/usr/bin/env python3
"""Summarize qwen36 HTTP bench workdirs into Markdown + JSON reports."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CaseSummary:
    name: str
    rounds: int
    skip_first: int
    scored_rounds: int
    metrics: dict[str, Any]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_case(
    name: str,
    jsonl_path: Path,
    *,
    skip_first: int | None = None,
) -> CaseSummary:
    rows = _load_jsonl(jsonl_path)
    if not rows:
        raise SystemExit(f"no metrics in {jsonl_path}")

    manifest_path = jsonl_path.parent / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    skip = int(manifest.get("skip_first", skip_first if skip_first is not None else 1))
    rounds = int(manifest.get("rounds", len(rows)))
    if skip >= rounds:
        raise SystemExit(f"{jsonl_path}: skip_first ({skip}) >= rounds ({rounds})")
    samples = rows[skip:]
    scored = len(samples)

    def collect_usage(key: str) -> list[float]:
        out: list[float] = []
        for row in samples:
            val = (row.get("usage") or {}).get(key)
            if val is not None:
                out.append(float(val))
        return out

    def collect_bench(key: str) -> list[float]:
        out: list[float] = []
        for row in samples:
            val = (row.get("bench") or {}).get(key)
            if val is not None:
                out.append(float(val))
        return out

    def collect_wall_ms() -> list[float]:
        return [float(r.get("wall_ms", 0.0)) for r in samples if r.get("wall_ms") is not None]

    server_ttft_vals: list[float] = []
    client_ttft_vals: list[float] = []
    ttft_display_vals: list[float] = []
    decode_tps_fallback: list[float] = []
    for row in samples:
        usage = row.get("usage") or {}
        bench = row.get("bench") or {}
        server_ttft = bench.get("ttft_ms")
        if server_ttft is None:
            server_ttft = bench.get("server_ttft_ms")
        if server_ttft is None:
            server_ttft = usage.get("ttft_ms")
        if server_ttft is None:
            server_ttft = usage.get("first_delta_ms")
        if server_ttft is not None:
            server_ttft_vals.append(float(server_ttft))

        client_ttft = bench.get("client_ttft_ms")
        if client_ttft is not None:
            client_ttft_vals.append(float(client_ttft))

        display_ttft = server_ttft if server_ttft is not None else client_ttft
        if display_ttft is not None:
            ttft_display_vals.append(float(display_ttft))

        tok = usage.get("tok_per_s") or usage.get("decode_tok_per_s")
        if tok is None:
            ct = usage.get("completion_tokens")
            decode_ms = usage.get("decode_ms")
            if decode_ms is not None and ct is not None and float(decode_ms) > 0:
                decode_tps_fallback.append(float(ct) * 1000.0 / float(decode_ms))
            else:
                wall = row.get("wall_ms")
                ttft_guess = server_ttft if server_ttft is not None else client_ttft
                if ct is not None and wall is not None:
                    decode_wall = float(wall)
                    if ttft_guess is not None:
                        decode_wall = max(1.0, decode_wall - float(ttft_guess))
                    if decode_wall > 0:
                        decode_tps_fallback.append(float(ct) * 1000.0 / decode_wall)

    routes = [
        str((r.get("usage") or {}).get("route"))
        for r in samples
        if (r.get("usage") or {}).get("route") is not None
    ]

    metrics: dict[str, Any] = {
        "prompt_tokens": _mean(collect_usage("prompt_tokens")),
        "completion_tokens": _mean(collect_usage("completion_tokens")),
        "server_ttft_ms": _mean(server_ttft_vals),
        "client_ttft_ms": _mean(client_ttft_vals),
        "ttft_ms": _mean(ttft_display_vals),
        "curl_wall_ms_mean": _mean(collect_wall_ms()),
        "prefill_ms": _mean(collect_usage("prefill_ms")),
        "decode_ms": _mean(collect_usage("decode_ms")),
        "tok_per_s": _mean(collect_usage("tok_per_s")),
        "decode_tok_per_s": _mean(collect_usage("decode_tok_per_s")),
        "e2e_tok_per_s": _mean(collect_usage("e2e_tok_per_s")),
        "route_last": routes[-1] if routes else None,
    }
    tok = metrics.get("tok_per_s") or metrics.get("decode_tok_per_s") or metrics.get("e2e_tok_per_s")
    if tok is None and decode_tps_fallback:
        tok = _mean(decode_tps_fallback)
        metrics["decode_tok_per_s_estimated"] = True
    metrics["decode_tok_per_s_best"] = tok

    return CaseSummary(
        name=name,
        rounds=rounds,
        skip_first=skip,
        scored_rounds=scored,
        metrics=metrics,
    )


def discover_cases(workdir: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for path in sorted(workdir.glob("*.metrics.jsonl")):
        stem = path.name[: -len(".metrics.jsonl")]
        out.append((stem, path))
    return out


def _fmt_num(val: Any, *, digits: int = 1) -> str:
    if val is None:
        return "n/a"
    if isinstance(val, float):
        if digits == 0:
            return f"{int(round(val))}"
        return f"{val:.{digits}f}"
    return str(val)


def _fmt_delta(a: float | None, b: float | None, *, higher_is_better: bool) -> str:
    if a is None or b is None or b == 0:
        return "n/a"
    pct = (a - b) / b * 100.0
    better = (pct > 0) if higher_is_better else (pct < 0)
    sign = "+" if pct > 0 else ""
    tag = "↑" if better else "↓"
    return f"{sign}{pct:.1f}% {tag}"


def render_backend_section(backend: str, workdir: Path, cases: list[CaseSummary]) -> list[str]:
    manifest: dict[str, Any] = {}
    manifest_path = workdir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    lines = [
        f"## {backend}",
        "",
        f"- workdir: `{workdir}`",
    ]
    if manifest:
        for key in (
            "server_cmd",
            "port",
            "K",
            "max_seq",
            "warmup_preset",
            "rounds",
            "skip_first",
            "profile",
            "long_tokens",
            "payload_dir",
            "shared_weights",
            "shared_payloads",
            "started_at",
            "finished_at",
            "health_wait_s",
            "gpu_name",
        ):
            if key in manifest and manifest[key] not in (None, ""):
                lines.append(f"- {key}: `{manifest[key]}`")
    lines.append("")
    lines.append("| case | prompt | completion | TTFT (ms) | decode tok/s | curl wall (ms) | route |")
    lines.append("|------|-------:|-----------:|-----------------:|-------------:|---------------:|-------|")
    for case in cases:
        m = case.metrics
        lines.append(
            "| "
            + " | ".join(
                [
                    case.name,
                    _fmt_num(m.get("prompt_tokens"), digits=0),
                    _fmt_num(m.get("completion_tokens"), digits=0),
                    _fmt_num(m.get("ttft_ms") or m.get("server_ttft_ms")),
                    _fmt_num(m.get("decode_tok_per_s_best")),
                    _fmt_num(m.get("curl_wall_ms_mean"), digits=0),
                    str(m.get("route_last") or "n/a"),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def render_compare_section(
    left: str,
    right: str,
    left_cases: dict[str, CaseSummary],
    right_cases: dict[str, CaseSummary],
) -> list[str]:
    shared = sorted(set(left_cases) & set(right_cases))
    if not shared:
        return ["## Comparison", "", "_No shared cases._", ""]

    lines = [
        "## Comparison",
        "",
        f"Delta column: `{left}` vs `{right}`. "
        "Positive % on decode tok/s means the left column is faster. "
        "Runs should share one checkpoint and identical HTTP payloads.",
        "",
        "| case | metric | "
        + " | ".join([left, right, "delta"])
        + " |",
        "|------|--------|" + "|".join(["---:"] * 3) + "|",
    ]
    metric_specs = [
        ("ttft_ms", "TTFT ms", False),
        ("decode_tok_per_s_best", "decode tok/s", True),
        ("curl_wall_ms_mean", "curl wall ms", False),
    ]
    for case_name in shared:
        lc = left_cases[case_name].metrics
        rc = right_cases[case_name].metrics
        for key, label, higher_better in metric_specs:
            lv = lc.get(key)
            rv = rc.get(key)
            lines.append(
                "| "
                + " | ".join(
                    [
                        case_name if label == "TTFT ms" else "",
                        label,
                        _fmt_num(lv, digits=0 if key == "curl_wall_ms_mean" else 1),
                        _fmt_num(rv, digits=0 if key == "curl_wall_ms_mean" else 1),
                        _fmt_delta(lv, rv, higher_is_better=higher_better),
                    ]
                )
                + " |"
            )
    lines.append("")
    return lines


def build_report(
    *,
    out_dir: Path,
    backends: dict[str, Path],
) -> tuple[str, dict[str, Any]]:
    backend_cases: dict[str, list[CaseSummary]] = {}
    backend_map: dict[str, dict[str, CaseSummary]] = {}

    for name, workdir in backends.items():
        cases: list[CaseSummary] = []
        case_map: dict[str, CaseSummary] = {}
        for case_name, jsonl in discover_cases(workdir):
            summary = summarize_case(case_name, jsonl)
            cases.append(summary)
            case_map[case_name] = summary
        backend_cases[name] = cases
        backend_map[name] = case_map

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Qwen3.6-27B bench report (FlashRT vs PyTorch HF)",
        "",
        f"Generated: {now}",
        "",
        "Metrics are means over scored rounds (after warmup skips). "
        "Both backends use the same HTTP payloads when run via `bench_qwen36_compare.sh`. "
        "`decode tok/s` uses server `usage.tok_per_s` when present; otherwise estimates from "
        "`completion_tokens` and curl `wall_ms` minus TTFT.",
        "",
    ]

    for name, workdir in backends.items():
        lines.extend(render_backend_section(name, workdir, backend_cases[name]))

    keys = list(backends.keys())
    if len(keys) == 2:
        lines.extend(render_compare_section(keys[0], keys[1], backend_map[keys[0]], backend_map[keys[1]]))

    payload: dict[str, Any] = {
        "generated_at": now,
        "out_dir": str(out_dir),
        "backends": {},
    }
    for name, workdir in backends.items():
        manifest_path = workdir / "manifest.json"
        manifest = {}
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["backends"][name] = {
            "workdir": str(workdir),
            "manifest": manifest,
            "cases": {
                c.name: {
                    "rounds": c.rounds,
                    "skip_first": c.skip_first,
                    "scored_rounds": c.scored_rounds,
                    "metrics": c.metrics,
                }
                for c in backend_cases[name]
            },
        }

    return "\n".join(lines) + "\n", payload


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True, help="Report output directory")
    p.add_argument("--flashcli", type=Path, default=None, help="flashcli + FlashRT bench workdir")
    p.add_argument(
        "--pytorch",
        type=Path,
        default=None,
        help="PyTorch HF baseline bench workdir",
    )
    p.add_argument(
        "--flashrt",
        type=Path,
        default=None,
        help="(deprecated) alias for --pytorch",
    )
    p.add_argument(
        "--backend",
        action="append",
        nargs=2,
        metavar=("NAME", "WORKDIR"),
        help="Extra backend workdir (repeatable)",
    )
    args = p.parse_args()

    backends: dict[str, Path] = {}
    if args.flashcli is not None:
        backends["flashcli + FlashRT"] = args.flashcli.expanduser().resolve()
    pytorch_dir = args.pytorch or args.flashrt
    if pytorch_dir is not None:
        backends["PyTorch HF (transformers)"] = pytorch_dir.expanduser().resolve()
    if args.backend:
        for name, workdir in args.backend:
            backends[name] = Path(workdir).expanduser().resolve()

    if not backends:
        raise SystemExit("Provide at least one of --flashcli, --pytorch, or --backend")

    for name, path in backends.items():
        if not path.is_dir():
            raise SystemExit(f"workdir not found for {name}: {path}")
        if not list(path.glob("*.metrics.jsonl")):
            raise SystemExit(f"no *.metrics.jsonl under {path}")

    out_dir = args.out.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    md, payload = build_report(out_dir=out_dir, backends=backends)
    md_path = out_dir / "REPORT.md"
    json_path = out_dir / "report.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {md_path}", file=sys.stderr)
    print(f"Wrote {json_path}", file=sys.stderr)
    print(md, file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
