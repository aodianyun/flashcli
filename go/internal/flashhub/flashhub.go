// Package flashhub is a Go client for the FlashHub bundle repo API.
//
// Mirrors flashcli_bundle/flashhub.py: repo URL = {base}/{ns}/{name}:{version},
// index = {code:0, data:{files:[{download_url,file_name,file_size,md5_hash}]}}.
package flashhub

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"hash"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/progress"
)

// DefaultAPIBase is the default FlashHub repos API.
const DefaultAPIBase = "https://flashhub-api.aodianyun.com/api/v1/repos"

// ManifestPath is the bundle manifest filename within a repo.
const ManifestPath = "flashcli-bundle.json"

var cdnPathRe = regexp.MustCompile(`/repo/\d+/versions/\d+/(.*)$`)

// APIBase resolves FLASHCLI_FLASHHUB_API (default DefaultAPIBase).
func APIBase() string {
	if v := strings.TrimRight(strings.TrimSpace(os.Getenv("FLASHCLI_FLASHHUB_API")), "/"); v != "" {
		return v
	}
	return DefaultAPIBase
}

// RepoURL builds the repo API URL.
func RepoURL(base, namespace, name, version string) (string, error) {
	ns := strings.Trim(strings.TrimSpace(namespace), "/")
	n := strings.Trim(strings.TrimSpace(name), "/")
	v := strings.TrimSpace(version)
	if ns == "" || n == "" || v == "" {
		return "", fmt.Errorf("invalid FlashHub repo parts: namespace=%q name=%q version=%q", namespace, name, version)
	}
	if strings.TrimSpace(base) == "" {
		base = APIBase()
	}
	return strings.TrimRight(base, "/") + "/" + ns + "/" + n + ":" + v, nil
}

// File is one downloadable repo file.
type File struct {
	Path string
	URL  string
	Size int64
	MD5  string
}

// Index is a parsed repo index.
type Index struct {
	RepoURL string
	Files   []File
}

// Find locates a file by bundle-relative path (exact, then suffix/basename).
func (ix *Index) Find(relPath string) *File {
	want := strings.Trim(strings.TrimSpace(relPath), "/")
	for i := range ix.Files {
		if ix.Files[i].Path == want {
			return &ix.Files[i]
		}
	}
	wantBase := want
	if idx := strings.LastIndex(want, "/"); idx >= 0 {
		wantBase = want[idx+1:]
	}
	for i := range ix.Files {
		if strings.HasSuffix(ix.Files[i].Path, "/"+want) || filepath.Base(ix.Files[i].Path) == wantBase {
			return &ix.Files[i]
		}
	}
	return nil
}

// Client fetches repo indices and files.
type Client struct {
	HTTP      *http.Client
	CacheDir  string
	UserAgent string
	policy    downloadPolicy
	httpOnce  sync.Once
	dlHTTP    *http.Client
}

type downloadPathLock struct {
	token chan struct{}
	refs  int
}

var downloadPathLocks = struct {
	sync.Mutex
	entries map[string]*downloadPathLock
}{entries: make(map[string]*downloadPathLock)}

// acquireDownloadPath serializes final validation and rename for one path.
func acquireDownloadPath(ctx context.Context, path string) (func(), error) {
	key, err := filepath.Abs(path)
	if err != nil {
		key = filepath.Clean(path)
	} else {
		key = filepath.Clean(key)
	}
	if runtime.GOOS == "windows" {
		key = strings.ToLower(key)
	}

	downloadPathLocks.Lock()
	lock := downloadPathLocks.entries[key]
	if lock == nil {
		lock = &downloadPathLock{token: make(chan struct{}, 1)}
		lock.token <- struct{}{}
		downloadPathLocks.entries[key] = lock
	}
	lock.refs++
	downloadPathLocks.Unlock()

	select {
	case <-lock.token:
		return func() {
			lock.token <- struct{}{}
			downloadPathLocks.Lock()
			lock.refs--
			if lock.refs == 0 {
				delete(downloadPathLocks.entries, key)
			}
			downloadPathLocks.Unlock()
		}, nil
	case <-ctx.Done():
		downloadPathLocks.Lock()
		lock.refs--
		if lock.refs == 0 {
			delete(downloadPathLocks.entries, key)
		}
		downloadPathLocks.Unlock()
		return nil, ctx.Err()
	}
}

