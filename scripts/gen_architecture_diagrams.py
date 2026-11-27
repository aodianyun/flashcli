#!/usr/bin/env python3
"""Generate the step-level architecture diagrams from Graphviz sources.

The system overview stays a hand-laid card map. Every other diagram is a
Graphviz flowchart (clusters, decisions, stores, error paths) generated from
this script so the implementation and the picture cannot drift apart silently.

Usage:
    python scripts/gen_architecture_diagrams.py
    dot -Tsvg docs/images/<name>.<lang>.dot -o docs/images/<name>.<lang>.svg
    dot -Tpng -Gdpi=110 docs/images/<name>.<lang>.dot -o docs/images/<name>.<lang>.png

The .dot files under docs/images are the source of truth for flow diagrams.
"""

from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
LANG = "en"

FONT = {
    "en": "Noto Sans CJK SC",
    "zh": "Noto Sans CJK SC",
}

# fill, border, edge/text accent
TONES = {
    "blue": ("#DBEAFE", "#3B82F6", "#2563EB"),
    "indigo": ("#E0E7FF", "#6366F1", "#4F46E5"),
    "violet": ("#EDE9FE", "#8B5CF6", "#7C3AED"),
    "green": ("#DCFCE7", "#22C55E", "#16A34A"),
    "teal": ("#CCFBF1", "#14B8A6", "#0D9488"),
    "amber": ("#FEF3C7", "#F59E0B", "#D97706"),
    "orange": ("#FFEDD5", "#F97316", "#EA580C"),
    "red": ("#FEE2E2", "#EF4444", "#DC2626"),
    "slate": ("#F1F5F9", "#CBD5E1", "#64748B"),
    "cyan": ("#E0F2FE", "#38BDF8", "#0284C7"),
    "pink": ("#FCE7F3", "#F472B6", "#DB2777"),
    "white": ("#FFFFFF", "#CBD5E1", "#334155"),
}


def L(zh: str, en: str | None = None) -> str:
    if en is None:
        return zh
    return zh if LANG.startswith("zh") else en


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def plain_label(title: str, lines: tuple[str, ...] | str = ()) -> str:
    if isinstance(lines, str):
        lines = (lines,)
    text = "\n".join((title, *lines))
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def label_html(title: str, lines: tuple[str, ...] | str = (), size: float = 13) -> str:
    if isinstance(lines, str):
        lines = (lines,)
    parts = [f"<B>{esc(title)}</B>"]
    for line in lines:
        parts.append(f'<FONT POINT-SIZE="{size - 1.5:g}">{esc(line)}</FONT>')
    return "<" + "<BR/>".join(parts) + ">"


def graph_label(title: str, subtitle: str) -> str:
    return (
        "<"
        f"<B>{esc(title)}</B><BR/>"
        f'<FONT POINT-SIZE="14" COLOR="#64748B">{esc(subtitle)}</FONT>'
        ">"
    )


class Dot:
    def __init__(self, name: str, title: str, subtitle: str, *, rankdir: str = "TB") -> None:
        self.name = name
        self.lines: list[str] = [
            f"digraph {name} {{",
            "  graph ["
            f'rankdir={rankdir}, bgcolor="#F7F9FC", pad=0.4, nodesep=0.4, ranksep=0.45, '
            f'fontname="{FONT[LANG and ("zh" if LANG.startswith("zh") else "en")]}", fontsize=30, '
            f'labelloc=t, label={graph_label(title, subtitle)}'
            "];",
            "  node ["
            f'shape=box, style="rounded,filled", fontname="{FONT["zh" if LANG.startswith("zh") else "en"]}", '
            'fontsize=13, margin="0.46,0.10", penwidth=1.3, color="#94A3B8"'
            "];",
            "  edge ["
            f'fontname="{FONT["zh" if LANG.startswith("zh") else "en"]}", fontsize=11, '
            'color="#64748B", fontcolor="#475569", arrowsize=0.7, penwidth=1.15'
            "];",
        ]
        self._cluster = 0

    def cluster(self, title: str, *, tone: str = "slate") -> None:
        self._cluster += 1
        border = TONES[tone][1]
        self.lines.append(f"  subgraph cluster_{self._cluster} {{")
        self.lines.append(f"    label={label_html(title, size=15)};")
        self.lines.append(
            f'    style="rounded,filled"; color="{border}"; fillcolor="#FFFFFF"; '
            'penwidth=1.3; fontcolor="#334155"; fontsize=15; margin=18;'
        )

    def end_cluster(self) -> None:
        self.lines.append("  }")

    @staticmethod
    def _units(text: str) -> int:
        return sum(2 if ord(ch) > 127 else 1 for ch in text)

    def node(
        self,
        key: str,
        title: str,
        lines: tuple[str, ...] | str = (),
        *,
        kind: str = "process",
        tone: str = "blue",
    ) -> None:
        if isinstance(lines, str):
            lines = (lines,)
        fill, border, _ = TONES[tone]
        shape = "box"
        style = "rounded,filled"
        size = 13.0
        penwidth = 1.3
        if kind == "decision":
            shape, style, size, penwidth = "diamond", "filled", 12.0, 1.45
        elif kind == "store":
            shape, style, size = "cylinder", "filled", 12.0
        elif kind == "note":
            shape, style, size = "note", "filled", 11.5
        elif kind == "term":
            style, size, penwidth = "rounded,filled", 14.0, 1.8
        elif kind == "box":
            shape, style = "box", "filled"
        max_units = max([self._units(title), *(self._units(line) for line in lines)])
        width_in = max(1.0, max_units * 0.080 + 0.32)
        self.lines.append(
            f'  {key} [shape={shape}, style="{style}", fillcolor="{fill}", '
            f'color="{border}", penwidth={penwidth:g}, fontsize={size:g}, '
            f"width={width_in:.2f}, label={plain_label(title, lines)}];"
        )

    def edge(
        self,
        src: str,
        dst: str,
        text: str = "",
        *,
        tone: str | None = None,
        style: str = "solid",
        weight: int | None = None,
    ) -> None:
        color = TONES[tone][2] if tone else "#64748B"
        attrs = [f'color="{color}"', f'style="{style}"']
        if text:
            attrs.append(f'label="{esc(text)}"')
        if weight is not None:
            attrs.append(f"weight={weight}")
        self.lines.append(f"  {src} -> {dst} [{', '.join(attrs)}];")

    def save(self) -> None:
        self.lines.append("}")
        path = OUT / f"{self.name.replace('_', '-')}.{LANG}.dot"
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8", newline="\n")
        print(path)


# ---------------------------------------------------------------------------
# flashcli run / serve
# ---------------------------------------------------------------------------


