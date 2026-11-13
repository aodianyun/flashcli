package server

import (
	"io"
	"strings"
	"sync"
)

const logRingMax = 800

var (
	logRingMu sync.Mutex
	logRing   []string
)

type ringWriter struct{}

func (ringWriter) Write(p []byte) (int, error) {
	logRingMu.Lock()
	defer logRingMu.Unlock()
	for _, line := range strings.Split(strings.TrimRight(string(p), "\n"), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		logRing = append(logRing, line)
	}
	if len(logRing) > logRingMax {
		logRing = append([]string(nil), logRing[len(logRing)-logRingMax:]...)
	}
	return len(p), nil
}

// LogSink returns a writer that keeps the most recent daemon log lines for the
// local console. Wire it into log.SetOutput next to stderr.
func LogSink() io.Writer { return ringWriter{} }

func serverLogLines(n int) []string {
	if n <= 0 {
		n = 200
	}
	logRingMu.Lock()
	defer logRingMu.Unlock()
	if n > len(logRing) {
		n = len(logRing)
	}
	out := make([]string, n)
	copy(out, logRing[len(logRing)-n:])
	return out
}
