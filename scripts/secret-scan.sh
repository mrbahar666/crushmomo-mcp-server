#!/bin/sh
# Fail if a likely secret or real .env is present. Run before every push.
# This is a pattern scan, not a proof: review the diff by hand as well.
set -eu
cd "$(dirname "$0")/.."
fail=0
if ls .env 2>/dev/null || find . -name '.env' -not -path './.git/*' | grep -q .; then echo "FAIL: real .env file present"; fail=1; fi
if grep -RInE --exclude-dir=.git -E 'password\s*=\s*["'"'"'][^"'"'"']{4,}|token\s*=\s*["'"'"'][A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}' . 2>/dev/null | grep -v 'PASTE_YOUR_OWN_TOKEN\|YOUR_TOKEN_IN_YOUR_OWN_CONFIG\|<your-token>\|Bearer \$' ; then echo "FAIL: possible secret pattern above"; fail=1; fi
if grep -RIn --exclude-dir=.git 'crus_cmprod\|144\.79\.249\.14' . | grep -v 'docs/' | grep -v README; then echo "NOTE: live DB/IP reference outside docs (review)"; fi
exit $fail