def flashcli_flow() -> None:
    g = Dot(
        "flashcli_flow",
        L("flashcli run / serve 执行流程", "flashcli run / serve execution flow"),
        L(
            "ref 解析 → 本地缓存 / FlashHub 同步 → 权重 / venv → bundle 进程内推理",
            "resolve ref → local cache / FlashHub sync → weights / venv → inference inside the bundle",
        ),
    )

    g.cluster(L("命令入口", "Command entry"), tone="blue")
    g.node("start", L("flashcli run | serve", "flashcli run | serve"),
           (L("<ref> [OPTIONS]，原始 argv", "<ref> [OPTIONS], raw argv"),
            L("cobra DisableFlagParsing", "cobra DisableFlagParsing")), kind="term", tone="blue")
    g.node("peel", L("peelHostFlags", "peelHostFlags"),
           (L("ref · --checkpoint · --mtp-checkpoint", "ref · --checkpoint · --mtp-checkpoint"),
            L("--quiet · --no-auto-install · -h", "--quiet · --no-auto-install · -h")), tone="indigo")
    g.node("help", L("仅 --help？", "help only?"), kind="decision", tone="amber")
    g.node("manifest", L("resolveManifestOnly", "resolveManifestOnly"),
           (L("本地 manifest 或只下载 flashcli-bundle.json", "local manifest, or download only flashcli-bundle.json"),), tone="amber")
    g.node("end_help", L("打印 bundle 选项，退出 0", "print bundle help, exit 0"), kind="term", tone="green")
    g.end_cluster()

    g.cluster(L("Bundle 树解析", "Bundle tree resolution"), tone="orange")
    g.node("ensure", "host.EnsureBundle(ref, quiet, force=false)",
           (L("force 恒为 false；run/serve 不调用 host.Pull", "force is always false; run/serve never call host.Pull"),), tone="blue")
    g.node("local", L("本地路径？", "local path?"), kind="decision", tone="amber")
    g.node("local_ret", L("abs path, version=local", "abs path, version=local"),
           (L("无网络，无 bundle 树同步", "no network, no tree sync"),), tone="blue")
    g.node("marker", L("FlashHub 标记存在？", "FlashHub marker present?"),
           (L("bundles/<name>/<ver>/.flashcli_bundle.json", "bundles/<name>/<ver>/.flashcli_bundle.json"),),
           kind="decision", tone="amber")
    g.node("reuse", L("复用 bundle 树（离线）", "reuse bundle tree (offline)"),
           (L("不校验文件、不访问网络", "no file validation, no network"),), tone="green")
    g.node("sync", L("DownloadManifest + SyncBundle", "DownloadManifest + SyncBundle"),
           (L("repo index → manifest", "repo index → manifest"),
            L("只下载选中的 runtime cell + 公共文件", "selected runtime cell + common files only"),
            L("MD5 校验；写 runtime / bundle 标记", "MD5 verify; write runtime / bundle markers")), tone="orange")
    g.end_cluster()

    g.cluster(L("Manifest 与环境", "Manifest and environment"), tone="violet")
    g.node("load", L("manifest.Load → ApplyEnv", "manifest.Load → ApplyEnv"),
           (L("v4 defaults + environments 合并", "merge v4 defaults + environments"),
            L("ResolveVariant · EntryFor(capability)", "ResolveVariant · EntryFor(capability)")), tone="violet")
    g.node("valid", L("manifest / env / entry 有效？", "manifest / env / entry valid?"),
           kind="decision", tone="amber")
    g.node("err_manifest", L("报错退出 1 / 2", "error exit 1 / 2"),
           (L("缺文件、协议版本、环境 key、变体、entry", "missing file, protocol, env key, variant, entry"),), kind="term", tone="red")
    g.node("markers", L("version == local？", "version == local?"), kind="decision", tone="amber")
    g.node("write_markers", L("writeLocalMarkers", "writeLocalMarkers"),
           (L("runtimes/<id>/.runtime.json", "runtimes/<id>/.runtime.json"),
            L("bundles/<id>/local/.flashcli_bundle.json", "bundles/<id>/local/.flashcli_bundle.json")), tone="amber")
    g.node("preflight", L("host.PreflightBundle", "host.PreflightBundle"),
           (L("HostEnvKey = SM + CUDA + Python ABI", "HostEnvKey = SM + CUDA + Python ABI"),
            L("识别 runtime cell 的原生 .so", "recognize native .so in the runtime cell"),
            L("host glibc / GLIBCXX / CXXABI 检查", "host glibc / GLIBCXX / CXXABI check"),
            L("FLASHCLI_SKIP_PREFLIGHT 可跳过", "skippable with FLASHCLI_SKIP_PREFLIGHT")), tone="violet")
    g.node("env_ok", L("runtime env key 匹配？", "runtime env key matched?"), kind="decision", tone="amber")
    g.node("err_env", L("环境不匹配，退出 2", "environment mismatch, exit 2"),
           (L("无 NVIDIA GPU 或该机器没有对应 cell", "no NVIDIA GPU or no matching cell"),), kind="term", tone="red")
    g.node("kind", L("entry.kind?", "entry.kind?"), kind="decision", tone="green")
    g.end_cluster()

    g.cluster(L("Python 运行时准备", "Python runtime preparation"), tone="pink")
    g.node("weights", L("host.ResolveWeights → PrepareBundle", "host.ResolveWeights → PrepareBundle"),
           (L("--checkpoint 覆盖 / FLASHCLI_SKIP_WEIGHTS", "--checkpoint override / FLASHCLI_SKIP_WEIGHTS"),
            L("store/<source>/<repo>@<rev>-<hash>", "store/<source>/<repo>@<rev>-<hash>"),
            L("extra_weights · extra_pull · post_pull", "extra_weights · extra_pull · post_pull"),
            L("allow / require 模式 + norm stats 就绪", "allow / require patterns + norm stats readiness"),
            L("host 下载清单 + 断点续传", "host download manifest + resume")), tone="amber")
    g.node("w_ok", L("权重就绪？", "weights ready?"), kind="decision", tone="amber")
    g.node("err_w", L("权重错误，退出 1", "weight error, exit 1"), kind="term", tone="red")
    g.node("sys1", L("EnsureSystemRequirements(m, \"\")", "EnsureSystemRequirements(m, \"\")"),
           (L("c/cxx 编译器、Python headers（venv 前）", "c/cxx compiler, Python headers (before venv)"),), tone="green")
    g.node("venv", L("venv.Ensure(runtimeID, manifest)", "venv.Ensure(runtimeID, manifest)"),
           (L("fingerprint = python_abi + torch index + deps", "fingerprint = python_abi + torch index + deps"),
            L("uv 默认 / pip 兜底", "uv by default / pip fallback"),
            L("flashcli-bundle[infer] + python_dependencies", "flashcli-bundle[infer] + python_dependencies"),
            L("共享 UV cache，hardlink 复用 torch/CUDA", "shared UV cache; hardlink torch/CUDA")), tone="pink")
    g.node("schema", L("EnsureProtocolCacheSchema", "EnsureProtocolCacheSchema"),
           (L("CACHE_SCHEMA_VERSION 变化时原地升级", "in-place upgrade when CACHE_SCHEMA_VERSION changes"),), tone="green")
    g.node("cuda", L("EnsureSystemRequirements(m, python) + cuda.Ensure", "EnsureSystemRequirements(m, python) + cuda.Ensure"),
           (L("headers 用实际解释器复查", "headers rechecked with the real interpreter"),
            L("CUDA SONAME 存在且可 dlopen", "CUDA SONAME present and dlopen-able"),
            L("缺失时可装 nvidia-cublas / cuda-runtime", "may install nvidia-cublas / cuda-runtime")), tone="cyan")
    g.node("exec", L("inferexec.Exec → syscall.Exec", "inferexec.Exec → syscall.Exec"),
           (L("python -m flashcli_bundle.infer <cap> <ref> ...", "python -m flashcli_bundle.infer <cap> <ref> ..."),
            L("HF_HUB_OFFLINE=1 + FLASHCLI_RUNTIME_ID", "HF_HUB_OFFLINE=1 + FLASHCLI_RUNTIME_ID"),
            L("FLASHCLI_BUNDLE_ROOT + VIRTUAL_ENV", "FLASHCLI_BUNDLE_ROOT + VIRTUAL_ENV")), kind="term", tone="green")
    g.end_cluster()

    g.cluster(L("Bundle 内执行（engine 模式）", "Inside the bundle (engine mode)"), tone="violet")
    g.node("infer", L("flashcli_bundle.infer 子进程", "flashcli_bundle.infer child"),
           (L("activate_for_preset: env key、布局、CUDA、.so", "activate_for_preset: env key, layout, CUDA, .so"),
            L("ensure_model_cached(download=False)", "ensure_model_cached(download=False)")), tone="violet")
    g.node("mode", L("entry mode?", "entry mode?"), kind="decision", tone="amber")
    g.node("engine", L("engine.load(checkpoint, preset, options)", "engine.load(checkpoint, preset, options)"),
           (L("RunEngine 或 ServeEngine", "RunEngine or ServeEngine"),), tone="violet")
    g.node("runp", L("run → predict()", "run → predict()"),
           (L("结果写 stdout，进程退出", "result on stdout, process exits"),), tone="blue")
    g.node("servep", L("serve → warmup() + build_app()", "serve → warmup() + build_app()"),
           (L("capabilities 决定挂载哪些标准路由", "capabilities decide the standard routes"),
            L("register_routes() 先于 host 路由挂载", "register_routes() mounts before host routes"),
            L("uvicorn 绑定 --host/--port（flashserver 用 127.0.0.1）", "uvicorn binds --host/--port (127.0.0.1 under flashserver)")), tone="green")
    g.node("script", L("script 模式", "script mode"),
           (L("main(argv) 自己处理一切", "main(argv) owns everything"),
            L("host 不挂路由；manifest env 不生效", "no host routes; manifest env is not applied")), tone="orange")
    g.node("flashrt", "FlashRT",
           (L("bundle 自带 flash_rt + .so", "bundle ships flash_rt + .so"),
            L("host 从不安装 FlashRT", "host never installs FlashRT")), kind="note", tone="slate")
    g.end_cluster()

    g.cluster(L("原生执行入口", "Native execution entries"), tone="cyan")
    g.node("native_exec", "native-exec",
           (L("权重准备后启动 bundle 可执行文件", "start the bundle executable after weights"),), tone="cyan")
    g.node("ne_transport", L("transport?", "transport?"), kind="decision", tone="amber")
    g.node("ne_http", L("http：输出 endpoint 后等待信号", "http: print endpoint, wait for signal"),
           (L("host 不代理；客户端直连", "host does not proxy; clients connect directly"),), tone="cyan")
    g.node("ne_stdio", L("stdio：serve 未实现", "stdio: serve not implemented"),
           (L("run 用 NDJSON run/health/shutdown", "run uses NDJSON run/health/shutdown"),), kind="term", tone="red")
    g.node("native_abi", "native-abi",
           (L("Open(preload, library, config)", "Open(preload, library, config)"),
            L("校验 abi_version=1 / struct_size", "validate abi_version=1 / struct_size")), tone="cyan")
    g.node("abi_session", L("声明 session_library?", "session_library declared?"), kind="decision", tone="amber")
    g.node("abi_plain", L("普通 native-abi", "plain native-abi"),
           (L("run 只做 ABI 探测并打印 JSON", "run probes the ABI and prints JSON"),
            L("serve 未实现", "serve not implemented")), kind="term", tone="red")
    g.node("abi_sess", L("Nexus session", "Nexus session"),
           (L("run: Apply → Tick → GetF32", "run: Apply → Tick → GetF32"),
            L("serve: /healthz /v1/act /v1/chat/completions", "serve: /healthz /v1/act /v1/chat/completions")), tone="cyan")
    g.end_cluster()

    g.node("offline", L("离线保证", "Offline guarantee"),
           (L("run/serve 本地优先：bundle 标记 + 完整权重 + venv fingerprint 命中时不联网", "run/serve are local-first: no network when the bundle marker, complete weights and venv fingerprint all match"),
            L("只有缺失资产、显式 pull 或 schema 升级才联网", "network only for missing artifacts, explicit pull, or a schema upgrade")),
           kind="note", tone="slate")

    g.edge("start", "peel")
    g.edge("peel", "help")
    g.edge("help", "manifest", L("是", "yes"), tone="amber")
    g.edge("manifest", "end_help", tone="green")
    g.edge("help", "ensure", L("否", "no"))
    g.edge("ensure", "local")
    g.edge("local", "local_ret", L("是", "yes"), tone="amber")
    g.edge("local", "marker", L("否", "no"))
    g.edge("marker", "reuse", L("是", "yes"), tone="green")
    g.edge("marker", "sync", L("否", "no"), tone="orange")
    g.edge("sync", "load", tone="orange")
    g.edge("reuse", "load", tone="green")
    g.edge("local_ret", "load")
    g.edge("load", "valid")
    g.edge("valid", "err_manifest", L("否", "no"), tone="red", style="dashed")
    g.edge("valid", "markers", L("是", "yes"), tone="green")
    g.edge("markers", "write_markers", L("是", "yes"), tone="amber")
    g.edge("markers", "preflight", L("否", "no"))
    g.edge("write_markers", "preflight", tone="amber")
    g.edge("preflight", "env_ok")
    g.edge("env_ok", "err_env", L("否", "no"), tone="red", style="dashed")
    g.edge("env_ok", "kind", L("是", "yes"), tone="green")
    g.edge("kind", "weights", L("python"), tone="pink")
    g.edge("kind", "native_exec", L("native-exec"), tone="cyan")
    g.edge("kind", "native_abi", L("native-abi"), tone="cyan")
    g.edge("weights", "w_ok")
    g.edge("w_ok", "err_w", L("否", "no"), tone="red", style="dashed")
    g.edge("w_ok", "sys1", L("是", "yes"), tone="green")
    g.edge("sys1", "venv", tone="green")
    g.edge("venv", "schema", tone="pink")
    g.edge("schema", "cuda", tone="green")
    g.edge("cuda", "exec", tone="cyan")
    g.edge("exec", "infer", tone="violet")
    g.edge("infer", "mode")
    g.edge("mode", "engine", L("engine"), tone="violet")
    g.edge("mode", "script", L("script"), tone="orange")
    g.edge("engine", "runp", L("run"), tone="blue")
    g.edge("engine", "servep", L("serve"), tone="green")
    g.edge("infer", "flashrt", L("import / dlopen", "import / dlopen"), style="dotted")
    g.edge("native_exec", "ne_transport", tone="cyan")
    g.edge("ne_transport", "ne_http", L("http"), tone="cyan")
    g.edge("ne_transport", "ne_stdio", L("stdio"), tone="red", style="dashed")
    g.edge("native_abi", "abi_session", tone="cyan")
    g.edge("abi_session", "abi_sess", L("是", "yes"), tone="cyan")
    g.edge("abi_session", "abi_plain", L("否", "no"), tone="red", style="dashed")
    g.edge("cuda", "offline", style="dotted")
    g.save()


