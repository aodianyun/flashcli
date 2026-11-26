//go:build windows

package setup

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
)

var (
	ErrWSLPermission    = errors.New("WSL installation requires administrator permissions")
	ErrWSLUnsupported   = errors.New("this Windows or WSL CLI version is not supported by automatic setup")
	ErrWSLTimeout       = errors.New("WSL installation timed out")
	ErrWSLUnknown       = errors.New("WSL runtime state could not be determined")
	ErrWSLInstallFailed = errors.New("WSL runtime installation did not complete")
)

type wslPolicy struct {
	commandTimeout time.Duration
	installTimeout time.Duration
	verifyTimeout  time.Duration
	pollInterval   time.Duration
	featureTimeout time.Duration
}

var defaultWSLPolicy = wslPolicy{
	commandTimeout: 10 * time.Second,
	installTimeout: 20 * time.Minute,
	verifyTimeout:  60 * time.Second,
	pollInterval:   3 * time.Second,
	featureTimeout: 5 * time.Minute,
}

type wslProbeResult struct {
	ready     bool
	statusErr error
	listErr   error
}

type wslFeatureState uint8

const (
	wslFeatureUnknown wslFeatureState = iota
	wslFeatureEnabled
	wslFeatureDisabled
	wslFeatureEnablePending
)

var wslFeatures = []string{
	"Microsoft-Windows-Subsystem-Linux",
	"VirtualMachinePlatform",
}

func detectWSLAvailable(ctx context.Context) bool {
	probeCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	return probeWSLRuntime(probeCtx, &installer{}).ready
}

func wslStatusOK(ctx context.Context) bool {
	probeCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	return probeWSLRuntime(probeCtx, &installer{}).ready
}

func probeWSLRuntime(ctx context.Context, i *installer) wslProbeResult {
	statusCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	_, statusErr := i.runDiagOutput(statusCtx, sysExe("wsl.exe"), "--status")
	cancel()
	if statusErr == nil {
		return wslProbeResult{ready: true}
	}

	// `--list --quiet` also succeeds on a usable runtime with no registered
	// distributions. No Ubuntu distribution is required to reuse WSL itself.
	listCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	_, listErr := i.runDiagOutput(listCtx, sysExe("wsl.exe"), "--list", "--quiet")
	cancel()
	return wslProbeResult{ready: listErr == nil, statusErr: statusErr, listErr: listErr}
}

func ensureWSL(ctx context.Context, opts Options, i *installer) error {
	return ensureWSLWithPolicy(ctx, opts, i, defaultWSLPolicy)
}

func ensureWSLWithPolicy(ctx context.Context, opts Options, i *installer, policy wslPolicy) error {
	if i.env.OS != "" && i.env.OS != "windows" {
		return fmt.Errorf("%w: WSL setup requires Windows", ErrWSLUnsupported)
	}
	if i.env.Arch != "" && i.env.Arch != "amd64" {
		return fmt.Errorf("%w: the Windows installer supports amd64, detected %s", ErrWSLUnsupported, i.env.Arch)
	}
	if opts.DryRun {
		i.printf("$ wsl.exe --install --no-distribution\n")
		i.printf("$ wsl.exe --install --web-download --no-distribution (fallback when supported)\n")
		return nil
	}

	if probe := probeWSLRuntime(ctx, i); probe.ready {
		i.printf("WSL runtime is available; reusing it without requiring a Linux distribution\n")
		return nil
	}
	i.printf("WSL runtime is not confirmed ready; checking supported install options\n")

	options, helpErr := queryWSLInstallOptions(ctx, i, policy.commandTimeout)
	if helpErr != nil {
		if errors.Is(helpErr, context.Canceled) {
			return helpErr
		}
		if errors.Is(helpErr, context.DeadlineExceeded) {
			return fmt.Errorf("%w: wsl --help capability probe timed out; no WSL installation command was started. See setup.log for details", ErrWSLTimeout)
		}
		return fmt.Errorf("%w: could not verify WSL CLI options from wsl --help: %s; no WSL installation command was started. See setup.log for details", ErrWSLUnknown, describeCommand("wsl --help", helpErr, nil))
	}
	if !options.install {
		return fmt.Errorf("%w: wsl --help does not advertise --install; no WSL installation command was started. See setup.log for details", ErrWSLUnsupported)
	}

	featureStates, featureErr := queryWSLFeatureStates(ctx, i, policy.commandTimeout)
	if err := ctx.Err(); err != nil {
		return err
	}
	if featureErr != nil {
		i.printf("Windows optional feature state is unknown; automatic DISM changes will be skipped unless a later read-only query succeeds\n")
	} else if hasFeatureState(featureStates, wslFeatureEnablePending) {
		return fmt.Errorf("%w: a WSL Windows feature is pending; restart Windows and run Setup again", ErrRebootRequired)
	}
	if !options.noDistribution {
		return ensureLegacyWSL(ctx, options, featureStates, featureErr, i, policy)
	}

	defaultAttempt := runWSLInstallAttempt(ctx, i, policy, "--install", "--no-distribution")
	if defaultAttempt.ready {
		return nil
	}
	if err := defaultAttempt.blockingError(ctx); err != nil {
		return stopWSLAfterBlock(err, "default WSL online installation", defaultAttempt.summary(), "not attempted")
	}
	if states, err := queryWSLFeatureStates(ctx, i, policy.commandTimeout); err == nil && hasFeatureState(states, wslFeatureEnablePending) {
		return fmt.Errorf("%w: a WSL Windows feature became pending during the default install; restart Windows and run Setup again", ErrRebootRequired)
	}
	if !options.webDownload {
		return finishWSLInstallFailure(ctx, i, policy, defaultAttempt, nil)
	}

	webAttempt := runWSLInstallAttempt(ctx, i, policy, "--install", "--web-download", "--no-distribution")
	if webAttempt.ready {
		return nil
	}
	if err := webAttempt.blockingError(ctx); err != nil {
		return stopWSLAfterBlock(err, "WSL web-download fallback", defaultAttempt.summary(), webAttempt.summary())
	}
	return finishWSLInstallFailure(ctx, i, policy, defaultAttempt, &webAttempt)
}