type downloadPolicy struct {
	connectTimeout time.Duration
	headerTimeout  time.Duration
	noProgress     time.Duration
	attemptTimeout time.Duration
	backoff        time.Duration
	maxAttempts    int
}

func (p downloadPolicy) withDefaults() downloadPolicy {
	if p.connectTimeout <= 0 {
		p.connectTimeout = 10 * time.Second
	}
	if p.headerTimeout <= 0 {
		p.headerTimeout = 30 * time.Second
	}
	if p.noProgress <= 0 {
		p.noProgress = 90 * time.Second
	}
	if p.attemptTimeout <= 0 {
		p.attemptTimeout = 2 * time.Hour
	}
	if p.backoff <= 0 {
		p.backoff = 250 * time.Millisecond
	}
	if p.maxAttempts <= 0 {
		p.maxAttempts = 3
	}
	return p
}

// NewClient returns a client with defaults.
func NewClient() *Client {
	return &Client{HTTP: http.DefaultClient, CacheDir: filepath.Join(paths.Cache(), "repo-index")}
}

type indexResponse struct {
	Code    *int   `json:"code"`
	Message string `json:"message"`
	Data    struct {
		Files []struct {
			DownloadURL string `json:"download_url"`
			FileName    string `json:"file_name"`
			FileSize    *int64 `json:"file_size"`
			MD5Hash     string `json:"md5_hash"`
		} `json:"files"`
	} `json:"data"`
}

// FetchIndex downloads and parses the repo index (optionally cached).
func (c *Client) FetchIndex(ctx context.Context, repoURL string, useCache bool) (*Index, error) {
	repoURL = strings.TrimRight(strings.TrimSpace(repoURL), "/")
	cachePath := c.cachePath(repoURL)
	if useCache {
		if blob, err := os.ReadFile(cachePath); err == nil {
			if ix, err := parseIndex(blob, repoURL); err == nil {
				return ix, nil
			}
		}
	}
	blob, err := c.get(ctx, repoURL)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(cachePath), 0o755); err == nil {
		_ = os.WriteFile(cachePath, append(blob, '\n'), 0o644)
	}
	return parseIndex(blob, repoURL)
}

