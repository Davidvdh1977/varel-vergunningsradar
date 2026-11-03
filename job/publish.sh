#!/usr/bin/env bash
# Publiceert index.html + kbo-data.json/js op de branch gh-pages (GitHub Pages).
# De branch krijgt telkens één verse commit, zodat de repo niet aangroeit.
# Gebruik: job/publish.sh <map met kbo-data.json en kbo-data.js>
set -euo pipefail
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
SRC=$(cd "$1" && pwd)
W=$(mktemp -d)
cp "$REPO_DIR/index.html" "$SRC/kbo-data.json" "$SRC/kbo-data.js" "$W/"
touch "$W/.nojekyll"
mkdir -p "$W/.github/workflows" && cp "$REPO_DIR/.github/workflows/kbo.yml" "$W/.github/workflows/"  # start de websitezoektocht
cd "$W"
git init -q -b gh-pages
git add -A
git -c user.name="varel-kbo-job" -c user.email="varel-kbo-job@users.noreply.github.com" commit -q -m "KBO-gegevens $(date +%F)"
git push -q -f "$(git -C "$REPO_DIR" remote get-url origin)" gh-pages
rm -rf "$W"
echo "Gepubliceerd op gh-pages"
