package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"

	"github.com/aodianyun/flashcli/go/internal/server"
	"github.com/aodianyun/flashcli/go/internal/version"
)

func main() {
	configPath := flag.String("config", "", "JSON config file")
	addr := flag.String("addr", "", "HTTP listen address (default 127.0.0.1:8790)")
	token := flag.String("token", "", "local API token")
	flashcliBin := flag.String("flashcli-bin", "", "path to flashcli binary")
	publicHost := flag.String("public-host", "", "host name returned in model endpoints")
	logDir := flag.String("log-dir", "", "directory for per-model serve logs")
	maxLoaded := flag.Int("max-loaded", 0, "maximum resident models (0 = GPU memory only)")
	minFreeVRAM := flag.Int64("min-free-vram-mib", 0, "free VRAM safety margin in MiB")
	showVersion := flag.Bool("version", false, "print version")
	flag.Parse()

	if *showVersion {
		fmt.Println(version.Version)
		return
	}

	cfg := server.Config{
		Addr: *addr, Token: *token, FlashcliBin: *flashcliBin, PublicHost: *publicHost,
		LogDir: *logDir, MaxLoaded: *maxLoaded, MinFreeVRAMMiB: *minFreeVRAM,
	}
	if *configPath != "" {
		loaded, err := server.LoadConfig(*configPath)
		if err != nil {
			log.Fatalf("load config: %v", err)
		}
		cfg = mergeConfig(loaded, cfg)
	}
	if cfg.FlashcliBin == "" {
		cfg.FlashcliBin = defaultFlashcliBin()
	}
	if cfg.Addr == "" {
		cfg.Addr = "127.0.0.1:8790"
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := server.NewFromConfig(cfg).Run(ctx); err != nil {
		log.Fatal(err)
	}
}

func mergeConfig(base, override server.Config) server.Config {
	if override.Addr != "" {
		base.Addr = override.Addr
	}
	if override.Token != "" {
		base.Token = override.Token
	}
	if override.FlashcliBin != "" {
		base.FlashcliBin = override.FlashcliBin
	}
	if override.PublicHost != "" {
		base.PublicHost = override.PublicHost
	}
	if override.LogDir != "" {
		base.LogDir = override.LogDir
	}
	if override.MaxLoaded != 0 {
		base.MaxLoaded = override.MaxLoaded
	}
	if override.MinFreeVRAMMiB != 0 {
		base.MinFreeVRAMMiB = override.MinFreeVRAMMiB
	}
	return base
}

func defaultFlashcliBin() string {
	if v := os.Getenv("FLASHCLI_BIN"); v != "" {
		return v
	}
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	name := "flashcli"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	candidate := filepath.Join(filepath.Dir(exe), name)
	if _, err := os.Stat(candidate); err == nil {
		return candidate
	}
	return ""
}