type wslInstallOptions struct {
	install        bool
	noDistribution bool
	webDownload    bool
	update         bool
}

func queryWSLInstallOptions(ctx context.Context, i *installer, timeout time.Duration) (wslInstallOptions, error) {
	helpCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	output, commandErr := i.runDiagOutput(helpCtx, sysExe("wsl.exe"), "--help")
	if err := helpCtx.Err(); err != nil {
		return wslInstallOptions{}, err
	}
	options := wslInstallOptions{
		install:        hasHelpOption(output, "--install"),
		noDistribution: hasHelpOption(output, "--no-distribution"),
		webDownload:    hasHelpOption(output, "--web-download"),
		update:         hasHelpOption(output, "--update"),
	}
	if !validWSLHelpText(output, commandErr != nil) {
		if commandErr != nil {
			return wslInstallOptions{}, fmt.Errorf("wsl --help produced no usable command list: %w", commandErr)
		}
		return wslInstallOptions{}, errors.New("wsl --help produced no usable command list")
	}
	if commandErr != nil {
		code, ok := commandExitCode(commandErr)
		if !ok {
			return wslInstallOptions{}, commandErr
		}
		i.printf("wsl --help exited with code %d, but its command list was parsed successfully\n", code)
	}
	return options, nil
}

func validWSLHelpText(help []byte, requireStructure bool) bool {
	commands := []string{"--install", "--update", "--status", "--help", "--list"}
	count := 0
	for _, command := range commands {
		if hasHelpOption(help, command) {
			count++
		}
	}
	if count == 0 {
		return false
	}
	if !requireStructure {
		return true
	}
	listedLines := 0
	for _, line := range strings.Split(string(normalizeDiagnostic(help)), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		for _, command := range commands {
			if hasHelpOption([]byte(line), command) {
				listedLines++
				break
			}
		}
		first := strings.Trim(fields[0], "`'\"()[]{}:,.;：，。；（）【】")
		if (strings.EqualFold(first, "wsl") || strings.EqualFold(first, "wsl.exe")) && len(fields) > 1 {
			first = strings.Trim(fields[1], "`'\"()[]{}:,.;：，。；（）【】")
		}
		for _, command := range commands {
			if first == command {
				return true
			}
		}
	}
	return listedLines >= 2
}

func hasHelpOption(help []byte, option string) bool {
	for _, field := range strings.Fields(string(normalizeDiagnostic(help))) {
		field = strings.Trim(field, "`'\"()[]{}:,.;：，。；（）【】")
		if field == option {
			return true
		}
	}
	return false
}

