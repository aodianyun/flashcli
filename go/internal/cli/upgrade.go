package cli

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	goruntime "runtime"
	"strings"

	"github.com/spf13/cobra"

	"github.com/aodianyun/flashcli/go/internal/selfupdate"
	"github.com/aodianyun/flashcli/go/internal/version"
)

const (
	defaultReleaseBase = "https://github.com/aodianyun/flashcli/releases/download"
	defaultReleaseAPI  = "https://api.github.com/repos/aodianyun/flashcli/releases/latest"
	checksumsAsset     = "sha256sums.txt"
)

func upgradeCmd() *cobra.Command {
	var check bool
	var targetVersion string
	var baseURL string
	var downloadURL string
	var sha256Hex string
	var target string
	var insecure bool

	cmd := &cobra.Command{
		Use:   "upgrade",
		Short: "Download and install a new flashcli-go binary",
		RunE: func(cmd *cobra.Command, args []string) error {
			out := cmd.OutOrStdout()
			client := &http.Client{}
			base := firstNonEmpty(baseURL, os.Getenv("FLASHCLI_GO_RELEASE_BASE"), defaultReleaseBase)
			api := firstNonEmpty(os.Getenv("FLASHCLI_GO_RELEASE_API"), defaultReleaseAPI)

			if target == "" {
				exe, err := selfupdate.Executable()
				if err != nil {
					return err
				}
				target = exe
			}

			if check {
				latest := targetVersion
				if latest == "" {
					var err error
					latest, err = selfupdate.LatestVersion(context.Background(), client, api)
					if err != nil {
						return err
					}
				}
				fmt.Fprintf(out, "current: %s\nlatest:  %s\n", version.Version, latest)
				return nil
			}

			asset := selfupdate.AssetName(goruntime.GOOS, goruntime.GOARCH)
			want := strings.TrimSpace(sha256Hex)
			url := downloadURL
			if url == "" {
				ver := targetVersion
				if ver == "" {
					var err error
					ver, err = selfupdate.LatestVersion(context.Background(), client, api)
					if err != nil {
						return err
					}
				}
				url = selfupdate.ReleaseURL(base, ver, asset)
				if want == "" {
					sumsURL := selfupdate.ReleaseURL(base, ver, checksumsAsset)
					sums, err := selfupdate.Download(context.Background(), client, sumsURL)
					if err != nil {
						return fmt.Errorf("%w (pass --sha256 or --insecure to override)", err)
					}
					want = selfupdate.ParseChecksums(string(sums))[asset]
					if want == "" {
						return fmt.Errorf("%s not found in %s", asset, sumsURL)
					}
				}
			}

			data, err := selfupdate.Download(context.Background(), client, url)
			if err != nil {
				return err
			}
			if want != "" {
				if err := selfupdate.Verify(data, want); err != nil {
					return err
				}
			} else if !insecure {
				return errors.New("refusing to install without a checksum (pass --sha256 or --insecure)")
			}
			if err := selfupdate.Replace(target, data); err != nil {
				return err
			}
			fmt.Fprintf(out, "[ok] upgraded %s -> %s\n", target, firstNonEmpty(targetVersion, "latest"))
			return nil
		},
	}
	cmd.Flags().BoolVar(&check, "check", false, "Only check the latest version")
	cmd.Flags().StringVar(&targetVersion, "version", "", "Target version (default: latest)")
	cmd.Flags().StringVar(&baseURL, "base-url", "", "Release base URL")
	cmd.Flags().StringVar(&downloadURL, "url", "", "Explicit binary URL")
	cmd.Flags().StringVar(&sha256Hex, "sha256", "", "Expected sha256 of the binary")
	cmd.Flags().StringVar(&target, "target", "", "Install path (default: running binary)")
	cmd.Flags().BoolVar(&insecure, "insecure", false, "Allow installing without a checksum")
	return cmd
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}
