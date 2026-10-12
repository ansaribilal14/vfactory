#!/usr/bin/env bash
# One-shot environment restore after sandbox reset. Run: bash tools/restore_env.sh
set -e
BASE=/home/z/my-project
GH_URL=https://github.com/ansaribilal14
# 1) token (env GH_TOKEN_NEW overrides; else file pasted below by operator)
T="${GH_TOKEN_NEW:-$(cat $BASE/.gh_token 2>/dev/null)}"
[ -n "$T" ] && printf '%s' "$T" > "$BASE/.gh_token" && chmod 600 "$BASE/.gh_token"
printf 'https://ansaribilal14:%s@github.com\n' "$T" > "$BASE/.git-credentials" && chmod 600 "$BASE/.git-credentials"
git config --global credential.helper "store --file $BASE/.git-credentials" || true
# 2) sync repos from the new account (source of truth)
for r in vfactory; do
  [ -d "$BASE/$r/.git" ] || git clone -q "$GH_URL/$r.git" "$BASE/$r" || true
  git -C "$BASE/$r" remote set-url origin "$GH_URL/$r.git"
  git -C "$BASE/$r" config credential.helper "store --file $BASE/.git-credentials"
  git -C "$BASE/$r" fetch -q origin && git -C "$BASE/$r" checkout -q main && \
  git -C "$BASE/$r" reset -q --hard origin/main
done
[ -d "$BASE/repo-work/dmarcduck/.git" ] && { git -C "$BASE/repo-work/dmarcduck" remote set-url origin "$GH_URL/dmarcduck.git"; \
  git -C "$BASE/repo-work/dmarcduck" config credential.helper "store --file $BASE/.git-credentials"; \
  git -C "$BASE/repo-work/dmarcduck" fetch -q origin; git -C "$BASE/repo-work/dmarcduck" reset -q --hard origin/main; } || true
# 3) purge GH-Actions YT downloaders (standing rule)
find "$BASE/agent-tools" "$BASE/repo-work" -path "*/.github/workflows/*.yml" -type f 2>/dev/null | \
  xargs -r rg -il "yt-dlp|youtube|pytube" 2>/dev/null | xargs -r rm -fv
find "$BASE/agent-tools" -path "*download-reference*.yml" -o -path "*yt-download-farm*" -name "*.yml" 2>/dev/null | xargs -r rm -fv
# 4) tools
python3 -m pip install -q --break-system-packages yt-dlp 2>/dev/null || pip install -q yt-dlp 2>/dev/null || true
echo "restore done: vfactory @ $(git -C $BASE/vfactory rev-parse --short HEAD)"
