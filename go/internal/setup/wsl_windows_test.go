//go:build windows

package setup

import (
	"bytes"
	"context"
	"debug/elf"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"unicode/utf16"
)

type fakeProcessExit struct{ code int }

func (e fakeProcessExit) Error() string { return fmt.Sprintf("fake exit code %d", e.code) }
func (e fakeProcessExit) ExitCode() int { return e.code }

type fakeWSLReply struct {
	output string
	err    error
	block  bool
}

type fakeWSLRunner struct {
	t       *testing.T
	replies map[string][]fakeWSLReply
	calls   [][]string
	onCall  func(string, []string)
}

func (f *fakeWSLRunner) run(ctx context.Context, name string, args ...string) ([]byte, error) {
	call := append([]string{name}, args...)
	f.calls = append(f.calls, call)
	key := fakeWSLCommandKey(name, args)
	if f.onCall != nil {
		f.onCall(key, args)
	}
	queue := f.replies[key]
	if len(queue) == 0 {
		return nil, fmt.Errorf("unexpected fake command: %s", key)
	}
	reply := queue[0]
	f.replies[key] = queue[1:]
	if reply.block {
		<-ctx.Done()
		return []byte(reply.output), ctx.Err()
	}
	return []byte(reply.output), reply.err
}

func fakeWSLCommandKey(name string, args []string) string {
	base := strings.ToLower(filepath.Base(name))
	if base == "powershell.exe" {
		return "features"
	}
	if base == "dism.exe" {
		return "dism " + strings.Join(args, " ")
	}
	return "wsl " + strings.Join(args, " ")
}

func (f *fakeWSLRunner) add(key string, replies ...fakeWSLReply) {
	f.replies[key] = append(f.replies[key], replies...)
}

func failedProbe() []fakeWSLReply {
	return []fakeWSLReply{{err: fakeProcessExit{code: 1}}}
}

func featureReply(wslState, vmState string) fakeWSLReply {
	return fakeWSLReply{output: "Microsoft-Windows-Subsystem-Linux=" + wslState + "\nVirtualMachinePlatform=" + vmState + "\n"}
}

func standardHelp(withWeb bool) fakeWSLReply {
	text := "Usage: wsl.exe [--install] [--no-distribution]"
	if withWeb {
		text += " [--web-download]"
	}
	return fakeWSLReply{output: text}
}

func utf16LEHelp(text string) string {
	units := utf16.Encode([]rune(text))
	out := make([]byte, 2*len(units))
	for n, unit := range units {
		binary.LittleEndian.PutUint16(out[2*n:], unit)
	}
	return string(out)
}

func testWSLPolicy() wslPolicy {
	return wslPolicy{
		commandTimeout: time.Second,
		installTimeout: time.Second,
		verifyTimeout:  0,
		pollInterval:   time.Millisecond,
		featureTimeout: time.Second,
	}
}

func newFakeInstaller(t *testing.T, runner *fakeWSLRunner) *installer {
	t.Helper()
	previous := diag
	diag = io.Discard
	t.Cleanup(func() { diag = previous })
	return &installer{
		env:    Env{OS: "windows", Arch: "amd64"},
		opts:   Options{},
		out:    io.Discard,
		runner: runner.run,
	}
}

func TestEnsureWSLReusesRuntimeWithoutDistribution(t *testing.T) {
	runner := &fakeWSLRunner{t: t, replies: map[string][]fakeWSLReply{
		"wsl --status": {{output: "Default Version: 2"}},
	}}
	i := newFakeInstaller(t, runner)
	if err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy()); err != nil {
		t.Fatalf("ensureWSL: %v", err)
	}
	if len(runner.calls) != 1 {
		t.Fatalf("commands=%v, want only read-only runtime probe", runner.calls)
	}
}

func TestVerifiedLocalPayloadContinuesToWSLPreparationWhenRuntimeMissing(t *testing.T) {
	payloadDir := filepath.Join(t.TempDir(), "local payload with spaces")
	writeTestLocalPayload(t, payloadDir, testELF(t, elf.EM_X86_64, "test-version"), testELF(t, elf.EM_X86_64, "test-version"))
	opts := Options{BinDir: payloadDir}
	cleanup, err := ensureAssetBinaries(context.Background(), Env{OS: "windows", Arch: "amd64"}, &opts, io.Discard)
	if err != nil {
		t.Fatalf("ensure local payload: %v", err)
	}
	defer cleanup()

	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    append(failedProbe(), fakeWSLReply{output: "ready"}),
		"wsl --list --quiet":              failedProbe(),
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{output: "installation started"}},
	}}
	i := newFakeInstaller(t, runner)
	i.opts = opts
	if err := ensureWSLWithPolicy(context.Background(), opts, i, testWSLPolicy()); err != nil {
		t.Fatalf("prepare WSL after validating local payload: %v", err)
	}
	if countWSLCall(runner.calls, "--install --no-distribution") != 1 {
		t.Fatalf("WSL default preparation was not reached exactly once: %v", runner.calls)
	}
}

