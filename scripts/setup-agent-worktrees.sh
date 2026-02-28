#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_NAME="$(basename "${REPO_ROOT}")"
DEFAULT_BASE_DIR="$(dirname "${REPO_ROOT}")"

BASE_DIR="${1:-${DEFAULT_BASE_DIR}}"
SKIP_CLEAN_CHECK="${SKIP_CLEAN_CHECK:-0}"

TASK_KEYS=(
  "tools-skills"
  "frontend-config"
  "memory-refactor"
)

TASK_LABELS=(
  "tools implementation and skills adaptation"
  "frontend and config pages optimization"
  "memory module refactor"
)

BRANCH_NAMES=(
  "feature/tools-skills-adaptation"
  "feature/frontend-config-optimization"
  "refactor/memory-module"
)

WORKTREE_DIRS=(
  "${BASE_DIR}/${REPO_NAME}-tools-skills"
  "${BASE_DIR}/${REPO_NAME}-frontend-config"
  "${BASE_DIR}/${REPO_NAME}-memory-refactor"
)

abort() {
  echo "Error: $*" >&2
  exit 1
}

check_prerequisites() {
  command -v git >/dev/null 2>&1 || abort "git not found in PATH."
  git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1 || abort "Not a git repository: ${REPO_ROOT}"

  if [[ "${SKIP_CLEAN_CHECK}" != "1" ]]; then
    if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]]; then
      abort "Repository has uncommitted changes. Commit/stash first, or run with SKIP_CLEAN_CHECK=1."
    fi
  fi
}

ensure_target_dirs_absent() {
  local i
  for i in "${!WORKTREE_DIRS[@]}"; do
    if [[ -e "${WORKTREE_DIRS[$i]}" ]]; then
      abort "Target directory already exists for ${TASK_KEYS[$i]}: ${WORKTREE_DIRS[$i]}"
    fi
  done
}

ensure_branches_absent() {
  local i
  for i in "${!BRANCH_NAMES[@]}"; do
    if git -C "${REPO_ROOT}" show-ref --verify --quiet "refs/heads/${BRANCH_NAMES[$i]}"; then
      abort "Local branch already exists for ${TASK_KEYS[$i]}: ${BRANCH_NAMES[$i]}"
    fi
    if git -C "${REPO_ROOT}" show-ref --verify --quiet "refs/remotes/origin/${BRANCH_NAMES[$i]}"; then
      abort "Remote branch already exists for ${TASK_KEYS[$i]}: origin/${BRANCH_NAMES[$i]}"
    fi
  done
}

create_worktrees() {
  local i
  for i in "${!TASK_KEYS[@]}"; do
    echo
    echo "Creating worktree: ${TASK_KEYS[$i]}"
    echo "  Branch: ${BRANCH_NAMES[$i]}"
    echo "  Path:   ${WORKTREE_DIRS[$i]}"
    git -C "${REPO_ROOT}" worktree add "${WORKTREE_DIRS[$i]}" -b "${BRANCH_NAMES[$i]}"
  done
}

print_summary() {
  local i
  echo
  echo "Done. Created worktrees:"
  for i in "${!TASK_KEYS[@]}"; do
    echo "- ${TASK_LABELS[$i]}"
    echo "  ${WORKTREE_DIRS[$i]}"
    echo "  branch: ${BRANCH_NAMES[$i]}"
  done

  echo
  echo "Current worktree list:"
  git -C "${REPO_ROOT}" worktree list

  echo
  echo "Suggested next commands:"
  for i in "${!TASK_KEYS[@]}"; do
    echo "- cd ${WORKTREE_DIRS[$i]}"
    echo "  git status --short --branch"
  done
}

main() {
  echo "Repo root: ${REPO_ROOT}"
  echo "Base dir:  ${BASE_DIR}"
  check_prerequisites
  ensure_target_dirs_absent
  ensure_branches_absent
  create_worktrees
  print_summary
}

main "$@"
