package apps

import (
	"fmt"
	"strings"
	"testing"
)

func setupManifest(script string) string {
	return fmt.Sprintf(`{
  "format": "flashcli-application",
  "app_format_version": 1,
  "protocol_version": 1,
  "name": "workbuddy",
  "version": "1.0.0",
  "supported": {"os": ["windows"], "arch": ["x86_64"]},
  "install": {"commands": {"windows": "https://example.com/app.exe"}},
  "model": {"bundles": [{"bundle": "xym/demo:1.0.0", "default": true}]},
  "setup": {"scripts": [%s]}
}`, script)
}

func TestSetupScriptValidation(t *testing.T) {
	valid := `{
      "key": "workbuddy",
      "kind": "python",
      "url": "https://example.com/setup.py",
      "sha256": "c3fed24df8cc3440e94091dbc8e31c1da8b355de1e3994388062f7270ea1f715",
      "args": ["{base_url}", "{model}", "--api-key {api_key}"]
    }`
	m, err := Parse([]byte(setupManifest(valid)))
	if err != nil {
		t.Fatal(err)
	}
	if len(m.Setup.Scripts) != 1 || m.Setup.Scripts[0].Key != "workbuddy" {
		t.Fatalf("setup = %+v", m.Setup)
	}

	cases := []struct {
		name   string
		script string
		want   string
	}{
		{
			name:   "bad hash",
			script: strings.Replace(valid, "c3fed24df8cc3440e94091dbc8e31c1da8b355de1e3994388062f7270ea1f715", "abc", 1),
			want:   "sha256",
		},
		{
			name:   "bad kind",
			script: strings.Replace(valid, `"python"`, `"powershell"`, 1),
			want:   "kind",
		},
		{
			name:   "http url",
			script: strings.Replace(valid, "https://example.com/setup.py", "http://example.com/setup.py", 1),
			want:   "https",
		},
		{
			name:   "unknown placeholder",
			script: strings.Replace(valid, "{model}", "{model_name}", 1),
			want:   "unknown placeholder",
		},
		{
			name:   "unterminated placeholder",
			script: strings.Replace(valid, "{model}", "{model", 1),
			want:   "unterminated",
		},
		{
			name:   "duplicate key",
			script: valid + `,` + valid,
			want:   "duplicated",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := Parse([]byte(setupManifest(tc.script)))
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error = %v, want substring %q", err, tc.want)
			}
		})
	}
}
