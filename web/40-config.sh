#!/bin/sh
set -eu
HTML_DIR="${PLAYMAKERS_HTML_DIR:-/usr/share/nginx/html}"
PROXY_DIR="${PLAYMAKERS_PROXY_DIR:-/etc/nginx/playmakers}"
API_UPSTREAM="${API_UPSTREAM-http://api:8000}"
# API_BASE is a URL/path, limited to URL-safe characters before JS interpolation.
case "$API_BASE" in *[!a-zA-Z0-9:/._-]*) echo 'Invalid API_BASE' >&2; exit 1;; esac
printf 'window.PLAYMAKERS_CONFIG={"apiBase":"%s"};\n' "$API_BASE" > "$HTML_DIR/config.js"
mkdir -p "$PROXY_DIR"
rm -f "$PROXY_DIR/api.conf"
[ -n "$API_UPSTREAM" ] || exit 0
case "$API_UPSTREAM" in
  *[!a-zA-Z0-9:/._-]*) echo 'Invalid API_UPSTREAM' >&2; exit 1;;
  http://?*|https://?*) ;;
  *) echo 'Invalid API_UPSTREAM' >&2; exit 1;;
esac
printf 'location /api/ {\n    proxy_pass %s/;\n    proxy_buffering off;\n    proxy_read_timeout 3600s;\n}\n' "${API_UPSTREAM%/}" > "$PROXY_DIR/api.conf"
