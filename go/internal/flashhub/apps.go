package flashhub

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// AppsBase is the FlashHub application API base (…/api/v1/apps), derived from
// the repos API base.
func AppsBase() string {
	base := strings.TrimRight(APIBase(), "/")
	base = strings.TrimSuffix(base, "/repos")
	return base + "/apps"
}

// AppRef is a FlashHub application reference: [namespace/]name[:version].
type AppRef struct {
	Org     string
	Name    string
	Version string
}

func (r AppRef) String() string {
	s := r.Name
	if r.Org != "" {
		s = r.Org + "/" + s
	}
	if r.Version != "" {
		s += ":" + r.Version
	}
	return s
}

// ParseAppRef parses [namespace/]name[:version].
func ParseAppRef(raw string) (AppRef, error) {
	s := strings.TrimSpace(raw)
	if s == "" {
		return AppRef{}, fmt.Errorf("empty application ref")
	}
	ref := AppRef{}
	if i := strings.LastIndex(s, ":"); i > 0 {
		ref.Version = strings.TrimSpace(s[i+1:])
		s = s[:i]
	}
	parts := strings.Split(strings.Trim(s, "/"), "/")
	switch len(parts) {
	case 1:
		ref.Name = parts[0]
	case 2:
		ref.Org, ref.Name = parts[0], parts[1]
	default:
		return AppRef{}, fmt.Errorf("invalid application ref %q (expected [namespace/]name[:version])", raw)
	}
	if ref.Name == "" || ref.Org == "" {
		return AppRef{}, fmt.Errorf("application ref %q needs a namespace (e.g. xym/workbuddy)", raw)
	}
	return ref, nil
}

// appEnvelope is the FlashHub API response wrapper.
type appEnvelope struct {
	Code    *int            `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data"`
}

// FetchAppManifest downloads the application manifest for ref.
func (c *Client) FetchAppManifest(ctx context.Context, ref AppRef) ([]byte, error) {
	if ref.Org == "" || ref.Name == "" {
		return nil, fmt.Errorf("application %q needs a namespace (e.g. xym/workbuddy)", ref.String())
	}
	path := ref.Org + "/" + ref.Name
	if ref.Version != "" {
		path += ":" + ref.Version
	}
	blob, err := c.get(ctx, AppsBase()+"/"+path)
	if err != nil {
		return nil, err
	}
	var env appEnvelope
	if err := json.Unmarshal(blob, &env); err != nil {
		return nil, fmt.Errorf("FlashHub application response is not JSON: %w", err)
	}
	if env.Code != nil && *env.Code != 0 {
		return nil, fmt.Errorf("FlashHub application error (code=%d): %s", *env.Code, env.Message)
	}
	if len(env.Data) == 0 {
		return nil, fmt.Errorf("FlashHub returned no manifest for %q", ref.String())
	}
	return env.Data, nil
}
