package apps

import (
	"context"

	"github.com/aodianyun/flashcli/go/internal/flashhub"
)

// FetchManifest downloads and validates an application manifest.
func FetchManifest(ctx context.Context, ref flashhub.AppRef) (*Manifest, []byte, error) {
	raw, err := flashhub.NewClient().FetchAppManifest(ctx, ref)
	if err != nil {
		return nil, nil, err
	}
	m, err := Parse(raw)
	if err != nil {
		return nil, nil, err
	}
	return m, raw, nil
}
