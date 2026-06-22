#!/usr/bin/env bash
set -eu

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'ERROR: agent preflight must run inside a git worktree\n' >&2
  exit 1
fi

if git rev-parse -q --verify MERGE_HEAD >/dev/null 2>&1; then
  printf 'ERROR: a merge is in progress\n' >&2
  exit 1
fi

status="$(git status --porcelain --untracked-files=all)"
if [ -n "$status" ]; then
  printf 'ERROR: commit or intentionally remove current changes first:\n' >&2
  printf '%s\n' "$status" >&2
  exit 1
fi

git diff --check
printf 'Repository checkpoint ready: %s\n' "$(git log -1 --oneline)"
