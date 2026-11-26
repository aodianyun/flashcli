//go:build windows

package main

import (
	"errors"
	"fmt"
	"runtime"
	"sync"
	"syscall"
	"unsafe"
)

const (
	waitObject0   = 0x00000000
	waitAbandoned = 0x00000080
	waitTimeout   = 0x00000102
	waitFailed    = 0xFFFFFFFF
)

var (
	kernel32SetupLock        = syscall.NewLazyDLL("kernel32.dll")
	createMutexWSetupLock    = kernel32SetupLock.NewProc("CreateMutexW")
	waitForSingleObjectSetup = kernel32SetupLock.NewProc("WaitForSingleObject")
	releaseMutexSetupLock    = kernel32SetupLock.NewProc("ReleaseMutex")
)

func acquireSetupRunLock() (func(), error) {
	// Windows mutex ownership belongs to the OS thread. Keep acquisition and
	// ReleaseMutex on the same thread for the lifetime of this setup run.
	runtime.LockOSThread()
	name, err := syscall.UTF16PtrFromString(`Local\flashcli-desktop-setup-run`)
	if err != nil {
		runtime.UnlockOSThread()
		return nil, err
	}
	handle, _, callErr := createMutexWSetupLock.Call(0, 0, uintptr(unsafe.Pointer(name)))
	if handle == 0 {
		runtime.UnlockOSThread()
		return nil, win32CallError("create setup mutex", callErr)
	}

	result, _, waitErr := waitForSingleObjectSetup.Call(handle, 0)
	switch result {
	case waitObject0, waitAbandoned:
		var once sync.Once
		return func() {
			once.Do(func() {
				_, _, _ = releaseMutexSetupLock.Call(handle)
				_ = syscall.CloseHandle(syscall.Handle(handle))
				runtime.UnlockOSThread()
			})
		}, nil
	case waitTimeout:
		_ = syscall.CloseHandle(syscall.Handle(handle))
		runtime.UnlockOSThread()
		return nil, ErrSetupAlreadyRunning
	case waitFailed:
		_ = syscall.CloseHandle(syscall.Handle(handle))
		runtime.UnlockOSThread()
		return nil, win32CallError("wait for setup mutex", waitErr)
	default:
		_ = syscall.CloseHandle(syscall.Handle(handle))
		runtime.UnlockOSThread()
		return nil, fmt.Errorf("wait for setup mutex returned unexpected result 0x%x", result)
	}
}

func win32CallError(operation string, err error) error {
	if err == nil || errors.Is(err, syscall.Errno(0)) {
		return fmt.Errorf("%s failed", operation)
	}
	return fmt.Errorf("%s: %w", operation, err)
}
