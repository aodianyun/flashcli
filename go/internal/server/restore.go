package server

import (
	"context"
	"log"
)

// restoreOnStart resumes model-page residents saved before the daemon stopped.
// Applications are gateway clients: their setup state is kept as-is and no
// model process is started on their behalf.
func (s *Server) restoreOnStart(ctx context.Context) {
	if s.Manager == nil {
		return
	}
	go func() {
		for _, err := range s.Manager.RestoreModels(ctx) {
			log.Printf("restore model: %v", err)
		}
	}()
}