# ---------------------------------------------------------------------------
# flashserver gateway (data plane request path)
# ---------------------------------------------------------------------------


def gateway_flow() -> None:
    g = Dot(
        "flashserver_gateway_flow",
        L("flashserver 网关请求流程", "flashserver gateway request flow"),
        L(
            "认证 → 路由 / 模型选择 → 磁盘与 capability 门禁 → 调度 → 代理 / 释放",
            "auth → route and model selection → disk and capability gates → schedule → proxy / release",
        ),
    )

    g.cluster(L("A. 请求与模型选择", "A. Request and model selection"), tone="blue")
    g.node("client", L("客户端", "Client"),
           (L("OpenAI SDK / Anthropic / App / Desktop", "OpenAI SDK / Anthropic / App / Desktop"),
            L("推理只走 /v1，永远拿不到子进程 endpoint", "inference uses /v1 only; child endpoints are never exposed")),
           kind="term", tone="blue")
    g.node("auth", L("token 已配置？", "token configured?"),
           (L("Bearer / X-Flashcli-Token", "Bearer / X-Flashcli-Token"),
            L("WS 可用 ?token=", "WS may use ?token=")), kind="decision", tone="violet")
    g.node("auth_ok", L("认证通过", "Authorized"),
           (L("/health / / /docs /openapi /ui 豁免", "/health / / /docs /openapi /ui exempt")), tone="green")
    g.node("e401", L("401 unauthorized", "401 unauthorized"), kind="term", tone="red")
    g.node("classify", L("路由归属？", "Route owner?"),
           (L("host 标准 / bundle 自定义 / 保留命名空间", "host standard / bundle custom / reserved")),
           kind="decision", tone="blue")
    g.node("models_ep", L("GET /v1/models · /v1/models/{id}", "GET /v1/models · /v1/models/{id}"),
           (L("本地 registry；不做 model 选择", "local registry; no model selection"),
            L("带 anthropic-version 时返回 Anthropic 形状", "Anthropic shape with anthropic-version")), tone="slate")
    g.node("std_sel", L("标准推理路由选择 model", "Standard inference route model source"),
           (L("JSON body：chat/completions/responses/...", "JSON body: chat/completions/responses/..."),
            L("multipart form：audio/images/videos（videos 也接受 JSON）", "multipart form: audio/images/videos (videos also accepts JSON)"),
            L("query：realtime / video jobs / response jobs", "query: realtime / video jobs / response jobs")), tone="blue")
    g.node("custom_sel", L("自定义 /v1/* 选择 model", "Custom /v1/* model source"),
           (L("JSON 对象 model / multipart form / ?model=", "JSON object model / multipart form / ?model="),
            L("其他 content-type：?model=，body 原样流式转发", "other content types: ?model=, body streamed unchanged")), tone="cyan")
    g.node("reserved", L("保留命名空间未知路径", "Unknown reserved path"),
           (L("/v1/models* /v1/responses/* /v1/videos/*", "/v1/models* /v1/responses/* /v1/videos/*")), tone="orange")
    g.node("e405", L("405 method_not_allowed", "405 method_not_allowed"),
           (L("或 404 route not found；绝不当作 custom", "or 404 route not found; never treated as custom")), kind="term", tone="red")
    g.node("resolve", L("resolveGatewayModel", "resolveGatewayModel"),
           (L("body / query 都是完整 ref", "body / query must be a full ref"),
            L("body 与 query 同时存在时必须相同", "body and query must match when both exist")), tone="violet")
    g.node("e400", L("400 model_conflict / required / invalid", "400 model_conflict / required / invalid"),
           (L("空值、短名、别名都不接受", "empty value, short name and alias are rejected")), kind="term", tone="red")
    g.node("ref", L("ref = namespace/name:version", "ref = namespace/name:version"),
           (L("缓存 key、调度 key、resident key 都是它", "the same value keys cache, scheduler and resident")), tone="green")
    g.end_cluster()

    g.cluster(L("B. 磁盘与契约门禁（prepareGateway）", "B. Disk and contract gates (prepareGateway)"), tone="amber")
    g.node("assets", L("资产就绪或 preloadReady？", "Assets ready or preloadReady?"),
           (L("bundle + weights + runtime 都来自共享 host cache", "bundle + weights + runtime come from the shared host cache"),),
           kind="decision", tone="amber")
    g.node("no_pull", L("404 model_not_found", "404 model_not_found"),
           (L("auto_pull=false，模型未预加载", "auto_pull=false and the model is not preloaded")), kind="term", tone="red")
    g.node("ensure_preload", L("ensurePreload", "ensurePreload"),
           (L("assetsReady → preloaded", "assetsReady → preloaded"),
            L("否则启动 host.Pull 后台 job（并发请求共享）", "otherwise start a host.Pull job shared by concurrent requests")), tone="orange")
    g.node("e503prep", L("503 model_preparing", "503 model_preparing"),
           (L("Retry-After + X-Flashcli-Preload-Job", "Retry-After + X-Flashcli-Preload-Job")), kind="term", tone="red")
    g.node("inspect", L("inspectRef → inspectBundle", "inspectRef → inspectBundle"),
           (L("host.EnsureBundle + manifest.Load", "host.EnsureBundle + manifest.Load"),
            L("Resources + ServeCapabilities", "Resources + ServeCapabilities")), tone="violet")
    g.node("e404", L("404 model_not_found", "404 model_not_found"),
           (L("bundle 或 manifest 不可读", "bundle or manifest is not readable")), kind="term", tone="red")
    g.node("runonly", L("有 serve entry？", "Has a serve entry?"), kind="decision", tone="amber")
    g.node("e_runonly", L("400 model_not_servable", "400 model_not_servable"), kind="term", tone="red")
    g.node("capability", L("标准路由 capability 已声明？", "Standard-route capability declared?"),
           (L("custom 路由跳过此门禁", "custom routes skip this gate")), kind="decision", tone="amber")
    g.node("e_cap", L("400 unsupported_capability", "400 unsupported_capability"), kind="term", tone="red")
    g.node("sched_ok", L("Scheduler 已配置？", "Scheduler configured?"), kind="decision", tone="amber")
    g.node("e_nosched", L("503 no_placement", "503 no_placement"), kind="term", tone="red")
    g.end_cluster()

    g.cluster(L("C. 调度与租约（细节见 scheduler 流程图）", "C. Schedule and lease (details in the scheduler diagram)"), tone="green")
    g.node("acquire", L("Scheduler.Acquire(ref)", "Scheduler.Acquire(ref)"),
           (L("等待 resident 启动 / 排队；默认 10s + 30s", "wait for start / queue; default 10s + 30s"),
            L("placement、LRU、队列见下一张图", "placement, LRU and queue are in the next diagram")), tone="green")
    g.node("lease", L("Lease（active_requests++）", "Lease (active_requests++)"),
           (L("阻止 LRU 淘汰、idle stop、force unload", "blocks LRU eviction, idle stop and force unload")), tone="green")
    g.node("e_queue", L("429 / 503 / 499", "429 / 503 / 499"),
           (L("queue_full / no_placement", "queue_full / no_placement"),
            L("model_starting / client_closed", "model_starting / client_closed")), kind="term", tone="red")
    g.end_cluster()

    g.cluster(L("D. 代理与释放", "D. Proxy and release"), tone="cyan")
    g.node("endpoint", L("Manager.Endpoint(ref)", "Manager.Endpoint(ref)"),
           (L("完整 ref 精确匹配；不按“唯一 resident”猜", "exact full-ref match; never guesses from a single resident")), tone="cyan")
    g.node("e_endpoint", L("503 model_starting", "503 model_starting"), kind="term", tone="red")
    g.node("proxy", L("proxyGateway", "proxyGateway"),
           (L("method / path / query / body 原样转发", "method / path / query / body forwarded unchanged"),
            L("剥离 host / auth / token / cookie / accept-encoding", "strips host / auth / token / cookie / accept-encoding"),
            L("客户端关闭 → cancel 上游请求", "client close → cancel upstream")), tone="cyan")
    g.node("rewrite", L("响应 model 重写", "Response model rewrite"),
           (L("SSE：逐条 data: 重写", "SSE: rewrite each data: line"),
            L("JSON ≤32MiB：顶层字符串 model 重写", "JSON ≤32MiB: rewrite top-level string model"),
            L("其他 / 超大：逐字节透传", "other / oversized: stream bytes")), tone="blue")
    g.node("release", L("lease.Release", "lease.Release"),
           (L("leases--；busy → ready；last_used=now", "leases--; busy → ready; last_used=now")), tone="green")
    g.node("idle", L("idle reaper（每秒）", "idle reaper (1s)"),
           (L("ready + leases=0 且超过 idle_stop_seconds → stop", "ready + leases=0 past idle_stop_seconds → stop")), tone="amber")
    g.end_cluster()

    g.node("mgmt_note", L("控制面不是推理路径", "Control plane is not the inference path"),
           (L("/api/v1/models/preload 只准备磁盘：inspectRef → checkPreloadVRAM(总显存) → host.Pull job", "/api/v1/models/preload prepares disk only: inspectRef → checkPreloadVRAM(total VRAM) → host.Pull job"),
            L("/api/v1/models/unload：busy 时 force / wait → stopResident → RemoveCachedRef", "/api/v1/models/unload: force / wait when busy → stopResident → RemoveCachedRef")),
           kind="note", tone="slate")

    g.edge("client", "auth")
    g.edge("auth", "auth_ok", L("是 / 未配置", "yes / unset"), tone="green")
    g.edge("auth", "e401", L("否", "no"), tone="red", style="dashed")
    g.edge("auth_ok", "classify")
    g.edge("classify", "models_ep", L("models", "models"))
    g.edge("classify", "std_sel", L("host 标准", "host standard"))
    g.edge("classify", "custom_sel", L("自定义", "custom"), tone="cyan")
    g.edge("classify", "reserved", L("保留前缀", "reserved"), tone="orange")
    g.edge("reserved", "e405", tone="red", style="dashed")
    g.edge("std_sel", "resolve")
    g.edge("custom_sel", "resolve", tone="cyan")
    g.edge("resolve", "ref", L("ok"), tone="green")
    g.edge("resolve", "e400", L("失败", "fail"), tone="red", style="dashed")
    g.edge("ref", "assets")
    g.edge("assets", "no_pull", L("否 + 禁自动拉取", "no + auto-pull off"), tone="red", style="dashed")
    g.edge("assets", "ensure_preload", L("否 + auto_pull", "no + auto_pull"), tone="orange")
    g.edge("ensure_preload", "e503prep", L("job", "job"), tone="orange", style="dashed")
    g.edge("assets", "inspect", L("是", "yes"), tone="green")
    g.edge("ensure_preload", "inspect", L("ready", "ready"), tone="green", style="dashed")
    g.edge("inspect", "e404", L("错误", "error"), tone="red", style="dashed")
    g.edge("inspect", "runonly")
    g.edge("runonly", "e_runonly", L("否", "no"), tone="red", style="dashed")
    g.edge("runonly", "capability", L("是", "yes"), tone="green")
    g.edge("capability", "e_cap", L("否", "no"), tone="red", style="dashed")
    g.edge("capability", "sched_ok", L("是 / custom", "yes / custom"), tone="green")
    g.edge("sched_ok", "e_nosched", L("否", "no"), tone="red", style="dashed")
    g.edge("sched_ok", "acquire", L("是", "yes"), tone="green")
    g.edge("acquire", "lease", L("ok"), tone="green")
    g.edge("acquire", "e_queue", L("失败", "fail"), tone="red", style="dashed")
    g.edge("lease", "endpoint")
    g.edge("endpoint", "e_endpoint", L("缺失", "missing"), tone="red", style="dashed")
    g.edge("endpoint", "proxy", L("ok"), tone="cyan")
    g.edge("proxy", "rewrite")
    g.edge("proxy", "release", L("完成 / 断开", "done / closed"), tone="green")
    g.edge("release", "idle", style="dotted")
    g.edge("idle", "mgmt_note", style="invis")
    g.save()


