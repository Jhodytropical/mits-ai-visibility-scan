#!/usr/bin/env bash
# Refuse to commit or push API keys or private files. Installed as git hooks by scripts/install_hooks.sh.
#   - blocks private paths (results, business profiles, notes, .env files other than .env.example, key files)
#   - blocks content that looks like an API key or token
#   - also blocks patterns listed in .private_patterns (one extended regex per line; gitignored, never published)
# Usage: check_no_secrets.sh [--staged | --rev <commit> | --all]   (default --staged)
set -uo pipefail
root="$(git rev-parse --show-toplevel)"; cd "$root"
mode="${1:---staged}"
case "$mode" in
  --rev) rev="$2"; files=$(git ls-tree -r --name-only "$rev"); show() { git show "$rev:$1" 2>/dev/null; } ;;
  --all) files=$(git ls-files); show() { cat "$1" 2>/dev/null; } ;;
  *)     files=$(git diff --cached --name-only --diff-filter=ACMR); show() { git show ":$1" 2>/dev/null; } ;;
esac
private_path() {
  [[ "$1" =~ (^|/)(out|profiles)/ || "$1" =~ (^|/)(OFFER|MITS_NOTES)\.md$ || "$1" =~ \.private_patterns$ ||
     "$1" =~ (^|/)(openai_key|anthropic_key|gemini_api_key)$ ]] && return 0
  [[ "$1" =~ (^|/)\.env ]] && [[ ! "$1" =~ (^|/)\.env\.example$ ]] && return 0
  return 1
}
key_re='sk-ant-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9_-]{32,}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}'
bad=0; n=0
while IFS= read -r f; do
  [ -z "$f" ] && continue; n=$((n+1))
  if private_path "$f"; then echo "BLOCKED path: $f"; bad=1; continue; fi
  if show "$f" | grep -q -E -- "$key_re"; then echo "BLOCKED: $f contains something that looks like an API key"; bad=1; fi
  if [ -f .private_patterns ]; then
    while IFS= read -r pat; do
      [[ -z "$pat" || "$pat" == \#* ]] && continue
      if show "$f" | grep -q -i -E -- "$pat"; then echo "BLOCKED: $f matches a .private_patterns entry"; bad=1; fi
    done < .private_patterns
  fi
done <<< "$files"
[ $bad -eq 0 ] || { echo "Secret check failed. Nothing was committed/pushed."; exit 1; }
echo "secret check passed ($n files)"
