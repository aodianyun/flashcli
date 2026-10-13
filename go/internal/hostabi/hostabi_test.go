package hostabi

import "testing"

func TestParseVersionText(t *testing.T) {
	req := ParseVersionText("Version needs section '.gnu.version_r':\n  GLIBC_2.2.5\n  GLIBC_2.34\n  GLIBCXX_3.4.21\n  GLIBCXX_3.4.30\n  CXXABI_1.3.13\n")
	if req.Glibc != "2.34" || req.Glibcxx != "3.4.30" || req.Cxxabi != "1.3.13" {
		t.Fatalf("unexpected requirements: %+v", req)
	}
}

func TestVersionAtLeast(t *testing.T) {
	if !VersionAtLeast("2.35", "2.34") {
		t.Fatal("2.35 should satisfy 2.34")
	}
	if VersionAtLeast("2.31", "2.34") {
		t.Fatal("2.31 should not satisfy 2.34")
	}
	if !VersionAtLeast("3.4.30", "3.4.30") {
		t.Fatal("equal should satisfy")
	}
}

func TestCheckSkipsWhenDisabled(t *testing.T) {
	t.Setenv("FLASHCLI_SKIP_NATIVE_HOST_ABI", "1")
	if errs := Check([]string{"/no/such/lib.so"}, true); errs != nil {
		t.Fatalf("expected skip, got %v", errs)
	}
}
