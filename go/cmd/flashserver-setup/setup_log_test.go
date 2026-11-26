package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestSetupLogKeepsRunHistoryAndLiveAlias(t *testing.T) {
	dir := t.TempDir()
	legacy := "previous failed install"
	if err := os.WriteFile(filepath.Join(dir, setupLogName), []byte(legacy), 0o600); err != nil {
		t.Fatal(err)
	}

	released := false
	first, err := openSetupLogIn(dir, func() { released = true })
	if err != nil {
		t.Fatalf("open first setup log: %v", err)
	}
	if n, err := first.Write([]byte("first run: token=example-secret\n")); err != nil || n == 0 {
		t.Fatalf("write first run: n=%d err=%v", n, err)
	}
	firstRun := first.runPath
	if firstRun == "" {
		t.Fatal("per-run log path is empty")
	}
	// The run file is written directly, so an abrupt process exit still leaves
	// completed writes in the file before Close performs its final Sync.
	partial, err := os.ReadFile(firstRun)
	if err != nil || !strings.Contains(string(partial), "first run") {
		t.Fatalf("read live run log: content=%q err=%v", partial, err)
	}
	if strings.Contains(string(partial), "example-secret") {
		t.Fatalf("run log retained a token: %q", partial)
	}
	if got, err := os.ReadFile(filepath.Join(dir, setupLogName)); err != nil || !strings.Contains(string(got), "first run") {
		t.Fatalf("setup.log is not live: content=%q err=%v", got, err)
	}
	if err := first.Close(); err != nil {
		t.Fatalf("close first setup log: %v", err)
	}
	if !released {
		t.Fatal("run lock was not released")
	}

	second, err := openSetupLogIn(dir, nil)
	if err != nil {
		t.Fatalf("open second setup log: %v", err)
	}
	if _, err := second.Write([]byte("second run\n")); err != nil {
		t.Fatal(err)
	}
	if second.runPath == firstRun {
		t.Fatal("two setup runs reused the same history filename")
	}
	if err := second.Close(); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{firstRun, second.runPath} {
		if _, err := os.Stat(path); err != nil {
			t.Errorf("history log %q was not retained: %v", path, err)
		}
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	legacyFound := false
	for _, entry := range entries {
		if strings.HasSuffix(entry.Name(), "-legacy.log") {
			got, err := os.ReadFile(filepath.Join(dir, entry.Name()))
			if err != nil {
				t.Fatal(err)
			}
			if string(got) == legacy {
				legacyFound = true
			}
		}
	}
	if !legacyFound {
		t.Fatal("legacy setup.log was not archived before being truncated")
	}
	alias, err := os.ReadFile(filepath.Join(dir, setupLogName))
	if err != nil || !strings.Contains(string(alias), "second run") {
		t.Fatalf("setup.log does not point at the latest run: %q err=%v", alias, err)
	}
}

func TestSetupLogFailureDoesNotBlockSetup(t *testing.T) {
	root := t.TempDir()
	file := filepath.Join(root, "not-a-directory")
	if err := os.WriteFile(file, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	session, err := openSetupLogIn(filepath.Join(file, "logs"), nil)
	if err == nil {
		t.Fatal("expected a visible log initialization warning")
	}
	if session == nil {
		t.Fatal("log failure should return a usable no-op session")
	}
	if n, writeErr := session.Write([]byte("continue")); writeErr != nil || n != len("continue") {
		t.Fatalf("no-op log write: n=%d err=%v", n, writeErr)
	}
	if closeErr := session.Close(); closeErr != nil {
		t.Fatalf("close no-op session: %v", closeErr)
	}
}

func TestSetupLogDoesNotTruncateNonRegularAlias(t *testing.T) {
	dir := t.TempDir()
	alias := filepath.Join(dir, setupLogName)
	if err := os.Mkdir(alias, 0o700); err != nil {
		t.Fatal(err)
	}
	session, err := openSetupLogIn(dir, nil)
	if err == nil {
		t.Fatal("expected a warning for a non-regular setup.log")
	}
	if session == nil || session.path() == "" || session.path() == alias {
		t.Fatalf("expected the per-run log path, got session=%+v", session)
	}
	if _, statErr := os.Stat(alias); statErr != nil {
		t.Fatalf("non-regular alias was changed: %v", statErr)
	}
	_ = session.Close()
}

func TestPruneSetupLogsOnlyRemovesOwnedHistory(t *testing.T) {
	dir := t.TempDir()
	old := time.Now().Add(-48 * time.Hour)
	for n := 0; n < maxSetupRunLogs+4; n++ {
		name := fmt.Sprintf("setup-run-20200101T000000.000000000Z-123-%d.log", n)
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, []byte("old"), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Chtimes(path, old, old); err != nil {
			t.Fatal(err)
		}
	}
	unknown := []string{"setup.log", "setup.log.bak", "msi-install.log", "setup-run-not-owned.log"}
	for _, name := range unknown {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("keep"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	pruneOwnedSetupRunLogs(dir, "")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	owned := 0
	for _, entry := range entries {
		if ownedSetupRunLog.MatchString(entry.Name()) {
			owned++
		}
	}
	if owned != maxSetupRunLogs {
		t.Fatalf("owned logs retained=%d, want %d", owned, maxSetupRunLogs)
	}
	for _, name := range unknown {
		if _, err := os.Stat(filepath.Join(dir, name)); err != nil {
			t.Errorf("unknown file %q was removed: %v", name, err)
		}
	}
}

func TestAppendFileRedactsSensitiveValues(t *testing.T) {
	path := filepath.Join(t.TempDir(), "progress.log")
	w := &appendFile{path: path}
	input := "https://name:password@example.invalid/path token=example-secret\n"
	if n, err := w.Write([]byte(input)); err != nil || n != len(input) {
		t.Fatalf("write progress: n=%d err=%v", n, err)
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(got), "password") || strings.Contains(string(got), "example-secret") {
		t.Fatalf("progress file retained sensitive values: %q", got)
	}
}

func TestAliasOnlyFailureSurvivesNextStart(t *testing.T) {
	dir := t.TempDir()
	old, err := openSetupLogIn(dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	old.Write([]byte("old run\n"))
	old.Close()
	session, err := openSetupLogWith(dir, nil, func(string) (*os.File, string, error) { return nil, "", errors.New("injected create failure") })
	if err == nil || !session.hasAlias {
		t.Fatalf("expected alias fallback with warning: %v", err)
	}
	session.Write([]byte("alias-only failed installation\n"))
	// Deliberately inspect the next startup without requiring graceful Close.
	session.Close()
	next, err := openSetupLogIn(dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer next.Close()
	files, _ := filepath.Glob(filepath.Join(dir, "*-legacy.log"))
	found := false
	for _, file := range files {
		data, _ := os.ReadFile(file)
		if strings.Contains(string(data), "alias-only failed installation") {
			found = true
		}
	}
	if !found {
		t.Fatal("alias-only diagnostics were lost")
	}
}

func TestLogFaultsWarnAndKeepOtherSink(t *testing.T) {
	for _, fault := range []string{"disk-full", "short-write", "sync"} {
		t.Run(fault, func(t *testing.T) {
			dir := t.TempDir()
			session, err := openSetupLogIn(dir, nil)
			if err != nil {
				t.Fatal(err)
			}
			var warnings bytes.Buffer
			session.warningSink = &warnings
			session.writeFile = func(f *os.File, p []byte) (int, error) {
				if f.Name() == session.runPath {
					if fault == "disk-full" {
						return 0, errors.New("disk full")
					}
					if fault == "short-write" {
						return 0, nil
					}
				}
				return f.Write(p)
			}
			if fault == "sync" {
				session.syncFile = func(*os.File) error { return errors.New("sync failure") }
			}
			session.Write([]byte("failed installation token=example-secret\n"))
			if !strings.Contains(warnings.String(), "may not be persisted") {
				t.Fatal("missing persistence warning")
			}
			data, _ := os.ReadFile(session.aliasPath)
			if !strings.Contains(string(data), "failed installation") || strings.Contains(string(data), "example-secret") {
				t.Fatalf("alias: %s", data)
			}
			session.Close()
			next, err := openSetupLogIn(dir, nil)
			if err != nil {
				t.Fatal(err)
			}
			next.Close()
			archives, _ := filepath.Glob(filepath.Join(dir, "*-legacy.log"))
			found := false
			for _, file := range archives {
				data, _ := os.ReadFile(file)
				found = found || strings.Contains(string(data), "failed installation")
			}
			if !found {
				t.Fatal("partial run was not archived")
			}
		})
	}
}

func TestOutputAndHistoryUseSameRedaction(t *testing.T) {
	dir := t.TempDir()
	session, err := openSetupLogIn(dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	var stdout bytes.Buffer
	progress := filepath.Join(dir, "progress.txt")
	out := &syncWriter{w: io.MultiWriter(&stdout, session, &appendFile{path: progress})}
	out.Write([]byte("token=example-secret\n"))
	session.Close()
	for _, file := range []string{session.aliasPath, session.runPath, progress} {
		data, _ := os.ReadFile(file)
		if string(data) != stdout.String() {
			t.Fatalf("different redaction: %s", file)
		}
	}
	if strings.Contains(stdout.String(), "example-secret") {
		t.Fatal("stdout leaked secret")
	}
}

func TestSetupLogAbruptExit(t *testing.T) {
	if dir := os.Getenv("FLASHCLI_TEST_CRASH_LOG_DIR"); dir != "" {
		log, err := openSetupLogIn(dir, nil)
		if err != nil {
			os.Exit(19)
		}
		log.Write([]byte("crash diagnostic token=example-secret\n"))
		os.Exit(17)
	}
	dir := t.TempDir()
	cmd := exec.Command(os.Args[0], "-test.run=^TestSetupLogAbruptExit$")
	cmd.Env = append(os.Environ(), "FLASHCLI_TEST_CRASH_LOG_DIR="+dir)
	err := cmd.Run()
	var exit *exec.ExitError
	if !errors.As(err, &exit) || exit.ExitCode() != 17 {
		t.Fatalf("helper: %v", err)
	}
	log, err := openSetupLogIn(dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	log.Close()
	files, _ := filepath.Glob(filepath.Join(dir, "*-legacy.log"))
	found := false
	for _, file := range files {
		data, _ := os.ReadFile(file)
		found = found || strings.Contains(string(data), "crash diagnostic")
		if strings.Contains(string(data), "example-secret") {
			t.Fatal("archive leaked secret")
		}
	}
	if !found {
		t.Fatal("crash diagnostics lost on restart")
	}
}

type failedOutput struct{}

func (failedOutput) Write([]byte) (int, error) { return 0, errors.New("broken pipe") }
func TestBrokenConsoleStillWritesHistoryAndProgress(t *testing.T) {
	var history, progress bytes.Buffer
	output := &syncWriter{w: bestEffortOutput{failedOutput{}, &history, &progress}}
	output.Write([]byte("token=example-secret\n"))
	if history.Len() == 0 || history.String() != progress.String() || strings.Contains(history.String(), "example-secret") {
		t.Fatal("diagnostics dropped or leaked")
	}
}

func TestBothLogSinksFailExplicitWarning(t *testing.T) {
	session, err := openSetupLogIn(t.TempDir(), nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	var warnings bytes.Buffer
	session.warningSink = &warnings
	session.writeFile = func(*os.File, []byte) (int, error) { return 0, errors.New("disk full") }
	session.Write([]byte("diagnostic\n"))
	if strings.Count(warnings.String(), "may not be persisted") != 2 {
		t.Fatal(warnings.String())
	}
}
func TestLegacyArchiveRedactsRawCredentials(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, setupLogName), []byte("token=example-secret\n"), 0600)
	session, err := openSetupLogIn(dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	session.Close()
	files, _ := filepath.Glob(filepath.Join(dir, "*-legacy.log"))
	if len(files) != 1 {
		t.Fatal(files)
	}
	data, _ := os.ReadFile(files[0])
	if strings.Contains(string(data), "example-secret") || !strings.Contains(string(data), "[REDACTED]") {
		t.Fatal("archive was not redacted")
	}
}