func TestEnsureWSLUsesEmptyListAsRuntimeReady(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": {{output: ""}},
	}}
	i := newFakeInstaller(t, runner)
	if err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy()); err != nil {
		t.Fatalf("ensureWSL: %v", err)
	}
	if len(runner.calls) != 2 {
		t.Fatalf("commands=%v, want status and list probes only", runner.calls)
	}
}

func TestHelpExitOneStillParsesChineseUTF16Help(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --help": {{output: utf16LEHelp("适用命令:\n命令 --install 安装 WSL\n命令 --update 更新 WSL\n命令 --status 查看状态\n命令 --help 显示帮助\n"), err: fakeProcessExit{code: 1}}},
	}}
	i := newFakeInstaller(t, runner)
	options, err := queryWSLInstallOptions(context.Background(), i, testWSLPolicy().commandTimeout)
	if err != nil {
		t.Fatalf("parse valid help with exit code 1: %v", err)
	}
	if !options.install || options.noDistribution || options.webDownload {
		t.Fatalf("parsed unsupported options from legacy help: %+v", options)
	}
}

func TestHelpExitOneWithModernOptionsUsesDistributionFreeInstall(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    append(failedProbe(), fakeWSLReply{output: "ready"}),
		"wsl --list --quiet":              failedProbe(),
		"wsl --help":                      {{output: "--install\n--no-distribution\n--help\n", err: fakeProcessExit{code: 1}}},
		"features":                        {featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{}},
	}}
	i := newFakeInstaller(t, runner)
	if err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy()); err != nil {
		t.Fatalf("distribution-free install: %v", err)
	}
	if countWSLCall(runner.calls, "--install --no-distribution") != 1 {
		t.Fatalf("distribution-free install was not called exactly once: %v", runner.calls)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestLegacyHelpEnablesOnlyDisabledWindowsFeatures(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{output: utf16LEHelp("适用命令:\n  --install  安装 WSL\n"), err: fakeProcessExit{code: 1}}},
		"features":           {featureReply("Disabled", "Enabled")},
		"dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart": {{}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrRebootRequired) {
		t.Fatalf("error=%v, want reboot after enabling the missing feature", err)
	}
	if countWSLCall(runner.calls, "/enable-feature /featurename:") != 1 {
		t.Fatalf("DISM changed an unconfirmed or already enabled feature: %v", runner.calls)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestLegacyHelpWithEnabledFeaturesUsesAdvertisedUpdate(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       append(failedProbe(), fakeWSLReply{output: "ready"}),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{output: "--install\n--update\n--status\n--help\n", err: fakeProcessExit{code: 1}}},
		"features":           {featureReply("Enabled", "Enabled")},
		"wsl --update":       {{}},
	}}
	i := newFakeInstaller(t, runner)
	if err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy()); err != nil {
		t.Fatalf("legacy update: %v", err)
	}
	if countWSLCall(runner.calls, "--update") != 1 {
		t.Fatalf("update was not called exactly once: %v", runner.calls)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestLegacyHelpWithoutSafeUpdateStops(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{output: "--install\n--web-download\n--help\n"}},
		"features":           {featureReply("Enabled", "Enabled")},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLUnsupported) || !strings.Contains(err.Error(), "--no-distribution") {
		t.Fatalf("error=%v, want explicit unsupported CLI result", err)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestLegacyHelpEnablesBothMissingFeaturesBeforeReboot(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{output: "--install\n--help\n"}},
		"features":           {featureReply("Disabled", "Disabled")},
		"dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart": {{err: fakeProcessExit{code: 3010}}},
		"dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart":            {{}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrRebootRequired) {
		t.Fatalf("error=%v, want reboot after both feature changes", err)
	}
	if countWSLCall(runner.calls, "/enable-feature /featurename:") != 2 {
		t.Fatalf("did not enable both confirmed missing features: %v", runner.calls)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestLegacyHelpWithUnknownFeatureStateStopsWithoutChanges(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{output: "--install\n--update\n--help\n"}},
		"features":           {{err: fakeProcessExit{code: 1}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLUnknown) || !strings.Contains(err.Error(), "feature state") {
		t.Fatalf("error=%v, want unknown feature state", err)
	}
	if containsWSLCall(runner.calls, "dism.exe") || containsWSLCall(runner.calls, "--update") {
		t.Fatalf("changed WSL without confirmed feature state: %v", runner.calls)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestLegacyHelpWithPendingFeatureStopsForReboot(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{output: "--install\n--help\n"}},
		"features":           {featureReply("EnablePending", "Enabled")},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrRebootRequired) {
		t.Fatalf("error=%v, want reboot", err)
	}
	if containsWSLCall(runner.calls, "dism.exe") || containsWSLCall(runner.calls, "--update") {
		t.Fatalf("changed WSL while a Windows feature was pending: %v", runner.calls)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestHelpFailureWithoutUsableOutputStops(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{output: "无法读取命令 --install", err: fakeProcessExit{code: 1}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLUnknown) {
		t.Fatalf("error=%v, want unknown CLI capabilities", err)
	}
	if containsWSLCall(runner.calls, "dism.exe") || containsWSLCall(runner.calls, "--update") {
		t.Fatalf("continued after invalid help output: %v", runner.calls)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestLegacyUpdateTimeoutDoesNotStartAnotherInstaller(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       {failedProbe()[0], failedProbe()[0]},
		"wsl --list --quiet": {failedProbe()[0], failedProbe()[0]},
		"wsl --help":         {{output: "--install\n--update\n--help\n"}},
		"features":           {featureReply("Enabled", "Enabled")},
		"wsl --update":       {{block: true}},
	}}
	i := newFakeInstaller(t, runner)
	policy := testWSLPolicy()
	policy.installTimeout = 5 * time.Millisecond
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, policy)
	if !errors.Is(err, ErrWSLTimeout) || !strings.Contains(err.Error(), "wsl --update") {
		t.Fatalf("error=%v, want update timeout", err)
	}
	if countWSLCall(runner.calls, "--update") != 1 {
		t.Fatalf("retried an uncertain update: %v", runner.calls)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestLegacyUpdatePermissionAndFailure(t *testing.T) {
	for _, tc := range []struct {
		name string
		code int
		want error
	}{
		{name: "permission", code: 740, want: ErrWSLPermission},
		{name: "failure", code: 31, want: ErrWSLInstallFailed},
	} {
		t.Run(tc.name, func(t *testing.T) {
			runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
				"wsl --status":       {failedProbe()[0], failedProbe()[0]},
				"wsl --list --quiet": {failedProbe()[0], failedProbe()[0]},
				"wsl --help":         {{output: "--install\n--update\n--help\n"}},
				"features":           {featureReply("Enabled", "Enabled")},
				"wsl --update":       {{err: fakeProcessExit{code: tc.code}}},
			}}
			i := newFakeInstaller(t, runner)
			err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
			if !errors.Is(err, tc.want) || !strings.Contains(err.Error(), "wsl --update") {
				t.Fatalf("error=%v, want %v with update details", err, tc.want)
			}
			assertNoBareWSLInstall(t, runner.calls)
		})
	}
}

func TestHelpCancellationStopsWithoutInstall(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{block: true}},
	}}
	runner.onCall = func(key string, _ []string) {
		if key == "wsl --help" {
			cancel()
		}
	}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(ctx, Options{}, i, testWSLPolicy())
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error=%v, want cancellation", err)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestHelpTimeoutStopsWithoutInstall(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{block: true}},
	}}
	i := newFakeInstaller(t, runner)
	policy := testWSLPolicy()
	policy.commandTimeout = 5 * time.Millisecond
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, policy)
	if !errors.Is(err, ErrWSLTimeout) {
		t.Fatalf("error=%v, want help timeout", err)
	}
	assertNoBareWSLInstall(t, runner.calls)
}

