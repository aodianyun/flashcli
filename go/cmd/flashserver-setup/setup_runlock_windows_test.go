//go:build windows

package main

import (
	"errors"
	"testing"
)

func TestSetupRunLockRejectsConcurrentInstance(t *testing.T) {
	release, err := acquireSetupRunLock()
	if err != nil {
		t.Fatalf("acquire first setup lock: %v", err)
	}
	defer release()

	result := make(chan error, 1)
	go func() {
		_, err := acquireSetupRunLock()
		result <- err
	}()
	if err := <-result; !errors.Is(err, ErrSetupAlreadyRunning) {
		t.Fatalf("second setup lock error=%v, want ErrSetupAlreadyRunning", err)
	}
}
