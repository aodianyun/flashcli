package flashhub

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aodianyun/flashcli/go/internal/progress"
)

func testDownloadClient(httpClient *http.Client) *Client {
	return &Client{
		HTTP: httpClient,
		policy: downloadPolicy{
			connectTimeout: 100 * time.Millisecond,
			headerTimeout:  100 * time.Millisecond,
			noProgress:     100 * time.Millisecond,
			attemptTimeout: 500 * time.Millisecond,
			backoff:        time.Millisecond,
			maxAttempts:    3,
		},
	}
}

func payloadMD5(data []byte) string {
	sum := md5.Sum(data)
	return hex.EncodeToString(sum[:])
}

func TestDownloadFileValidatesSizeAndMD5(t *testing.T) {
	payload := []byte("verified payload")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "model.bin")
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "model.bin", URL: srv.URL, Size: int64(len(payload)), MD5: payloadMD5(payload)}, dest, false, true, nil,
	)
	if err != nil {
		t.Fatalf("DownloadFile: %v", err)
	}
	got, err := os.ReadFile(dest)
	if err != nil || string(got) != string(payload) {
		t.Fatalf("destination = %q, err = %v", got, err)
	}
}

func TestDownloadFileRejectsWrongSizeAndPreservesDestination(t *testing.T) {
	payload := []byte("short")
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "model.bin")
	if err := os.WriteFile(dest, []byte("old valid content"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "model.bin", URL: srv.URL, Size: int64(len(payload) + 1)}, dest, true, true, nil,
	)
	if err == nil || !strings.Contains(err.Error(), "size mismatch") {
		t.Fatalf("DownloadFile error = %v, want size mismatch", err)
	}
	got, readErr := os.ReadFile(dest)
	if readErr != nil || string(got) != "old valid content" {
		t.Fatalf("old destination = %q, err = %v", got, readErr)
	}
	if requests.Load() != 1 {
		t.Fatalf("requests = %d, want 1 (integrity errors are not retried)", requests.Load())
	}
	assertNoDownloadTemps(t, dest)
}

func TestDownloadFileRejectsOversizedResponse(t *testing.T) {
	payload := []byte("too long")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "f.bin")
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "f.bin", URL: srv.URL, Size: int64(len(payload) - 1)}, dest, true, true, nil,
	)
	if err == nil || !strings.Contains(err.Error(), "size mismatch") {
		t.Fatalf("error = %v, want size mismatch", err)
	}
	if _, statErr := os.Stat(dest); !os.IsNotExist(statErr) {
		t.Fatalf("destination stat error = %v, want not exist", statErr)
	}
	assertNoDownloadTemps(t, dest)
}

func TestDownloadFileDoesNotRetryMD5MismatchOrReplaceExistingFile(t *testing.T) {
	payload := []byte("bad payload")
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "f.bin")
	if err := os.WriteFile(dest, []byte("previous file"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "f.bin", URL: srv.URL, MD5: payloadMD5([]byte("expected payload"))}, dest, true, true, nil,
	)
	if err == nil || !strings.Contains(err.Error(), "MD5 mismatch") {
		t.Fatalf("error = %v, want MD5 mismatch", err)
	}
	if requests.Load() != 1 {
		t.Fatalf("requests = %d, want 1", requests.Load())
	}
	got, readErr := os.ReadFile(dest)
	if readErr != nil || string(got) != "previous file" {
		t.Fatalf("destination = %q, err = %v", got, readErr)
	}
	assertNoDownloadTemps(t, dest)
}

func TestDownloadFileCacheValidatesKnownSize(t *testing.T) {
	payload := []byte("correct")
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "model.bin")
	if err := os.WriteFile(dest, []byte("wrong"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "model.bin", URL: srv.URL, Size: int64(len(payload))}, dest, false, true, nil,
	)
	if err != nil {
		t.Fatalf("DownloadFile: %v", err)
	}
	if requests.Load() != 1 {
		t.Fatalf("requests = %d, want 1 (damaged cache must be fetched)", requests.Load())
	}
	got, _ := os.ReadFile(dest)
	if string(got) != string(payload) {
		t.Fatalf("destination = %q", got)
	}
}

