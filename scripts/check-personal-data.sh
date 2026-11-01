#!/usr/bin/env bash
# Blocks financial data from entering commits or reaching the remote.
#
#   check-personal-data.sh staged            # pre-commit: checks the index
#   check-personal-data.sh range <rev-args>  # pre-push: checks every commit in range
#
# Checks: forbidden file types (DBs, backups, exports, .env), IBAN-like strings,
# and strings listed in the gitignored .personal-patterns file.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
patterns_file="$root/.personal-patterns"
mode=${1:-staged}
shift || true

forbidden_path_re='\.(db|db-[a-z]+|sqlite3?|bak|dump|csv|pdf|xlsx?|ods)$|(^|/)(data|backups|exports)/|(^|/)\.env(\.|$)|(^|/)\.personal-patterns$'
allowed_path_re='(^|/)\.env\.example$|^tests/fixtures/'
iban_re='\b[A-Z]{2}[0-9]{2} ?([0-9A-Z]{4} ?){3,7}[0-9A-Z]{0,4}\b'

fail=0
err() { echo "✗ $*" >&2; fail=1; }

if [[ $mode == staged ]]; then
  files=$(git diff --cached --name-only --diff-filter=ACMR)
  added=$(git diff --cached -U0 --no-color --diff-filter=ACMR | grep -E '^\+' | grep -vE '^\+\+\+ ' || true)
elif [[ $mode == range ]]; then
  files=$(git log --name-only --format= --diff-filter=ACMR "$@" | sort -u)
  added=$(git log -p -U0 --no-color --format= --diff-filter=ACMR "$@" | grep -E '^\+' | grep -vE '^\+\+\+ ' || true)
else
  echo "usage: $0 staged | range <rev-args>" >&2
  exit 2
fi

# 1. Forbidden file types.
while read -r f; do
  [[ -z $f ]] && continue
  if [[ $f =~ $forbidden_path_re ]] && ! [[ $f =~ $allowed_path_re ]]; then
    err "forbidden file (may contain financial data): $f"
  fi
done <<< "$files"

# 2. IBAN-like strings in added lines.
if hits=$(grep -oE "$iban_re" <<< "$added"); then
  err "IBAN-like string(s) found: $(tr '\n' ' ' <<< "$hits")"
fi

# 3. Strings from the local blocklist (one fixed string per line, case-sensitive, whole word).
if [[ -f $patterns_file ]]; then
  if hits=$(grep -nFw -f <(grep -vE '^\s*(#|$)' "$patterns_file") <<< "$added"); then
    err "blocklisted string(s) from .personal-patterns found in added lines:"
    sed 's/^/    /' <<< "$hits" >&2
  fi
else
  echo "! .personal-patterns not found – skipping blocklist check" >&2
fi

if (( fail )); then
  echo "Blocked: financial data must never reach GitHub. Fix the above (see README → Privacy)." >&2
  exit 1
fi