func (c *Client) get(ctx context.Context, rawURL string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, err
	}
	if c.UserAgent != "" {
		req.Header.Set("User-Agent", c.UserAgent)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("FlashHub %s: HTTP %d", rawURL, resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

func (c *Client) cachePath(repoURL string) string {
	sum := md5.Sum([]byte(repoURL))
	// sha-like key using md5 is fine for a cache filename; mirrors Python's short hash.
	return filepath.Join(c.CacheDir, hex.EncodeToString(sum[:])[:16]+".json")
}

func parseIndex(blob []byte, repoURL string) (*Index, error) {
	var payload indexResponse
	if err := json.Unmarshal(blob, &payload); err != nil {
		return nil, fmt.Errorf("FlashHub response is not JSON: %w", err)
	}
	if payload.Code != nil && *payload.Code != 0 {
		return nil, fmt.Errorf("FlashHub API error (code=%d): %s", *payload.Code, payload.Message)
	}
	ix := &Index{RepoURL: repoURL}
	for _, e := range payload.Data.Files {
		path := pathFromDownloadURL(e.DownloadURL)
		if path != "" && e.FileName != "" {
			if idx := strings.LastIndex(path, "/"); idx >= 0 {
				parent := path[:idx]
				path = path[:idx+1] + e.FileName
				// FlashHub's newer CDN layout stores a file at
				// "<logical path>/<name>", where <logical path> already ends
				// with <name>, so the URL repeats the filename. Collapse the
				// duplicate instead of creating "<name>/<name>" on disk.
				if filepath.Base(parent) == e.FileName {
					path = parent
				}
			} else {
				path = e.FileName
			}
		} else if path == "" {
			path = e.FileName
		}
		if path == "" || strings.TrimSpace(e.DownloadURL) == "" {
			continue
		}
		f := File{Path: path, URL: e.DownloadURL, MD5: strings.ToLower(strings.TrimSpace(e.MD5Hash))}
		if e.FileSize != nil {
			f.Size = *e.FileSize
		}
		ix.Files = append(ix.Files, f)
	}
	if len(ix.Files) == 0 {
		return nil, fmt.Errorf("FlashHub repo %q returned no downloadable files", repoURL)
	}
	return ix, nil
}

func pathFromDownloadURL(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return ""
	}
	if m := cdnPathRe.FindStringSubmatch(u.Path); m != nil {
		decoded, _ := url.PathUnescape(m[1])
		return strings.Trim(decoded, "/")
	}
	decoded, _ := url.PathUnescape(u.Path)
	return strings.Trim(decoded, "/")
}

// DownloadFile fetches a repo file to dest, verifying indexed size and MD5
// when known. Failed attempts restart from byte zero; partial files are not
// resumed. onBytes receives committed-file bytes after validation succeeds.
func (c *Client) DownloadFile(ctx context.Context, f File, dest string, force, quiet bool, onBytes func(int)) error {
	return c.downloadFile(ctx, f, dest, force, quiet, onBytes, nil)
}

func (c *Client) downloadFile(ctx context.Context, f File, dest string, force, quiet bool, onBytes func(int), onAttemptProgress func(int64)) error {
	if !force {
		if ok, _ := matchesFileMetadata(f, dest); ok {
			return nil
		}
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return fmt.Errorf("download %s: create destination directory: %w", f.Path, err)
	}

	policy := c.policy.withDefaults()
	client := c.downloadHTTPClient(policy)
	var last *downloadFailure
	attempted := 0
	for attempt := 1; attempt <= policy.maxAttempts; attempt++ {
		attempted = attempt
		if err := ctx.Err(); err != nil {
			return fmt.Errorf("download %s: %w", f.Path, err)
		}
		tmpPath, size, retryable, retryAfter, failure := c.downloadAttempt(ctx, client, policy, f, dest, onAttemptProgress)
		if failure == nil {
			if err := ctx.Err(); err != nil {
				if cleanupErr := removeDownloadTemp(tmpPath); cleanupErr != nil {
					return fmt.Errorf("download %s canceled after %d attempt(s): %w (temporary file cleanup failed: %v)", f.Path, attempt, err, cleanupErr)
				}
				return &downloadError{path: f.Path, reason: "request canceled before commit", attempts: attempt, cause: err}
			}
			releaseCommitLock, err := acquireDownloadPath(ctx, dest)
			if err != nil {
				if cleanupErr := removeDownloadTemp(tmpPath); cleanupErr != nil {
					return fmt.Errorf("download %s canceled after %d attempt(s): %w (temporary file cleanup failed: %v)", f.Path, attempt, err, cleanupErr)
				}
				return &downloadError{path: f.Path, reason: "request canceled before commit", attempts: attempt, cause: err}
			}
			defer releaseCommitLock()
			if err := ctx.Err(); err != nil {
				if cleanupErr := removeDownloadTemp(tmpPath); cleanupErr != nil {
					return fmt.Errorf("download %s canceled after %d attempt(s): %w (temporary file cleanup failed: %v)", f.Path, attempt, err, cleanupErr)
				}
				return &downloadError{path: f.Path, reason: "request canceled before commit", attempts: attempt, cause: err}
			}
			if !force {
				if ok, _ := matchesFileMetadata(f, dest); ok {
					if err := removeDownloadTemp(tmpPath); err != nil {
						return fmt.Errorf("download %s failed after %d attempt(s): discard duplicate temporary file: %w", f.Path, attempt, err)
					}
					return nil
				}
			}
			if err := os.Rename(tmpPath, dest); err != nil {
				if matches, _ := matchesFileMetadata(f, dest); matches && (f.Size > 0 || strings.TrimSpace(f.MD5) != "") {
					if cleanupErr := removeDownloadTemp(tmpPath); cleanupErr != nil {
						return fmt.Errorf("download %s failed after %d attempt(s): discard duplicate temporary file: %w", f.Path, attempt, cleanupErr)
					}
					return nil
				}
				if cleanupErr := removeDownloadTemp(tmpPath); cleanupErr != nil {
					return fmt.Errorf("download %s failed after %d attempt(s): replace destination: %w (temporary file cleanup failed: %v)", f.Path, attempt, err, cleanupErr)
				}
				return fmt.Errorf("download %s failed after %d attempt(s): replace destination: %w", f.Path, attempt, err)
			}
			notifyDownloadedBytes(onBytes, size)
			return nil
		}
		if tmpPath != "" {
			if err := removeDownloadTemp(tmpPath); err != nil {
				return fmt.Errorf("download %s failed after %d attempt(s): %s; temporary file %s cleanup failed: %w", f.Path, attempt, failure.reason, tmpPath, err)
			}
		}
		last = failure
		if !retryable || attempt == policy.maxAttempts {
			break
		}
		wait := retryDelay(policy.backoff, attempt, retryAfter)
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			return &downloadError{path: f.Path, reason: "request canceled during retry wait", attempts: attempt, cause: ctx.Err()}
		case <-timer.C:
		}
	}
	if last == nil {
		return fmt.Errorf("download %s: failed without an attempt", f.Path)
	}
	return &downloadError{path: f.Path, reason: last.reason, attempts: attempted, cause: last.cause}
}