func ensureLegacyWSL(ctx context.Context, options wslInstallOptions, states map[string]wslFeatureState, featureErr error, i *installer, policy wslPolicy) error {
	i.printf("WSL CLI does not advertise --no-distribution; the compatibility path will not run bare wsl --install\n")
	if featureErr != nil {
		return fmt.Errorf("%w: WSL CLI install options are limited and Windows feature state could not be verified: %v; no installation command was started. See setup.log for details", ErrWSLUnknown, featureErr)
	}

	missing := missingWSLFeatures(states)
	if len(missing) > 0 {
		i.printf("Enabling only confirmed disabled WSL Windows features with DISM; a restart is required before continuing\n")
		if _, err := enableMissingWSLFeatures(ctx, i, policy, missing); err != nil {
			if errors.Is(err, context.Canceled) {
				return err
			}
			if errors.Is(err, context.DeadlineExceeded) {
				return fmt.Errorf("%w: enabling WSL Windows features timed out: %v; no WSL install command was started. See setup.log for details", ErrWSLTimeout, err)
			}
			if errors.Is(err, ErrWSLPermission) {
				return fmt.Errorf("%w: could not enable confirmed missing WSL Windows features: %v. See setup.log for details", ErrWSLPermission, err)
			}
			return fmt.Errorf("%w: could not enable confirmed missing WSL Windows features: %v. See setup.log for details", ErrWSLInstallFailed, err)
		}
		return fmt.Errorf("%w: confirmed missing WSL Windows features were enabled; restart Windows and run Setup again", ErrRebootRequired)
	}

	if !options.update {
		return fmt.Errorf("%w: this WSL CLI does not advertise --no-distribution or --update; bare wsl --install could install a default distribution. No WSL installation command was started. See setup.log for details", ErrWSLUnsupported)
	}
	i.printf("WSL CLI advertises --update; updating WSL without installing a default distribution\n")
	attempt := runWSLInstallAttempt(ctx, i, policy, "--update")
	if attempt.ready {
		return nil
	}
	if err := attempt.blockingError(ctx); err != nil {
		return fmt.Errorf("%w: %s. See setup.log for details", err, attempt.summary())
	}
	return fmt.Errorf("%w: wsl --update did not make the WSL runtime available; %s. See setup.log for details", ErrWSLInstallFailed, attempt.summary())
}

func missingWSLFeatures(states map[string]wslFeatureState) []string {
	missing := make([]string, 0, len(wslFeatures))
	for _, feature := range wslFeatures {
		if states[feature] == wslFeatureDisabled {
			missing = append(missing, feature)
		}
	}
	return missing
}

func enableMissingWSLFeatures(ctx context.Context, i *installer, policy wslPolicy, missing []string) (bool, error) {
	dismCtx, cancel := context.WithTimeout(ctx, policy.featureTimeout)
	defer cancel()
	rebootRequired := false
	for _, feature := range missing {
		if err := ctx.Err(); err != nil {
			return rebootRequired, err
		}
		if err := dismEnable(dismCtx, i, feature); err != nil {
			if errors.Is(err, ErrRebootRequired) {
				rebootRequired = true
				continue
			}
			return rebootRequired, fmt.Errorf("%s: %w", feature, err)
		}
	}
	if err := ctx.Err(); err != nil {
		return rebootRequired, err
	}
	return rebootRequired, nil
}

type wslInstallAttempt struct {
	commandErr    error
	commandCtxErr error
	ready         bool
	probeErr      error
	name          string
}

func runWSLInstallAttempt(ctx context.Context, i *installer, policy wslPolicy, args ...string) wslInstallAttempt {
	name := "wsl " + strings.Join(args, " ")
	installCtx, cancel := context.WithTimeout(ctx, policy.installTimeout)
	_, commandErr := i.runDiagOutput(installCtx, sysExe("wsl.exe"), args...)
	commandCtxErr := installCtx.Err()
	cancel()
	if ctx.Err() != nil {
		return wslInstallAttempt{name: name, commandErr: commandErr, commandCtxErr: ctx.Err(), probeErr: ctx.Err()}
	}
	if errors.Is(commandCtxErr, context.DeadlineExceeded) {
		i.printf("Official WSL command timed out: %s; rechecking runtime before stopping.\n", name)
	}

	ready, probeErr := waitForWSLRuntime(ctx, i, policy)
	return wslInstallAttempt{
		commandErr: commandErr, commandCtxErr: commandCtxErr,
		ready: ready, probeErr: probeErr, name: name,
	}
}

