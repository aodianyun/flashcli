# FlashHub Bundle Download Reliability

Status: PR 1 implemented and Review Ready; not committed, merged, or released.
PR 2 is planned and not implemented.

This document is the authoritative English specification and implementation record.
The Chinese companion mirrors its scope, behavior, limitations, and verification status.

## 1. Problem and scope

Before PR 1, FlashHub downloads did not validate a positive indexed size, had no
bounded retry policy, and used one fixed incomplete path. This work improves
integrity checks, full-download retry behavior, cancellation, time bounds,
temporary-file handling, final commits, and progress accounting.

Only the FlashHub downloader and its focused tests are in scope. This PR does
not change other downloaders, bundle selection, model execution, or the FlashHub
index/API contract.

## 2. PR 1 — implemented

### 2.1 Validation, cache, and commit

- When File.Size > 0, the downloaded byte count must equal File.Size exactly.
  Oversized responses are rejected as soon as they exceed it; short responses
  fail at EOF.
- A non-empty File.MD5 is checked against the complete candidate file. If both
  size and MD5 are supplied, both checks must pass.
- Existing cache files are reused only if every available validator passes.
  If Size and MD5 are both absent, the existing-file cache-hit behavior is
  preserved; that hit is unverified.
- Each attempt writes to a unique temporary file in the destination directory.
  A candidate body is validated, then synced and closed before it is renamed
  to the final path. Failed downloads and failed replacements leave an existing
  final path. Failed downloads and failed replacements leave an existing
  destination untouched.
- Each attempt starts from byte zero. PR 1 sends no Range request and does not
  reuse partial bytes.

### 2.2 Retry, timeout, and cancellation

- The default limit is three complete attempts per file, including the initial
  request.
- Retryable cases include network connection/request failures, interrupted
  response bodies, HTTP 408, HTTP 429, and HTTP 5xx. Ordinary permanent 4xx
  responses, invalid URLs, integrity mismatches, and local file errors do not
  enter the retry loop.
- Backoff is bounded and cancellable. The default base is 250 ms with
  exponential growth and a 2 second maximum; Retry-After is considered for
  HTTP 429 and is capped at that maximum.
- For standard HTTP transports, the default connection/TLS bound is 10 seconds
  and the response-header bound is 30 seconds. The no-progress bound is 90
  seconds and the total attempt bound is 2 hours. An earlier caller context
  deadline or cancellation takes precedence.
- Standard HTTP transports are cloned before applying connection and header
  limits. For a custom RoundTripper, the code can apply a cancellable header
  wait, but cannot impose an independent connection-phase timeout; the request
  and attempt bounds depend on the RoundTripper honoring context cancellation.

### 2.3 Concurrency and progress

- Concurrent calls use independent temporary files. A process-local,
  per-destination lock protects the final destination recheck and rename; it
  does not serialize network transfers or provide a cross-process lock.
- Each promoted candidate passes the validators supplied by its own caller. If
  those validators are absent or incomplete, they cannot prove content identity.
  Concurrent calls can still duplicate network traffic.
- If concurrent calls use conflicting metadata for the same path, the last
  successful commit wins. PR 1 does not provide directory-level or version-level
  transaction semantics.
- SyncBundle reports live transfer progress. It tracks the greatest offset
  reached across attempts, so restarting a transfer does not count the same
  logical bytes twice. Known-size progress stays below completion until the
  download succeeds, then completes to the indexed size. Unknown-size files do
  not consume a known aggregate total.
- DownloadFile's Go signature is unchanged, but its onBytes callback now reports
  bytes only after validation and commit, in bounded increments. It is not a
  live per-read callback. SyncBundle uses a separate internal callback for live
  progress.

### 2.4 Errors and compatibility

- Downloader errors identify the bundle-relative file and failure category or
  HTTP status, with the attempt count where applicable. They do not include the
  raw signed URL, URL userinfo, query string, or token.
- Public Go method signatures, FlashHub index fields, download URLs, final
  destination paths, and completed-cache layout are unchanged.
- A failed transfer does not replace an existing destination.
- The legacy path <dest>.incomplete is neither resumed nor automatically
  deleted. It may remain on disk and consume space. Cleanup is intentionally
  omitted because PR 1 cannot establish whether an old process still owns or
  writes that file.
- When both Size and MD5 are absent, PR 1 retains the legacy cache behavior and
  cannot establish that an existing file is complete or correct.

## 3. PR 1 verification and acceptance boundary

Recorded validation for this implementation:

- Windows: go test ./internal/flashhub -count=1 -v — passed.
- Linux/WSL: go test ./internal/flashhub -count=1 -v — passed.
- Linux/WSL: go test -race ./internal/flashhub -count=1 — passed.
- Linux/WSL: go test ./... -count=1 -timeout 900s — passed.
- git diff --check — passed.

These are recorded results, not tests rerun during a documentation-only update.
The Go implementation and tests were left unchanged during this document
consolidation.

PR 1 acceptance is limited to the behavior described above: integrity checking
for available metadata, bounded full-download retries and timeouts, safe
temporary-file commits, progress accounting, and credential-safe downloader
errors. PR 1 does not require any resume behavior.

## 4. PR 2 — planned, not implemented

PR 2 is a separate follow-up. Its planned scope is:

- HTTP Range requests and Content-Range validation.
- Correct handling of 206 and 416 responses, including malformed or mismatched
  range metadata.
- ETag and If-Range handling, with remote file/version consistency checks.
- Reuse of partial files across requests or process restarts.
- Safe resume ownership, cache recovery, cleanup, and resumed-progress policy.

None of these capabilities is implemented or required for PR 1. PR 2 must retain
PR 1's size/MD5 validation, bounded retries and timeouts, cancellation, and safe
final commit.

## 5. Files

- go/internal/flashhub/flashhub.go — FlashHub download implementation.
- go/internal/flashhub/download_test.go — focused local HTTP tests.
- docs/plans/flashhub-download-reliability.md — this authoritative specification.
- docs/plans/flashhub-download-reliability.zh-CN.md — synchronized Chinese
  companion.