func TestDefaultInstallTimeoutButRuntimeReadyDoesNotFallback(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    append(failedProbe(), fakeWSLReply{output: "ready"}),
		"wsl --list --quiet":              failedProbe(),
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{block: true}},
	}}
	i := newFakeInstaller(t, runner)
	policy := testWSLPolicy()
	policy.installTimeout = 5 * time.Millisecond
	if err := ensureWSLWithPolicy(context.Background(), Options{}, i, policy); err != nil {
		t.Fatalf("ensureWSL after timed out command: %v", err)
	}
	if containsWSLCall(runner.calls, "--web-download") {
		t.Fatalf("web fallback ran after runtime probe became ready: %v", runner.calls)
	}
}

func TestDefaultInstallTimeoutWithoutReadyRuntimeDoesNotStartSecondInstaller(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    {failedProbe()[0], failedProbe()[0]},
		"wsl --list --quiet":              {failedProbe()[0], failedProbe()[0]},
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{block: true}},
	}}
	i := newFakeInstaller(t, runner)
	policy := testWSLPolicy()
	policy.installTimeout = 5 * time.Millisecond
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, policy)
	if !strings.Contains(err.Error(), "wsl --install --no-distribution") || !strings.Contains(err.Error(), "setup.log") {
		t.Fatalf("timeout error omitted command details or log reference: %v", err)
	}
	if !errors.Is(err, ErrWSLTimeout) {
		t.Fatalf("error=%v, want ErrWSLTimeout", err)
	}
	if containsWSLCall(runner.calls, "--web-download") {
		t.Fatalf("web fallback ran while default install completion was uncertain: %v", runner.calls)
	}
}

