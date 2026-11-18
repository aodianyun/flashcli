package server

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

const (
	logRingMax  = 2000
	logFileMax  = 4 << 20 // rotate at 4 MiB
	logKeepTail = 2000
)

var (
	logRingMu  sync.Mutex
	logRing    []string
	logFile    *os.File
	logPath    string
	logWritten int64
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
		if logFile != nil {
			if _, err := logFile.WriteString(line + "\n"); err != nil {
				_ = logFile.Close()
				logFile = nil
			} else {
				logWritten += int64(len(line) + 1)
			}
		}
	}
	if len(logRing) > logRingMax {
		logRing = append([]string(nil), logRing[len(logRing)-logRingMax:]...)
	}
	rotateLogLocked()
	return len(p), nil
}

// InitLogFile persists the service log so the 日志 page still shows earlier
// activity after a daemon restart. It loads the existing tail back into the
// ring and rotates oversized files (one .1 backup is kept).
func InitLogFile(path string) {
	logRingMu.Lock()
	defer logRingMu.Unlock()
	if logFile != nil {
		_ = logFile.Close()
		logFile = nil
	}
	logPath = ""
	logWritten = 0
	if strings.TrimSpace(path) == "" {
		logRing = nil
		return
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		logRing = nil
		return
	}
	rotateIfNeeded(path)
	logPath = path
	seedLogRingLocked(path)
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	if info, err := f.Stat(); err == nil {
		logWritten = info.Size()
	}
	logFile = f
}

// LogFilePath returns the persisted service log path (empty when persistence
// is not initialized).
func LogFilePath() string {
	logRingMu.Lock()
	defer logRingMu.Unlock()
	return logPath
}

func seedLogRingLocked(path string) {
	blob, err := os.ReadFile(path)
	if err != nil || len(blob) == 0 {
		logRing = nil
		return
	}
	lines := strings.Split(strings.TrimRight(string(blob), "\n"), "\n")
	if len(lines) > logKeepTail {
		lines = lines[len(lines)-logKeepTail:]
	}
	logRing = append([]string(nil), lines...)
}

func rotateIfNeeded(path string) {
	info, err := os.Stat(path)
	if err != nil || info.Size() < logFileMax {
		return
	}
	_ = os.Remove(path + ".1")
	_ = os.Rename(path, path+".1")
}

func rotateLogLocked() {
	if logFile == nil || logPath == "" || logWritten < logFileMax {
		return
	}
	_ = logFile.Close()
	logFile = nil
	logWritten = 0
	_ = os.Remove(logPath + ".1")
	if err := os.Rename(logPath, logPath+".1"); err != nil {
		return
	}
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	logFile = f
}

// LogSink returns a writer that keeps the most recent daemon log lines for the
// local console and persists them to the initialized log file.
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
