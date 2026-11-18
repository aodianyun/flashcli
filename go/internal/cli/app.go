package cli

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"runtime"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/apps"
	"github.com/aodianyun/flashcli/go/internal/flashhub"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
	"github.com/aodianyun/flashcli/go/internal/paths"
)

func appCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "app",
		Short: "FlashHub application utilities",
	}
	cmd.AddCommand(
		appListCmd(), appShowCmd(), appInstallCmd(), appStatusCmd(),
		appStartCmd(), appStopCmd(), appRestartCmd(), appLogsCmd(), appUninstallCmd(),
	)
	return cmd
}

func newAppService(cmd *cobra.Command) *apps.Service {
	svc := apps.New(paths.Home())
	svc.Out = cmd.OutOrStdout()
	svc.Stdin = os.Stdin
	svc.Bin = strings.TrimSpace(os.Getenv("FLASHCLI_BIN"))
	svc.ConfirmSetup = func(script apps.SetupScript) bool {
		fmt.Fprintf(cmd.OutOrStdout(), "Setup script %s: %s\n", script.Key, script.URL)
		fmt.Fprintf(cmd.OutOrStdout(), "Execute it now? [y/N]: ")
		return readYes(cmd)
	}
	return svc
}

func appListCmd() *cobra.Command {
	var (
		asJSON   bool
		search   string
		domain   string
		page     int
		pageSize int
	)
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List FlashHub applications",
		RunE: func(cmd *cobra.Command, _ []string) error {
			list, total, err := flashhub.NewClient().ListApps(cmd.Context(), search, domain, page, pageSize)
			if err != nil {
				return failed(cmd, err)
			}
			if asJSON {
				blob, _ := json.MarshalIndent(map[string]any{"apps": list, "total": total}, "", "  ")
				fmt.Fprintln(cmd.OutOrStdout(), string(blob))
				return nil
			}
			out := cmd.OutOrStdout()
			fmt.Fprintf(out, "%-24s %-10s %-12s %-12s %s\n", "APP", "VERSION", "DOMAIN", "ORG", "BUNDLES")
			for _, a := range list {
				fmt.Fprintf(out, "%-24s %-10s %-12s %-12s %d\n",
					truncate(a.DisplayName, 24), a.Version, truncate(a.Domain, 12),
					truncate(a.Organization.Name, 12), len(a.ModelBundles))
			}
			fmt.Fprintf(out, "\n%d app(s), total %d\n", len(list), total)
			return nil
		},
	}
	cmd.Flags().BoolVar(&asJSON, "json", false, "Emit machine-readable JSON")
	cmd.Flags().StringVar(&search, "search", "", "Search by name")
	cmd.Flags().StringVar(&domain, "domain", "", "Filter by domain")
	cmd.Flags().IntVar(&page, "page", 1, "Page number")
	cmd.Flags().IntVar(&pageSize, "page-size", 20, "Page size")
	return cmd
}

func appShowCmd() *cobra.Command {
	var asJSON bool
	cmd := &cobra.Command{
		Use:   "show <namespace/name[:version]>",
		Short: "Show a FlashHub application manifest",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ref, err := flashhub.ParseAppRef(args[0])
			if err != nil {
				return failed(cmd, err)
			}
			m, raw, err := apps.FetchManifest(cmd.Context(), ref)
			if err != nil {
				return failed(cmd, err)
			}
			if asJSON {
				_, _ = cmd.OutOrStdout().Write(raw)
				fmt.Fprintln(cmd.OutOrStdout())
				return nil
			}
			out := cmd.OutOrStdout()
			fmt.Fprintf(out, "%s %s (%s)\n", m.DisplayName, m.Version, m.Name)
			fmt.Fprintf(out, "supported: %s / %s\n", strings.Join(m.Supported.OS, ","), strings.Join(m.Supported.Arch, ","))
			if key, command, ok := apps.PlatformCommand(m, runtime.GOOS, runtime.GOARCH); ok {
				kind := "command"
				if apps.IsURL(command) {
					kind = "download"
				}
				fmt.Fprintf(out, "install (%s): %s  [%s]\n", key, command, kind)
			} else {
				fmt.Fprintf(out, "install: no command for %s/%s\n", runtime.GOOS, runtime.GOARCH)
			}
			fmt.Fprintf(out, "bundles (%d):\n", len(m.Model.Bundles))
			for _, b := range m.Model.Bundles {
				mark := ""
				if b.Default {
					mark = "  (default)"
				}
				fmt.Fprintf(out, "  - %s%s\n", b.Bundle, mark)
			}
			return nil
		},
	}
	cmd.Flags().BoolVar(&asJSON, "json", false, "Print the raw manifest JSON")
	return cmd
}

