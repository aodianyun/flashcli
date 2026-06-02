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


def _row_engine_ttft(row: dict[str, Any]) -> float | None:
    """Engine TTFT from serve.log merge or usage; never prefer client when engine exists."""
    usage = row.get("usage") or {}
    bench = row.get("bench") or {}
    if bench.get("metrics_source") or usage.get("metrics_source"):
        for key in ("server_ttft_ms",):
            val = bench.get(key)
            if val is not None:
                return float(val)
        for key in ("ttft_ms", "first_delta_ms", "prefill_ms"):
            val = usage.get(key)
            if val is not None:
                return float(val)
    for key in ("server_ttft_ms",):
        val = bench.get(key)
        if val is not None:
            return float(val)
    for key in ("ttft_ms", "first_delta_ms"):
        val = usage.get(key)
        if val is not None:
            return float(val)
    return None


def _row_decode_tps(row: dict[str, Any]) -> float | None:
    usage = row.get("usage") or {}
    for key in ("decode_tok_per_s", "tok_per_s", "e2e_tok_per_s"):
        val = usage.get(key)
        if val is not None:
            return float(val)
    return None


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

    engine_ttft_vals: list[float] = []
    client_ttft_vals: list[float] = []
    decode_tps_engine: list[float] = []
    decode_tps_fallback: list[float] = []
    for row in samples:
        usage = row.get("usage") or {}
        bench = row.get("bench") or {}
        engine_ttft = _row_engine_ttft(row)
        if engine_ttft is not None:
            engine_ttft_vals.append(engine_ttft)

        client_ttft = bench.get("client_ttft_ms")
        if client_ttft is not None:
            client_ttft_vals.append(float(client_ttft))

        tok = _row_decode_tps(row)
        if tok is not None:
            decode_tps_engine.append(tok)
        else:
            ct = usage.get("completion_tokens")
            decode_ms = usage.get("decode_ms")
            if decode_ms is not None and ct is not None and float(decode_ms) > 0:
                decode_tps_fallback.append(float(ct) * 1000.0 / float(decode_ms))
            else:
                wall = row.get("wall_ms")
                ttft_guess = engine_ttft if engine_ttft is not None else client_ttft
                if ct is not None and wall is not None and ttft_guess is not None:
                    decode_wall = max(1.0, float(wall) - float(ttft_guess))
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
        "engine_ttft_ms": _mean(engine_ttft_vals),
        "server_ttft_ms": _mean(engine_ttft_vals),
        "client_ttft_ms": _mean(client_ttft_vals),
        "ttft_ms": _mean(engine_ttft_vals) or _mean(client_ttft_vals),
        "curl_wall_ms_mean": _mean(collect_wall_ms()),
        "prefill_ms": _mean(collect_usage("prefill_ms")),
        "decode_ms": _mean(collect_usage("decode_ms")),
        "tok_per_s": _mean(collect_usage("tok_per_s")),
        "decode_tok_per_s": _mean(collect_usage("decode_tok_per_s")),
        "e2e_tok_per_s": _mean(collect_usage("e2e_tok_per_s")),
        "route_last": routes[-1] if routes else None,
        "metrics_from_serve_log": any(
            (r.get("bench") or {}).get("metrics_source") == "serve_log_flashrt"
            or (r.get("usage") or {}).get("metrics_source") == "serve_log_flashrt"
            for r in samples
        ),
    }
    tok = _mean(decode_tps_engine)
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
    lines.append(
        "| case | prompt | completion | engine TTFT (ms) | client TTFT (ms) | "
        "decode tok/s | curl wall (ms) | route |"
    )
    lines.append(
        "|------|-------:|-----------:|-----------------:|-----------------:|"
        "-------------:|---------------:|-------|"
    )
    for case in cases:
        m = case.metrics
        est = "†" if m.get("decode_tok_per_s_estimated") else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    case.name,
                    _fmt_num(m.get("prompt_tokens"), digits=0),
                    _fmt_num(m.get("completion_tokens"), digits=0),
                    _fmt_num(m.get("engine_ttft_ms") or m.get("server_ttft_ms")),
                    _fmt_num(m.get("client_ttft_ms")),
                    _fmt_num(m.get("decode_tok_per_s_best")) + est,
                    _fmt_num(m.get("curl_wall_ms_mean"), digits=0),
                    str(m.get("route_last") or "n/a"),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append(
        "† = decode estimated from curl wall when serve.log / usage had no engine decode_tok_per_s."
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
        "Runs should share one checkpoint and identical HTTP payloads. "
        "Long-context rows appear only when both arms ran the same `qwen36_long` case.",
        "",
        "| case | metric | "
        + " | ".join([left, right, "delta"])
        + " |",
        "|------|--------|" + "|".join(["---:"] * 3) + "|",
    ]
    metric_specs = [
        ("engine_ttft_ms", "engine TTFT ms", False),
        ("client_ttft_ms", "client TTFT ms", False),
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
                        case_name if label == "engine TTFT ms" else "",
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


def render_fairness_section(out_dir: Path) -> list[str]:
    cfg_path = out_dir / "bench_config.json"
    if not cfg_path.is_file():
        return []
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    lines = ["## Bench fairness (from bench_config.json)", ""]
    w = cfg.get("weights") or {}
    lines.append(
        f"- **Weights**: identical={w.get('identical')} "
        f"(FlashRT `{w.get('flashrt')}`, vLLM `{w.get('vllm')}`)"
    )
    api = cfg.get("api_model") or {}
    lines.append(
        f"- **API model id**: identical={api.get('identical')} "
        f"(`{api.get('flashrt')}` / `{api.get('vllm')}`)"
    )
    http = cfg.get("http_request") or {}
    lines.append(
        f"- **HTTP**: temperature={http.get('temperature')} top_p={http.get('top_p')} "
        f"stream={http.get('stream')} enable_thinking="
        f"{(http.get('chat_template_kwargs') or {}).get('enable_thinking')}"
    )
    ctx = cfg.get("context") or {}
    lines.append(
        f"- **Context**: cases={cfg.get('bench_cases')} max_seq_flashrt={ctx.get('max_seq_flashrt')} "
        f"vllm_max_model_len={ctx.get('vllm_max_model_len')} vllm_skip_long={ctx.get('vllm_skip_long')}"
    )
    asym = cfg.get("known_asymmetries") or []
    if asym:
        lines.append("- **Known asymmetries** (not bugs):")
        for item in asym:
            lines.append(f"  - {item}")
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
        "# Qwen3.6-27B NVFP4 bench report (FlashRT vs vLLM)",
        "",
        f"Generated: {now}",
        "",
        "Metrics are means over scored rounds (after warmup skips). "
        "Both backends use the same NVFP4 weights and HTTP payloads from `bench_qwen36_compare.sh`. "
        "**Engine TTFT / decode** come from FlashRT `stream |` lines in `serve.log` "
        "(merged into metrics automatically). **Client TTFT** is the first HTTP content chunk. "
        "Compare arms using **engine TTFT**, not client TTFT, for qwen36.",
        "",
    ]
    lines.extend(render_fairness_section(out_dir))

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


