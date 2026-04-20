#!/usr/bin/env bash
set -euo pipefail

URL="https://www.youtube.com/watch?v=LI--daqSSUY"
case "${1:-}" in
  --url)
    if [ "$#" -lt 2 ] || [ -z "${2:-}" ]; then
      echo "error: --url requires a value" >&2
      exit 2
    fi
    URL="$2"
    shift 2
    ;;
  --url=*)
    URL="${1#--url=}"
    shift 1
    ;;
  -*)
    ;;
  "")
    ;;
  *)
    URL="$1"
    shift 1
    ;;
esac
CONTAINER="${OPENCLAW_CONTAINER:-openclaw-openclaw-gateway-1}"
WORKSPACE="${OPENCLAW_WORKSPACE:-/home/node/.openclaw/workspace}"
IMAGE="${OPENCLAW_IMAGE:-openclaw:local}"
LOCAL_LIBS_VOLUME="${OPENCLAW_LOCAL_LIBS_VOLUME:-openclaw-extract-slides-from-video-local-libs}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
HOST_RUNTIME_ROOT="${HOST_RUNTIME_ROOT:-$HOST_WORKSPACE_ROOT/.openclaw-tmp/extract-slides-from-video}"
HOST_RUNTIME_RUNS="$HOST_RUNTIME_ROOT/runs"

mkdir -p "$HOST_RUNTIME_RUNS"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "error: container not found: $CONTAINER" >&2
  exit 1
fi

docker exec -u root "$CONTAINER" sh -lc '
  set -e
  runtime_root="/home/node/.openclaw/workspace/.openclaw-tmp/extract-slides-from-video"
  mkdir -p "$runtime_root"
  if [ -e /tmp/extract-slides-from-video ] && [ ! -L /tmp/extract-slides-from-video ]; then
    rm -rf /tmp/extract-slides-from-video
  fi
  ln -sfn "$runtime_root" /tmp/extract-slides-from-video
'

docker run --rm -u root --volumes-from "$CONTAINER" -v "$HOST_RUNTIME_RUNS:/tmp/extract-slides-from-video/runs" -v "$LOCAL_LIBS_VOLUME:/tmp/extract-slides-from-video/.local-libs" -w "$WORKSPACE" -e URL="$URL" "$IMAGE" sh -lc '
  set -e
  export PATH="/tmp/extract-slides-from-video/.local-libs/bin:$PATH"
  if ! command -v yt-dlp >/dev/null 2>&1; then
    python3 -m pip install --disable-pip-version-check --root-user-action=ignore --upgrade --target /tmp/extract-slides-from-video/.local-libs -q yt-dlp
  fi
  python3 skills/extract-slides-from-video/handler.py --url "$URL" "$@"
' sh "$@"