type downloadFailure struct {
	reason string
	cause  error
}

type downloadError struct {
	path     string
	reason   string
	attempts int
	cause    error
}

func (e *downloadError) Error() string {
	return fmt.Sprintf("download %s failed after %d attempt(s): %s", e.path, e.attempts, e.reason)
}

func (e *downloadError) Unwrap() error { return e.cause }

type connectionTimeoutError struct{}

func (connectionTimeoutError) Error() string   { return "connection timed out" }
func (connectionTimeoutError) Timeout() bool   { return true }
func (connectionTimeoutError) Temporary() bool { return true }

// downloadHTTPClient clones HTTP once so downloads share a configured
// transport and connection pool. Set HTTP before the first DownloadFile call.
func (c *Client) downloadHTTPClient(policy downloadPolicy) *http.Client {
	c.httpOnce.Do(func() {
		base := c.HTTP
		if base == nil {
			base = http.DefaultClient
		}
		client := &http.Client{
			Transport:     base.Transport,
			CheckRedirect: base.CheckRedirect,
			Jar:           base.Jar,
			Timeout:       base.Timeout,
		}
		transport := base.Transport
		if transport == nil {
			transport = http.DefaultTransport
		}
		if standard, ok := transport.(*http.Transport); ok {
			clone := standard.Clone()
			if clone.DialTLSContext != nil {
				dialTLS := clone.DialTLSContext
				clone.DialTLSContext = func(ctx context.Context, network, addr string) (net.Conn, error) {
					dialCtx, cancel := context.WithTimeout(ctx, policy.connectTimeout)
					defer cancel()
					conn, err := dialTLS(dialCtx, network, addr)
					if errors.Is(dialCtx.Err(), context.DeadlineExceeded) {
						if conn != nil {
							_ = conn.Close()
						}
						return nil, connectionTimeoutError{}
					}
					return conn, err
				}
			} else {
				dial := clone.DialContext
				if dial == nil {
					dialer := &net.Dialer{}
					dial = dialer.DialContext
				}
				clone.DialContext = func(ctx context.Context, network, addr string) (net.Conn, error) {
					dialCtx, cancel := context.WithTimeout(ctx, policy.connectTimeout)
					defer cancel()
					conn, err := dial(dialCtx, network, addr)
					if errors.Is(dialCtx.Err(), context.DeadlineExceeded) {
						if conn != nil {
							_ = conn.Close()
						}
						return nil, connectionTimeoutError{}
					}
					return conn, err
				}
			}
			if clone.TLSHandshakeTimeout == 0 || clone.TLSHandshakeTimeout > policy.connectTimeout {
				clone.TLSHandshakeTimeout = policy.connectTimeout
			}
			if clone.ResponseHeaderTimeout == 0 || clone.ResponseHeaderTimeout > policy.headerTimeout {
				clone.ResponseHeaderTimeout = policy.headerTimeout
			}
			client.Transport = clone
		}
		c.dlHTTP = client
	})
	return c.dlHTTP
}

