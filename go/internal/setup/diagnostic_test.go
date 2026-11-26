package setup

import (
	"strings"
	"testing"
)

func TestRedactDiagnosticSecrets(t *testing.T) {
	input := "https://alice:secret@example.invalid/x Authorization: Bearer abc token=xyz password=hunter2"
	got := string(redactDiagnostic([]byte(input)))
	for _, secret := range []string{"alice:secret", "Bearer abc", "token=xyz", "password=hunter2"} {
		if strings.Contains(got, secret) {
			t.Errorf("diagnostic retained %q: %s", secret, got)
		}
	}
	for _, marker := range []string{"[REDACTED]"} {
		if !strings.Contains(got, marker) {
			t.Errorf("diagnostic missing redaction marker: %s", got)
		}
	}
}