func TestWebDownloadFallbackRunsOnceAndSucceeds(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    append(failedProbe(), failedProbe()...),
		"wsl --list --quiet":              append(failedProbe(), failedProbe()...),
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled"), featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{err: fakeProcessExit{code: 1}}},
		"wsl --install --web-download --no-distribution": {{output: "downloaded"}},
	}}
	// Add the successful status result after the initial probe, default postcheck,
	// and the web fallback postcheck.
	runner.replies["wsl --status"] = append(runner.replies["wsl --status"], fakeWSLReply{output: "ready"})
	i := newFakeInstaller(t, runner)
	if err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy()); err != nil {
		t.Fatalf("ensureWSL fallback: %v", err)
	}
	if countWSLCall(runner.calls, "--install --web-download --no-distribution") != 1 {
		t.Fatalf("web fallback call count is not one: %v", runner.calls)
	}
}

func TestWebDownloadUnsupportedPreservesInstallFailure(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    append(failedProbe(), failedProbe()...),
		"wsl --list --quiet":              append(failedProbe(), failedProbe()...),
		"wsl --help":                      {standardHelp(false)},
		"features":                        {featureReply("Enabled", "Enabled"), featureReply("Enabled", "Enabled"), featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{err: fakeProcessExit{code: 1}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLInstallFailed) {
		t.Fatalf("error=%v, want ErrWSLInstallFailed", err)
	}
	for _, want := range []string{"exit code 1", "web-download: not available", "setup.log"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error missing %q: %v", want, err)
		}
	}
	if containsWSLCall(runner.calls, "--web-download") || containsWSLCall(runner.calls, "dism.exe") {
		t.Fatalf("unsupported fallback or unnecessary DISM ran: %v", runner.calls)
	}
}

func TestBothOnlinePathsFailPreservesBothAttemptResults(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    {failedProbe()[0], failedProbe()[0], failedProbe()[0]},
		"wsl --list --quiet":              {failedProbe()[0], failedProbe()[0], failedProbe()[0]},
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled"), featureReply("Enabled", "Enabled"), featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{err: fakeProcessExit{code: 31}}},
		"wsl --install --web-download --no-distribution": {{err: fakeProcessExit{code: 42}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLInstallFailed) {
		t.Fatalf("error=%v, want ErrWSLInstallFailed", err)
	}
	for _, want := range []string{"exit code 31", "exit code 42", "setup.log"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error missing %q: %v", want, err)
		}
	}
	if countWSLCall(runner.calls, "--install --no-distribution") != 1 || countWSLCall(runner.calls, "--install --web-download --no-distribution") != 1 {
		t.Fatalf("online paths were not bounded to one attempt each: %v", runner.calls)
	}
}

