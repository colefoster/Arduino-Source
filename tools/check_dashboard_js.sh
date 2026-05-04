#!/usr/bin/env bash
# Parse-check every JS file in the dashboard before deploy.
#
# Catches SyntaxErrors (duplicate const, unclosed brace, stray comma) that
# would otherwise ship to ash and silently break the page — the entire script
# tag fails to evaluate, so any earlier render runs but no later JS does, and
# the failure mode is "page goes blank" with cryptic console errors.
#
# Run before any deploy of dashboard/static/js/*.js. Exit non-zero on failure
# so a chained `scp && ssh` short-circuits.

set -euo pipefail

cd "$(dirname "$0")/.."

fail=0
for f in dashboard/static/js/*.js; do
    if ! node -e "new Function(require('fs').readFileSync('$f','utf8'))" 2>/tmp/jschk_err; then
        echo "PARSE ERROR in $f:"
        sed 's/^/  /' /tmp/jschk_err
        fail=1
    fi
done

rm -f /tmp/jschk_err

if [ $fail -eq 0 ]; then
    echo "dashboard JS: parse-check passed ($(ls dashboard/static/js/*.js | wc -l | tr -d ' ') files)"
fi
exit $fail
