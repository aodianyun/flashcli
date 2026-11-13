package progress

import (
	"bytes"
	"context"
	"strings"
	"testing"
)

func TestSinkUpdates(t *testing.T) {
	SetQuiet(true)
	defer SetQuiet(false)

	var updates []Update
	ctx := WithSink(context.Background(), func(u Update) {
		updates = append(updates, u)
	})
	st := StartWithSink("weights", "repo/x", SinkFromContext(ctx))
	st.Totals(2, 100)
	st.Add(50)
	st.FileDone()
	st.Add(50)
	st.FileDone()
	st.Done()

	if len(updates) < 3 {
		t.Fatalf("updates=%v", updates)
	}
	if updates[0].Total != 100 || updates[0].Stage != "weights" {
		t.Fatalf("first update = %+v", updates[0])
	}
	last := updates[len(updates)-1]
	if last.Percent != 100 || !last.Done {
		t.Fatalf("last update = %+v", last)
	}
}

func TestNoteCtxSink(t *testing.T) {
	SetQuiet(true)
	defer SetQuiet(false)

	var got string
	ctx := WithSink(context.Background(), func(u Update) {
		got = u.Detail
	})
	NoteCtx(ctx, "venv: installing torch %s", "cu130")
	if !strings.Contains(got, "installing torch") {
		t.Fatalf("note sink = %q", got)
	}
}

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
