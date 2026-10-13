// Command flashcli is the Go host for FlashRT model bundles.
package main

import (
	"os"

	"github.com/aodianyun/flashcli/go/internal/cli"
)

func main() {
	os.Exit(cli.Main(os.Args[1:]))
}