func TestUnknownFeatureStateSkipsAutomaticDISM(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    {failedProbe()[0], failedProbe()[0], failedProbe()[0]},
		"wsl --list --quiet":              {failedProbe()[0], failedProbe()[0], failedProbe()[0]},
		"wsl --help":                      {standardHelp(true)},
		"features":                        {{err: fakeProcessExit{code: 1}}, {err: fakeProcessExit{code: 1}}, {err: fakeProcessExit{code: 1}}},
		"wsl --install --no-distribution": {{err: fakeProcessExit{code: 1}}},
		"wsl --install --web-download --no-distribution": {{err: fakeProcessExit{code: 1}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLInstallFailed) {
		t.Fatalf("error=%v, want ErrWSLInstallFailed", err)
	}
	if containsWSLCall(runner.calls, "dism.exe") {
		t.Fatalf("DISM ran without a reliable feature-state query: %v", runner.calls)
	}
}

func TestUnsupportedInstallOptionsStopBeforeDownloads(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {{output: "Usage: wsl.exe --list --verbose"}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLUnsupported) {
		t.Fatalf("error=%v, want ErrWSLUnsupported", err)
	}
	if containsWSLCall(runner.calls, "--install") || containsWSLCall(runner.calls, "--web-download") {
		t.Fatalf("unsupported install options were invoked: %v", runner.calls)
	}
}

func TestPermissionFailureDoesNotRunWebFallback(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    append(failedProbe(), failedProbe()...),
		"wsl --list --quiet":              append(failedProbe(), failedProbe()...),
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{err: fakeProcessExit{code: 740}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLPermission) {
		t.Fatalf("error=%v, want ErrWSLPermission", err)
	}
	if containsWSLCall(runner.calls, "--web-download") {
		t.Fatalf("web fallback ran after a permission failure: %v", runner.calls)
	}
}

func TestWSLInstall3010StopsForRebootWithoutFallback(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    {failedProbe()[0], failedProbe()[0]},
		"wsl --list --quiet":              {failedProbe()[0], failedProbe()[0]},
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled")},
		"wsl --install --no-distribution": {{err: fakeProcessExit{code: 3010}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrRebootRequired) {
		t.Fatalf("error=%v, want ErrRebootRequired", err)
	}
	if containsWSLCall(runner.calls, "--web-download") {
		t.Fatalf("setup continued into the online fallback after reboot result: err=%v calls=%v", err, runner.calls)
	}
}

func TestEnablePendingFeatureStopsForReboot(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":       failedProbe(),
		"wsl --list --quiet": failedProbe(),
		"wsl --help":         {standardHelp(true)},
		"features":           {featureReply("Enable Pending", "Enabled")},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrRebootRequired) {
		t.Fatalf("error=%v, want ErrRebootRequired", err)
	}
	if containsWSLCall(runner.calls, "--install") || containsWSLCall(runner.calls, "dism.exe") {
		t.Fatalf("installation continued while reboot was pending: %v", runner.calls)
	}
}

func TestFeatureBecomingPendingAfterDefaultInstallStopsWebFallback(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    {failedProbe()[0], failedProbe()[0]},
		"wsl --list --quiet":              {failedProbe()[0], failedProbe()[0]},
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled"), featureReply("EnablePending", "Enabled")},
		"wsl --install --no-distribution": {{err: fakeProcessExit{code: 1}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrRebootRequired) {
		t.Fatalf("error=%v, want ErrRebootRequired", err)
	}
	if containsWSLCall(runner.calls, "--web-download") {
		t.Fatalf("web fallback ran after a feature became restart-pending: %v", runner.calls)
	}
}

func TestDism3010StopsForRebootAndOnlyEnablesMissingFeature(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --status":                    {failedProbe()[0], failedProbe()[0], failedProbe()[0]},
		"wsl --list --quiet":              {failedProbe()[0], failedProbe()[0], failedProbe()[0]},
		"wsl --help":                      {standardHelp(true)},
		"features":                        {featureReply("Enabled", "Enabled"), featureReply("Enabled", "Enabled"), featureReply("Disabled", "Enabled")},
		"wsl --install --no-distribution": {{err: fakeProcessExit{code: 1}}},
		"wsl --install --web-download --no-distribution":                                              {{err: fakeProcessExit{code: 1}}},
		"dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart": {{err: fakeProcessExit{code: 3010}}},
	}}
	i := newFakeInstaller(t, runner)
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrRebootRequired) {
		t.Fatalf("error=%v, want ErrRebootRequired", err)
	}
	if countWSLCall(runner.calls, "/enable-feature /featurename:") != 1 {
		t.Fatalf("DISM did not enable exactly the confirmed missing feature: %v", runner.calls)
	}
	for _, call := range runner.calls {
		joined := strings.Join(call, " ")
		if strings.Contains(strings.ToLower(joined), "dism.exe") && strings.Contains(joined, "VirtualMachinePlatform") {
			t.Fatalf("enabled a feature that was reported enabled: %v", runner.calls)
		}
	}
}

func TestUnsupportedArchitectureStopsBeforeExternalCommands(t *testing.T) {
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{}}
	i := newFakeInstaller(t, runner)
	i.env.Arch = "arm64"
	err := ensureWSLWithPolicy(context.Background(), Options{}, i, testWSLPolicy())
	if !errors.Is(err, ErrWSLUnsupported) {
		t.Fatalf("error=%v, want ErrWSLUnsupported", err)
	}
	if len(runner.calls) != 0 {
		t.Fatalf("unsupported architecture ran commands: %v", runner.calls)
	}
}

