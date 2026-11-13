//go:build !linux

package host

import "os"

func fileKeyFor(os.FileInfo) (fileKey, bool) {
	return fileKey{}, false
}

func allocatedBytes(info os.FileInfo) int64 {
	return info.Size()
}
