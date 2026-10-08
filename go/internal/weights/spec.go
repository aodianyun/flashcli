package weights

import "strings"

// Spec is a parsed “weights“ / “extra_weights“ block.
type Spec struct {
	Source             string
	Repo               string
	Revision           string
	AllowPatterns      []string
	RequireAnyPatterns []string
	RequireNormStats   bool
	CheckpointSubdir   string
	CacheName          string
	Endpoint           string
	RelativeDir        string
	URL                string
	Raw                map[string]any
}

// SpecFromMap parses a manifest weights block.
func SpecFromMap(m map[string]any) Spec {
	s := Spec{Raw: m}
	s.Source = strings.ToLower(orDefault(str(m["source"]), "huggingface"))
	s.Repo = strings.TrimSpace(str(m["repo"]))
	s.Revision = strings.TrimSpace(str(m["revision"]))
	s.AllowPatterns = strSlice(m["allow_patterns"])
	s.RequireAnyPatterns = strSlice(m["require_any_patterns"])
	s.CheckpointSubdir = strings.Trim(strings.TrimSpace(str(m["checkpoint_subdir"])), "/")
	s.CacheName = strings.TrimSpace(str(m["cache_name"]))
	s.Endpoint = strings.TrimRight(strings.TrimSpace(str(m["endpoint"])), "/")
	s.RelativeDir = strings.TrimSpace(str(m["relative_dir"]))
	s.URL = strings.TrimSpace(str(m["url"]))
	s.RequireNormStats = WeightsRequireNormStats(m)
	return s
}

// WeightsRequireNormStats mirrors Python weights_require_norm_stats.
func WeightsRequireNormStats(m map[string]any) bool {
	if m == nil {
		return false
	}
	if v, ok := m["require_norm_stats"].(bool); ok {
		return v
	}
	repo := strings.ToLower(str(m["repo"]))
	for _, token := range []string{"pi05", "pi0_libero", "pi0_"} {
		if strings.Contains(repo, token) {
			return true
		}
	}
	return false
}

func str(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	default:
		return ""
	}
}

func orDefault(v, fallback string) string {
	if strings.TrimSpace(v) == "" {
		return fallback
	}
	return v
}

func strSlice(v any) []string {
	list, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(list))
	for _, item := range list {
		if s, ok := item.(string); ok && s != "" {
			out = append(out, s)
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}