# ---------------------------------------------------------------------------
# flashserver scheduler (placement and resident lifecycle)
# ---------------------------------------------------------------------------


def scheduler_flow() -> None:
    g = Dot(
        "flashserver_scheduler_flow",
        L("flashserver 调度与 resident 生命周期", "flashserver scheduler and resident lifecycle"),
        L(
            "max_loaded=0 表示不限制槽位；准入由 runtime cell、空闲显存和 CPU 策略决定",
            "max_loaded=0 means no slot limit; admission is driven by runtime cells, free VRAM and CPU policy",
        ),
    )

    g.cluster(L("A. Acquire 循环", "A. Acquire loop"), tone="blue")
    g.node("acquire", "Scheduler.Acquire(ctx, ref)",
           (L("deadline = now + queue_timeout_seconds", "deadline = now + queue_timeout_seconds"),
            L("每次循环重新 Inspect + Inventory（锁外）", "Inspect + Inventory outside the lock on every loop")), kind="term", tone="blue")
    g.node("state", L("resident 状态？", "resident state?"), kind="decision", tone="violet")
    g.node("lease_hit", L("leases++；ready → busy", "leases++; ready → busy"),
           (L("last_used=now；返回 Lease", "last_used=now; return Lease")), tone="green")
    g.node("wait_call", L("等待 starting / stopping 完成", "wait for starting / stopping"),
           (L("共享同一个 startCall / stopCall", "shares one startCall / stopCall"),), tone="amber")
    g.node("plan", L("planLocked(ref, info, inventory)", "planLocked(ref, info, inventory)"), tone="violet")
    g.end_cluster()

    g.cluster(L("B. 准入判断", "B. Admission"), tone="amber")
    g.node("active", L("active = residents + manager slots", "active = residents + manager slots"),
           (L("starting / ready / busy 都算占用", "starting / ready / busy all count"),), tone="amber")
    g.node("slot", L("max_loaded > 0 且 active >= max？", "max_loaded > 0 and active >= max?"),
           kind="decision", tone="amber")
    g.node("idle", L("存在 idle resident？", "Idle resident exists?"), kind="decision", tone="amber")
    g.node("evict", L("evictIdle → LRU", "evictIdle → LRU"),
           (L("只淘汰 ready 且 leases=0", "only ready residents with leases=0"),
            L("等 300ms 让驱动释放显存", "wait 300ms for the driver to release VRAM"),
            L("磁盘资产保留", "disk assets are kept")), tone="orange")
    g.node("no_slot", L("no_placement: resource_exhausted", "no_placement: resource_exhausted"), kind="term", tone="red")
    g.node("place", L("placementFor(manifest, inventory)", "placementFor(manifest, inventory)"),
           (L("runtime cell：SM + CUDA + Python ABI", "runtime cell: SM + CUDA + Python ABI"),
            L("每 GPU 空闲显存 ≥ min_vram_mib + headroom", "free VRAM per GPU ≥ min_vram_mib + headroom"),
            L("满足 gpu_count；legacy 无声明用 6144MiB 下限", "satisfies gpu_count; legacy bundles use a 6144MiB floor"),
            L("starting resident 的显存先扣减", "VRAM of starting residents is reserved first")), tone="cyan")
    g.node("cpu", L("无 GPU cell → CPU 兜底", "No GPU cell → CPU fallback"),
           (L("需有 CPU runtime cell；声明 min_ram_mib 时检查空闲内存", "requires a CPU runtime cell; checks free RAM when min_ram_mib is declared"),
            L("cpu_fallback=disabled 时禁止", "forbidden when cpu_fallback=disabled")), tone="teal")
    g.node("place_result", L("placement 结果", "Placement result"), kind="decision", tone="amber")
    g.node("plan_ok", L("plan：GPU 列表 + CUDA_VISIBLE_DEVICES", "plan: GPU list + CUDA_VISIBLE_DEVICES"),
           (L("无 manifest（legacy/测试）不限制设备", "no manifest (legacy/test) leaves the device unconstrained")), tone="green")
    g.node("no_runtime", L("no_placement: no_compatible_runtime", "no_placement: no_compatible_runtime"),
           (L("永久错误，不排队", "permanent error, never queued")), kind="term", tone="red")
    g.node("queue", L("enqueue（QueueMax 默认 16）", "enqueue (QueueMax default 16)"),
           (L("只对 resource_exhausted 且已有活动 resident", "only for resource_exhausted with an active resident"),
            L("等待 notify / deadline / ctx", "wait for notify / deadline / ctx")), tone="amber")
    g.node("queue_full", L("429 queue_full", "429 queue_full"), kind="term", tone="red")
    g.node("queue_timeout", L("deadline → 返回 no_placement", "deadline → return no_placement"), kind="term", tone="red")
    g.end_cluster()

    g.cluster(L("C. 启动 resident", "C. Start resident"), tone="green")
    g.node("start", L("startResident（后台 context）", "startResident (background context)"),
           (L("客户端超时不会取消加载", "a client timeout does not cancel loading"),), tone="green")
    g.node("loadsched", L("Manager.LoadScheduled(ref, env)", "Manager.LoadScheduled(ref, env)"),
           (L("跳过管理面 slot/VRAM 检查（调度器已准入）", "skips admin slot/VRAM checks (scheduler admitted)"),
            L("owner=scheduler，不持久化到 models.json", "owner=scheduler; never persisted to models.json")), tone="green")
    g.node("child", L("flashcli serve <ref>", "flashcli serve <ref>"),
           (L("--host 127.0.0.1 --port <free>", "--host 127.0.0.1 --port <free>"),
            L("日志 ~/.flashcli/logs/serve/<ref>.log", "log ~/.flashcli/logs/serve/<ref>.log"),
            L("WaitHealthy 最多 120s（/health → /healthz）", "WaitHealthy up to 120s (/health → /healthz)")), tone="orange")
    g.node("start_result", L("启动结果", "Start result"), kind="decision", tone="amber")
    g.node("ready", L("resident = ready", "resident = ready"),
           (L("广播 resident_started；等待请求", "broadcast resident_started; wait for requests")), tone="green")
    g.node("failed", L("删除 resident；广播失败", "delete resident; broadcast failure"),
           (L("OOM 且未声明 min_vram → 提示补声明", "OOM without min_vram → hint to declare it")), kind="term", tone="red")
    g.node("race", L("force stop 抢先？", "Force stop raced?"),
           (L("卸载新进程，唤醒 start/stop 等待者", "unload the new process; wake both waiters")), kind="decision", tone="red")
    g.end_cluster()

    g.cluster(L("D. 释放 / 回收 / 外部状态", "D. Release / reap / external state"), tone="amber")
    g.node("release", L("lease.Release（幂等）", "lease.Release (idempotent)"),
           (L("只对同一 resident generation 生效", "only affects the same resident generation"),
            L("leases=0 且 busy → ready", "leases=0 and busy → ready")), tone="green")
    g.node("reap", L("reap（每秒）", "reap (every second)"),
           (L("ready + leases=0 + last_used < now-idle_stop", "ready + leases=0 + last_used < now-idle_stop"),
            L("stopResident → Manager.Unload", "stopResident → Manager.Unload")), tone="amber")
    g.node("force", L("Scheduler.Stop / force unload", "Scheduler.Stop / force unload"),
           (L("leases 清零；活动请求按取消处理", "zero leases; active requests are treated as cancelled")), tone="red")
    g.node("reconcile", L("reconcileLocked", "reconcileLocked"),
           (L("Manager 报告进程已死 → 丢弃 resident", "Manager reports a dead process → drop the resident"),
            L("下一个请求重新启动，不复用死端点", "the next request starts fresh instead of reusing a dead endpoint")), tone="amber")
    g.node("telemetry", L("States / Snapshot", "States / Snapshot"),
           (L("GET /api/v1/scheduler：reservations、queue、leases", "GET /api/v1/scheduler: reservations, queue, leases")), kind="store", tone="slate")
    g.end_cluster()

    g.edge("acquire", "state")
    g.edge("state", "lease_hit", L("ready / busy"), tone="green")
    g.edge("state", "wait_call", L("starting / stopping"), tone="amber")
    g.edge("wait_call", "acquire", L("done", "done"), style="dashed")
    g.edge("state", "plan", L("无 resident", "absent"))
    g.edge("plan", "active")
    g.edge("active", "slot")
    g.edge("slot", "idle", L("是", "yes"), tone="amber")
    g.edge("idle", "evict", L("是", "yes"), tone="orange")
    g.edge("idle", "no_slot", L("否", "no"), tone="red", style="dashed")
    g.edge("evict", "plan", L("重试", "retry"), style="dashed")
    g.edge("slot", "place", L("否", "no"), tone="green")
    g.edge("place", "cpu", L("无 GPU cell", "no GPU cell"), tone="teal")
    g.edge("place", "place_result", tone="cyan")
    g.edge("cpu", "place_result", tone="teal")
    g.edge("place_result", "plan_ok", L("GPU / CPU", "GPU / CPU"), tone="green")
    g.edge("place_result", "no_runtime", L("无兼容 cell", "no compatible cell"), tone="red", style="dashed")
    g.edge("place_result", "queue", L("显存不足", "VRAM short"), tone="amber")
    g.edge("queue", "queue_full", L("满", "full"), tone="red", style="dashed")
    g.edge("queue", "queue_timeout", L("超时", "timeout"), tone="red", style="dashed")
    g.edge("queue", "acquire", L("notify", "notify"), style="dashed")
    g.edge("plan_ok", "start")
    g.edge("start", "loadsched")
    g.edge("loadsched", "child", tone="orange")
    g.edge("child", "start_result")
    g.edge("start_result", "ready", L("healthy"), tone="green")
    g.edge("start_result", "failed", L("失败", "fail"), tone="red", style="dashed")
    g.edge("start", "race", L("stop 请求", "stop request"), tone="red", style="dotted")
    g.edge("race", "failed", L("是", "yes"), tone="red", style="dashed")
    g.edge("ready", "release", L("请求结束", "request ends"), tone="green")
    g.edge("release", "reap", style="dotted")
    g.edge("force", "reap", style="dotted")
    g.edge("reap", "reconcile", style="dotted")
    g.edge("ready", "telemetry", style="dotted")
    g.edge("queue", "telemetry", style="dotted")
    g.save()


