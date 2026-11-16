package manifest

import (
	"fmt"
	"sort"
	"strings"
)

// Serve protocol capability identifiers. Host-owned routes are mounted only
// for the capabilities a bundle declares; legacy Python engine entries without
// the field keep the pre-capability openai.chat behavior.
const (
	ServeCapOpenAIChat              = "openai.chat"
	ServeCapOpenAIResponses         = "openai.responses"
	ServeCapOpenAICompletions       = "openai.completions"
	ServeCapOpenAIEmbeddings        = "openai.embeddings"
	ServeCapOpenAIModerations       = "openai.moderations"
	ServeCapOpenAIAudioTranscribe   = "openai.audio.transcriptions"
	ServeCapOpenAIAudioTranslate    = "openai.audio.translations"
	ServeCapOpenAIAudioSpeech       = "openai.audio.speech"
	ServeCapOpenAIImagesGenerations = "openai.images.generations"
	ServeCapOpenAIImagesEdits       = "openai.images.edits"
	ServeCapOpenAIImagesVariations  = "openai.images.variations"
	ServeCapOpenAIVideos            = "openai.videos"
	ServeCapOpenAIRealtime          = "openai.realtime"
	ServeCapAnthropicMessages       = "anthropic.messages"
	ServeCapAnthropicCountTokens    = "anthropic.count_tokens"
	ServeCapAnthropicModels         = "anthropic.models"
)

// ServeCapabilitySet is the closed set of capability identifiers.
var ServeCapabilitySet = map[string]bool{
	ServeCapOpenAIChat:              true,
	ServeCapOpenAIResponses:         true,
	ServeCapOpenAICompletions:       true,
	ServeCapOpenAIEmbeddings:        true,
	ServeCapOpenAIModerations:       true,
	ServeCapOpenAIAudioTranscribe:   true,
	ServeCapOpenAIAudioTranslate:    true,
	ServeCapOpenAIAudioSpeech:       true,
	ServeCapOpenAIImagesGenerations: true,
	ServeCapOpenAIImagesEdits:       true,
	ServeCapOpenAIImagesVariations:  true,
	ServeCapOpenAIVideos:            true,
	ServeCapOpenAIRealtime:          true,
	ServeCapAnthropicMessages:       true,
	ServeCapAnthropicCountTokens:    true,
	ServeCapAnthropicModels:         true,
}

// LegacyServeCapabilities is the implicit route set for old manifests.
var LegacyServeCapabilities = []string{ServeCapOpenAIChat}

// EffectiveServeCapabilities resolves host-owned protocol routes for a serve
// entry. Native and script entries expose no host-owned protocol routes.
func (e *EntrySpec) EffectiveServeCapabilities() []string {
	if e == nil || e.Kind != "python" || e.Mode != "engine" {
		return nil
	}
	if !e.CapabilitiesSet {
		return append([]string(nil), LegacyServeCapabilities...)
	}
	return append([]string(nil), e.Capabilities...)
}

// ServeCapabilities is the effective capability list for this manifest.
func (m *Manifest) ServeCapabilities() []string {
	return m.EntryServe.EffectiveServeCapabilities()
}

func validateOneServeSpec(label string, spec *EntrySpec) []string {
	if spec == nil {
		return nil
	}
	if spec.CapabilitiesInvalid != "" {
		return []string{fmt.Sprintf("%s.capabilities: %s", label, spec.CapabilitiesInvalid)}
	}
	if !spec.CapabilitiesSet {
		return nil
	}
	if spec.Kind != "python" || spec.Mode != "engine" {
		return []string{fmt.Sprintf("%s.capabilities is only valid for python engine serve", label)}
	}
	seen := map[string]bool{}
	var errors []string
	for _, cap := range spec.Capabilities {
		if !ServeCapabilitySet[cap] {
			errors = append(errors, fmt.Sprintf("%s.capabilities: unknown capability %q", label, cap))
		} else if seen[cap] {
			errors = append(errors, fmt.Sprintf("%s.capabilities: duplicate capability %q", label, cap))
		}
		seen[cap] = true
	}
	sort.Strings(errors)
	return errors
}

func validateAllServeCapabilities(m *Manifest) []string {
	var errors []string
	errors = append(errors, validateOneServeSpec("entry.serve", m.EntryServe)...)
	if m.FormatVersion >= FormatVersionV4 {
		for _, key := range m.EnvironmentKeys() {
			envManifest, err := m.ApplyEnv(key)
			if err != nil {
				errors = append(errors, err.Error())
				continue
			}
			errors = append(errors, validateOneServeSpec("environments."+key+".entry.serve", envManifest.EntryServe)...)
		}
	}
	variants := variantBlocksRaw(m)
	names := make([]string, 0, len(variants))
	for name := range variants {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		errors = append(errors, validateOneServeSpec("variants."+name+".entry.serve", m.EntryFor("serve", name))...)
	}
	return errors
}

// TrimServeCapability normalizes one capability id.
func TrimServeCapability(s string) string { return strings.TrimSpace(s) }
