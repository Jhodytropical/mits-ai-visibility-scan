#!/usr/bin/env bash
# Install pre-commit and pre-push hooks that run scripts/check_no_secrets.sh.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
printf '#!/usr/bin/env bash\nexec "%s/scripts/check_no_secrets.sh" --staged\n' "$root" > "$root/.git/hooks/pre-commit"
printf '#!/usr/bin/env bash\nwhile read -r _ sha _ _; do\n  [ "$sha" = "0000000000000000000000000000000000000000" ] && continue\n  "%s/scripts/check_no_secrets.sh" --rev "$sha" || exit 1\ndone\n' "$root" > "$root/.git/hooks/pre-push"
chmod +x "$root/.git/hooks/pre-commit" "$root/.git/hooks/pre-push" "$root/scripts/check_no_secrets.sh"
echo "hooks installed"
