package server

import (
	"context"
	"log"
	"sort"
	"time"

	"github.com/aodianyun/flashcli/go/internal/apps"
)

// restoreOnStart resumes the session that was running before the daemon
// stopped: models loaded from the 模型 page and applications that were ready
// with live models. The OS autostart toggle only decides whether the service
// starts at boot; once it runs, its previous state is restored.
//
// Apps are marked starting before the HTTP server accepts requests, so an early
// status poll cannot downgrade a restore-in-progress to stopped. The actual
// loads happen in the background because a model can take a minute.
func (s *Server) restoreOnStart(ctx context.Context) {
	if s.Manager == nil {
		return
	}
	svc := s.appService()
	now := time.Now().UTC().Format(time.RFC3339)
	var keys []string
	if err := svc.Registry.Update(func(m map[string]apps.AppState) error {
		for key, st := range m {
			switch st.State {
			case apps.StateStarting:
				// The daemon stopped during a start (or a restore). Retry it;
				// a model that cannot start turns the app into failed with a
				// reason instead of leaving it stuck in 启动中 forever.
			case apps.StateInstalling, apps.StatePreparing:
				// The install was interrupted; its download/install state is
				// unknown, so surface it and let the user reinstall.
				st.State = apps.StateFailed
				st.Error = "daemon restarted before the install finished; reinstall the application"
				st.UpdatedAt = now
				m[key] = st
				continue
			case apps.StateStopping:
				// The models died with the daemon; finish the stop.
				for i := range st.Models {
					st.Models[i].PID = 0
					st.Models[i].Endpoint = ""
				}
				st.State = apps.StateStopped
				st.Error = ""
				st.SetupError = ""
				st.UpdatedAt = now
				m[key] = st
				continue
			default:
				if !appWasRunning(st) {
					continue
				}
			}
			st.State = apps.StateStarting
			st.Error = ""
			st.SetupError = ""
			st.UpdatedAt = now
			m[key] = st
			keys = append(keys, key)
		}
		return nil
	}); err != nil {
		log.Printf("restore apps: %v", err)
	}
	sort.Strings(keys)
	go func() {
		for _, err := range s.Manager.RestoreModels(ctx) {
			log.Printf("restore model: %v", err)
		}
		for _, key := range keys {
			svc := s.appService()
			if _, err := svc.Start(ctx, key, false); err != nil {
				log.Printf("restore app %s: %v", key, err)
			}
		}
	}()
}

// appWasRunning distinguishes an app that had live models from one installed
// with start=false (ready state, but no pid/endpoint yet).
func appWasRunning(st apps.AppState) bool {
	return apps.WasRunning(st)
}
