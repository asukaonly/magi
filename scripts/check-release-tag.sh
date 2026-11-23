#!/usr/bin/env bash
set -euo pipefail

tag="${1:?Missing release tag}"
expected="${2:?Missing release commit}"
git fetch --no-tags origin "refs/tags/$tag"
actual="$(git rev-parse 'FETCH_HEAD^{commit}')"
if [[ "$actual" != "$expected" ]]; then
  echo "Release tag $tag points to $actual, expected $expected." >&2
  exit 1
fi