def rehydrate_backends(backends: dict[str, Path], *, backend_kind: str = "auto") -> None:
    """Merge serve.log into metrics jsonl before summarizing."""
    try:
        from bench_qwen36_serve_metrics import rehydrate_workdir
    except ImportError:
        import importlib.util

        mod_path = Path(__file__).resolve().parent / "bench_qwen36_serve_metrics.py"
        spec = importlib.util.spec_from_file_location("bench_qwen36_serve_metrics", mod_path)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rehydrate_workdir = mod.rehydrate_workdir

    for _name, workdir in backends.items():
        log_path = workdir / "serve.log"
        if not log_path.is_file():
            manifest_path = workdir / "manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                alt = manifest.get("serve_log_path")
                if alt:
                    log_path = Path(str(alt)).expanduser()
        kind = backend_kind
        if "vLLM" in _name or "vllm" in _name.lower():
            kind = "vllm"
        rehydrate_workdir(workdir, log_path, backend=kind)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True, help="Report output directory")
    p.add_argument(
        "--no-rehydrate",
        action="store_true",
        help="Skip merging serve.log into metrics (default: rehydrate when serve.log exists)",
    )
    p.add_argument("--flashcli", type=Path, default=None, help="flashcli + FlashRT bench workdir")
    p.add_argument(
        "--vllm",
        type=Path,
        default=None,
        help="vLLM baseline bench workdir",
    )
    p.add_argument(
        "--pytorch",
        type=Path,
        default=None,
        help="(deprecated) alias for --vllm",
    )
    p.add_argument(
        "--flashrt",
        type=Path,
        default=None,
        help="(deprecated) alias for --vllm",
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
    vllm_dir = args.vllm or args.pytorch or args.flashrt
    if vllm_dir is not None:
        backends["vLLM"] = vllm_dir.expanduser().resolve()
    if args.backend:
        for name, workdir in args.backend:
            backends[name] = Path(workdir).expanduser().resolve()

    if not backends:
        raise SystemExit("Provide at least one of --flashcli, --vllm, or --backend")

    for name, path in backends.items():
        if not path.is_dir():
            raise SystemExit(f"workdir not found for {name}: {path}")
        if not list(path.glob("*.metrics.jsonl")):
            raise SystemExit(f"no *.metrics.jsonl under {path}")

    out_dir = args.out.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_rehydrate:
        rehydrate_backends(backends)

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
