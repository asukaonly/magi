#!/usr/bin/env bash
#
# Bump the repo version, commit, run a fast local sanity check, push the branch,
# then GATE ON THE REMOTE CI RUN: only after ci.yml goes green do we create and
# push the release tag (v*), which triggers release.yml's desktop builds.
#
# Why remote-CI-gated: CI installs the supported dependencies in a clean
# environment and runs the complete cross-platform validation. A long-lived
# local environment may lag those versions, so GitHub CI is the source of truth.
# The local sanity step only checks the environment-independent parts.
#
# Usage:
#   scripts/bump-release.sh <major|minor|patch>
#   scripts/bump-release.sh patch   # 0.1.14 -> 0.1.15
#   scripts/bump-release.sh minor   # 0.1.14 -> 0.2.0
#   scripts/bump-release.sh major   # 0.1.14 -> 1.0.0
#
set -euo pipefail

PART="${1:-}"
case "$PART" in
  major|minor|patch) ;;
  *) echo "usage: $0 <major|minor|patch>" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- preflight ------------------------------------------------------------
command -v gh >/dev/null || { echo "ERROR: gh CLI required for the remote-CI gate." >&2; exit 1; }
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree is not clean — commit or stash changes first." >&2
  exit 1
fi
BRANCH="$(git branch --show-current)"
[[ -n "$BRANCH" ]] || { echo "ERROR: detached HEAD — checkout a branch first." >&2; exit 1; }

# --- compute next version (current + 1 on the requested part) -------------
CURRENT="$(tr -d '[:space:]' < VERSION)"
if [[ ! "$CURRENT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: VERSION '$CURRENT' is not a semver x.y.z." >&2
  exit 1
fi
IFS=. read -r MA MI PA <<<"$CURRENT"
case "$PART" in
  major) MA=$((MA + 1)); MI=0; PA=0 ;;
  minor) MI=$((MI + 1)); PA=0 ;;
  patch) PA=$((PA + 1)) ;;
esac
NEW="${MA}.${MI}.${PA}"
TAG="v${NEW}"

echo ">>> Release ${CURRENT} -> ${NEW} (${PART}) on branch ${BRANCH}; tag ${TAG}"
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  echo "ERROR: tag ${TAG} already exists." >&2
  exit 1
fi

# --- sync version metadata + commit ---------------------------------------
python scripts/release-version.py sync "${NEW}"
python scripts/release-version.py validate --version "${NEW}"
git add -A
git commit -m "chore(release): ${TAG}"

# --- local sanity (environment-independent: batch suite avoids fastapi) ---
echo ">>> Local sanity: backend batch suite"
if ! ( cd backend && python -m pytest tests/agent/batch -q ); then
  echo "" >&2
  echo ">>> Local sanity FAILED — release commit is LOCAL-ONLY (nothing pushed)." >&2
  echo ">>> Undo with:  git reset --hard HEAD~1" >&2
  exit 1
fi

# --- push branch, then gate on the remote CI run it triggers --------------
echo ">>> Pushing ${BRANCH} (remote CI is the source of truth) ..."
git push origin "${BRANCH}"

echo ">>> Waiting for CI to register the run ..."
sleep 8
HEAD_SHA="$(git rev-parse HEAD)"
RUN_ID="$(gh run list --branch "${BRANCH}" --workflow ci.yml --limit 20 \
  --json databaseId,headSha -q "[.[] | select(.headSha==\"${HEAD_SHA}\")][0].databaseId")"
if [[ -z "${RUN_ID}" ]]; then
  echo "ERROR: no ci.yml run found for ${HEAD_SHA}." >&2
  echo "       Check 'gh run list'; once it's green, tag manually:" >&2
  echo "       git tag -a ${TAG} -m 'Release ${TAG}' && git push origin ${TAG}" >&2
  exit 1
fi

echo ">>> Watching CI run ${RUN_ID} (this blocks until CI finishes) ..."
if ! gh run watch "${RUN_ID}" --exit-status; then
  echo "" >&2
  echo ">>> CI FAILED. The commit is pushed on ${BRANCH}, but NO tag was created" >&2
  echo ">>> (release.yml NOT triggered). Fix forward and re-run, or revert on remote." >&2
  exit 1
fi

# --- CI green -> tag + push tag (triggers release.yml) --------------------
echo ">>> CI green. Tagging ${TAG} ..."
git tag -a "${TAG}" -m "Release ${TAG}"
git push origin "${TAG}"

echo ">>> Released ${TAG}: pushed ${BRANCH} and ${TAG}."
echo ">>> release.yml will now build the desktop bundles (macOS/Windows)."
