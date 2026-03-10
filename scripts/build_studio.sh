#!/usr/bin/env bash
# Build Studio UI and copy into hippomem/server/static for packaging.
# Run from project root: ./scripts/build_studio.sh

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Building Studio..."
cd studio
npm run build
cd ..

echo "Copying build to hippomem/server/static..."
rm -rf hippomem/server/static
mkdir -p hippomem/server
cp -r studio/dist hippomem/server/static

echo "Done. Studio UI is at hippomem/server/static/"