func appInstallCmd() *cobra.Command {
	var opts apps.InstallOptions
	cmd := &cobra.Command{
		Use:   "install <namespace/name[:version]>",
		Short: "Install a FlashHub application and prepare its models",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			svc := newAppService(cmd)
			opts.Confirm = func(string) bool {
				fmt.Fprintf(cmd.OutOrStdout(), "\nRun this command? [y/N]: ")
				return readYes(cmd)
			}
			res, err := svc.Install(cmd.Context(), args[0], opts)
			if err != nil {
				return failed(cmd, err)
			}
			if opts.DryRun {
				return nil
			}
			out := cmd.OutOrStdout()
			if res.AlreadyReady {
				fmt.Fprintf(out, "%s %s is already installed (state: %s).\n", res.State.Key, res.State.Version, res.State.State)
			}
			return nil
		},
	}
	f := cmd.Flags()
	f.BoolVarP(&opts.Yes, "yes", "y", false, "Run install commands without asking")
	f.BoolVar(&opts.DryRun, "dry-run", false, "Print the plan without changing anything")
	f.BoolVar(&opts.Force, "force", false, "Re-run the install command and refresh models")
	f.BoolVar(&opts.NoInstall, "no-install", false, "Skip the application install command")
	f.BoolVar(&opts.NoModel, "no-model", false, "Skip preparing the model bundles")
	f.StringArrayVar(&opts.Bundles, "bundle", nil, "Override the default bundles (repeatable)")
	return cmd
}

func appStatusCmd() *cobra.Command {
	var asJSON bool
	cmd := &cobra.Command{
		Use:   "status <namespace/name[:version]>",
		Short: "Show the local state of an installed application",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ref, err := flashhub.ParseAppRef(args[0])
			if err != nil {
				return failed(cmd, err)
			}
			svc := newAppService(cmd)
			key, err := svc.ResolveKey(ref)
			if err != nil {
				return failed(cmd, err)
			}
			st, err := svc.Status(cmd.Context(), key)
			if err != nil {
				return failed(cmd, err)
			}
			if asJSON {
				blob, _ := json.MarshalIndent(st, "", "  ")
				fmt.Fprintln(cmd.OutOrStdout(), string(blob))
				return nil
			}
			out := cmd.OutOrStdout()
			fmt.Fprintf(out, "%s  %s\n", st.Key, st.State)
			if st.Version != "" {
				fmt.Fprintf(out, "version:   %s\n", st.Version)
			}
			if st.InstalledAt != "" {
				fmt.Fprintf(out, "installed: %s\n", st.InstalledAt)
			}
			if st.Install.Executed {
				fmt.Fprintf(out, "install:   %s\n", st.Install.Command)
			} else if st.Install.Skipped {
				fmt.Fprintln(out, "install:   skipped (run the command manually)")
			}
			for _, m := range st.Models {
				state := "prepared"
				if m.PID > 0 {
					state = "running"
				}
				fmt.Fprintf(out, "model:     %-24s %-8s %s\n", m.ID, state, m.Endpoint)
			}
			if st.Error != "" {
				fmt.Fprintf(out, "error:     %s\n", st.Error)
			}
			return nil
		},
	}
	cmd.Flags().BoolVar(&asJSON, "json", false, "Emit machine-readable JSON")
	return cmd
}

func appStartCmd() *cobra.Command {
	var keepPartial bool
	cmd := &cobra.Command{
		Use:   "start <namespace/name[:version]>",
		Short: "Start an installed application's models",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return withAppKey(cmd, args[0], func(svc *apps.Service, key string) error {
				st, err := svc.Start(cmd.Context(), key, keepPartial)
				if err != nil {
					return failed(cmd, err)
				}
				fmt.Fprintf(cmd.OutOrStdout(), "%s started (%d models)\n", st.Key, len(st.Models))
				return nil
			})
		},
	}
	cmd.Flags().BoolVar(&keepPartial, "keep-partial", false, "Keep models started before a failure")
	return cmd
}

func appStopCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stop <namespace/name[:version]>",
		Short: "Stop an installed application's models",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return withAppKey(cmd, args[0], func(svc *apps.Service, key string) error {
				st, err := svc.Stop(cmd.Context(), key)
				if err != nil {
					return failed(cmd, err)
				}
				fmt.Fprintf(cmd.OutOrStdout(), "%s stopped\n", st.Key)
				return nil
			})
		},
	}
	return cmd
}

