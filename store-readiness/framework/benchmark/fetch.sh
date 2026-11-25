#!/bin/bash
# Fetch the benchmark corpus at the pinned commits into ./corpus/<app name>. Needs network access to GitHub.
set -e
cd "$(dirname "$0")"
mkdir -p corpus
export GIT_LFS_SKIP_SMUDGE=1 GIT_TERMINAL_PROMPT=0
python3 - <<'PY' | while read -r name repo sha; do
import json
for a in json.load(open("real_apps.json"))["apps"]:
    print(a["name"], a["repo"], a["commit"])
PY
  if [ -d "corpus/$name/.git" ]; then echo "have $name"; continue; fi
  mkdir -p "corpus/$name" && cd "corpus/$name"
  git init -q && git remote add origin "https://github.com/$repo"
  git fetch -q --depth 1 origin "$sha" && git checkout -q FETCH_HEAD && echo "fetched $name @ $sha" || echo "FAILED $name"
  cd ../..
done
