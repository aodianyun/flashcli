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

func TestParseTelemetry(t *testing.T) {
	line := "0, NVIDIA GeForce RTX 4060, 8188, 1000, 7188, 27, 12, 55, 40.5, 115.0, 30, 2100, 7001, 591.86, On, Default\n"
	devices, err := Parse(line)
	if err != nil {
		t.Fatal(err)
	}
	if len(devices) != 1 {
		t.Fatalf("devices=%+v", devices)
	}
	d := devices[0]
	if d.UtilizationGPU == nil || *d.UtilizationGPU != 27 {
		t.Fatalf("util = %v", d.UtilizationGPU)
	}
	if d.TemperatureC == nil || *d.TemperatureC != 55 {
		t.Fatalf("temp = %v", d.TemperatureC)
	}
	if d.PowerDrawW == nil || *d.PowerDrawW != 40.5 {
		t.Fatalf("power = %v", d.PowerDrawW)
	}
	if d.DriverVersion != "591.86" || d.PersistenceMode != "On" {
		t.Fatalf("driver/persistence = %q/%q", d.DriverVersion, d.PersistenceMode)
	}
}

func TestParseTelemetryUnavailable(t *testing.T) {
	line := "0, RTX 4060, 8188, 1000, 7188, N/A, N/A, N/A, [N/A], [N/A], [N/A], N/A, N/A, 591.86, N/A, N/A\n"
	devices, err := Parse(line)
	if err != nil {
		t.Fatal(err)
	}
	d := devices[0]
	if d.UtilizationGPU != nil || d.PowerDrawW != nil || d.FanSpeedPct != nil {
		t.Fatalf("expected nil telemetry, got %+v", d)
	}
	if d.DriverVersion != "591.86" {
		t.Fatalf("driver = %q", d.DriverVersion)
	}
}

func TestParseProcesses(t *testing.T) {
	procs := ParseProcesses("1234, python, 3072\nbad-line\n5678, /usr/bin/python3, N/A\n")
	if len(procs) != 1 {
		t.Fatalf("procs = %+v", procs)
	}
	if procs[0].PID != 1234 || procs[0].Name != "python" || procs[0].MemoryBytes != 3072*1024*1024 {
		t.Fatalf("proc = %+v", procs[0])
	}
}