func appRestartCmd() *cobra.Command {
	var keepPartial bool
	cmd := &cobra.Command{
		Use:   "restart <namespace/name[:version]>",
		Short: "Restart an installed application's models",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return withAppKey(cmd, args[0], func(svc *apps.Service, key string) error {
				if _, err := svc.Stop(cmd.Context(), key); err != nil {
					return failed(cmd, err)
				}
				st, err := svc.Start(cmd.Context(), key, keepPartial)
				if err != nil {
					return failed(cmd, err)
				}
				fmt.Fprintf(cmd.OutOrStdout(), "%s restarted (%d models)\n", st.Key, len(st.Models))
				return nil
			})
		},
	}
	cmd.Flags().BoolVar(&keepPartial, "keep-partial", false, "Keep models started before a failure")
	return cmd
}

func appLogsCmd() *cobra.Command {
	var (
		ref    string
		lines  int
		follow bool
	)
	cmd := &cobra.Command{
		Use:   "logs <namespace/name[:version]>",
		Short: "Show an application's model logs",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return withAppKey(cmd, args[0], func(svc *apps.Service, key string) error {
				st, _, err := svc.Registry.Get(key)
				if err != nil {
					return failed(cmd, err)
				}
				out := cmd.OutOrStdout()
				for _, m := range st.Models {
					if ref != "" && m.Ref != ref {
						continue
					}
					fmt.Fprintf(out, "== %s (%s)\n", m.ID, m.Ref)
					path := svc.ModelLogPath(m.Ref)
					if err := tailFileTo(out, path, lines); err != nil {
						fmt.Fprintf(out, "  (no log: %v)\n", err)
					}
				}
				if follow {
					for {
						select {
						case <-cmd.Context().Done():
							return nil
						case <-time.After(time.Second):
						}
						for _, m := range st.Models {
							if ref != "" && m.Ref != ref {
								continue
							}
							_ = tailFileTo(out, svc.ModelLogPath(m.Ref), 5)
						}
					}
				}
				return nil
			})
		},
	}
	cmd.Flags().StringVar(&ref, "ref", "", "Only show one model ref")
	cmd.Flags().IntVar(&lines, "lines", 50, "Lines per model")
	cmd.Flags().BoolVarP(&follow, "follow", "f", false, "Keep streaming new lines")
	return cmd
}

func appUninstallCmd() *cobra.Command {
	var (
		yes         bool
		purgeModels bool
	)
	cmd := &cobra.Command{
		Use:   "uninstall <namespace/name[:version]>",
		Short: "Remove an application's local state (models stay unless --purge-models)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return withAppKey(cmd, args[0], func(svc *apps.Service, key string) error {
				fmt.Fprintf(cmd.OutOrStdout(), "Will stop models and remove the state of %s\n", key)
				if !yes {
					fmt.Fprint(cmd.OutOrStdout(), "Continue? [y/N]: ")
					if !readYes(cmd) {
						fmt.Fprintln(cmd.OutOrStdout(), "Aborted.")
						return nil
					}
				}
				if _, err := svc.Uninstall(cmd.Context(), key, purgeModels); err != nil {
					return failed(cmd, err)
				}
				fmt.Fprintln(cmd.OutOrStdout(), "Uninstalled (model caches kept unless --purge-models).")
				return nil
			})
		},
	}
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "Skip the confirmation")
	cmd.Flags().BoolVar(&purgeModels, "purge-models", false, "Also remove the application's model caches")
	return cmd
}

func withAppKey(cmd *cobra.Command, raw string, fn func(*apps.Service, string) error) error {
	ref, err := flashhub.ParseAppRef(raw)
	if err != nil {
		return failed(cmd, err)
	}
	svc := newAppService(cmd)
	key, err := svc.ResolveKey(ref)
	if err != nil {
		return failed(cmd, err)
	}
	return fn(svc, key)
}

func readYes(cmd *cobra.Command) bool {
	line, err := bufio.NewReader(cmd.InOrStdin()).ReadString('\n')
	if err != nil && line == "" {
		return false
	}
	switch strings.ToLower(strings.TrimSpace(line)) {
	case "y", "yes":
		return true
	}
	return false
}

func truncate(s string, n int) string {
	runes := []rune(s)
	if len(runes) <= n {
		return s
	}
	return string(runes[:n])
}

// tailFileTo writes the last n lines of path to w.
func tailFileTo(w io.Writer, path string, n int) error {
	lines, err := modelrun.TailLines(path, n)
	if err != nil {
		return err
	}
	for _, line := range lines {
		_, _ = fmt.Fprintln(w, line)
	}
	return nil
}
