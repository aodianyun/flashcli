//go:build !windows

package main

func ensureElevated() bool { return false }