# ---------------------------------------------------------------------------
# Bundle / FlashRT runtime stack
# ---------------------------------------------------------------------------


def bundle_stack() -> None:
    g = Dot(
        "bundle_runtime_stack",
        L("Model Bundle 与 FlashRT 运行时栈", "Model Bundle and FlashRT runtime stack"),
        L(
            "清单契约 → host 准备 bundle / venv / 权重 → 三种 entry 执行 → bundle 自带 FlashRT",
            "manifest contract → host prepares bundle / venv / weights → three entry kinds → bundle ships FlashRT",
        ),
    )

    g.cluster(L("A. FlashHub 产物与权重源", "A. FlashHub artifacts and weight sources"), tone="orange")
    g.node("repo", L("Bundle 版本", "Bundle version"),
           (L("namespace/name:version", "namespace/name:version"),
            L("flashcli-bundle.json + 各 runtime cell", "flashcli-bundle.json + runtime cells"),
            L("weights 只记录来源，不打包", "weights record their source; they are never packaged")), kind="store", tone="orange")
    g.node("weights_src", L("权重源", "Weight source"),
           (L("HuggingFace / ModelScope / bundled", "HuggingFace / ModelScope / bundled"),
            L("repo + revision + allow patterns", "repo + revision + allow patterns")), kind="store", tone="amber")
    g.end_cluster()

    g.cluster(L("B. Manifest 契约（v4）", "B. Manifest contract (v4)"), tone="red")
    g.node("identity", L("版本轴", "Version axes"),
           (L("format_version 3 / 4", "format_version 3 / 4"),
            L("protocol_version = 1", "protocol_version = 1"),
            L("runtime_abi_version = 1（native-abi）", "runtime_abi_version = 1 (native-abi)"),
            L("exec_protocol_version = 1（native-exec）", "exec_protocol_version = 1 (native-exec)")), tone="red")
    g.node("env", L("defaults + environments", "defaults + environments"),
           (L("按 SM / CUDA / Python ABI 选 env key", "select env key by SM / CUDA / Python ABI"),
            L("精确 key 优先，其次 match 兜底", "exact key first, then match fallback"),
            L("选中后合并为有效 manifest", "merge into the effective manifest")), tone="violet")
    g.node("entry", L("entry.run / entry.serve", "entry.run / entry.serve"),
           (L("kind: python | native-exec | native-abi", "kind: python | native-exec | native-abi"),
            L("mode: engine | script（仅 python）", "mode: engine | script (python only)"),
            L("capabilities + concurrency", "capabilities + concurrency")), tone="violet")
    g.node("resources", L("resources / system / options", "resources / system / options"),
           (L("min_vram_mib · gpu_count · min_ram_mib", "min_vram_mib · gpu_count · min_ram_mib"),
            L("c/cxx compiler · python headers", "c/cxx compiler · python headers"),
            L("run_options / serve_options 的默认值", "run_options / serve_options defaults")), tone="amber")
    g.node("deps", L("python_dependencies", "python_dependencies"),
           (L("torch index + pip 列表", "torch index + pip list"),
            L("必须与 runtime cell 的 -py<abi> 一致", "must match the runtime cell's -py<abi>")), tone="pink")
    g.node("weights_meta", L("weights / extra_weights", "weights / extra_weights"),
           (L("source · repo · revision", "source · repo · revision"),
            L("allow_patterns · require_any_patterns", "allow_patterns · require_any_patterns"),
            L("require_norm_stats · weights_dir", "require_norm_stats · weights_dir"),
            L("post_pull / extra_pull", "post_pull / extra_pull")), tone="amber")
    g.end_cluster()

    g.cluster(L("C. Host 准备（共享 cache 层）", "C. Host preparation (shared cache layer)"), tone="green")
    g.node("ensure_bundle", L("host.EnsureBundle", "host.EnsureBundle"),
           (L("本地路径直接使用", "local paths are used directly"),
            L("FlashHub：标记或 index → manifest → SyncBundle", "FlashHub: marker or index → manifest → SyncBundle"),
            L("只取选中的 runtime cell", "only the selected runtime cell is fetched"),
            L("写 .flashcli_bundle.json + .runtime.json", "writes .flashcli_bundle.json + .runtime.json")), tone="blue")
    g.node("preflight", L("PreflightBundle", "PreflightBundle"),
           (L("env key 必须匹配本机", "env key must match this host"),
            L("识别 .so；host glibc / GLIBCXX / CXXABI", "recognize .so; host glibc / GLIBCXX / CXXABI")), tone="violet")
    g.node("venv", L("venv.Ensure", "venv.Ensure"),
           (L("runtimes/<runtime_id>/venv", "runtimes/<runtime_id>/venv"),
            L("uv 默认；pip 是退役兜底", "uv by default; pip is a deprecated fallback"),
            L("fingerprint 命中即离线复用", "offline reuse when the fingerprint matches")), tone="pink")
    g.node("weights", L("weights.PrepareBundle", "weights.PrepareBundle"),
           (L("models/store/<source>/<repo>@<rev>-<hash>", "models/store/<source>/<repo>@<rev>-<hash>"),
            L("主权重 + extra_weights + extra_pull", "main weights + extra_weights + extra_pull"),
            L("host 完整性：.flashcli_download.json", "host completeness: .flashcli_download.json"),
            L("bundle 就绪：allow/require + norm stats", "bundle readiness: allow/require + norm stats"),
            L("post_pull：paligemma 等", "post_pull: paligemma and similar")), tone="amber")
    g.node("protocol", L("Protocol schema", "Protocol schema"),
           (L("CACHE_SCHEMA_VERSION 变化时只升级", "on CACHE_SCHEMA_VERSION change, upgrade only"),
            L("flashcli-bundle，不重装 torch", "flashcli-bundle; torch remains")), tone="green")
    g.end_cluster()

    g.cluster(L("D. 执行入口", "D. Execution entries"), tone="cyan")
    g.node("py_engine", L("python + engine", "python + engine"),
           (L("import bundle.entry；实例化 RunEngine/ServeEngine", "import bundle.entry; instantiate RunEngine/ServeEngine"),
            L("load(checkpoint, preset, options)", "load(checkpoint, preset, options)")), tone="violet")
    g.node("py_run", L("run → predict()", "run → predict()"), tone="blue")
    g.node("py_serve", L("serve → warmup() + build_app()", "serve → warmup() + build_app()"),
           (L("标准路由由 flashcli-bundle 挂载", "standard routes are mounted by flashcli-bundle"),
            L("register_routes() 可覆盖/新增路由", "register_routes() may override or add routes")), tone="green")
    g.node("script", L("python + script", "python + script"),
           (L("main(argv) 自己创建服务器/协议", "main(argv) creates its own server/protocol"),
            L("host 不挂路由；manifest env 不生效", "no host routes; manifest env is not applied")), tone="orange")
    g.node("native_exec", L("native-exec", "native-exec"),
           (L("可执行文件 + NDJSON 或 HTTP", "executable + NDJSON or HTTP"),
            L("serve(stdio) 未实现；run 可用", "serve over stdio is not implemented; run works")), tone="cyan")
    g.node("native_abi", L("native-abi", "native-abi"),
           (L("dlopen 生产库 + config JSON", "dlopen producer library + config JSON"),
            L("普通 run 只探测 ABI；session 才能推理", "plain run only probes the ABI; sessions run inference")), tone="cyan")
    g.node("flashrt", "FlashRT",
           (L("bundle 的 flash_rt/ 与 runtime/<env>/ 下 .so", "bundle's flash_rt/ and .so under runtime/<env>/"),
            L("register_native_modules 先注册，再 import", "register_native_modules runs before import"),
            L("host 只检查 ABI，不安装内核", "host checks the ABI; it never installs kernels")), kind="note", tone="slate")
    g.end_cluster()

    g.node("readiness", L("完整性 ≠ 就绪", "Completeness ≠ readiness"),
           (L("host 只负责文件是否下载完整；bundle 负责 allow/require/norm stats 是否可用", "host owns download completeness; the bundle owns allow/require/norm-stats readiness"),
            L("present-but-incomplete 永不接受；legacy 无标记且就绪可离线接受", "a present-but-incomplete manifest is never accepted; a ready legacy cache is accepted offline")),
           kind="note", tone="amber")

    g.edge("repo", "env", L("解析", "parse"))
    g.edge("repo", "identity", L("校验", "validate"), tone="red")
    g.edge("identity", "env")
    g.edge("env", "entry")
    g.edge("env", "resources")
    g.edge("env", "deps")
    g.edge("env", "weights_meta")
    g.edge("repo", "ensure_bundle", L("同步", "sync"), tone="orange")
    g.edge("ensure_bundle", "preflight")
    g.edge("preflight", "venv", L("Python cell", "Python cell"), tone="pink")
    g.edge("preflight", "weights", L("native cell", "native cell"), tone="amber", style="dashed")
    g.edge("venv", "protocol")
    g.edge("weights", "protocol", style="dotted")
    g.edge("preflight", "py_engine", L("entry.kind", "entry.kind"), tone="violet")
    g.edge("preflight", "native_exec", L("native-exec", "native-exec"), tone="cyan")
    g.edge("preflight", "native_abi", L("native-abi", "native-abi"), tone="cyan")
    g.edge("entry", "py_engine", L("engine"), tone="violet", style="dotted")
    g.edge("entry", "script", L("script"), tone="orange", style="dotted")
    g.edge("py_engine", "py_run", L("run"), tone="blue")
    g.edge("py_engine", "py_serve", L("serve"), tone="green")
    g.edge("py_engine", "flashrt", L("import / dlopen", "import / dlopen"), style="dotted")
    g.edge("native_exec", "flashrt", style="dotted")
    g.edge("native_abi", "flashrt", style="dotted")
    g.edge("deps", "venv", L("安装", "install"), tone="pink", style="dashed")
    g.edge("weights_src", "weights_meta", L("声明", "declare"), tone="amber", style="dashed")
    g.edge("weights_meta", "weights", L("模式 / 下载 / 就绪", "patterns / download / readiness"), tone="amber", style="dashed")
    g.edge("weights", "readiness", style="dotted")
    g.save()