func (c *Client) downloadAttempt(parent context.Context, client *http.Client, policy downloadPolicy, f File, dest string, onAttemptProgress func(int64)) (string, int64, bool, time.Duration, *downloadFailure) {
	attemptCtx, cancelAttempt := context.WithTimeout(parent, policy.attemptTimeout)
	defer cancelAttempt()
	requestCtx, cancelRequest := context.WithCancel(attemptCtx)
	defer cancelRequest()

	request, err := http.NewRequestWithContext(requestCtx, http.MethodGet, f.URL, nil)
	if err != nil {
		return "", 0, false, 0, &downloadFailure{reason: "invalid download URL"}
	}
	if c.UserAgent != "" {
		request.Header.Set("User-Agent", c.UserAgent)
	}
	var headerTimedOut atomic.Bool
	var headerTimer *time.Timer
	var headerDone chan struct{}
	if _, standardTransport := client.Transport.(*http.Transport); !standardTransport {
		// Custom RoundTrippers must honor the request context for this bound to
		// interrupt a RoundTrip that is still waiting for response headers.
		headerDone = make(chan struct{})
		headerTimer = time.AfterFunc(policy.headerTimeout, func() {
			defer close(headerDone)
			headerTimedOut.Store(true)
			cancelRequest()
		})
	}
	response, err := client.Do(request)
	if headerTimer != nil {
		if !headerTimer.Stop() {
			// Wait for a racing timeout callback before inspecting its result.
			<-headerDone
		}
	}
	if err != nil {
		if response != nil && response.Body != nil {
			_ = response.Body.Close()
		}
		if parent.Err() != nil {
			return "", 0, false, 0, &downloadFailure{reason: "request canceled", cause: parent.Err()}
		}
		var connectionTimeout connectionTimeoutError
		if errors.As(err, &connectionTimeout) {
			return "", 0, true, 0, &downloadFailure{reason: connectionTimeout.Error()}
		}
		if headerTimedOut.Load() {
			return "", 0, true, 0, &downloadFailure{reason: "response headers timed out"}
		}
		if attemptCtx.Err() != nil {
			return "", 0, true, 0, &downloadFailure{reason: "attempt timed out", cause: attemptCtx.Err()}
		}
		if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
			return "", 0, true, 0, &downloadFailure{reason: "response ended before headers completed"}
		}
		var networkError net.Error
		if errors.As(err, &networkError) && networkError.Timeout() {
			return "", 0, true, 0, &downloadFailure{reason: "request timed out"}
		}
		var operationError *net.OpError
		if errors.As(err, &operationError) || (errors.As(err, &networkError) && networkError.Temporary()) {
			return "", 0, true, 0, &downloadFailure{reason: "network request failed"}
		}
		return "", 0, false, 0, &downloadFailure{reason: "request failed"}
	}
	if parent.Err() != nil {
		_ = response.Body.Close()
		return "", 0, false, 0, &downloadFailure{reason: "request canceled", cause: parent.Err()}
	}
	if headerTimedOut.Load() {
		_ = response.Body.Close()
		return "", 0, true, 0, &downloadFailure{reason: "response headers timed out"}
	}
	if attemptCtx.Err() != nil {
		_ = response.Body.Close()
		return "", 0, true, 0, &downloadFailure{reason: "attempt timed out", cause: attemptCtx.Err()}
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		retryable := response.StatusCode == http.StatusRequestTimeout || response.StatusCode == http.StatusTooManyRequests || response.StatusCode >= 500
		var retryAfter time.Duration
		if response.StatusCode == http.StatusTooManyRequests {
			retryAfter = parseRetryAfter(response.Header.Get("Retry-After"))
		}
		return "", 0, retryable, retryAfter, &downloadFailure{
			reason: fmt.Sprintf("HTTP %d", response.StatusCode),
		}
	}

	out, err := os.CreateTemp(filepath.Dir(dest), ".flashhub-download-")
	if err != nil {
		return "", 0, false, 0, &downloadFailure{reason: "create temporary file failed", cause: err}
	}
	tmpPath := out.Name()
	closed := false
	closeOut := func() error {
		if closed {
			return nil
		}
		closed = true
		return out.Close()
	}
	defer closeOut()

	var writer io.Writer = out
	var md5Hash hash.Hash
	expectedMD5 := strings.TrimSpace(f.MD5)
	if expectedMD5 != "" {
		md5Hash = md5.New()
		writer = io.MultiWriter(out, md5Hash)
	}
	var written int64
	var noProgressTimedOut atomic.Bool
	progressTimer := time.AfterFunc(policy.noProgress, func() {
		noProgressTimedOut.Store(true)
		cancelRequest()
	})
	defer progressTimer.Stop()
	buffer := make([]byte, 64*1024)
	for {
		read, readErr := response.Body.Read(buffer)
		if read > 0 {
			n, writeErr := writer.Write(buffer[:read])
			written += int64(n)
			if writeErr != nil {
				_ = closeOut()
				return tmpPath, written, false, 0, &downloadFailure{reason: "write temporary file failed", cause: writeErr}
			}
			if n != read {
				_ = closeOut()
				return tmpPath, written, false, 0, &downloadFailure{reason: "write temporary file failed", cause: io.ErrShortWrite}
			}
			if f.Size > 0 && written > f.Size {
				_ = closeOut()
				return tmpPath, written, false, 0, &downloadFailure{reason: fmt.Sprintf("size mismatch (received more than expected %d bytes)", f.Size)}
			}
			if requestCtx.Err() == nil {
				progressTimer.Reset(policy.noProgress)
			}
			if onAttemptProgress != nil {
				onAttemptProgress(written)
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			_ = closeOut()
			if parent.Err() != nil {
				return tmpPath, written, false, 0, &downloadFailure{reason: "request canceled", cause: parent.Err()}
			}
			if noProgressTimedOut.Load() {
				return tmpPath, written, true, 0, &downloadFailure{reason: "download made no progress before timeout"}
			}
			if attemptCtx.Err() != nil {
				return tmpPath, written, true, 0, &downloadFailure{reason: "attempt timed out", cause: attemptCtx.Err()}
			}
			return tmpPath, written, true, 0, &downloadFailure{reason: "response body interrupted"}
		}
	}
	if err := parent.Err(); err != nil {
		_ = closeOut()
		return tmpPath, written, false, 0, &downloadFailure{reason: "request canceled", cause: err}
	}
	if attemptCtx.Err() != nil {
		_ = closeOut()
		return tmpPath, written, true, 0, &downloadFailure{reason: "attempt timed out", cause: attemptCtx.Err()}
	}
	if noProgressTimedOut.Load() {
		_ = closeOut()
		return tmpPath, written, true, 0, &downloadFailure{reason: "download made no progress before timeout"}
	}
	if f.Size > 0 && written != f.Size {
		_ = closeOut()
		return tmpPath, written, false, 0, &downloadFailure{reason: fmt.Sprintf("size mismatch (received %d bytes, expected %d)", written, f.Size)}
	}
	if md5Hash != nil && !strings.EqualFold(hex.EncodeToString(md5Hash.Sum(nil)), expectedMD5) {
		_ = closeOut()
		return tmpPath, written, false, 0, &downloadFailure{reason: "MD5 mismatch"}
	}
	if err := out.Chmod(0o644); err != nil {
		_ = closeOut()
		return tmpPath, written, false, 0, &downloadFailure{reason: "set downloaded file permissions failed", cause: err}
	}
	if err := out.Sync(); err != nil {
		_ = closeOut()
		return tmpPath, written, false, 0, &downloadFailure{reason: "flush temporary file failed", cause: err}
	}
	if err := closeOut(); err != nil {
		return tmpPath, written, false, 0, &downloadFailure{reason: "close temporary file failed", cause: err}
	}
	if err := parent.Err(); err != nil {
		return tmpPath, written, false, 0, &downloadFailure{reason: "request canceled", cause: err}
	}
	if err := attemptCtx.Err(); err != nil {
		return tmpPath, written, true, 0, &downloadFailure{reason: "attempt timed out", cause: err}
	}
	return tmpPath, written, false, 0, nil
}

