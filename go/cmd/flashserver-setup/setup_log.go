package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/aodianyun/flashcli/go/internal/paths"
	"github.com/aodianyun/flashcli/go/internal/setup"
)

const (
	setupLogName       = "setup.log"
	maxSetupRunLogs    = 20
	maxSetupRunLogSize = int64(100 << 20)
)

var ErrSetupAlreadyRunning = errors.New("another flashserver setup instance is already running")

var ownedSetupRunLog = regexp.MustCompile(`^setup-run-\d{8}T\d{6}\.\d{9}Z-\d+-(?:\d+|legacy)\.log$`)

type setupLog struct {
	mu          sync.Mutex
	files       []*os.File
	aliasPath   string
	runPath     string
	releaseLock func()
	warned      map[string]bool
	warningSink io.Writer
	writeFile   func(*os.File, []byte) (int, error)
	syncFile    func(*os.File) error
	warningMu   sync.Mutex
	warningErr  error
	hasAlias    bool
	closed      bool
}

func openSetupLog() (*setupLog, error) {
	release, err := acquireSetupRunLock()
	if err != nil {
		return nil, err
	}

	dir := filepath.Join(paths.Home(), "logs")
	if state := setup.WindowsStateDir(); state != "" {
		dir = filepath.Join(state, "logs")
	}
	return openSetupLogIn(dir, release)
}

func openSetupLogIn(dir string, release func()) (*setupLog, error) {
	return openSetupLogWith(dir, release, createSetupRunLog)
}

func openSetupLogWith(dir string, release func(), createRun func(string) (*os.File, string, error)) (*setupLog, error) {
	session := &setupLog{aliasPath: filepath.Join(dir, setupLogName), releaseLock: release}
	if release == nil {
		session.releaseLock = func() {}
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return session, fmt.Errorf("create setup log directory: %w", err)
	}

	archiveErr := archiveLegacySetupLog(dir)
	if archiveErr != nil {
		session.warn("could not archive the previous setup.log; keeping it intact and logging this run separately")
	}

	if runFile, path, err := createRun(dir); err != nil {
		session.warn("could not create a per-run setup log: " + err.Error())
	} else {
		session.runPath = path
		session.files = append(session.files, runFile)
	}

	// Keep the fixed file as a live alias for the existing Inno Setup UI.
	// Never truncate a legacy-only log unless the archive was safely written.
	if archiveErr != nil {
		session.warn("leaving the compatibility setup.log unchanged because its archive failed")
	} else if alias, err := openCurrentSetupAlias(session.aliasPath); err != nil {
		session.warn("could not open setup.log for the current run: " + err.Error())
	} else {
		session.files = append(session.files, alias)
		session.hasAlias = true
	}

	if session.warning() == nil {
		pruneOwnedSetupRunLogs(dir, session.runPath)
	}
	return session, session.warning()
}

func createSetupRunLog(dir string) (*os.File, string, error) {
	base := "setup-run-" + time.Now().UTC().Format("20060102T150405.000000000Z") + "-" + strconv.Itoa(os.Getpid())
	for suffix := 0; suffix < 100; suffix++ {
		path := filepath.Join(dir, base+"-"+strconv.Itoa(suffix)+".log")
		file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
		if err == nil {
			return file, path, nil
		}
		if !os.IsExist(err) {
			return nil, "", err
		}
	}
	return nil, "", fmt.Errorf("could not allocate a unique log filename")
}

func archiveLegacySetupLog(dir string) error {
	// An older owned log does not prove the latest alias has a complete copy.
	// Archive before every truncation, including recovery after a failed write.
	source := filepath.Join(dir, setupLogName)
	linkInfo, err := os.Lstat(source)
	if err == nil && !linkInfo.Mode().IsRegular() {
		return fmt.Errorf("legacy setup.log is not a regular file")
	}
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	in, err := os.Open(source)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	defer in.Close()
	info, err := in.Stat()
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() == 0 {
		return nil
	}

	base := "setup-run-" + time.Now().UTC().Format("20060102T150405.000000000Z") + "-" + strconv.Itoa(os.Getpid()) + "-legacy.log"
	destination := filepath.Join(dir, base)
	out, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	data, readErr := io.ReadAll(in)
	if readErr != nil {
		err = readErr
	} else {
		_, err = out.Write(redactSetupLog(data))
	}
	if err == nil {
		err = out.Sync()
	}
	if closeErr := out.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		_ = os.Remove(destination)
		return err
	}
	return nil
}

