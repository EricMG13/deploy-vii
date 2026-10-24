#!/usr/bin/env bash
# Reads changed paths (one per line) on stdin; prints "true" unless every path is
# docs-only. Fail-closed: empty input, any unmatched path or any error -> "true".
set -u
trap 'echo true; exit 0' ERR
count=0
while IFS= read -r path || [ -n "$path" ]; do
  [ -z "$path" ] && continue
  count=$((count + 1))
  case "$path" in
    docs/*) ;;
    */*) echo true; exit 0 ;;
    *.md | LICENSE | LICENSE.* | LICENSE-* | .gitignore | .gitattributes | CODEOWNERS) ;;
    *) echo true; exit 0 ;;
  esac
done
if [ "$count" -eq 0 ]; then echo true; else echo false; fi