func matchesFileMetadata(f File, path string) (bool, error) {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		return false, err
	}
	if f.Size > 0 && info.Size() != f.Size {
		return false, nil
	}
	if strings.TrimSpace(f.MD5) == "" {
		return true, nil
	}
	got, err := fileMD5(path)
	if err != nil {
		return false, err
	}
	return strings.EqualFold(got, strings.TrimSpace(f.MD5)), nil
}

func removeDownloadTemp(path string) error {
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

func notifyDownloadedBytes(onBytes func(int), total int64) {
	if onBytes == nil {
		return
	}
	const chunk = int64(1 << 20)
	for total > 0 {
		n := total
		if n > chunk {
			n = chunk
		}
		onBytes(int(n))
		total -= n
	}
}

func retryDelay(base time.Duration, attempt int, retryAfter time.Duration) time.Duration {
	wait := base << (attempt - 1)
	const maxWait = 2 * time.Second
	if retryAfter > wait {
		wait = retryAfter
	}
	if wait > maxWait {
		return maxWait
	}
	return wait
}

func parseRetryAfter(value string) time.Duration {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0
	}
	if seconds, err := time.ParseDuration(value + "s"); err == nil {
		return seconds
	}
	if when, err := http.ParseTime(value); err == nil {
		if delay := time.Until(when); delay > 0 {
			return delay
		}
	}
	return 0
}