func registrationReply(path string) fakeWSLReply {
	data, _ := json.Marshal(map[string]string{"DistributionName": "flashserver_ubuntu", "BasePath": path})
	return fakeWSLReply{output: string(data)}
}
func TestMoveDistroStateTable(t *testing.T) {
	for _, tc := range []struct {
		name                  string
		consent               bool
		firstErr, shutdownErr error
		same, mismatch        bool
		otherRunning          bool
	}{
		{name: "same path", same: true},
		{name: "target only move succeeds"},
		{name: "other distro stays running", otherRunning: true},
		{name: "target only move fails without consent", firstErr: fakeProcessExit{code: 1}},
		{name: "authorized global retry", firstErr: fakeProcessExit{code: 1}, consent: true},
		{name: "authorized shutdown fails", firstErr: fakeProcessExit{code: 1}, consent: true, shutdownErr: fakeProcessExit{code: 2}},
		{name: "post move path mismatch", mismatch: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			source := filepath.Join(t.TempDir(), "source")
			target := filepath.Join(t.TempDir(), "target")
			os.MkdirAll(source, 0700)
			os.WriteFile(filepath.Join(source, "ext4.vhdx"), []byte("existing"), 0600)
			if tc.same {
				target = source
			}
			final := target
			if tc.mismatch {
				final = source
			}
			runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{"features": {registrationReply(source)}, "wsl --help": {{output: "--manage --move"}}, "wsl --terminate flashserver_ubuntu": {{}}, "wsl --manage flashserver_ubuntu --move " + target: {{err: tc.firstErr}}, "wsl --shutdown": {{err: tc.shutdownErr}}}}
			if tc.otherRunning {
				runner.add("wsl --list --running --quiet", fakeWSLReply{output: "Ubuntu\nflashserver_ubuntu"})
			}
			if !tc.same {
				if tc.firstErr != nil {
					runner.add("features", registrationReply(source))
				}
				if tc.consent && tc.firstErr != nil && tc.shutdownErr == nil {
					runner.add("features", registrationReply(source))
				}
				if tc.firstErr == nil || (tc.consent && tc.shutdownErr == nil) {
					runner.add("features", registrationReply(final))
				}
				if tc.consent && tc.firstErr != nil && tc.shutdownErr == nil {
					runner.add("wsl --manage flashserver_ubuntu --move "+target, fakeWSLReply{})
				}
			}
			runner.onCall = func(key string, _ []string) {
				if strings.Contains(key, "--manage flashserver_ubuntu --move") && (tc.firstErr == nil || len(runner.calls) > 4) && !tc.mismatch {
					os.WriteFile(filepath.Join(target, "ext4.vhdx"), []byte("moved"), 0600)
				}
			}
			i := newFakeInstaller(t, runner)
			var output bytes.Buffer
			i.out = &output
			err := moveDistro(context.Background(), Options{Distro: "flashserver_ubuntu", WSLDir: target, AllowGlobalWSLShutdown: tc.consent}, i)
			wantErr := (tc.firstErr != nil && (!tc.consent || tc.shutdownErr != nil)) || tc.mismatch
			if (err != nil) != wantErr {
				t.Fatalf("err=%v calls=%v", err, runner.calls)
			}
			if !tc.consent && containsWSLCall(runner.calls, "--shutdown") {
				t.Fatal("unauthorized shutdown")
			}
			if tc.otherRunning && containsWSLCall(runner.calls, "--terminate Ubuntu") {
				t.Fatal("unrelated distribution was stopped")
			}
			if tc.same && len(runner.calls) != 1 {
				t.Fatal(runner.calls)
			}
			if tc.firstErr != nil && !tc.consent && !strings.Contains(err.Error(), "not authorized") {
				t.Fatal(err)
			}
			if tc.consent && tc.firstErr != nil && countWSLCall(runner.calls, "--shutdown") != 1 {
				t.Fatal(runner.calls)
			}
			if _, e := os.Stat(filepath.Join(source, "ext4.vhdx")); e != nil {
				t.Fatal("source was deleted")
			}
		})
	}
}

func TestImportLocationAndFailureSafety(t *testing.T) {
	for _, tc := range []struct {
		name, target string
		prepareErr   error
		importErr    error
		expectedErr  bool
	}{
		{name: "default"}, {name: "custom D drive", target: `D:\FlashServer Data`},
		{name: "spaces and Chinese", target: "中文 with space"},
		{name: "target has files", target: "occupied", expectedErr: true},
		{name: "target not writable", target: "unwritable", prepareErr: errors.New("access denied"), expectedErr: true},
		{name: "import failure preserves target", target: "failed", importErr: fakeProcessExit{code: 1}, expectedErr: true},
		{name: "disk full import preserves target", target: "diskfull", importErr: fakeProcessExit{code: 112}, expectedErr: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			base := t.TempDir()
			t.Setenv("LOCALAPPDATA", base)
			target := tc.target
			if target == "" {
				target = filepath.Join(base, "wsl", "flashserver_ubuntu")
			}
			if target == "occupied" || target == "unwritable" || target == "failed" || target == "diskfull" || strings.Contains(target, "中文") {
				target = filepath.Join(base, target)
			}
			if tc.name == "target has files" {
				os.MkdirAll(target, 0700)
				os.WriteFile(filepath.Join(target, "keep.txt"), []byte("keep"), 0600)
			}
			rootfs := filepath.Join(base, "rootfs.tar.xz")
			os.WriteFile(rootfs, []byte("fake"), 0600)
			runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{"wsl --list --quiet": {{}}, "wsl --import flashserver_ubuntu " + target + " " + rootfs + " --version 2": {{err: tc.importErr}}}}
			i := newFakeInstaller(t, runner)
			if tc.name == "custom D drive" || tc.prepareErr != nil {
				i.prepareLocation = func(string) error { return tc.prepareErr }
			}
			err := importDistroRootfs(context.Background(), Options{Distro: "flashserver_ubuntu", WSLDir: func() string {
				if tc.name == "default" {
					return ""
				}
				return target
			}(), DistroRootfs: rootfs}, i)
			if (err != nil) != tc.expectedErr {
				t.Fatalf("err=%v calls=%v", err, runner.calls)
			}
			if tc.name == "custom D drive" && !containsWSLCall(runner.calls, `D:\FlashServer Data`) {
				t.Fatal(runner.calls)
			}
			if tc.name == "target has files" {
				data, _ := os.ReadFile(filepath.Join(target, "keep.txt"))
				if string(data) != "keep" {
					t.Fatal("existing file changed")
				}
			}
			if tc.name == "import failure preserves target" || tc.name == "disk full import preserves target" {
				if _, e := os.Stat(target); e != nil {
					t.Fatal("target deleted")
				}
			}
		})
	}
}