# ---------------------------------------------------------------------------
# FlashHub publish / consume
# ---------------------------------------------------------------------------


def flashhub_flow() -> None:
    g = Dot(
        "flashhub_flow",
        L("FlashHub 发布与消费流程", "FlashHub publish and consume flow"),
        L(
            "仓库内只负责 build / pack / validate；上传是人工步骤，消费端通过 HTTP 解析与同步",
            "this repo builds, packs and validates; upload is manual, consumers resolve and sync over HTTP",
        ),
    )

    g.cluster(L("A. 发布方（Bundle / App）", "A. Publishers (bundle / app)"), tone="orange")
    g.node("build", L("bundles/<name>/build.sh", "bundles/<name>/build.sh"),
           (L("编译 FlashRT，组装 runtime cell", "compile FlashRT, assemble runtime cells"),
            L("本地当前环境或 Docker 矩阵", "current host or Docker matrix")), tone="orange")
    g.node("pack", L("scripts/pack_bundle.sh", "scripts/pack_bundle.sh"),
           (L("只复制 RELEASE_PACK_FILES", "copies only RELEASE_PACK_FILES"),
            L("选择 runtime cell，重写 dist/flashcli-bundle.json", "selects runtime cells, rewrites dist/flashcli-bundle.json"),
            L("写入 build 来源；不打包权重", "writes build provenance; never packages weights")), tone="amber")
    g.node("validate", L("flashcli bundle validate", "flashcli bundle validate"),
           (L("协议 / entry / capabilities / resources", "protocol / entry / capabilities / resources"),
            L("runtime cell 与 .so ABI 探测", "runtime cell and .so ABI probe"),
            L("校验的是源目录，不是 dist", "validates the source tree, not dist")), tone="violet")
    g.node("upload", L("人工上传 dist/", "manual dist/ upload"),
           (L("仓库内没有上传客户端", "no upload client in this repo"),
            L("保留相对路径；版本即 ref", "preserve relative paths; the version is the ref")), kind="term", tone="red")
    g.node("app_author", L("App 作者", "App author"),
           (L("app manifest + install/setup scripts", "app manifest + install/setup scripts"),), tone="violet")
    g.end_cluster()

    g.cluster(L("B. FlashHub 服务", "B. FlashHub service"), tone="red")
    g.node("repo_api", L("Repo index", "Repo index"),
           (L("GET /api/v1/repos/{ns}/{name}:{ver}", "GET /api/v1/repos/{ns}/{name}:{ver}"),
            L("返回 files[] + download_url + md5", "returns files[] + download_url + md5")), kind="store", tone="red")
    g.node("catalog_api", L("Catalog API", "Catalog API"),
           (L("/repositories · /repositories/{id}", "/repositories · /repositories/{id}"),
            L("/repositories/{id}/versions · /tags", "/repositories/{id}/versions · /tags"),
            L("release_status 只读展示", "release_status is read-only")), kind="store", tone="orange")
    g.node("app_api", L("App registry", "App registry"),
           (L("GET /api/v1/apps/{org}/{name}[:ver]", "GET /api/v1/apps/{org}/{name}[:ver]"),
            L("app manifest + setup scripts + default bundles", "app manifest + setup scripts + default bundles")), kind="store", tone="violet")
    g.end_cluster()

    g.cluster(L("C. CLI 消费", "C. CLI consumers"), tone="green")
    g.node("pull", L("flashcli pull", "flashcli pull"),
           (L("host.EnsureBundle → host.EnsureRuntime", "host.EnsureBundle → host.EnsureRuntime"),
            L("→ weights.PrepareBundle(verifyRemote=true)", "→ weights.PrepareBundle(verifyRemote=true)")), tone="green")
    g.node("runserve", L("flashcli run / serve", "flashcli run / serve"),
           (L("EnsureBundle + ResolveWeights（本地优先）", "EnsureBundle + ResolveWeights (local-first)"),
            L("不调用 host.Pull", "does not call host.Pull")), tone="teal")
    g.end_cluster()

    g.cluster(L("D. flashserver / Desktop 消费", "D. flashserver / Desktop consumers"), tone="violet")
    g.node("srv_catalog", L("flashserver /api/v1/catalog", "flashserver /api/v1/catalog"),
           (L("代理 ListRepositories / GetRepository / ListVersions", "proxies ListRepositories / GetRepository / ListVersions"),
            L("每次请求实时访问，无 5 分钟缓存", "live request every time; no 5-minute cache")), tone="violet")
    g.node("srv_preload", L("POST /api/v1/models/preload", "POST /api/v1/models/preload"),
           (L("job → host.Pull（bundle + venv + weights）", "job → host.Pull (bundle + venv + weights)"),
            L("只准备磁盘；resident 由调度器按需启动", "disk only; the scheduler starts residents on demand")), tone="violet")
    g.node("srv_app", L("POST /api/v1/apps/.../install", "POST /api/v1/apps/.../install"),
           (L("FetchAppManifest → 平台/脚本决策", "FetchAppManifest → platform/script decision"),
            L("default bundles → host.Pull", "default bundles → host.Pull"),
            L("setup 只写 Connection，不启动模型", "setup writes Connection only; never starts models")), tone="violet")
    g.node("desktop", "Desktop",
           (L("只访问 flashserver，不直连 FlashHub API", "talks to flashserver only, never the FlashHub API"),
            L("安装器/封面图可直接访问第三方 URL", "installer/cover URLs may be fetched directly"),
            L("推理只走 /v1", "inference uses /v1 only")), tone="blue")
    g.end_cluster()

    g.cluster(L("E. 本地缓存", "E. Local cache"), tone="amber")
    g.node("cache_bundle", L("bundles/<name>/<version>", "bundles/<name>/<version>"),
           (L(".flashcli_bundle.json（标记存在即离线）", ".flashcli_bundle.json (marker present = offline)"),), kind="store", tone="amber")
    g.node("cache_weights", L("models/store/<source>/<repo>@<rev>-<hash>", "models/store/<source>/<repo>@<rev>-<hash>"),
           (L(".flashcli_download.json + .incomplete", ".flashcli_download.json + .incomplete"),
            L("allow / require / norm stats 就绪", "allow / require / norm stats readiness")), kind="store", tone="amber")
    g.node("cache_runtime", L("runtimes/<runtime_id>", "runtimes/<runtime_id>"),
           (L("venv + .venv-fingerprint + .runtime.json", "venv + .venv-fingerprint + .runtime.json"),), kind="store", tone="green")
    g.end_cluster()

    g.edge("build", "pack", tone="orange")
    g.edge("pack", "validate", tone="amber")
    g.edge("validate", "upload", L("通过", "pass"), tone="red")
    g.edge("upload", "repo_api", L("发布版本", "publish version"), tone="red")
    g.edge("app_author", "app_api", L("发布应用", "publish app"), tone="violet")
    g.edge("repo_api", "catalog_api", L("索引", "index"), style="dashed")
    g.edge("repo_api", "pull", L("index + files", "index + files"), tone="green")
    g.edge("catalog_api", "srv_catalog", L("catalog", "catalog"), tone="violet")
    g.edge("repo_api", "srv_preload", L("bundle + weights", "bundle + weights"), tone="violet", style="dashed")
    g.edge("app_api", "srv_app", L("app manifest", "app manifest"), tone="violet")
    g.edge("repo_api", "runserve", L("bundle 树", "bundle tree"), tone="teal", style="dashed")
    g.edge("srv_catalog", "desktop", tone="blue")
    g.edge("srv_preload", "desktop", tone="blue")
    g.edge("srv_app", "desktop", tone="blue")
    g.edge("pull", "cache_bundle", L("树", "tree"), tone="amber")
    g.edge("pull", "cache_weights", L("权重", "weights"), tone="amber")
    g.edge("pull", "cache_runtime", L("venv", "venv"), tone="green")
    g.edge("runserve", "cache_bundle", style="dotted")
    g.edge("srv_preload", "cache_bundle", style="dotted")
    g.edge("srv_app", "cache_bundle", style="dotted")
    g.save()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