func TestDownloadFileReusesValidCache(t *testing.T) {
	payload := []byte("cached bytes")
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		_, _ = w.Write([]byte("unexpected network request"))
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "cached.bin")
	if err := os.WriteFile(dest, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "cached.bin", URL: srv.URL, Size: int64(len(payload)), MD5: payloadMD5(payload)}, dest, false, true, nil,
	)
	if err != nil {
		t.Fatalf("DownloadFile: %v", err)
	}
	if requests.Load() != 0 {
		t.Fatalf("requests = %d, want 0", requests.Load())
	}
}

func TestDownloadFileKeepsLegacyCacheWhenValidatorsMissing(t *testing.T) {
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		_, _ = io.WriteString(w, "new")
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "legacy.bin")
	if err := os.WriteFile(dest, []byte("legacy"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "legacy.bin", URL: srv.URL}, dest, false, true, nil,
	); err != nil {
		t.Fatal(err)
	}
	if requests.Load() != 0 {
		t.Fatalf("requests = %d, want 0", requests.Load())
	}
	got, _ := os.ReadFile(dest)
	if string(got) != "legacy" {
		t.Fatalf("destination = %q", got)
	}
}

func TestDownloadFileRetriesInterruptedTransferFromStartAndProgressIsCommittedBytes(t *testing.T) {
	payload := []byte("complete payload")
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if requests.Add(1) == 1 {
			w.Header().Set("Content-Length", fmt.Sprint(len(payload)))
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write(payload[:5])
			w.(http.Flusher).Flush()
			conn, _, err := w.(http.Hijacker).Hijack()
			if err == nil {
				_ = conn.Close()
			}
			return
		}
		if r.Header.Get("Range") != "" {
			t.Errorf("unexpected Range header: %q", r.Header.Get("Range"))
		}
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "model.bin")
	var progress atomic.Int64
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "model.bin", URL: srv.URL, Size: int64(len(payload)), MD5: payloadMD5(payload)}, dest, false, true,
		func(n int) { progress.Add(int64(n)) },
	)
	if err != nil {
		t.Fatalf("DownloadFile: %v", err)
	}
	if requests.Load() != 2 {
		t.Fatalf("requests = %d, want 2", requests.Load())
	}
	if progress.Load() != int64(len(payload)) {
		t.Fatalf("reported bytes = %d, want %d", progress.Load(), len(payload))
	}
	assertNoDownloadTemps(t, dest)
}

func TestDownloadFileRetriesEOFUnexpectedEOFAndConnectionResetBeforeHeaders(t *testing.T) {
	for _, test := range []struct {
		name string
		err  error
	}{
		{name: "eof", err: io.EOF},
		{name: "unexpected-eof", err: io.ErrUnexpectedEOF},
		{name: "connection-reset", err: &net.OpError{Op: "read", Net: "tcp", Err: errors.New("connection reset by peer")}},
	} {
		t.Run(test.name, func(t *testing.T) {
			var requests atomic.Int32
			transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
				if requests.Add(1) == 1 {
					return nil, test.err
				}
				body := []byte("payload")
				return &http.Response{
					StatusCode:    http.StatusOK,
					Header:        make(http.Header),
					Body:          io.NopCloser(strings.NewReader(string(body))),
					ContentLength: int64(len(body)),
					Request:       r,
				}, nil
			})
			client := testDownloadClient(&http.Client{Transport: transport})
			dest := filepath.Join(t.TempDir(), "f.bin")
			err := client.DownloadFile(
				context.Background(), File{Path: "f.bin", URL: "http://local.test/file", Size: int64(len("payload"))}, dest, true, true, nil,
			)
			if err != nil {
				t.Fatalf("DownloadFile: %v", err)
			}
			if requests.Load() != 2 {
				t.Fatalf("requests = %d, want 2", requests.Load())
			}
			got, readErr := os.ReadFile(dest)
			if readErr != nil || string(got) != "payload" {
				t.Fatalf("destination = %q, err = %v", got, readErr)
			}
		})
	}
}

func TestDownloadFileRetriesConnectionClosedBeforeResponseHeaders(t *testing.T) {
	var requests atomic.Int32
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if requests.Add(1) == 1 {
			conn, _, err := w.(http.Hijacker).Hijack()
			if err != nil {
				t.Errorf("hijack: %v", err)
				return
			}
			_ = conn.Close()
			return
		}
		_, _ = io.WriteString(w, "payload")
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "f.bin")
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "f.bin", URL: srv.URL, Size: int64(len("payload"))}, dest, true, true, nil,
	)
	if err != nil {
		t.Fatalf("DownloadFile: %v", err)
	}
	if requests.Load() != 2 {
		t.Fatalf("requests = %d, want retry after EOF before response headers", requests.Load())
	}
}