func TestCancellationDuringImportWaitsForCommandAndChecksLocation(t *testing.T) {
	base := t.TempDir()
	target := filepath.Join(base, "distro")
	rootfs := filepath.Join(base, "rootfs.tar.xz")
	if err := os.WriteFile(rootfs, []byte("fake"), 0600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"wsl --list --quiet": {{}, {output: "flashserver_ubuntu"}},
		"features":           {registrationReply(target)},
		"wsl --import flashserver_ubuntu " + target + " " + rootfs + " --version 2": {{}},
	}}
	runner.onCall = func(key string, _ []string) {
		if strings.Contains(key, "--import flashserver_ubuntu") {
			cancel()
			if err := os.WriteFile(filepath.Join(target, "ext4.vhdx"), []byte("imported"), 0600); err != nil {
				t.Fatal(err)
			}
		}
	}
	i := newFakeInstaller(t, runner)
	err := importDistroRootfs(ctx, Options{Distro: "flashserver_ubuntu", WSLDir: target, DistroRootfs: rootfs}, i)
	if !errors.Is(err, context.Canceled) || !strings.Contains(err.Error(), "setup stopped before later steps") {
		t.Fatalf("err=%v calls=%v", err, runner.calls)
	}
	if _, err := os.Stat(filepath.Join(target, "ext4.vhdx")); err != nil {
		t.Fatal("import result was not preserved")
	}
}

func TestCancelledInstallDoesNotProbeOrFallback(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	i := &installer{out: io.Discard, runner: func(context.Context, string, ...string) ([]byte, error) { cancel(); return nil, context.Canceled }}
	attempt := runWSLInstallAttempt(ctx, i, testWSLPolicy(), "--install", "--no-distribution")
	err := stopWSLAfterBlock(attempt.blockingError(ctx), attempt.name, attempt.summary(), "not attempted")
	if !errors.Is(err, context.Canceled) || errors.Is(err, ErrWSLTimeout) || !strings.Contains(err.Error(), "user cancelled") {
		t.Fatal(err)
	}
}

func containsWSLCall(calls [][]string, fragment string) bool {
	for _, call := range calls {
		if strings.Contains(strings.Join(call, " "), fragment) {
			return true
		}
	}
	return false
}

func countWSLCall(calls [][]string, fragment string) int {
	count := 0
	for _, call := range calls {
		if strings.Contains(strings.Join(call, " "), fragment) {
			count++
		}
	}
	return count
}

func assertNoBareWSLInstall(t *testing.T, calls [][]string) {
	t.Helper()
	for _, call := range calls {
		if len(call) == 2 && strings.EqualFold(filepath.Base(call[0]), "wsl.exe") && call[1] == "--install" {
			t.Fatalf("bare wsl --install may add a default distribution: %v", calls)
		}
	}
}

func TestMoveCancelledNeverShutsDown(t *testing.T) {
	base := t.TempDir()
	source := filepath.Join(base, "source")
	target := filepath.Join(base, "target")
	os.MkdirAll(source, 0700)
	os.WriteFile(filepath.Join(source, "ext4.vhdx"), []byte("keep"), 0600)
	ctx, cancel := context.WithCancel(context.Background())
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{"features": {registrationReply(source)}, "wsl --help": {{output: "--manage --move"}}, "wsl --terminate flashserver_ubuntu": {{}}, "wsl --manage flashserver_ubuntu --move " + target: {{err: context.Canceled}}}}
	runner.onCall = func(key string, _ []string) {
		if strings.Contains(key, "--manage flashserver_ubuntu --move") {
			cancel()
		}
	}
	i := newFakeInstaller(t, runner)
	err := moveDistro(ctx, Options{Distro: "flashserver_ubuntu", WSLDir: target, AllowGlobalWSLShutdown: true}, i)
	if !errors.Is(err, context.Canceled) || containsWSLCall(runner.calls, "--shutdown") {
		t.Fatalf("err=%v calls=%v", err, runner.calls)
	}
}