func waitForWSLRuntime(ctx context.Context, i *installer, policy wslPolicy) (bool, error) {
	verifyCtx, cancel := context.WithTimeout(ctx, policy.verifyTimeout)
	defer cancel()
	deadline := time.Now().Add(policy.verifyTimeout)
	for {
		probe := probeWSLRuntime(verifyCtx, i)
		if probe.ready {
			return true, nil
		}
		lastErr := probeError(probe)
		if policy.verifyTimeout <= 0 || time.Now().After(deadline) {
			return false, lastErr
		}
		if ctx.Err() != nil {
			return false, ctx.Err()
		}
		if verifyCtx.Err() != nil {
			return false, verifyCtx.Err()
		}
		if err := i.pause(verifyCtx, policy.pollInterval); err != nil {
			return false, err
		}
	}
}

func probeError(probe wslProbeResult) error {
	return fmt.Errorf("wsl --status: %s; wsl --list --quiet: %s", describeCommand("wsl --status", probe.statusErr, nil), describeCommand("wsl --list --quiet", probe.listErr, nil))
}

func (a wslInstallAttempt) blockingError(parent context.Context) error {
	if parent.Err() != nil {
		return parent.Err()
	}
	if errors.Is(a.commandCtxErr, context.DeadlineExceeded) || errors.Is(a.probeErr, context.DeadlineExceeded) {
		return fmt.Errorf("%w: %s; no second online install will be started while completion is uncertain", ErrWSLTimeout, a.name)
	}
	if code, ok := commandExitCode(a.commandErr); ok {
		switch code {
		case 3010:
			return ErrRebootRequired
		case 5, 740:
			return ErrWSLPermission
		}
	}
	return nil
}

func (a wslInstallAttempt) summary() string {
	command := describeCommand(a.name, a.commandErr, a.commandCtxErr)
	if a.ready {
		return command + "; runtime is ready"
	}
	return command + "; runtime recheck: " + describeCommand("WSL probe", a.probeErr, nil)
}

func commandExitCode(err error) (int, bool) {
	var exitErr interface{ ExitCode() int }
	if !errors.As(err, &exitErr) {
		return 0, false
	}
	return exitErr.ExitCode(), true
}

func describeCommand(name string, err, ctxErr error) string {
	if ctxErr != nil {
		return fmt.Sprintf("%s: %v", name, ctxErr)
	}
	if err == nil {
		return name + ": completed"
	}
	if code, ok := commandExitCode(err); ok {
		return fmt.Sprintf("%s: exit code %d", name, code)
	}
	return fmt.Sprintf("%s: %v", name, err)
}

