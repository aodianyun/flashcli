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
	// VerifyWeights re-lists the remote weights even when the local download
	// manifest is complete (explicit `flashcli pull`). App installs leave it
	// false so an already cached model is used without touching the network.
	VerifyWeights bool
	// Force re-downloads the bundle tree/manifest even when the cache marker is
	// present (model-page 重新同步 for an in-place content refresh).
	Force    bool
	Progress func(PullEvent)
}

// PullResult is the materialized bundle/checkpoint after a successful pull.
type PullResult struct {
	BundleRoot string
	Version    string
	Variant    string
	Checkpoint string
}
