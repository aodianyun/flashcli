package cli

import (
	"fmt"
	"io/fs"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/paths"
)

func duCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "du",
		Short: "Show disk usage for bundles, models, runtimes, and caches",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			printDiskUsage(cmd.OutOrStdout())
			return nil
		},
	}
}

func printDiskUsage(out interface{ Write([]byte) (int, error) }) {
	items := []struct {
		name string
		path string
	}{
		{"bundles", paths.Bundles()},
		{"models", paths.Models()},
		{"runtimes", paths.Runtimes()},
		{"cache", filepath.Join(paths.Home(), "cache")},
		{"tools", filepath.Join(paths.Home(), "tools")},
		{"python", filepath.Join(paths.Home(), "python")},
	}
	fmt.Fprintf(out, "Disk usage (apparent size) at %s:\n", paths.Home())
	var total int64
	for _, item := range items {
		size := dirSize(item.path)
		total += size
		fmt.Fprintf(out, "  %-10s %s\n", item.name, humanSize(size))
	}
	fmt.Fprintf(out, "  %-10s %s\n", "total", humanSize(total))
}

func dirSize(root string) int64 {
	var total int64
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return nil
		}
		if info, err := d.Info(); err == nil {
			total += info.Size()
		}
		return nil
	})
	return total
}

func humanSize(n int64) string {
	const unit = 1024
	if n < unit {
		return fmt.Sprintf("%d B", n)
	}
	div, exp := int64(unit), 0
	for v := n / unit; v >= unit; v /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %ciB", float64(n)/float64(div), "KMGTPE"[exp])
}