def app_lifecycle() -> None:
    g = Dot(
        "app_lifecycle",
        L("flashserver 应用生命周期", "flashserver application lifecycle"),
        L(
            "planned → preparing → prepared → ready；应用只调用 /v1，不启动/停止模型",
            "planned → preparing → prepared → ready; applications call /v1 and never start or stop models",
        ),
        rankdir="TB",
    )

    g.cluster(L("安装与准备", "Install and prepare"), tone="orange")
    g.node("resolve", L("FetchAppManifest + Validate + Platform", "FetchAppManifest + Validate + Platform"),
           (L("平台命令 / default bundles / 版本固定", "platform command / default bundles / pinned version"),), tone="orange")
    g.node("already", L("已 prepared / ready 且 force=false？", "Already prepared / ready and force=false?"),
           kind="decision", tone="violet")
    g.node("noop", L("AlreadyReady（无操作）", "AlreadyReady (no-op)"), kind="term", tone="slate")
    g.node("planned", "planned",
           (L("install 命令执行前写入 apps.json", "written to apps.json before the install command"),
            L("持久化，跨进程锁", "persisted under a cross-process lock")), kind="term", tone="indigo")
    g.node("install_cmd", L("install.command", "install.command"),
           (L("run：daemon 执行 shell", "run: daemon executes the shell command"),
            L("client：桌面端本地执行，daemon 只记录", "client: desktop runs it; daemon only records"),
            L("URL：只展示下载页，不抓取", "URL: show the download page, never fetch"),
            L("skip：不执行", "skip: do not execute")), tone="orange")
    g.node("preparing", "preparing",
           (L("对 default bundles 串行 Prepare", "serially Prepare the default bundles"),
            L("Prepare = host.Pull", "Prepare = host.Pull")), tone="amber")
    g.node("prepared", "prepared",
           (L("所有选中 bundle 的 Prepared=true", "all selected bundles have Prepared=true"),
            L("Connection = {base_url, api_key=local, models, model_refs}", "Connection = {base_url, api_key=local, models, model_refs}")), tone="green")
    g.node("failed", "failed",
           (L("安装命令或 Prepare 失败；保留日志", "install command or Prepare failed; logs kept"),
            L("可重试；已缓存的 bundle 保留", "retryable; cached bundles are kept")), kind="term", tone="red")
    g.end_cluster()

    g.cluster(L("配置与激活", "Configure and activate"), tone="violet")
    g.node("setup", L("POST /api/v1/apps/{org}/{name}/setup", "POST /api/v1/apps/{org}/{name}/setup"),
           (L("可同步返回 AppState 或 ?async=1 job", "returns AppState or an ?async=1 job"),
            L("body: setup_scripts[] + client_home", "body: setup_scripts[] + client_home")), tone="violet")
    g.node("set_ready", L("先把 state=ready 并清 error", "set state=ready and clear error first"),
           (L("然后才执行 setup scripts", "only then run the setup scripts"),
            L("setup 失败只写 setup_error，状态仍是 ready", "script failure writes setup_error; state stays ready")), tone="green")
    g.node("scripts", L("applySetupScripts", "applySetupScripts"),
           (L("有已保存 plan 且未显式选择 → 离线重放", "saved plan and no explicit selection → replay offline"),
            L("否则按 manifest 顺序固定脚本 + SHA-256", "otherwise pin manifest order + SHA-256"),
            L("脚本缓存 setup-cache/<sha256>.py", "script cache setup-cache/<sha256>.py"),
            L("第一个失败停止后续", "the first failure stops the rest")), tone="amber")
    g.node("ready", "ready",
           (L("应用已配置，可接收请求", "app configured and ready for requests"),
            L("Connection 仅在 apps.json；APIKey 固定 local", "Connection only in apps.json; APIKey is always local")), kind="term", tone="green")
    g.end_cluster()

    g.cluster(L("运行时与卸载", "Runtime and uninstall"), tone="teal")
    g.node("infer", L("推理只走 /v1", "Inference through /v1 only"),
           (L("gateway → scheduler → resident", "gateway → scheduler → resident"),
            L("应用没有 PID / child endpoint", "apps have no PID / child endpoint"),
            L("应用不能 start / stop / load / unload", "apps cannot start / stop / load / unload")), tone="blue")
    g.node("status", L("GET .../status", "GET .../status"),
           (L("读 apps.json；transitional 超过 ~10m → failed", "reads apps.json; transitional older than ~10m → failed"),), tone="slate")
    g.node("uninstall", L("DELETE /api/v1/apps/{org}/{name}", "DELETE /api/v1/apps/{org}/{name}"),
           (L("默认只删 registry 条目", "by default removes the registry entry only"),
            L("?purge_models=1 再 RemoveCachedRef", "?purge_models=1 also calls RemoveCachedRef"),
            L("共享资产保留；未缓存会中断 purge", "shared assets kept; an uncached ref aborts purge")), tone="orange")
    g.node("uninstalled", "uninstalled",
           (L("模型缓存 / 日志 / setup-cache 默认保留", "model cache / logs / setup-cache kept by default"),
            L("不会自动停止 resident", "never stops a resident")), kind="term", tone="slate")
    g.node("prepare_only", L("POST .../prepare", "POST .../prepare"),
           (L("NoInstall + PrepareOnly + Force", "NoInstall + PrepareOnly + Force"),
            L("可给未安装应用创建 prepared 状态", "may create prepared state for an uninstalled app")), tone="amber")
    g.node("desktop_note", L("Desktop 的角色", "Desktop role"),
           (L("client 命令 / 安装器在本地执行", "runs client commands / installers locally"),
            L("随后 POST install；配置走 /setup", "then POST install; configuration uses /setup"),
            L("不直接启动/停止模型，推理只走 /v1", "never starts/stops models; inference via /v1")), kind="note", tone="blue")
    g.end_cluster()

    g.edge("resolve", "already")
    g.edge("already", "noop", L("是", "yes"), tone="slate")
    g.edge("already", "planned", L("否", "no"), tone="indigo")
    g.edge("planned", "install_cmd")
    g.edge("install_cmd", "failed", L("失败", "fail"), tone="red", style="dashed")
    g.edge("install_cmd", "preparing", L("成功 + 有模型", "ok + models"), tone="amber")
    g.edge("install_cmd", "prepared", L("成功 + 无模型", "ok + no models"), tone="green", style="dashed")
    g.edge("preparing", "prepared", L("全部拉取完成", "all pulled"), tone="green")
    g.edge("preparing", "failed", L("失败", "fail"), tone="red", style="dashed")
    g.edge("prepared", "setup", L("激活", "activate"), tone="violet")
    g.edge("setup", "set_ready", tone="green")
    g.edge("set_ready", "scripts", tone="amber")
    g.edge("scripts", "ready", L("完成 / 失败都 ready", "done / failure both ready"), tone="green")
    g.edge("ready", "infer", L("请求", "request"), tone="blue")
    g.edge("ready", "setup", L("重新配置", "reconfigure"), tone="violet", style="dashed")
    g.edge("ready", "status", style="dotted")
    g.edge("ready", "uninstall", L("卸载", "uninstall"), tone="orange")
    g.edge("uninstall", "uninstalled", tone="slate")
    g.edge("prepare_only", "prepared", L("只准备", "prepare only"), tone="amber", style="dashed")
    g.edge("failed", "resolve", L("重试", "retry"), tone="red", style="dashed")
    g.edge("install_cmd", "desktop_note", style="dotted")
    g.save()


