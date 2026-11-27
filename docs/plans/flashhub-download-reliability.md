# FlashHub Bundle Download Reliability

This document describes the FlashHub Bundle downloader's implemented behavior,
limitations, and future work. The Chinese companion mirrors this specification.

## Scope

The downloader fetches the FlashHub index and selected Bundle files. This change
hardens file integrity checks, retries, cancellation, time bounds, temporary
file handling, final commits, and progress accounting. It does not change other
downloaders, Bundle selection, model execution, or the FlashHub index/API
contract.

## Implemented behavior

### Validation and final commit

- When `File.Size > 0`, the received byte count must match it exactly.
  Oversized responses fail as soon as they exceed the expected size; short
  responses fail at EOF.
- A non-empty `File.MD5` is checked against the complete candidate file. When
  both size and MD5 are supplied, both checks must pass.
- Existing cache files are reused only when every available validator passes.
  If size and MD5 are both absent, the existing cache-hit behavior remains, but
  the file is unverified.
- Each attempt writes to a unique temporary file in the destination directory.
  The candidate is validated, synced, and closed before it is renamed to the
  final path. A failed download or replacement leaves an existing destination
  untouched.
- Each attempt starts from byte zero. Partial bytes are not reused.

### Retries, timeouts, and cancellation

- The default limit is three complete attempts per file, including the initial
  request.
- Retryable cases include network connection/request failures, interrupted
  response bodies, HTTP 408, HTTP 429, and HTTP 5xx. Ordinary permanent 4xx
  responses, invalid URLs, integrity mismatches, and local file errors are not
  retried.
- Backoff is bounded and cancellable. The default base is 250 ms with
  exponential growth and a 2 second maximum. `Retry-After` is considered for
  HTTP 429 and is capped at that maximum.
- Standard HTTP transports use a 10 second connection/TLS bound and a 30 second
  response-header bound by default. The no-progress bound is 90 seconds and
  the total attempt bound is 2 hours. An earlier caller context deadline or
  cancellation takes precedence.
- Standard HTTP transports are cloned before connection and header limits are
  applied. For a custom `RoundTripper`, the code can bound a cancellable header
  wait, but cannot impose an independent connection-phase timeout. The request
  and attempt bounds depend on the custom transport honoring context
  cancellation.

### Temporary-file cleanup and concurrency

- At the start of `SyncBundle`, before fetching the index, the client walks the
  Bundle directory recursively. It removes only regular files whose basename
  starts with `.flashhub-download-` and whose modification time is more than
  24 hours old. Nested Bundle directories are included. A symlink used as the
  Bundle root and nested symlink directories are not followed. Other file names,
  directories, and legacy `.incomplete` files are left alone.
- The current process tracks temporary paths from creation through removal or
  final rename. The sweep skips every path still registered as active in that
  process. Missing files during a concurrent or repeated sweep are treated as
  already cleaned. Scan and removal errors are logged as warnings; `SyncBundle`
  continues so an undeletable orphan does not block otherwise valid downloads.
  The next `SyncBundle` call can retry cleanup.
- Cleanup resolves entries and removes them through a directory-rooted file
  handle. It rechecks file identity and age before removal. This prevents
  symlink or `..` path swaps from redirecting removal outside the opened Bundle
  root; mount points within the root are still traversed.
- The 24 hour age limit reduces the chance of deleting a temporary file used by
  another process, but it is not a cross-process ownership lock. The age and
  identity checks are snapshots; another process can resume or replace a file
  after the final check and before removal. An unusually long active download
  whose file has not been modified for over 24 hours can also be removed. Older
  downloader processes do not participate in the in-process registry. Cleanup
  therefore cannot provide an absolute guarantee against every cross-process
  race.
- A process crash can leave a temporary file until a later `SyncBundle` call
  encounters it after the age limit. Cleanup does not run at the instant of a
  crash or power loss.
- The legacy `<dest>.incomplete` path is neither resumed nor automatically
  deleted. It may remain on disk and consume space.
- Concurrent downloads use independent temporary files. A process-local,
  per-destination lock protects the final destination recheck and rename; it
  does not serialize network transfers or provide a cross-process lock.
- Each committed candidate passes the validators supplied by its caller. If
  those validators are absent or incomplete, they cannot prove content
  identity. Concurrent calls can duplicate network traffic. Calls with
  conflicting metadata for the same path retain last-successful-commit-wins
  behavior; there is no directory-level or version-level transaction.

### Progress and errors

- `SyncBundle` reports live transfer progress. It tracks the greatest offset
  reached across attempts, so a retry does not count the same logical bytes
  twice. Known-size progress stays below completion until the download
  succeeds, then completes to the indexed size. Unknown-size files do not
  consume a known aggregate total.
- `DownloadFile` keeps its Go signature, but `onBytes` reports bytes only after
  validation and commit, in bounded increments. It is not a live per-read
  callback. `SyncBundle` uses a separate internal callback for live progress.
- Downloader errors identify the Bundle-relative file and failure category or
  HTTP status, with an attempt count where applicable. They do not include the
  raw signed URL, URL userinfo, query string, or token.
- Public Go method signatures, FlashHub index fields, download URLs, final
  destination paths, and completed-cache layout are unchanged.

## Future work

HTTP Range resume is not implemented. A future change may add `Range` and
`Content-Range` validation, correct handling of 206 and 416 responses, ETag and
`If-Range` consistency checks, partial-file reuse across requests or restarts,
and resumed-progress accounting. Any resume implementation must retain the
integrity checks, cancellation, bounded retries, and safe final commit described
here.

## Verification

The focused Go checks are:

```bash
cd go
go test ./internal/flashhub -count=1 -v
go test -race ./internal/flashhub -count=1
```

The tests use local HTTP servers and temporary directories; they do not require
FlashHub credentials or model artifacts.

## Files

- `go/internal/flashhub/flashhub.go` — FlashHub download implementation.
- `go/internal/flashhub/download_test.go` — isolated downloader tests.
- `docs/plans/flashhub-download-reliability.md` — this specification.
- `docs/plans/flashhub-download-reliability.zh-CN.md` — Chinese companion.