func queryWSLFeatureStates(ctx context.Context, i *installer, timeout time.Duration) (map[string]wslFeatureState, error) {
	queryCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	const script = `$ErrorActionPreference = 'Stop'; $names = @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform'); foreach ($name in $names) { $feature = Get-WindowsOptionalFeature -Online -FeatureName $name -ErrorAction Stop; if ($null -eq $feature) { throw 'Feature query returned no object' }; [Console]::WriteLine(('{0}={1}' -f $name, $feature.State.ToString())) }`
	output, err := i.runDiagOutput(queryCtx, sysExe("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", script)
	if err != nil {
		return nil, err
	}
	states := make(map[string]wslFeatureState, len(wslFeatures))
	for _, line := range strings.Split(string(output), "\n") {
		name, value, ok := strings.Cut(strings.TrimSpace(line), "=")
		if !ok {
			continue
		}
		state := parseWSLFeatureState(value)
		if state == wslFeatureUnknown {
			return nil, fmt.Errorf("unrecognized state for Windows feature %q", name)
		}
		states[name] = state
	}
	for _, name := range wslFeatures {
		if _, ok := states[name]; !ok {
			return nil, fmt.Errorf("Windows feature query omitted %q", name)
		}
	}
	return states, nil
}

func parseWSLFeatureState(value string) wslFeatureState {
	normalized := strings.ToLower(strings.NewReplacer(" ", "", "_", "", "-", "").Replace(strings.TrimSpace(value)))
	switch normalized {
	case "enabled":
		return wslFeatureEnabled
	case "disabled", "disabledwithpayloadremoved", "notpresent", "removed", "staged":
		return wslFeatureDisabled
	case "enablepending", "installpending":
		return wslFeatureEnablePending
	default:
		return wslFeatureUnknown
	}
}

func hasFeatureState(states map[string]wslFeatureState, wanted wslFeatureState) bool {
	for _, name := range wslFeatures {
		if states[name] == wanted {
			return true
		}
	}
	return false
}

func finishWSLInstallFailure(ctx context.Context, i *installer, policy wslPolicy, defaultAttempt wslInstallAttempt, webAttempt *wslInstallAttempt) error {
	webSummary := "not available"
	if webAttempt != nil {
		webSummary = webAttempt.summary()
	}
	states, queryErr := queryWSLFeatureStates(ctx, i, policy.commandTimeout)
	if queryErr != nil {
		return wslSetupError(ErrWSLInstallFailed, "WSL runtime remained unavailable; Windows feature state could not be confirmed", defaultAttempt.summary(), webSummary+"; feature query: "+queryErr.Error())
	}
	if hasFeatureState(states, wslFeatureEnablePending) {
		return fmt.Errorf("%w: WSL Windows features are pending; restart Windows and run Setup again", ErrRebootRequired)
	}

	missing := missingWSLFeatures(states)
	if len(missing) > 0 {
		i.printf("WSL installation failed and Windows reports disabled WSL features; enabling only confirmed disabled features with DISM\n")
		rebootRequired, err := enableMissingWSLFeatures(ctx, i, policy, missing)
		if err != nil {
			if errors.Is(err, context.Canceled) {
				return err
			}
			if errors.Is(err, context.DeadlineExceeded) {
				return wslSetupError(ErrWSLTimeout, "enabling confirmed missing Windows features timed out", defaultAttempt.summary(), webSummary+"; DISM: "+err.Error())
			}
			if errors.Is(err, ErrWSLPermission) {
				return wslSetupError(ErrWSLPermission, "could not enable confirmed missing Windows features", defaultAttempt.summary(), webSummary+"; DISM: "+err.Error())
			}
			return wslSetupError(ErrWSLInstallFailed, "could not enable confirmed missing Windows features", defaultAttempt.summary(), webSummary+"; DISM: "+err.Error())
		}
		if rebootRequired {
			return fmt.Errorf("%w: WSL Windows features were enabled and require a restart; run Setup again after restarting Windows", ErrRebootRequired)
		}

		states, queryErr = queryWSLFeatureStates(ctx, i, policy.commandTimeout)
		if queryErr == nil && hasFeatureState(states, wslFeatureEnablePending) {
			return fmt.Errorf("%w: WSL Windows features are pending; restart Windows and run Setup again", ErrRebootRequired)
		}
		ready, probeErr := waitForWSLRuntime(ctx, i, policy)
		if ready {
			return nil
		}
		if probeErr != nil {
			i.printf("WSL runtime remains unavailable after enabling confirmed features: %v\n", probeErr)
		}
	}
	return wslSetupError(ErrWSLInstallFailed, "WSL runtime remained unavailable after the available online paths", defaultAttempt.summary(), webSummary)
}

func dismEnable(ctx context.Context, i *installer, feature string) error {
	err := i.run(ctx, sysExe("dism.exe"), "/online", "/enable-feature", "/featurename:"+feature, "/all", "/norestart")
	if err == nil {
		return nil
	}
	if code, ok := commandExitCode(err); ok {
		switch code {
		case 3010:
			return fmt.Errorf("%w: DISM enabled %s and requires a restart", ErrRebootRequired, feature)
		case 5, 740:
			return fmt.Errorf("%w: DISM exit code %d", ErrWSLPermission, code)
		}
	}
	return err
}

func wslSetupError(kind error, reason, defaultResult, webResult string) error {
	return fmt.Errorf("%w: %s\nDefault online installation: %s\nweb-download: %s\nFlashServer setup cannot continue. Check network connectivity and the Windows environment, then retry. See setup.log for details.", kind, reason, defaultResult, webResult)
}

func stopWSLAfterBlock(kind error, stage, defaultResult, webResult string) error {
	if errors.Is(kind, ErrRebootRequired) {
		return fmt.Errorf("%w: %s; default online result: %s; web-download result: %s", ErrRebootRequired, stage, defaultResult, webResult)
	}
	if errors.Is(kind, ErrWSLPermission) {
		return fmt.Errorf("%w: %s; default online result: %s; web-download result: %s; run Setup from an elevated account and retry", ErrWSLPermission, stage, defaultResult, webResult)
	}
	if errors.Is(kind, ErrWSLTimeout) {
		return wslSetupError(ErrWSLTimeout, stage+": runtime is not confirmed ready. No second installer was started. Wait for the timed-out installer and its child processes to exit; restart Windows if completion remains uncertain", defaultResult, webResult)
	}
	if errors.Is(kind, context.Canceled) {
		return fmt.Errorf("%w: user cancelled %s; no fallback installer started", context.Canceled, stage)
	}
	return kind
}
