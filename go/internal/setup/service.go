package setup

import (
	"path"
	"strings"
)

func systemdUnit(opts Options, binDir string) string {
	var b strings.Builder
	b.WriteString("[Unit]\n")
	b.WriteString("Description=flashserver model scheduler\n")
	b.WriteString("After=network-online.target\n")
	b.WriteString("Wants=network-online.target\n\n")
	b.WriteString("[Service]\n")
	b.WriteString("Type=simple\n")
	if opts.User != "" && opts.User != "root" {
		b.WriteString("User=" + opts.User + "\n")
	}
	b.WriteString("Environment=FLASHCLI_HOME=" + opts.Home + "\n")
	if opts.Home != "" {
		b.WriteString("Environment=HOME=" + path.Dir(opts.Home) + "\n")
	}
	b.WriteString("ExecStart=" + path.Join(binDir, "flashserver") + " --config " + opts.ConfigPath + "\n")
	b.WriteString("Restart=on-failure\n")
	b.WriteString("RestartSec=3\n")
	b.WriteString("LimitNOFILE=1048576\n\n")
	b.WriteString("[Install]\n")
	b.WriteString("WantedBy=multi-user.target\n")
	return b.String()
}
