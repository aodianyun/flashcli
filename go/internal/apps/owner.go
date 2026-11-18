package apps

import "context"

type ownerKey struct{}

// WithOwner records which application owns the models started or stopped with
// ctx. The daemon's scheduler uses it to keep a shared model resident until the
// last application (or the model page) releases it.
func WithOwner(ctx context.Context, key string) context.Context {
	if key == "" {
		return ctx
	}
	return context.WithValue(ctx, ownerKey{}, key)
}

// OwnerFrom returns the application key recorded by WithOwner.
func OwnerFrom(ctx context.Context) string {
	owner, _ := ctx.Value(ownerKey{}).(string)
	return owner
}
