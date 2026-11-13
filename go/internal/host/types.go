package host

// PullEvent describes a pull phase for CLI/server progress sinks.
type PullEvent struct {
	Phase   string `json:"phase"`
	Message string `json:"message,omitempty"`
	Ref     string `json:"ref"`
}

// PullOptions controls a pull operation.
type PullOptions struct {
	Quiet         bool
	NoAutoInstall bool
	Progress      func(PullEvent)
}

// PullResult is the materialized bundle/checkpoint after a successful pull.
type PullResult struct {
	BundleRoot string
	Version    string
	Variant    string
	Checkpoint string
}
