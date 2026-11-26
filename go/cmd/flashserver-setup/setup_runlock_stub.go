//go:build !windows

package main

func acquireSetupRunLock() (func(), error) {
	return func() {}, nil
}
