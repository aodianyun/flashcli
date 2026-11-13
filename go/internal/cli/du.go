package cli

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/host"
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
	fmt.Fprintf(out, "Disk usage (unique allocated) at %s:\n", paths.Home())
	var total int64
	for _, area := range host.Storage() {
		total += area.Bytes
		fmt.Fprintf(out, "  %-10s %s\n", area.Name, humanSize(area.Bytes))
	}
	fmt.Fprintf(out, "  %-10s %s\n", "total", humanSize(total))
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
