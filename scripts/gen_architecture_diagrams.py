#!/usr/bin/env python3
"""Generate the architecture flow diagrams with Graphviz.

Keep only the five diagrams that matter:
  * system overview (hand-laid SVG, not generated here)
  * flashcli model inference flow
  * application install/setup flow
  * flashserver gateway request + model scheduling flow
  * FlashHub bundle/weights fetch and cache flow

The Graphviz source is authoritative. Render with:
  dot -Tsvg docs/images/<name>.<lang>.dot -o docs/images/<name>.<lang>.svg
  dot -Tpng -Gdpi=110 docs/images/<name>.<lang>.dot -o docs/images/<name>.<lang>.png
"""

from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
LANG = "en"
FONT = "Noto Sans CJK SC"

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
}


def L(zh: str, en: str | None = None) -> str:
    if en is None:
        return zh
    return zh if LANG.startswith("zh") else en


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def label(title: str, lines: tuple[str, ...] = ()) -> str:
    out = f"<B>{esc(title)}</B>"
    for line in lines:
        out += f'<BR/><FONT POINT-SIZE="10.5">{esc(line)}</FONT>'
    return "<" + out + ">"


def graph_label(title: str, subtitle: str) -> str:
    return (
        "<"
        f"<B>{esc(title)}</B><BR/>"
        f'<FONT POINT-SIZE="14" COLOR="#64748B">{esc(subtitle)}</FONT>'
        ">"
    )


class Dot:
    def __init__(self, name: str, title: str, subtitle: str) -> None:
        self.name = name
        gid = name.replace("-", "_")
        self.lines = [
            f"digraph {gid} {{",
            "  graph ["
            'rankdir=TB, bgcolor="#F7F9FC", pad=0.4, nodesep=0.45, ranksep=0.5, '
            f'fontname="{FONT}", fontsize=28, labelloc=t, label={graph_label(title, subtitle)}'
            "];",
            "  node ["
            f'shape=box, style="rounded,filled", fontname="{FONT}", fontsize=12.5, '
            'margin="0.30,0.10", penwidth=1.3, color="#94A3B8"'
            "];",
            "  edge ["
            f'fontname="{FONT}", fontsize=10.5, color="#64748B", fontcolor="#475569", '
            'arrowsize=0.7, penwidth=1.15'
            "];",
        ]

    def node(
        self,
        key: str,
        title: str,
        lines: tuple[str, ...] = (),
        *,
        kind: str = "process",
        tone: str = "blue",
    ) -> None:
        fill, border, _ = TONES[tone]
        shape = "box"
        style = "rounded,filled"
        size = 12.5
        if kind == "decision":
            shape, style, size = "diamond", "filled", 12.0
        elif kind == "note":
            shape, style, size = "note", "filled", 10.5
        elif kind == "term":
            style, size = "rounded,filled", 13.5
        self.lines.append(
            f'  {key} [shape={shape}, style="{style}", fillcolor="{fill}", '
            f'color="{border}", fontsize={size:g}, label={label(title, lines)}];'
        )

    def edge(self, src: str, dst: str, text: str = "", *, tone: str | None = None,
             style: str = "solid") -> None:
        color = TONES[tone][2] if tone else "#64748B"
        attrs = [f'color="{color}"', f'style="{style}"']
        if text:
            attrs.append(f'label="{esc(text)}"')
        self.lines.append(f"  {src} -> {dst} [{', '.join(attrs)}];")

    def save(self) -> None:
        self.lines.append("}")
        path = OUT / f"{self.name}.{LANG}.dot"
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8", newline="\n")
        print(path)


# ---------------------------------------------------------------------------
# 1. flashcli model inference flow
# ---------------------------------------------------------------------------