func TestSyncBundleProgressIsLiveAndBoundedAcrossRetry(t *testing.T) {
	previousQuiet := progress.IsQuiet()
	progress.SetQuiet(true)
	defer progress.SetQuiet(previousQuiet)

	manifest := []byte(`{"name":"test"}`)
	model := []byte(strings.Repeat("m", 100))
	firstChunk := make(chan struct{}, 1)
	allowFirstFailure := make(chan struct{}, 1)
	var requests atomic.Int32
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/index":
			index, err := json.Marshal(map[string]any{"code": 0, "data": map[string]any{"files": []any{
				map[string]any{"download_url": srv.URL + "/flashcli-bundle.json", "file_name": "flashcli-bundle.json", "file_size": len(manifest), "md5_hash": payloadMD5(manifest)},
				map[string]any{"download_url": srv.URL + "/model.bin", "file_name": "model.bin", "file_size": len(model), "md5_hash": payloadMD5(model)},
			}}})
			if err != nil {
				t.Errorf("marshal index: %v", err)
				return
			}
			_, _ = w.Write(index)
		case "/flashcli-bundle.json":
			_, _ = w.Write(manifest)
		case "/model.bin":
			if requests.Add(1) == 1 {
				conn, rw, err := w.(http.Hijacker).Hijack()
				if err != nil {
					t.Errorf("hijack: %v", err)
					return
				}
				_, _ = fmt.Fprintf(rw, "HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n", len(model))
				_, _ = rw.Write(model[:40])
				if err := rw.Flush(); err != nil {
					t.Errorf("flush partial response: %v", err)
					_ = conn.Close()
					return
				}
				firstChunk <- struct{}{}
				<-allowFirstFailure
				_ = conn.Close()
				return
			}
			w.Header().Set("Content-Length", fmt.Sprint(len(model)))
			_, _ = w.Write(model)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	client := NewClient()
	client.HTTP = srv.Client()
	client.CacheDir = filepath.Join(t.TempDir(), "index-cache")
	bundleDir := t.TempDir()
	updates := make(chan progress.Update, 32)
	ctx := progress.WithSink(context.Background(), func(update progress.Update) {
		select {
		case updates <- update:
		default:
		}
	})
	done := make(chan error, 1)
	finished := false
	defer func() {
		if !finished {
			select {
			case allowFirstFailure <- struct{}{}:
			default:
			}
			select {
			case <-done:
			case <-time.After(time.Second):
			}
		}
	}()
	go func() {
		_, err := client.SyncBundle(ctx, srv.URL+"/index", bundleDir, "", nil, true)
		done <- err
	}()
	select {
	case <-firstChunk:
	case <-time.After(time.Second):
		t.Fatal("first partial response did not arrive")
	}
	var firstLive progress.Update
	deadline := time.After(time.Second)
	for firstLive.Written == 0 {
		select {
		case update := <-updates:
			if update.Written > int64(len(manifest)) {
				firstLive = update
			}
		case <-deadline:
			t.Fatal("SyncBundle did not report bytes while the first attempt was still active")
		}
	}
	if firstLive.Percent >= 100 {
		t.Fatalf("partial-attempt progress = %+v, want less than 100%% before commit", firstLive)
	}
	allowFirstFailure <- struct{}{}
	select {
	case err := <-done:
		finished = true
		if err != nil {
			t.Fatalf("SyncBundle: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("SyncBundle did not finish after retry")
	}
	var last progress.Update
	for {
		select {
		case update := <-updates:
			if update.Written > update.Total && update.Total > 0 {
				t.Fatalf("progress exceeded total: %+v", update)
			}
			if update.Percent > 100 {
				t.Fatalf("progress exceeded 100%%: %+v", update)
			}
			last = update
		default:
			if last.Written == 0 {
				t.Fatal("no final progress update received")
			}
			if last.Total <= 0 || last.Written != last.Total || last.Percent != 100 || !last.Done {
				t.Fatalf("final progress = %+v, want complete exact total", last)
			}
			return
		}
	}
}

func TestDownloadFileRetriesTemporaryStatusesOnly(t *testing.T) {
	for _, status := range []int{http.StatusRequestTimeout, http.StatusTooManyRequests, http.StatusInternalServerError, http.StatusServiceUnavailable} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			payload := []byte("ok")
			var requests atomic.Int32
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if requests.Add(1) == 1 {
					w.WriteHeader(status)
					return
				}
				_, _ = w.Write(payload)
			}))
			defer srv.Close()

			dest := filepath.Join(t.TempDir(), "f.bin")
			err := testDownloadClient(srv.Client()).DownloadFile(
				context.Background(), File{Path: "f.bin", URL: srv.URL, Size: int64(len(payload))}, dest, true, true, nil,
			)
			if err != nil {
				t.Fatalf("DownloadFile: %v", err)
			}
			if requests.Load() != 2 {
				t.Fatalf("requests = %d, want 2", requests.Load())
			}
		})
	}
}

