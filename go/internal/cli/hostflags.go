package cli

import "strings"

// hostFlags are the host-only run/serve flags (peeled before the bundle sees them).
type hostFlags struct {
	Ref           string
	Checkpoint    string
	MTPCheckpoint string
	Quiet         bool
	NoAutoInstall bool
	WantsHelp     bool
}

// peelHostFlags extracts host-only flags from run/serve argv. The ref is the
// first non-flag argument. Mirrors src/flashcli/bundle/run_argv.py.
func peelHostFlags(args []string) hostFlags {
	var hf hostFlags
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--checkpoint":
			if i+1 < len(args) {
				hf.Checkpoint = args[i+1]
				i++
			}
		case strings.HasPrefix(a, "--checkpoint="):
			hf.Checkpoint = strings.TrimPrefix(a, "--checkpoint=")
		case a == "--mtp-checkpoint":
			if i+1 < len(args) {
				hf.MTPCheckpoint = args[i+1]
				i++
			}
		case strings.HasPrefix(a, "--mtp-checkpoint="):
			hf.MTPCheckpoint = strings.TrimPrefix(a, "--mtp-checkpoint=")
		case a == "--quiet" || a == "-q":
			hf.Quiet = true
		case a == "--no-auto-install":
			hf.NoAutoInstall = true
		case a == "-h" || a == "--help":
			hf.WantsHelp = true
		case !strings.HasPrefix(a, "-") && hf.Ref == "":
			hf.Ref = a
		}
	}
	return hf
}

// hostFlagNames are host flags that must not be forwarded as bundle options.
var hostFlagNames = map[string]bool{
	"--checkpoint": true, "--mtp-checkpoint": true, "--quiet": true, "-q": true,
	"--no-auto-install": true, "-h": true, "--help": true,
}
