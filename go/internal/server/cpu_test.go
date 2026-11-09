package server

import "testing"

func TestCPUUsageBetween(t *testing.T) {
	prev := []cpuCounters{
		{total: 100, idle: 50},
		{total: 100, idle: 50},
		{total: 100, idle: 50},
	}
	cur := []cpuCounters{
		{total: 200, idle: 75},
		{total: 200, idle: 50},
		{total: 200, idle: 100},
	}
	overall, cores := cpuUsageBetween(prev, cur)
	if overall != 75 {
		t.Fatalf("overall = %v", overall)
	}
	if len(cores) != 2 || cores[0] != 100 || cores[1] != 50 {
		t.Fatalf("cores = %v", cores)
	}
}

func TestCPUUsageBetweenMismatch(t *testing.T) {
	overall, cores := cpuUsageBetween([]cpuCounters{{total: 1, idle: 0}}, []cpuCounters{{total: 2, idle: 1}, {total: 2, idle: 1}})
	if overall != 0 || cores != nil {
		t.Fatalf("want zero/nil, got %v/%v", overall, cores)
	}
}