def flashcli_flow() -> None:
    g = Dot(
        "flashcli-flow",
        L("flashcli 模型推理流程", "flashcli model inference flow"),
        L("ref → bundle 树 → 权重 / venv / CUDA → bundle 进程内推理",
          "ref → bundle tree → weights / venv / CUDA → inference inside the bundle"),
    )
    g.node("start", L("flashcli run | serve", "flashcli run | serve"),
           (L("<ref> [OPTIONS] · 原始 argv", "<ref> [OPTIONS] · raw argv"),
            L("cobra DisableFlagParsing", "cobra DisableFlagParsing")), kind="term", tone="blue")
    g.node("peel", "peelHostFlags",
           (L("ref · --checkpoint · --mtp-checkpoint", "ref · --checkpoint · --mtp-checkpoint"),
            L("--quiet · --no-auto-install · -h", "--quiet · --no-auto-install · -h")), tone="indigo")
    g.node("ensure", "host.EnsureBundle",
           (L("force=false；run/serve 不调用 host.Pull", "force=false; run/serve never call host.Pull"),), tone="blue")
    g.node("source", L("bundle 来源？", "bundle source?"),
           (L("本地路径 / FlashHub 标记 / 需要同步", "local path / FlashHub marker / sync"),),
           kind="decision", tone="amber")
    g.node("sync", "DownloadManifest + SyncBundle",
           (L("repo index → manifest", "repo index → manifest"),
            L("选中 runtime cell + 公共文件 + 标记", "selected runtime cell + common files + markers")), tone="orange")
    g.node("root", L("bundle 树就绪", "bundle tree ready"),
           (L("local / reuse / sync 汇合", "local / reuse / sync converge"),), tone="green")
    g.node("manifest", "manifest.Load → ApplyEnv → PreflightBundle",
           (L("ResolveVariant · EntryFor(capability)", "ResolveVariant · EntryFor(capability)"),
            L("HostEnvKey = SM + CUDA + Python ABI", "HostEnvKey = SM + CUDA + Python ABI"),
            L("识别 native .so + host ABI", "recognize native .so + host ABI")), tone="violet")
    g.node("valid", L("manifest / env / entry 有效？", "manifest / env / entry valid?"),
           (L("无效 → exit 1/2", "invalid → exit 1/2"),), kind="decision", tone="amber")
    g.node("weights", "weights.PrepareBundle",
           (L("store key · 下载清单 · 断点续传", "store key · download manifest · resume"),
            L("extra_weights · extra_pull · post_pull", "extra_weights · extra_pull · post_pull"),
            L("allow / require + norm stats 就绪", "allow / require + norm stats readiness")), tone="amber")
    g.node("venv", "venv.Ensure + protocol schema",
           (L("venv 前：EnsureSystemRequirements", "before venv: EnsureSystemRequirements"),
            L("uv · flashcli-bundle[infer] · python_dependencies", "uv · flashcli-bundle[infer] · python_dependencies"),
            L("fingerprint 命中即离线复用", "offline reuse when the fingerprint matches")), tone="pink")
    g.node("cuda", "cuda.Ensure",
           (L("CUDA SONAME 存在且可 dlopen", "CUDA SONAME present and dlopen-able"),
            L("缺失时可装 nvidia-cublas / cuda-runtime", "may install nvidia-cublas / cuda-runtime")), tone="cyan")
    g.node("exec", "inferexec.Exec",
           (L("syscall.Exec 替换 host 进程", "syscall.Exec replaces the host process"),
            L("python -m flashcli_bundle.infer <cap> <ref>", "python -m flashcli_bundle.infer <cap> <ref>")), kind="term", tone="green")
    g.node("infer", "flashcli_bundle.infer",
           (L("activate_for_preset", "activate_for_preset"),
            L("ensure_model_cached(download=False)", "ensure_model_cached(download=False)")), tone="violet")
    g.node("engine", L("RunEngine / ServeEngine", "RunEngine / ServeEngine"),
           (L("run：load → predict() → stdout", "run: load → predict() → stdout"),
            L("serve：load → warmup() → build_app()", "serve: load → warmup() → build_app()"),
            L("register_routes 先于标准路由", "register_routes before standard routes")), tone="green")
    g.node("note", L("其他入口与边界", "Other entries and boundaries"),
           (L("script：main(argv) 自己创建协议/服务器", "script: main(argv) creates its own protocol/server"),
            L("native-exec：http serve 可用；stdio serve 未实现", "native-exec: http serve works; stdio serve not implemented"),
            L("native-abi：普通 run 只探测 ABI；session 才推理", "native-abi: plain run probes the ABI; sessions run inference"),
            L("离线：标记 + 权重 + fingerprint 命中则不联网", "offline: no network when marker + weights + fingerprint match")),
           kind="note", tone="slate")

    g.edge("start", "peel")
    g.edge("peel", "ensure")
    g.edge("ensure", "source")
    g.edge("source", "sync", L("FlashHub / 无标记", "FlashHub / no marker"), tone="orange")
    g.edge("source", "root", L("local / 标记存在", "local / marker present"), tone="green", style="dashed")
    g.edge("sync", "root", tone="orange")
    g.edge("root", "manifest")
    g.edge("manifest", "valid")
    g.edge("valid", "weights", L("是", "yes"), tone="green")

    g.edge("weights", "venv", tone="amber")
    g.edge("venv", "cuda", tone="pink")
    g.edge("cuda", "exec", tone="cyan")
    g.edge("exec", "infer", tone="green")
    g.edge("infer", "engine", tone="violet")
    g.edge("engine", "note", style="dotted")
    g.save()