func TestDownloadFileStopsAtRetryLimit(t *testing.T) {
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	client := testDownloadClient(srv.Client())
	dest := filepath.Join(t.TempDir(), "f.bin")
	err := client.DownloadFile(context.Background(), File{Path: "f.bin", URL: srv.URL}, dest, true, true, nil)
	if err == nil || !strings.Contains(err.Error(), "after 3 attempt(s)") {
		t.Fatalf("error = %v, want bounded retry error", err)
	}
	if requests.Load() != 3 {
		t.Fatalf("requests = %d, want 3", requests.Load())
	}
}

func TestDownloadFileHonorsCancellationDuringRetryWait(t *testing.T) {
	firstRequest := make(chan struct{})
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if requests.Add(1) == 1 {
			close(firstRequest)
		}
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	client := testDownloadClient(srv.Client())
	client.policy.backoff = 200 * time.Millisecond
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	dest := filepath.Join(t.TempDir(), "f.bin")
	go func() {
		done <- client.DownloadFile(ctx, File{Path: "f.bin", URL: srv.URL}, dest, true, true, nil)
	}()
	<-firstRequest
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error = %v, want context.Canceled", err)
		}
	case <-time.After(time.Second):
		t.Fatal("DownloadFile did not stop during retry wait")
	}
	if requests.Load() != 1 {
		t.Fatalf("requests = %d, want 1 after cancellation", requests.Load())
	}
}

func TestDownloadFileDoesNotRetryPermanentStatusesOrLeakURL(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden, http.StatusNotFound} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			var requests atomic.Int32
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				w.WriteHeader(status)
			}))
			defer srv.Close()

			secret := "secret-token-value"
			url := strings.Replace(srv.URL, "http://", "http://user:"+secret+"@", 1) + "/file?token=" + secret
			dest := filepath.Join(t.TempDir(), "f.bin")
			err := testDownloadClient(srv.Client()).DownloadFile(
				context.Background(), File{Path: "f.bin", URL: url}, dest, true, true, nil,
			)
			if err == nil || strings.Contains(err.Error(), secret) || strings.Contains(err.Error(), "?token=") || strings.Contains(err.Error(), "user:") {
				t.Fatalf("error must be present and redact URL credentials: %v", err)
			}
			if requests.Load() != 1 {
				t.Fatalf("requests = %d, want 1", requests.Load())
			}
		})
	}
}

func TestDownloadFileHonorsCancellationDuringBodyRead(t *testing.T) {
	started := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "100")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "a")
		w.(http.Flusher).Flush()
		close(started)
		<-r.Context().Done()
	}))
	defer srv.Close()

	ctx, cancel := context.WithCancel(context.Background())
	dest := filepath.Join(t.TempDir(), "f.bin")
	done := make(chan error, 1)
	go func() {
		done <- testDownloadClient(srv.Client()).DownloadFile(
			ctx, File{Path: "f.bin", URL: srv.URL}, dest, true, true, nil,
		)
	}()
	<-started
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error = %v, want context.Canceled", err)
		}
	case <-time.After(time.Second):
		t.Fatal("DownloadFile did not stop after context cancellation")
	}
	if _, err := os.Stat(dest); !os.IsNotExist(err) {
		t.Fatalf("destination stat error = %v, want not exist", err)
	}
	assertNoDownloadTemps(t, dest)
}

