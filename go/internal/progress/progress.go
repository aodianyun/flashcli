// Package progress is the unified, concise status reporter for the Go host.
//
// Design (not a port of the old tqdm output): one aggregated status line per
// stage — e.g. weights shows "files done/total", total bytes and speed — rather
// than one bar per file. On a TTY the line updates in place; on a non-TTY it
// prints sparse milestones. quiet (-q / FLASHCLI_QUIET) suppresses everything
// except warnings.
package progress

import (
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"time"
)

var (
	mu    sync.Mutex
	out   io.Writer = os.Stderr
	quiet bool
	tty   bool
)

func init() {
	if fi, err := os.Stderr.Stat(); err == nil {
		tty = fi.Mode()&os.ModeCharDevice != 0
	}
}

// SetQuiet enables/disables status output (warnings still print).
func SetQuiet(q bool) { mu.Lock(); quiet = q; mu.Unlock() }

// SetOutput redirects status output (tests/embedding).
func SetOutput(w io.Writer) { mu.Lock(); out = w; mu.Unlock() }

// IsQuiet reports whether status output is suppressed.
func IsQuiet() bool { mu.Lock(); defer mu.Unlock(); return quiet }

// Note prints a one-line status (`  • msg`) unless quiet.
func Note(format string, args ...any) {
	if IsQuiet() {
		return
	}
	mu.Lock()
	defer mu.Unlock()
	fmt.Fprintf(out, "  • %s\n", fmt.Sprintf(format, args...))
}

// Warn always prints a warning line to stderr.
func Warn(format string, args ...any) {
	mu.Lock()
	defer mu.Unlock()
	fmt.Fprintf(out, "  ! %s\n", fmt.Sprintf(format, args...))
}

// FormatBytes humanizes a byte count (KiB/MiB/GiB).
func FormatBytes(n int64) string {
	switch {
	case n < 1024:
		return fmt.Sprintf("%d B", n)
	case n < 1024*1024:
		return fmt.Sprintf("%.1f KiB", float64(n)/1024)
	case n < 1024*1024*1024:
		return fmt.Sprintf("%.1f MiB", float64(n)/(1024*1024))
	default:
		return fmt.Sprintf("%.2f GiB", float64(n)/(1024*1024*1024))
	}
}

// Stage is one aggregated progress stage (e.g. weights).
type Stage struct {
	name   string
	detail string
	start  time.Time

	smu        sync.Mutex
	written    int64
	totalBytes int64
	filesDone  int
	filesTotal int
	last       time.Time
	lastPct    int
	done       bool
}

// Start begins a stage and prints its header line.
func Start(name, detail string) *Stage {
	s := &Stage{name: name, detail: detail, start: time.Now(), last: time.Now()}
	if IsQuiet() {
		return s
	}
	mu.Lock()
	defer mu.Unlock()
	if tty {
		fmt.Fprintf(out, "\r\033[K")
	}
	if detail != "" {
		fmt.Fprintf(out, "▸ %s  %s\n", name, detail)
	} else {
		fmt.Fprintf(out, "▸ %s\n", name)
	}
	return s
}

// Totals sets the expected file count and total bytes (0 = unknown).
func (s *Stage) Totals(files int, bytes int64) {
	if s == nil {
		return
	}
	s.smu.Lock()
	s.filesTotal = files
	s.totalBytes = bytes
	s.smu.Unlock()
	s.render(false)
}

// Add records bytes transferred (current file).
func (s *Stage) Add(n int) {
	if s == nil || n <= 0 {
		return
	}
	s.smu.Lock()
	s.written += int64(n)
	s.smu.Unlock()
	s.render(false)
}

// FileDone marks one file complete.
func (s *Stage) FileDone() {
	if s == nil {
		return
	}
	s.smu.Lock()
	s.filesDone++
	s.smu.Unlock()
	s.render(false)
}

// Done finishes the stage with a concise summary.
func (s *Stage) Done() {
	if s == nil || s.done {
		return
	}
	s.done = true
	if IsQuiet() {
		return
	}
	s.smu.Lock()
	written, files := s.written, s.filesDone
	s.smu.Unlock()
	mu.Lock()
	defer mu.Unlock()
	if tty {
		fmt.Fprintf(out, "\r\033[K")
	}
	elapsed := time.Since(s.start)
	summary := FormatBytes(written)
	if files > 0 {
		summary = fmt.Sprintf("%d file(s), %s", files, summary)
	}
	fmt.Fprintf(out, "✓ %s  %s  (%s)\n", s.name, summary, elapsed.Round(time.Second))
}

func (s *Stage) render(final bool) {
	if IsQuiet() || s == nil {
		return
	}
	s.smu.Lock()
	written, totalBytes := s.written, s.totalBytes
	filesDone, filesTotal := s.filesDone, s.filesTotal
	s.smu.Unlock()

	pct := 0
	if totalBytes > 0 {
		pct = int(written * 100 / totalBytes)
	} else if filesTotal > 0 {
		pct = filesDone * 100 / filesTotal
	}

	if tty {
		mu.Lock()
		fmt.Fprintf(out, "\r\033[K  %s  %s", s.head(), s.parts(written, totalBytes, filesDone, filesTotal))
		mu.Unlock()
		return
	}
	// Non-TTY: print milestones (each 10%) at most every 15s, plus final.
	s.smu.Lock()
	if !final && pct/10 == s.lastPct/10 && time.Since(s.last) < 15*time.Second {
		s.smu.Unlock()
		return
	}
	s.lastPct = pct
	s.last = time.Now()
	s.smu.Unlock()
	mu.Lock()
	fmt.Fprintf(out, "  %s\n", s.parts(written, totalBytes, filesDone, filesTotal))
	mu.Unlock()
}

func (s *Stage) head() string {
	if s.detail != "" {
		return s.name + ": " + trim(s.detail)
	}
	return s.name
}

func (s *Stage) parts(written, totalBytes int64, filesDone, filesTotal int) string {
	parts := []string{}
	if filesTotal > 0 {
		parts = append(parts, fmt.Sprintf("%d/%d files", filesDone, filesTotal))
	}
	if totalBytes > 0 {
		parts = append(parts, fmt.Sprintf("%s/%s", FormatBytes(written), FormatBytes(totalBytes)))
	} else {
		parts = append(parts, FormatBytes(written))
	}
	if sp := s.speed(written); sp != "" {
		parts = append(parts, sp)
	}
	return strings.Join(parts, "  ")
}

func (s *Stage) speed(written int64) string {
	sec := time.Since(s.start).Seconds()
	if sec < 1 || written < 1<<20 {
		return ""
	}
	bps := float64(written) / sec
	return FormatBytes(int64(bps)) + "/s"
}

func trim(s string) string {
	s = strings.TrimSpace(s)
	if len(s) > 48 {
		return s[:47] + "…"
	}
	return s
}
