package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestCancelFileStopsSetupContext(t *testing.T) {
	path := filepath.Join(t.TempDir(), "cancel.txt")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stop := watchCancelFile(path, cancel)
	defer stop()
	if err := os.WriteFile(path, []byte("cancel"), 0600); err != nil {
		t.Fatal(err)
	}
	select {
	case <-ctx.Done():
	case <-time.After(2 * time.Second):
		t.Fatal("cancel file was not observed")
	}
}
