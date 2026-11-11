package cli

import (
	"bufio"
	"fmt"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/host"
)

// confirmCleanup prints the exact paths that will be removed and asks for
// confirmation. --yes skips the prompt; non-interactive runs must pass it.
func confirmCleanup(cmd *cobra.Command, paths []string, yes bool) ([]string, error) {
	out := cmd.OutOrStdout()
	paths = existingPaths(paths)
	if len(paths) == 0 {
		fmt.Fprintln(out, "No matching cache entries to remove.")
		return nil, nil
	}
	fmt.Fprintf(out, "Will remove %d path(s):\n", len(paths))
	for _, p := range paths {
		fmt.Fprintf(out, "  %s\n", p)
	}
	if yes {
		return paths, nil
	}
	fmt.Fprint(out, "Continue? [y/N]: ")
	line, err := bufio.NewReader(cmd.InOrStdin()).ReadString('\n')
	if err != nil && line == "" {
		fmt.Fprintln(out, "Aborted (confirmation required; use --yes).")
		return nil, ErrFailed
	}
	switch strings.ToLower(strings.TrimSpace(line)) {
	case "y", "yes":
		return paths, nil
	default:
		fmt.Fprintln(out, "Aborted.")
		return nil, nil
	}
}

func existingPaths(paths []string) []string {
	out := host.ExistingPaths(paths)
	sort.Strings(out)
	return out
}

func removePaths(cmd *cobra.Command, paths []string) error {
	if len(paths) == 0 {
		return nil
	}
	if _, err := host.RemovePaths(paths); err != nil {
		return failed(cmd, err)
	}
	for _, p := range paths {
		fmt.Fprintf(cmd.OutOrStdout(), "Removed %s\n", p)
	}
	return nil
}