func TestDownloadFileStopsAfterNoProgressTimeout(t *testing.T) {
	started := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "100")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "a")
		w.(http.Flusher).Flush()
		close(started)
		<-r.Context().Done()
	}))
	defer srv.Close()

	client := testDownloadClient(srv.Client())
	client.policy.noProgress = 40 * time.Millisecond
	client.policy.maxAttempts = 1
	dest := filepath.Join(t.TempDir(), "f.bin")
	err, elapsed := downloadWithin(t, func() error {
		return client.DownloadFile(context.Background(), File{Path: "f.bin", URL: srv.URL}, dest, true, true, nil)
	})
	if err == nil {
		t.Fatal("expected no-progress timeout")
	}
	if elapsed > time.Second {
		t.Fatalf("no-progress timeout took %s", elapsed)
	}
	assertNoDownloadTemps(t, dest)
}

func TestDownloadFileEnforcesHeaderTimeout(t *testing.T) {
	started := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		<-r.Context().Done()
	}))
	defer srv.Close()

	client := testDownloadClient(srv.Client())
	client.policy.headerTimeout = 40 * time.Millisecond
	client.policy.maxAttempts = 1
	dest := filepath.Join(t.TempDir(), "f.bin")
	err, elapsed := downloadWithin(t, func() error {
		return client.DownloadFile(context.Background(), File{Path: "f.bin", URL: srv.URL}, dest, true, true, nil)
	})
	if err == nil {
		t.Fatal("expected response-header timeout")
	}
	if elapsed > time.Second {
		t.Fatalf("header timeout took %s", elapsed)
	}
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("server did not receive the header-timeout request")
	}
}

func TestDownloadFileBoundsHeadersForCustomRoundTripper(t *testing.T) {
	started := make(chan struct{})
	transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		close(started)
		<-r.Context().Done()
		return nil, r.Context().Err()
	})
	client := testDownloadClient(&http.Client{Transport: transport})
	client.policy.headerTimeout = 40 * time.Millisecond
	client.policy.maxAttempts = 1
	dest := filepath.Join(t.TempDir(), "f.bin")
	err, _ := downloadWithin(t, func() error {
		return client.DownloadFile(
			context.Background(), File{Path: "f.bin", URL: "http://example.invalid/file"}, dest, true, true, nil,
		)
	})
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("custom transport did not receive the request")
	}
	if err == nil || !strings.Contains(err.Error(), "response headers timed out") {
		t.Fatalf("error = %v, want response header timeout", err)
	}
}

func TestDownloadFileDoesNotRetryPermanentTransportFailure(t *testing.T) {
	var requests atomic.Int32
	transport := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		requests.Add(1)
		return nil, errors.New("certificate rejected")
	})
	client := testDownloadClient(&http.Client{Transport: transport})
	dest := filepath.Join(t.TempDir(), "f.bin")
	err := client.DownloadFile(
		context.Background(), File{Path: "f.bin", URL: "https://example.invalid/file"}, dest, true, true, nil,
	)
	if err == nil || !strings.Contains(err.Error(), "after 1 attempt(s)") {
		t.Fatalf("error = %v, want one permanent failed attempt", err)
	}
	if requests.Load() != 1 {
		t.Fatalf("requests = %d, want 1", requests.Load())
	}
}

func TestDownloadFileDoesNotRetryInvalidURL(t *testing.T) {
	client := testDownloadClient(http.DefaultClient)
	err := client.DownloadFile(
		context.Background(), File{Path: "f.bin", URL: "://invalid"}, filepath.Join(t.TempDir(), "f.bin"), true, true, nil,
	)
	if err == nil || !strings.Contains(err.Error(), "after 1 attempt(s)") || !strings.Contains(err.Error(), "invalid download URL") {
		t.Fatalf("error = %v, want one invalid-URL attempt", err)
	}
}

func TestDownloadFileEnforcesConnectionTimeout(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	srv.Close()
	transport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		<-ctx.Done()
		return nil, ctx.Err()
	}}
	defer transport.CloseIdleConnections()
	client := testDownloadClient(&http.Client{Transport: transport})
	client.policy.connectTimeout = 40 * time.Millisecond
	client.policy.maxAttempts = 1
	dest := filepath.Join(t.TempDir(), "f.bin")
	err, elapsed := downloadWithin(t, func() error {
		return client.DownloadFile(
			context.Background(), File{Path: "f.bin", URL: srv.URL}, dest, true, true, nil,
		)
	})
	if err == nil {
		t.Fatal("expected connection timeout")
	}
	if elapsed > time.Second {
		t.Fatalf("connection timeout took %s", elapsed)
	}
}