# ---------------------------------------------------------------------------
# Go module map
# ---------------------------------------------------------------------------


def go_module_map() -> None:
    g = Dot(
        "go_module_map",
        L("Go host 模块地图", "Go host module map"),
        L(
            "cmd → 前端 → 共享 host 服务 → 执行后端；共享逻辑只实现一次",
            "cmd → frontends → shared host services → execution backends; shared logic is implemented once",
        ),
        rankdir="LR",
    )

    g.cluster(L("入口", "Entry points"), tone="blue")
    g.node("cmd_cli", "cmd/flashcli", (L("pull / run / serve", "pull / run / serve"), L("bundle / models / app", "bundle / models / app")), tone="blue")
    g.node("cmd_srv", "cmd/flashserver", (L("gateway + scheduler", "gateway + scheduler"), L("management API + console", "management API + console")), tone="blue")
    g.node("cmd_setup", "cmd/flashserver-setup", (L("Linux / WSL 安装", "Linux / WSL install"),), tone="blue")
    g.end_cluster()

    g.cluster(L("前端", "Frontends"), tone="violet")
    g.node("cli", "internal/cli", (L("flags / prompts / tables", "flags / prompts / tables"), L("编排 host 服务", "orchestrates host services")), tone="violet")
    g.node("server", "internal/server", (L("HTTP / auth / jobs / ws", "HTTP / auth / jobs / ws"), L("gateway / scheduler / manager", "gateway / scheduler / manager"), L("preload / apps / catalog", "preload / apps / catalog")), tone="violet")
    g.node("setup", "internal/setup", (L("systemd / WSL / 服务注册", "systemd / WSL / service registration"),), tone="violet")
    g.end_cluster()

    g.cluster(L("共享 host 服务（CLI 与 flashserver 必须一致）", "Shared host services (CLI and flashserver must agree)"), tone="green")
    g.node("host", "internal/host", (L("cache discovery / readiness", "cache discovery / readiness"), L("pull / EnsureRuntime / ResolveWeights", "pull / EnsureRuntime / ResolveWeights"), L("cleanup / storage", "cleanup / storage")), tone="green")
    g.node("weights", "internal/weights", (L("store key / download manifest", "store key / download manifest"), L("resume / allow/require / norm stats", "resume / allow/require / norm stats")), tone="amber")
    g.node("runtime", "internal/runtime", (L("runtime IDs / markers / paths", "runtime IDs / markers / paths"),), tone="teal")
    g.node("venv", "internal/venv", (L("uv / pip / python deps", "uv / pip / python deps"), L("fingerprint / protocol schema", "fingerprint / protocol schema")), tone="pink")
    g.node("manifest", "internal/manifest", (L("v3/v4 parse / validate", "v3/v4 parse / validate"), L("entry / capabilities / resources", "entry / capabilities / resources")), tone="red")
    g.node("apps", "internal/apps", (L("app install / setup / state", "app install / setup / state"),), tone="orange")
    g.node("modelrun", "internal/modelrun", (L("serve launch / logs / WaitHealthy", "serve launch / logs / WaitHealthy"),), tone="cyan")
    g.node("gpu", "internal/gpu · preflight · cuda", (L("GPU / SM / CUDA probes", "GPU / SM / CUDA probes"), L("host ABI / system requirements", "host ABI / system requirements")), tone="slate")
    g.node("ref", "internal/ref · flashhub", (L("ref parse / cache key", "ref parse / cache key"), L("FlashHub index / catalog / apps", "FlashHub index / catalog / apps")), tone="orange")
    g.end_cluster()

    g.cluster(L("执行后端", "Execution backends"), tone="cyan")
    g.node("inferexec", "internal/inferexec", (L("reexec bundle venv", "reexec bundle venv"), L("python -m flashcli_bundle.infer", "python -m flashcli_bundle.infer")), tone="cyan")
    g.node("nativeexec", "internal/nativeexec", (L("native-exec process", "native-exec process"), L("NDJSON / HTTP", "NDJSON / HTTP")), tone="cyan")
    g.node("nativeabi", "internal/nativeabi · hostabi", (L("ABI / .so / sessions", "ABI / .so / sessions"), L("host glibc / GLIBCXX checks", "host glibc / GLIBCXX checks")), tone="cyan")
    g.end_cluster()

    g.cluster(L("边界与机械门禁", "Boundaries and mechanical gates"), tone="red")
    g.node("protocol", "flashcli-bundle", (L("dependencies = []", "dependencies = []"), L("protocol + infer 包", "protocol + infer package")), tone="red")
    g.node("guard", "go/internal/architecture tests", (L("禁止重复 nvidia-smi / walker / log 名", "forbid duplicate nvidia-smi / walkers / log names"), L("禁止在 go/ 写模型专属逻辑", "forbid model-specific logic in go/")), tone="red")
    g.end_cluster()

    g.edge("cmd_cli", "cli")
    g.edge("cmd_srv", "server")
    g.edge("cmd_setup", "setup")
    g.edge("cli", "host", L("pull / run / serve", "pull / run / serve"), tone="green")
    g.edge("server", "host", L("preload / catalog", "preload / catalog"), tone="green")
    g.edge("server", "modelrun", L("resident", "resident"), tone="cyan")
    g.edge("server", "apps", L("apps", "apps"), tone="orange")
    g.edge("host", "weights", tone="amber")
    g.edge("host", "runtime", tone="teal")
    g.edge("host", "venv", tone="pink")
    g.edge("host", "manifest", tone="red")
    g.edge("host", "ref", tone="orange")
    g.edge("server", "gpu", tone="slate")
    g.edge("cli", "gpu", tone="slate", style="dashed")
    g.edge("cli", "apps", L("app", "app"), tone="orange", style="dashed")
    g.edge("apps", "host", L("Pull", "Pull"), tone="green", style="dashed")
    g.edge("venv", "inferexec", L("python", "python"), tone="cyan")
    g.edge("modelrun", "inferexec", L("serve", "serve"), tone="cyan")
    g.edge("manifest", "nativeexec", L("native-exec", "native-exec"), tone="cyan")
    g.edge("manifest", "nativeabi", L("native-abi", "native-abi"), tone="cyan")
    g.edge("venv", "protocol", L("安装", "install"), tone="red", style="dashed")
    g.edge("guard", "protocol", L("检查", "check"), tone="red", style="dotted")
    g.edge("guard", "host", L("检查", "check"), tone="red", style="dotted")
    g.save()


def main() -> None:
    global LANG
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in ("en", "zh-CN"):
        LANG = lang
        flashcli_flow()
        gateway_flow()
        scheduler_flow()
        bundle_stack()
        flashhub_flow()
        app_lifecycle()
        go_module_map()


if __name__ == "__main__":
    main()
