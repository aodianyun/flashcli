package server

import (
	"context"

	"github.com/aodianyun/flashcli/go/internal/apps"
	"github.com/aodianyun/flashcli/go/internal/modelrun"
)

// managerLauncher adapts the daemon's model Manager to apps.Launcher so that
// application models go through the same admission as models started from the
// 模型 page: the max_loaded slot limit and the bundle's resources.min_vram_mib.
// Each application registers as an owner, so stopping one app keeps a model
// that another app still uses resident.
type managerLauncher struct {
	manager *Manager
	// Log receives the serve child's progress lines (weight loading etc.) so
	// an app start job is not silent while a model loads.
	Log func(string)
}

func (l managerLauncher) StartWithOptions(
	ctx context.Context,
	refStr string,
	_ modelrun.LoadOptions,
) (modelrun.ServeProcess, error) {
	owner := apps.OwnerFrom(ctx)
	var (
		info *InstanceInfo
		err  error
	)
	if l.Log != nil {
		info, err = l.manager.LoadForWithProgress(ctx, refStr, owner, func(_, message string) {
			if message != "" {
				l.Log(message)
			}
		})
	} else {
		info, err = l.manager.LoadFor(ctx, refStr, owner)
	}
	if err != nil {
		return nil, err
	}
	return &managerProcess{manager: l.manager, ref: refStr, owner: owner, info: *info}, nil
}

// managerProcess exposes a Manager-owned instance as a ServeProcess.
type managerProcess struct {
	manager *Manager
	ref     string
	owner   string
	info    InstanceInfo
}

func (p *managerProcess) Ref() string      { return p.ref }
func (p *managerProcess) Endpoint() string { return p.info.Endpoint }
func (p *managerProcess) PID() int         { return p.info.PID }
func (p *managerProcess) Running() bool    { return p.manager.IsRunning(p.ref) }
func (p *managerProcess) LastLog() string  { return "" }

func (p *managerProcess) Healthy(ctx context.Context) error {
	return modelrun.HealthyEndpoint(ctx, p.info.Endpoint)
}

func (p *managerProcess) Stop(ctx context.Context) error {
	_, err := p.manager.ReleaseFor(ctx, p.ref, p.owner)
	return err
}