func TestDownloadFileEnforcesOverallAttemptTimeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "2")
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "a")
		w.(http.Flusher).Flush()
		select {
		case <-r.Context().Done():
		case <-time.After(time.Second):
		}
	}))
	defer srv.Close()

	client := testDownloadClient(srv.Client())
	client.policy.noProgress = time.Second
	client.policy.attemptTimeout = 40 * time.Millisecond
	client.policy.maxAttempts = 1
	dest := filepath.Join(t.TempDir(), "f.bin")
	err, elapsed := downloadWithin(t, func() error {
		return client.DownloadFile(context.Background(), File{Path: "f.bin", URL: srv.URL}, dest, true, true, nil)
	})
	if err == nil || !strings.Contains(err.Error(), "attempt timed out") {
		t.Fatalf("error = %v, want overall attempt timeout", err)
	}
	if elapsed > time.Second {
		t.Fatalf("overall timeout took %s", elapsed)
	}
}

func TestDownloadFileConcurrentCallsUseIndependentTemporaryFiles(t *testing.T) {
	payload := []byte("shared complete bytes")
	var requests atomic.Int32
	entered := make(chan struct{}, 2)
	release := make(chan struct{}, 2)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		entered <- struct{}{}
		<-release
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	client := testDownloadClient(srv.Client())
	dest := filepath.Join(t.TempDir(), "same.bin")
	file := File{Path: "same.bin", URL: srv.URL, Size: int64(len(payload)), MD5: payloadMD5(payload)}
	results := make(chan error, 2)
	var reported atomic.Int64
	for range 2 {
		go func() {
			results <- client.DownloadFile(context.Background(), file, dest, false, true, func(n int) {
				reported.Add(int64(n))
			})
		}()
	}
	for range 2 {
		select {
		case <-entered:
		case <-time.After(time.Second):
			t.Fatal("downloads did not overlap")
		}
	}
	release <- struct{}{}
	if err := <-results; err != nil {
		t.Fatalf("first DownloadFile: %v", err)
	}
	release <- struct{}{}
	if err := <-results; err != nil {
		t.Fatalf("second DownloadFile: %v", err)
	}
	if requests.Load() != 2 {
		t.Fatalf("requests = %d, want 2", requests.Load())
	}
	if reported.Load() != int64(len(payload)) {
		t.Fatalf("reported bytes = %d, want %d for one logical destination", reported.Load(), len(payload))
	}
	got, err := os.ReadFile(dest)
	if err != nil || string(got) != string(payload) {
		t.Fatalf("destination = %q, err = %v", got, err)
	}
	assertNoDownloadTemps(t, dest)
}

func TestDownloadFileRenameFailurePreservesExistingDestination(t *testing.T) {
	payload := []byte("payload")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "destination")
	if err := os.Mkdir(dest, 0o700); err != nil {
		t.Fatal(err)
	}
	err := testDownloadClient(srv.Client()).DownloadFile(
		context.Background(), File{Path: "destination", URL: srv.URL, Size: int64(len(payload))}, dest, true, true, nil,
	)
	if err == nil || !strings.Contains(err.Error(), "replace destination") {
		t.Fatalf("DownloadFile error = %v, want replacement error", err)
	}
	info, statErr := os.Stat(dest)
	if statErr != nil || !info.IsDir() {
		t.Fatalf("destination was changed: info=%v err=%v", info, statErr)
	}
	assertNoDownloadTemps(t, dest)
}

func assertNoDownloadTemps(t *testing.T, dest string) {
	t.Helper()
	matches, err := filepath.Glob(filepath.Join(filepath.Dir(dest), ".flashhub-download-*"))
	if err != nil {
		t.Fatal(err)
	}
	if len(matches) != 0 {
		t.Fatalf("temporary files remain: %v", matches)
	}
}

func downloadWithin(t *testing.T, download func() error) (error, time.Duration) {
	t.Helper()
	started := time.Now()
	done := make(chan error, 1)
	go func() { done <- download() }()
	select {
	case err := <-done:
		return err, time.Since(started)
	case <-time.After(2 * time.Second):
		t.Fatal("DownloadFile exceeded test timeout")
		return nil, 0
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
