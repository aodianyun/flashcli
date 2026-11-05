package gpu

import "testing"

func TestParse(t *testing.T) {
	devices, err := Parse("0, NVIDIA GeForce RTX 5060 Ti, 16376, 1000, 15376\n")
	if err != nil {
		t.Fatal(err)
	}
	if len(devices) != 1 || devices[0].Index != 0 || devices[0].MemoryTotal != 16376*1024*1024 {
		t.Fatalf("devices=%+v", devices)
	}
}

func TestParseBad(t *testing.T) {
	if _, err := Parse("0,bad"); err == nil {
		t.Fatal("expected error")
	}
}
