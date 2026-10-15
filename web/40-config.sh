#!/bin/sh
set -eu
# API_BASE is a URL/path, limited to URL-safe characters before JS interpolation.
case "$API_BASE" in *[!a-zA-Z0-9:/._-]*) echo 'Invalid API_BASE' >&2; exit 1;; esac
printf 'window.PLAYMAKERS_CONFIG={"apiBase":"%s"};\n' "$API_BASE" > /usr/share/nginx/html/config.js