# ---------------------------------------------------------------------------
# 2. application install / setup flow
# ---------------------------------------------------------------------------


def app_lifecycle() -> None:
    g = Dot(
        "app-lifecycle",
        L("应用安装与配置流程", "Application install and setup flow"),
        L("install → prepare → setup → ready；应用只调用 /v1，不拥有模型启停",
          "install → prepare → setup → ready; apps call /v1 and never own model start/stop"),
    )
    g.node("install", "POST /api/v1/apps/{org}/{name}/install",
           (L("body：version · bundles · install_command", "body: version · bundles · install_command"),
            L("client_os / client_arch / force", "client_os / client_arch / force")), kind="term", tone="blue")
    g.node("fetch", "FetchAppManifest + Validate + Platform",
           (L("FlashHub app manifest", "FlashHub app manifest"),
            L("platform command · default bundles · 版本固定", "platform command · default bundles · pinned version")), tone="orange")
    g.node("already", L("已 prepared / ready 且 force=false？", "prepared / ready and force=false?"),
           kind="decision", tone="violet")
    g.node("noop", L("AlreadyReady（无操作）", "AlreadyReady (no-op)"), kind="term", tone="slate")
    g.node("planned", "planned",
           (L("install 命令执行前写入 apps.json", "written to apps.json before the install command"),
            L("跨进程锁 + 原子写", "cross-process lock + atomic write")), tone="indigo")
    g.node("cmd", "install.command",
           (L("run：daemon 执行 shell", "run: daemon executes the shell command"),
            L("client：桌面端本地执行，daemon 只记录", "client: desktop runs it; daemon only records"),
            L("URL：只展示下载页；skip：不执行", "URL: show the download page; skip: do not execute")), tone="orange")
    g.node("failed", "failed",
           (L("install / prepare 失败；日志保留", "install / prepare failed; logs kept"),
            L("已缓存 bundle 保留；重试 = 重新 POST install", "cached bundles kept; retry = POST install again")), kind="term", tone="red")
    g.node("models", L("需要准备默认模型？", "Prepare default models?"), kind="decision", tone="amber")
    g.node("preparing", "preparing",
           (L("对 default bundles 串行 host.Pull", "serially host.Pull the default bundles"),
            L("全部 Prepared=true", "all Prepared=true")), tone="amber")
    g.node("prepared", "prepared",
           (L("Connection = {base_url, api_key=local, models, model_refs}", "Connection = {base_url, api_key=local, models, model_refs}"),), tone="green")
    g.node("setup", "POST /api/v1/apps/{org}/{name}/setup",
           (L("先把 state=ready，再执行 setup scripts", "set state=ready, then run setup scripts"),
            L("脚本：保存的 plan / SHA-256 校验 / 按序执行", "scripts: saved plan / SHA-256 verify / ordered run"),
            L("脚本失败只写 setup_error，状态仍是 ready", "script failure writes setup_error; state stays ready")), tone="violet")
    g.node("ready", "ready",
           (L("Connection 在 apps.json；APIKey 固定 local", "Connection in apps.json; APIKey is always local"),
            L("推理只走 /v1 → gateway → scheduler", "inference via /v1 → gateway → scheduler")), kind="term", tone="green")
    g.node("uninstall", "DELETE /api/v1/apps/{org}/{name}",
           (L("默认只删 registry 条目", "by default removes the registry entry only"),
            L("?purge_models=1 再 RemoveCachedRef", "?purge_models=1 also calls RemoveCachedRef"),
            L("共享资产保留；不自动停 resident", "shared assets kept; never stops a resident")), tone="orange")
    g.node("uninstalled", "uninstalled",
           (L("模型缓存 / 日志 / setup-cache 默认保留", "model cache / logs / setup-cache kept by default"),), kind="term", tone="slate")
    g.node("note", L("桌面端与准备", "Desktop and prepare"),
           (L("client 命令 / 安装器在本地执行，随后 POST install", "client commands / installers run locally, then POST install"),
            L("POST .../prepare：NoInstall + PrepareOnly + Force", "POST .../prepare: NoInstall + PrepareOnly + Force"),
            L("应用没有 PID / child endpoint，也不能 start/stop 模型", "apps have no PID / child endpoint and cannot start/stop models")),
           kind="note", tone="slate")

    g.edge("install", "fetch")
    g.edge("fetch", "already")
    g.edge("already", "noop", L("是", "yes"), tone="slate")
    g.edge("already", "planned", L("否", "no"), tone="indigo")
    g.edge("planned", "cmd")
    g.edge("cmd", "failed", L("失败", "fail"), tone="red", style="dashed")
    g.edge("cmd", "models", L("成功", "ok"), tone="green")
    g.edge("models", "preparing", L("是", "yes"), tone="amber")
    g.edge("models", "prepared", L("否", "no"), tone="green", style="dashed")
    g.edge("preparing", "prepared", L("全部完成", "all done"), tone="green")
    g.edge("preparing", "failed", L("失败", "fail"), tone="red", style="dashed")
    g.edge("prepared", "setup", L("配置", "configure"), tone="violet")
    g.edge("setup", "ready", L("完成 / 脚本失败都 ready", "done / script failure both ready"), tone="green")
    g.edge("ready", "uninstall", L("卸载", "uninstall"), tone="orange")
    g.edge("uninstall", "uninstalled", tone="slate")
    g.edge("ready", "setup", L("重新配置", "reconfigure"), tone="violet", style="dashed")

    g.edge("prepared", "note", style="dotted")
    g.save()


