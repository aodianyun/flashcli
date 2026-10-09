package errs

import (
	"errors"
	"strings"
	"testing"
)

func TestEnvironmentErrors(t *testing.T) {
	for _, err := range []error{Envf("missing %s", "gpu"), EnvWrapf("bad %d", 7)} {
		if !errors.Is(err, Environment) {
			t.Fatalf("%v is not an Environment error", err)
		}
	}
	if !strings.Contains(Envf("missing %s", "gpu").Error(), "missing gpu") {
		t.Fatal("Envf should format the message")
	}
	if !strings.Contains(EnvWrapf("bad %d", 7).Error(), "bad 7") {
		t.Fatal("EnvWrapf should format the message")
	}
}