func openCurrentSetupAlias(path string) (*os.File, error) {
	if info, err := os.Lstat(path); err == nil && !info.Mode().IsRegular() {
		return nil, fmt.Errorf("setup.log is not a regular file")
	} else if err != nil && !os.IsNotExist(err) {
		return nil, err
	}
	return os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
}

func pruneOwnedSetupRunLogs(dir, current string) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	type candidate struct {
		path    string
		modTime time.Time
		size    int64
	}
	logs := make([]candidate, 0, len(entries))
	for _, entry := range entries {
		if !ownedSetupRunLog.MatchString(entry.Name()) {
			continue
		}
		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() {
			continue
		}
		logs = append(logs, candidate{path: filepath.Join(dir, entry.Name()), modTime: info.ModTime(), size: info.Size()})
	}
	sort.Slice(logs, func(i, j int) bool { return logs[i].modTime.After(logs[j].modTime) })

	keptCount := 0
	keptBytes := int64(0)
	for _, log := range logs {
		if log.path == current {
			keptCount++
			keptBytes += log.size
			continue
		}
		if keptCount >= maxSetupRunLogs || (keptBytes+log.size > maxSetupRunLogSize && keptCount > 0) {
			_ = os.Remove(log.path)
			continue
		}
		keptCount++
		keptBytes += log.size
	}
}

func (l *setupLog) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	written := len(p)
	if l.closed {
		return written, nil
	}
	p = redactSetupLog(p)
	for _, file := range l.files {
		write := file.Write
		if l.writeFile != nil {
			write = func(data []byte) (int, error) { return l.writeFile(file, data) }
		}
		n, err := write(p)
		if err == nil && n != len(p) {
			err = io.ErrShortWrite
		}
		if err != nil {
			l.warn(fmt.Sprintf("diagnostics may not be persisted: write %s: %v", file.Name(), err))
			continue
		}
		syncFile := file.Sync
		if l.syncFile != nil {
			syncFile = func() error { return l.syncFile(file) }
		}
		if err := syncFile(); err != nil {
			l.warn(fmt.Sprintf("diagnostics may not be persisted: sync %s: %v", file.Name(), err))
		}
	}
	return written, nil
}

func (l *setupLog) Close() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.closed {
		return nil
	}
	l.closed = true
	var firstErr error
	for _, file := range l.files {
		if err := file.Sync(); err != nil && firstErr == nil {
			firstErr = err
		}
		if err := file.Close(); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	if firstErr != nil {
		l.warn("a setup log could not be fully flushed")
	}
	l.releaseLock()
	return firstErr
}

func (l *setupLog) path() string {
	if l.hasAlias {
		return l.aliasPath
	}
	return l.runPath
}

func (l *setupLog) warning() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.warningMu.Lock()
	defer l.warningMu.Unlock()
	if l.warningErr != nil {
		return l.warningErr
	}
	if len(l.files) == 0 {
		return fmt.Errorf("no setup log file could be opened")
	}
	return nil
}

func (l *setupLog) warn(message string) {
	l.warningMu.Lock()
	if l.warned == nil {
		l.warned = make(map[string]bool)
	}
	if l.warned[message] {
		l.warningMu.Unlock()
		return
	}
	l.warned[message] = true
	l.warningErr = errors.New(strings.TrimSpace(message))
	l.warningMu.Unlock()
	sink := l.warningSink
	if sink == nil {
		sink = os.Stderr
	}
	_, _ = sink.Write(redactSetupLog([]byte("warning: " + message + "\n")))
}

var setupLogRedactors = []*regexp.Regexp{
	regexp.MustCompile(`(?i)(https?://)[^/@\s]+:[^/@\s]+@`),
	regexp.MustCompile(`(?i)(authorization\s*:\s*bearer\s+)[^\s]+`),
	regexp.MustCompile(`(?i)((?:access[_-]?token|api[_-]?key|password|passwd|secret|token)=)[^&\s]+`),
}

func redactSetupLog(p []byte) []byte {
	text := string(p)
	text = setupLogRedactors[0].ReplaceAllString(text, `${1}[REDACTED]@`)
	text = setupLogRedactors[1].ReplaceAllString(text, `${1}[REDACTED]`)
	text = setupLogRedactors[2].ReplaceAllString(text, `${1}[REDACTED]`)
	return []byte(text)
}