func TestCancellationDuringMoveWaitsForCommandAndChecksLocation(t *testing.T) {
	base := t.TempDir()
	source := filepath.Join(base, "source")
	target := filepath.Join(base, "target")
	cancelFile := filepath.Join(base, "cancel.txt")
	if err := os.MkdirAll(source, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "ext4.vhdx"), []byte("source"), 0600); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{
		"features":                           {registrationReply(source), registrationReply(target)},
		"wsl --help":                         {{output: "--manage --move"}},
		"wsl --terminate flashserver_ubuntu": {{}},
		"wsl --manage flashserver_ubuntu --move " + target: {{}},
	}}
	runner.onCall = func(key string, _ []string) {
		if strings.Contains(key, "--manage flashserver_ubuntu --move") {
			if err := os.WriteFile(cancelFile, []byte("cancel"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(target, "ext4.vhdx"), []byte("moved"), 0600); err != nil {
				t.Fatal(err)
			}
		}
	}
	i := newFakeInstaller(t, runner)
	err := moveDistro(ctx, Options{Distro: "flashserver_ubuntu", WSLDir: target, CancelFile: cancelFile, AllowGlobalWSLShutdown: true}, i)
	if !errors.Is(err, context.Canceled) || !strings.Contains(err.Error(), "setup stopped before later steps") {
		t.Fatalf("err=%v calls=%v", err, runner.calls)
	}
	if countWSLCall(runner.calls, "--manage flashserver_ubuntu --move") != 1 || containsWSLCall(runner.calls, "--shutdown") {
		t.Fatal(runner.calls)
	}
}
func TestFailedMoveCanRetryWithoutLosingSource(t *testing.T) {
	base := t.TempDir()
	source := filepath.Join(base, "source")
	target := filepath.Join(base, "target")
	os.MkdirAll(source, 0700)
	os.WriteFile(filepath.Join(source, "ext4.vhdx"), []byte("keep"), 0600)
	opts := Options{Distro: "flashserver_ubuntu", WSLDir: target}
	first := &fakeWSLRunner{replies: map[string][]fakeWSLReply{"features": {registrationReply(source), registrationReply(source)}, "wsl --help": {{output: "--manage --move"}}, "wsl --terminate flashserver_ubuntu": {{}}, "wsl --manage flashserver_ubuntu --move " + target: {{err: fakeProcessExit{code: 1}}}}}
	i := newFakeInstaller(t, first)
	if err := moveDistro(context.Background(), opts, i); err == nil {
		t.Fatal("first move should fail")
	}
	if _, err := os.Stat(filepath.Join(source, "ext4.vhdx")); err != nil {
		t.Fatal("source lost")
	}
	second := &fakeWSLRunner{replies: map[string][]fakeWSLReply{"features": {registrationReply(source), registrationReply(target)}, "wsl --help": {{output: "--manage --move"}}, "wsl --terminate flashserver_ubuntu": {{}}, "wsl --manage flashserver_ubuntu --move " + target: {{}}}}
	second.onCall = func(key string, _ []string) {
		if strings.Contains(key, "--manage flashserver_ubuntu --move") {
			os.WriteFile(filepath.Join(target, "ext4.vhdx"), []byte("moved"), 0600)
		}
	}
	i = newFakeInstaller(t, second)
	if err := moveDistro(context.Background(), opts, i); err != nil {
		t.Fatal(err)
	}
	if containsWSLCall(second.calls, "--shutdown") {
		t.Fatal("unapproved shutdown")
	}
}

func TestExistingDistroRejectsOccupiedTarget(t *testing.T) {
	base := t.TempDir()
	source := filepath.Join(base, "source")
	target := filepath.Join(base, "occupied")
	os.MkdirAll(source, 0700)
	os.MkdirAll(target, 0700)
	os.WriteFile(filepath.Join(source, "ext4.vhdx"), []byte("source"), 0600)
	os.WriteFile(filepath.Join(target, "user.txt"), []byte("user"), 0600)
	runner := &fakeWSLRunner{replies: map[string][]fakeWSLReply{"features": {registrationReply(source)}}}
	i := newFakeInstaller(t, runner)
	err := moveDistro(context.Background(), Options{Distro: "flashserver_ubuntu", WSLDir: target}, i)
	if err == nil || containsWSLCall(runner.calls, "--terminate") || containsWSLCall(runner.calls, "--shutdown") || containsWSLCall(runner.calls, "--move") {
		t.Fatalf("err=%v calls=%v", err, runner.calls)
	}
	data, _ := os.ReadFile(filepath.Join(target, "user.txt"))
	if string(data) != "user" {
		t.Fatal("user file changed")
	}
}
