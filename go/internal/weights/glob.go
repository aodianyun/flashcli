package weights

import (
	"regexp"
	"strings"
	"sync"
)

var (
	globCacheMu sync.Mutex
	globCache   = map[string]*regexp.Regexp{}
)

// matchPattern reports whether a slash-separated relative path matches pattern.
// Supports *, ?, [...] and ** (crossing directory boundaries). A pattern with
// no wildcard matches the exact path or any file under that directory prefix.
func matchPattern(rel, pattern string) bool {
	rel = strings.ReplaceAll(rel, "\\", "/")
	pattern = strings.TrimSpace(pattern)
	if pattern == "" {
		return false
	}
	if !strings.ContainsAny(pattern, "*?[") {
		pattern = strings.Trim(pattern, "/")
		return rel == pattern || strings.HasPrefix(rel, pattern+"/")
	}
	re := compileGlob(pattern)
	if re == nil {
		return false
	}
	return re.MatchString(rel)
}

func compileGlob(pattern string) *regexp.Regexp {
	globCacheMu.Lock()
	defer globCacheMu.Unlock()
	if re, ok := globCache[pattern]; ok {
		return re
	}
	var b strings.Builder
	b.WriteString("^")
	for i := 0; i < len(pattern); {
		c := pattern[i]
		switch c {
		case '*':
			if i+1 < len(pattern) && pattern[i+1] == '*' {
				i += 2
				if i < len(pattern) && pattern[i] == '/' {
					b.WriteString("(?:.*/)?")
					i++
				} else {
					b.WriteString(".*")
				}
			} else {
				b.WriteString("[^/]*")
				i++
			}
		case '?':
			b.WriteString("[^/]")
			i++
		case '[':
			j := i + 1
			for j < len(pattern) && pattern[j] != ']' {
				j++
			}
			if j < len(pattern) {
				b.WriteString(pattern[i : j+1])
				i = j + 1
			} else {
				b.WriteString(regexp.QuoteMeta("["))
				i++
			}
		default:
			b.WriteString(regexp.QuoteMeta(string(c)))
			i++
		}
	}
	b.WriteString("$")
	re, err := regexp.Compile(b.String())
	if err != nil {
		return nil
	}
	globCache[pattern] = re
	return re
}
