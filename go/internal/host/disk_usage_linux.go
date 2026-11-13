//go:build linux

package host

import (
	"os"
	"syscall"
)

func fileKeyFor(info os.FileInfo) (fileKey, bool) {
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return fileKey{}, false
	}
	return fileKey{dev: uint64(st.Dev), ino: uint64(st.Ino)}, true
}

func allocatedBytes(info os.FileInfo) int64 {
	if st, ok := info.Sys().(*syscall.Stat_t); ok {
		return int64(st.Blocks) * 512
	}
	return info.Size()
}