# ---------------------------------------------------------------------------
# 3. flashserver gateway request + model scheduling
# ---------------------------------------------------------------------------


def gateway_flow() -> None:
    g = Dot(
        "flashserver-gateway-flow",
        L("flashserver 网关与模型调度流程", "flashserver gateway and model scheduling flow"),
        L("/v1 请求 → 路由 / 模型选择 → 磁盘与 capability 门禁 → 调度 → 代理 / 释放",
          "/v1 request → route / model selection → disk and capability gates → schedule → proxy / release"),
    )
    g.node("client", L("客户端 /v1 请求", "Client /v1 request"),
           (L("OpenAI / Anthropic SDK / App / Desktop", "OpenAI / Anthropic SDK / App / Desktop"),
            L("推理永远不直接访问 child endpoint", "inference never touches a child endpoint")), kind="term", tone="blue")
    g.node("auth", L("token 已配置？", "token configured?"),
           (L("Bearer / X-Flashcli-Token", "Bearer / X-Flashcli-Token"),
            L("失败 → 401", "failure → 401")), kind="decision", tone="violet")
    g.node("route", L("路由归属？", "Route owner?"),
           (L("host 标准 / bundle 自定义 / 保留前缀", "host standard / bundle custom / reserved"),
            L("保留前缀未知路径 → 405/404", "unknown reserved path → 405/404")),
           kind="decision", tone="blue")
    g.node("model", L("选择模型（resolveGatewayModel）", "Select model (resolveGatewayModel)"),
           (L("JSON body / multipart form / ?model=", "JSON body / multipart form / ?model="),
            L("必须是完整 ref；body 与 query 冲突 → 400", "must be a full ref; body/query conflict → 400")), tone="blue")
    g.node("assets", L("资产就绪 / preloadReady？", "Assets ready / preloadReady?"),
           (L("bundle + weights + runtime", "bundle + weights + runtime"),
            L("auto_pull=false 且缺失 → 404", "missing with auto_pull=false → 404")), kind="decision", tone="amber")
    g.node("preload", "ensurePreload",
           (L("启动 host.Pull 后台 job", "start a host.Pull job"),
            L("返回 503 + Retry-After / job id", "return 503 + Retry-After / job id")), tone="orange")
    g.node("capability", L("capability 已声明？", "capability declared?"),
           (L("仅标准路由；custom 跳过", "standard routes only; custom skips"),
            L("未声明 → 400 unsupported", "undeclared → 400 unsupported")), kind="decision", tone="amber")
    g.node("acquire", "Scheduler.Acquire(ref)",
           (L("等待 resident 启动 / 排队", "wait for resident start / queue"),
            L("默认 resident_start_wait 10s + queue 30s", "default resident_start_wait 10s + queue 30s")), tone="green")
    g.node("placement", "planLocked + placementFor",
           (L("max_loaded=0 表示不限制槽位", "max_loaded=0 means no slot limit"),
            L("runtime cell：SM + CUDA + Python ABI", "runtime cell: SM + CUDA + Python ABI"),
            L("每 GPU 空闲显存 ≥ min_vram + headroom；gpu_count", "free VRAM/GPU ≥ min_vram + headroom; gpu_count"),
            L("无 GPU cell → CPU fallback（可禁用）", "no GPU cell → CPU fallback (can be disabled)"),
            L("满槽 / 显存不足 → LRU 淘汰 idle 或排队", "slots/VRAM short → LRU evict idle or queue")), tone="cyan")
    g.node("queue", L("队列 / 无放置", "Queue / no placement"),
           (L("QueueMax 默认 16；queue_full → 429", "QueueMax default 16; queue_full → 429"),
            L("no_compatible_runtime 立即失败，不排队", "no_compatible_runtime fails immediately")), kind="note", tone="red")
    g.node("start", L("启动 / 复用 resident", "Start or reuse resident"),
           (L("Manager.LoadScheduled → flashcli serve child", "Manager.LoadScheduled → flashcli serve child"),
            L("WaitHealthy ≤120s；失败 → resident_start_failed", "WaitHealthy ≤120s; failure → resident_start_failed")), tone="green")
    g.node("lease", "Lease + Manager.Endpoint(ref)",
           (L("active_requests++；阻止淘汰 / idle stop", "active_requests++; blocks eviction / idle stop"),
            L("完整 ref 精确匹配 endpoint", "exact full-ref endpoint match")), tone="green")
    g.node("proxy", "proxyGateway",
           (L("method / path / query / body 原样转发", "method / path / query / body unchanged"),
            L("剥离 auth / token / cookie；客户端断开 → cancel", "strips auth / token / cookie; client close → cancel"),
            L("SSE 逐条重写；JSON ≤32MiB 重写 model", "rewrite SSE data lines; JSON ≤32MiB model")), tone="cyan")
    g.node("release", "lease.Release",
           (L("leases--；busy → ready；last_used=now", "leases--; busy → ready; last_used=now"),
            L("idle reaper / reconcile 死进程", "idle reaper / reconcile dead children")), tone="green")
    g.node("errors", L("错误映射", "Error mapping"),
           (L("400 conflict / required / invalid / unsupported", "400 conflict / required / invalid / unsupported"),
            L("404 not_found / not_servable；405 reserved", "404 not_found / not_servable; 405 reserved"),
            L("429 queue_full；503 preparing / no_placement / starting", "429 queue_full; 503 preparing / no_placement / starting"),
            L("499 client_closed；502 proxy / start_failed", "499 client_closed; 502 proxy / start_failed")),
           kind="note", tone="red")
    g.node("mgmt", L("控制面不是推理路径", "Control plane is not the inference path"),
           (L("/api/v1/models/preload：只准备磁盘", "/api/v1/models/preload: disk only"),
            L("/api/v1/models/unload：停止 + 删除缓存", "/api/v1/models/unload: stop + remove cache")),
           kind="note", tone="slate")

    g.edge("client", "auth")
    g.edge("auth", "route", L("是 / 未配置", "yes / unset"), tone="green")
    g.edge("route", "model", L("标准 / 自定义", "standard / custom"), tone="blue")
    g.edge("model", "assets")
    g.edge("assets", "preload", L("否 + auto_pull", "no + auto_pull"), tone="orange")
    g.edge("assets", "capability", L("是", "yes"), tone="green")
    g.edge("capability", "acquire", L("是 / custom", "yes / custom"), tone="green")
    g.edge("acquire", "placement")
    g.edge("placement", "start", L("有放置", "placed"), tone="green")
    g.edge("placement", "queue", L("资源不足", "resource short"), tone="red", style="dashed")
    g.edge("start", "lease", L("ready", "ready"), tone="green")
    g.edge("lease", "proxy")
    g.edge("proxy", "release", L("完成 / 断开", "done / closed"), tone="green")
    g.edge("release", "mgmt", style="dotted")
    g.edge("release", "errors", style="invis")
    g.save()


