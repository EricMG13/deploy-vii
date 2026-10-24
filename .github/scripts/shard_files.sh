#!/usr/bin/env bash
# Prints the test files of one Product checks shard, space separated.
# Usage: shard_files.sh <shard-name>; source of truth: .github/shards/product.txt
set -eu
shard="${1:?shard name required}"
list="$(dirname "$0")/../shards/product.txt"
files=$(awk -v s="$shard" '$1 !~ /^#/ && NF == 2 && $1 == s { print $2 }' "$list" | tr '\n' ' ')
[ -n "$files" ] || { echo "unknown or empty shard: $shard" >&2; exit 1; }
printf '%s\n' "${files% }"
