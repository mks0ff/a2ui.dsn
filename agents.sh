#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <claude|gemini|codex> <matt|google|pstack|addy> [remove]" >&2
  exit 1
}

[ $# -ge 2 ] && [ $# -le 3 ] || usage

agent="$1"
source_name="$2"
action="${3:-link}"
BASE="/Users/zof/github/skills"

case "$action" in
  link|remove) ;;
  *) usage ;;
esac

# Agent -> target skills directory
case "$agent" in
  claude|gemini|codex) target=".$agent/skills" ;;
  *) usage ;;
esac

# Skill source -> root dir + groups ("." = skills sit directly in root)
case "$source_name" in
  matt)   root="$BASE/matt-skills/skills";          groups=(productivity engineering) ;;
  google) root="$BASE/google-skills/skills";        groups=(cloud identity) ;;
  pstack) root="$BASE/poteto-skills/pstack/skills"; groups=(.) ;;
  addy)   root="$BASE/addy-skills/skills";          groups=(.) ;;
  *) usage ;;
esac

update_repos() {
  local repo
  for repo in "$BASE"/*/; do
    repo="${repo%/}"
    [ -d "$repo/.git" ] || continue
    echo "Updating $(basename "$repo")..."
    git -C "$repo" pull --ff-only --quiet \
      || echo "  Warning: could not update $(basename "$repo"), continuing" >&2
  done
}

if [ "$action" = "link" ]; then
  update_repos

  if [ ! -d "$target" ]; then
    mkdir -p "$target"
    echo "Created $target"
  fi

  for g in "${groups[@]}"; do
    for d in "$root/$g"/*/; do
      [ -d "$d" ] || continue
      ln -fns "${d%/}" "$target/"
    done
  done
  echo "Linked $source_name skills into $target"

else
  removed=0
  for g in "${groups[@]}"; do
    for d in "$root/$g"/*/; do
      [ -d "$d" ] || continue
      d="${d%/}"
      link="$target/$(basename "$d")"
      # Only remove symlinks that point at this source's skill
      if [ -L "$link" ] && [ "$(readlink "$link")" = "$d" ]; then
        rm "$link"
        removed=$((removed + 1))
      fi
    done
  done
  echo "Removed $removed $source_name skill links from $target"
fi