// DownloadManifest fetches flashcli-bundle.json from a repo into dest.
func (c *Client) DownloadManifest(ctx context.Context, repoURL, dest string, force, quiet bool) (map[string]any, error) {
	ix, err := c.FetchIndex(ctx, repoURL, false)
	if err != nil {
		return nil, err
	}
	entry := ix.Find(ManifestPath)
	if entry == nil {
		return nil, fmt.Errorf("No %s in FlashHub repo %q", ManifestPath, repoURL)
	}
	if err := c.DownloadFile(ctx, *entry, dest, force, quiet, nil); err != nil {
		return nil, err
	}
	blob, err := os.ReadFile(dest)
	if err != nil {
		return nil, err
	}
	var data map[string]any
	if err := json.Unmarshal(blob, &data); err != nil {
		return nil, err
	}
	return data, nil
}

func fileMD5(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := md5.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// syncFileProgress reports the highest offset reached in any attempt for one
// logical file, then completes the indexed size only after DownloadFile returns.
type syncFileProgress struct {
	stage      *progress.Stage
	fileSize   int64
	totalBytes int64
	reported   int64
	highWater  int64
}

func (p *syncFileProgress) update(attemptBytes int64) {
	if p == nil || p.stage == nil || attemptBytes <= p.highWater {
		return
	}
	p.highWater = attemptBytes
	limit := attemptBytes
	if p.fileSize > 0 {
		limit = p.fileSize - 1
	} else if p.totalBytes > 0 {
		// An unknown-size file cannot safely consume a known aggregate total.
		return
	}
	if limit > attemptBytes {
		limit = attemptBytes
	}
	if limit <= p.reported {
		return
	}
	addSyncProgress(p.stage, limit-p.reported)
	p.reported = limit
}

func (p *syncFileProgress) complete() {
	if p == nil || p.stage == nil || p.fileSize <= p.reported {
		return
	}
	addSyncProgress(p.stage, p.fileSize-p.reported)
	p.reported = p.fileSize
}

func addSyncProgress(stage *progress.Stage, total int64) {
	const chunk = int64(1 << 20)
	for total > 0 {
		n := total
		if n > chunk {
			n = chunk
		}
		stage.Add(int(n))
		total -= n
	}
}

// ErrNotFound is returned when a repo/file is absent.
var ErrNotFound = errors.New("flashhub: not found")

// SyncBundle downloads the bundle entry tree plus only the selected runtime
// directory into bundleDir, and returns the parsed manifest. runtimeRel may be
// empty for pure-Python bundles. allRuntimeRels lists every runtime directory
// declared by the manifest so unselected cells are skipped even when they do
// not live under the legacy top-level runtime/ directory.
func (c *Client) SyncBundle(ctx context.Context, repoURL, bundleDir, runtimeRel string, allRuntimeRels []string, quiet bool) (map[string]any, error) {
	// Always fetch a fresh index: a cached one may list artifacts from an
	// earlier upload (stale download URLs → 404).
	ix, err := c.FetchIndex(ctx, repoURL, false)
	if err != nil {
		return nil, err
	}
	manifestEntry := ix.Find(ManifestPath)
	if manifestEntry == nil {
		return nil, fmt.Errorf("No %s in FlashHub repo %q", ManifestPath, repoURL)
	}
	manifestDest := filepath.Join(bundleDir, ManifestPath)
	if err := c.DownloadFile(ctx, *manifestEntry, manifestDest, false, quiet, nil); err != nil {
		return nil, err
	}
	blob, err := os.ReadFile(manifestDest)
	if err != nil {
		return nil, err
	}
	var manifest map[string]any
	if err := json.Unmarshal(blob, &manifest); err != nil {
		return nil, fmt.Errorf("parse %s: %w", ManifestPath, err)
	}

	var wanted []File
	var totalBytes int64
	for _, f := range ix.Files {
		if !WantFile(f.Path, runtimeRel, allRuntimeRels) {
			continue
		}
		wanted = append(wanted, f)
		totalBytes += f.Size
	}
	st := progress.StartWithSink("sync", repoURL, progress.SinkFromContext(ctx))
	st.Totals(len(wanted), totalBytes)
	for _, f := range wanted {
		dest := filepath.Join(bundleDir, filepath.FromSlash(f.Path))
		fileProgress := &syncFileProgress{stage: st, fileSize: f.Size, totalBytes: totalBytes}
		if err := c.downloadFile(ctx, f, dest, false, quiet, nil, fileProgress.update); err != nil {
			return nil, err
		}
		fileProgress.complete()
		st.FileDone()
	}
	st.Done()
	return manifest, nil
}

// WantFile reports whether a repo-relative path should be synced. The selected
// runtime directory is always included. Other manifest-declared runtime
// directories are excluded, regardless of where they live. Paths under the
// legacy top-level runtime/ tree are also excluded unless selected.
func WantFile(path, runtimeRel string, allRuntimeRels []string) bool {
	p := strings.Trim(path, "/")
	selected := strings.Trim(strings.TrimSpace(runtimeRel), "/")
	if selected != "" && pathWithin(p, selected) {
		return true
	}
	for _, rel := range allRuntimeRels {
		rel = strings.Trim(strings.TrimSpace(rel), "/")
		if rel == "" || rel == selected {
			continue
		}
		if pathWithin(p, rel) {
			return false
		}
	}
	// Preserve the legacy behavior: unselected cells under the top-level
	// runtime/ tree are never downloaded, even if the manifest no longer
	// declares them (for example stale directories from an older release).
	if strings.HasPrefix(p, "runtime/") {
		return false
	}
	return true
}

func pathWithin(path, rel string) bool {
	return path == rel || strings.HasPrefix(path, rel+"/")
}

// MarkerName is the bundle sync marker filename.
const MarkerName = ".flashcli_bundle.json"

// WriteMarker writes the bundle sync marker under bundleDir from data.
func WriteMarker(bundleDir string, data map[string]any) error {
	blob, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(bundleDir, MarkerName), append(blob, '\n'), 0o644)
}
