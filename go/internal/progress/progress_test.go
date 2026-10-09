package progress

import (
	"bytes"
	"strings"
	"testing"
)

func TestFormatBytes(t *testing.T) {
	cases := map[int64]string{
		512:                    "512 B",
		2048:                   "2.0 KiB",
		5 * 1024 * 1024:        "5.0 MiB",
		3 * 1024 * 1024 * 1024: "3.00 GiB",
	}
	for in, want := range cases {
		if got := FormatBytes(in); got != want {
			t.Fatalf("FormatBytes(%d) = %q want %q", in, got, want)
		}
	}
}

func TestStageAndQuiet(t *testing.T) {
	var buf bytes.Buffer
	oldOut, oldTTY := out, tty
	out, tty = &buf, false
	defer func() { out, tty = oldOut, oldTTY }()

	SetQuiet(false)
	defer SetQuiet(false)

	st := Start("weights", "repo/x")
	st.Totals(2, 100*1024*1024)
	st.Add(50 * 1024 * 1024)
	st.FileDone()
	st.Done()

	got := buf.String()
	if !strings.Contains(got, "▸ weights  repo/x") {
		t.Fatalf("missing header: %q", got)
	}
	if !strings.Contains(got, "✓ weights") {
		t.Fatalf("missing done line: %q", got)
	}

	buf.Reset()
	SetQuiet(true)
	Note("should be hidden")
	Start("x", "y").Done()
	if buf.Len() != 0 {
		t.Fatalf("quiet should suppress output, got %q", buf.String())
	}
}