# ---------------------------------------------------------------------------
# 4. FlashHub bundle / weights fetch and cache
# ---------------------------------------------------------------------------


def flashhub_flow() -> None:
    g = Dot(
        "flashhub-flow",
        L("FlashHub bundle 与权重获取 / 缓存流程", "FlashHub bundle and weights fetch / cache flow"),
        L("发布 → repo index → bundle 树 → venv / 权重 → 本地缓存；离线优先",
          "publish → repo index → bundle tree → venv / weights → local cache; offline first"),
    )
    g.node("build", L("bundles/<name>/build.sh", "bundles/<name>/build.sh"),
           (L("编译 FlashRT，组装 runtime cell", "compile FlashRT, assemble runtime cells"),
            L("当前环境或 Docker 矩阵", "current host or Docker matrix")), kind="term", tone="orange")
    g.node("pack", "scripts/pack_bundle.sh",
           (L("只复制 RELEASE_PACK_FILES", "copies only RELEASE_PACK_FILES"),
            L("选择 runtime cell；重写 dist/flashcli-bundle.json", "select runtime cell; rewrite dist/flashcli-bundle.json"),
            L("写 build 来源；不打包权重", "writes build provenance; never packages weights")), tone="amber")
    g.node("validate", "flashcli bundle validate",
           (L("协议 / entry / capabilities / resources", "protocol / entry / capabilities / resources"),
            L("runtime cell + .so ABI 探测", "runtime cell + .so ABI probe"),
            L("校验源目录，不是 dist", "validates the source tree, not dist")), tone="violet")
    g.node("upload", L("人工上传 dist/", "Manual dist/ upload"),
           (L("仓库内没有上传客户端", "no upload client in this repo"),
            L("保留相对路径；版本即 ref", "preserve relative paths; the version is the ref")), kind="term", tone="red")
    g.node("repo", L("FlashHub repo index", "FlashHub repo index"),
           (L("GET /api/v1/repos/{ns}/{name}:{ver}", "GET /api/v1/repos/{ns}/{name}:{ver}"),
            L("files[] + download_url + md5", "files[] + download_url + md5")), kind="store", tone="orange")
    g.node("entry", L("flashcli pull / run / serve", "flashcli pull / run / serve"),
           (L("pull：verifyRemote=true，强制远端校验", "pull: verifyRemote=true, force remote check"),
            L("run/serve：本地优先，不调用 host.Pull", "run/serve: local-first, never call host.Pull")), kind="term", tone="blue")
    g.node("ensure", "host.EnsureBundle",
           (L("本地路径直接使用", "local paths are used directly"),
            L("FlashHub：标记或 index → manifest → SyncBundle", "FlashHub: marker or index → manifest → SyncBundle"),
            L("只取选中的 runtime cell + 公共文件", "fetch only the selected runtime cell + common files")), tone="blue")
    g.node("marker", L("bundle 标记存在？", "bundle marker present?"),
           (L("bundles/<name>/<ver>/.flashcli_bundle.json", "bundles/<name>/<ver>/.flashcli_bundle.json"),),
           kind="decision", tone="amber")
    g.node("reuse", L("复用 bundle 树（离线）", "Reuse bundle tree (offline)"),
           (L("不校验文件、不访问网络", "no file validation, no network"),), tone="green")
    g.node("sync", "DownloadManifest + SyncBundle",
           (L("repo index → manifest", "repo index → manifest"),
            L("MD5 校验；写 runtime / bundle 标记", "MD5 verify; write runtime / bundle markers")), tone="orange")
    g.node("runtime", "host.EnsureRuntime / venv.Ensure",
           (L("PreflightBundle：env key / .so / host ABI", "PreflightBundle: env key / .so / host ABI"),
            L("uv · flashcli-bundle[infer] · python_dependencies", "uv · flashcli-bundle[infer] · python_dependencies"),
            L("fingerprint 命中即离线复用", "offline reuse when the fingerprint matches")), tone="pink")
    g.node("weights", "weights.PrepareBundle",
           (L("models/store/<source>/<repo>@<rev>-<hash>", "models/store/<source>/<repo>@<rev>-<hash>"),
            L("host 完整性：.flashcli_download.json + .incomplete", "host completeness: .flashcli_download.json + .incomplete"),
            L("bundle 就绪：allow / require / norm stats", "bundle readiness: allow / require / norm stats"),
            L("extra_weights / extra_pull / post_pull", "extra_weights / extra_pull / post_pull")), tone="amber")
    g.node("cache", L("本地缓存", "Local cache"),
           (L("bundles/<name>/<version>", "bundles/<name>/<version>"),
            L("models/store/<source>/<repo>@<rev>-<hash>", "models/store/<source>/<repo>@<rev>-<hash>"),
            L("runtimes/<runtime_id>/venv", "runtimes/<runtime_id>/venv")), kind="store", tone="green")
    g.node("offline", L("离线与就绪", "Offline and readiness"),
           (L("bundle 标记 + 权重完整 + fingerprint 命中 → 不联网", "marker + complete weights + fingerprint → no network"),
            L("present-but-incomplete 永不接受；legacy 就绪可接受", "present-but-incomplete is never accepted; a ready legacy cache is"),
            L("catalog / app registry / desktop 走 /api/v1，不直连 FlashHub", "catalog / app registry / desktop use /api/v1, never FlashHub directly")),
           kind="note", tone="slate")

    g.edge("build", "pack", tone="orange")
    g.edge("pack", "validate", tone="amber")
    g.edge("validate", "upload", L("通过", "pass"), tone="red")
    g.edge("upload", "repo", L("发布版本", "publish version"), tone="red")
    g.edge("repo", "entry", L("index + files", "index + files"), tone="orange")
    g.edge("entry", "ensure")
    g.edge("ensure", "marker")
    g.edge("marker", "reuse", L("是", "yes"), tone="green")
    g.edge("marker", "sync", L("否", "no"), tone="orange")
    g.edge("sync", "runtime", tone="orange")
    g.edge("reuse", "runtime", tone="green", style="dashed")
    g.edge("runtime", "weights", tone="pink")
    g.edge("weights", "cache", tone="amber")
    g.edge("cache", "offline", style="dotted")
    g.save()


def main() -> None:
    global LANG
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in ("en", "zh-CN"):
        LANG = lang
        flashcli_flow()
        app_lifecycle()
        gateway_flow()
        flashhub_flow()


if __name__ == "__main__":
    main()
