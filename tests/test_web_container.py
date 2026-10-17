from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
TEMP_PATHS = ("client_body", "proxy", "fastcgi", "uwsgi", "scgi")
NGINX = shutil.which("nginx") or ("/usr/sbin/nginx" if Path("/usr/sbin/nginx").exists() else None)


def configure(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "html").mkdir(exist_ok=True)
    return subprocess.run(
        ["sh", str(WEB / "40-config.sh")],
        env={
            "PATH": os.environ["PATH"],
            "PLAYMAKERS_HTML_DIR": str(tmp_path / "html"),
            "PLAYMAKERS_PROXY_DIR": str(tmp_path / "proxy"),
            **env,
        },
        capture_output=True,
        text=True,
    )


def test_default_image_proxies_api_for_docker_compose(tmp_path: Path) -> None:
    assert configure(tmp_path, API_BASE="/api").returncode == 0
    assert (tmp_path / "html" / "config.js").read_text() == (
        'window.PLAYMAKERS_CONFIG={"apiBase":"/api"};\n'
    )
    proxy = (tmp_path / "proxy" / "api.conf").read_text()
    assert "proxy_pass http://api:8000/;" in proxy
    assert "proxy_buffering off;" in proxy


def test_configurable_upstream_and_direct_api_base(tmp_path: Path) -> None:
    result = configure(tmp_path, API_BASE="/api", API_UPSTREAM="http://ca-api.internal:8000/")
    assert result.returncode == 0
    assert "proxy_pass http://ca-api.internal:8000/;" in (tmp_path / "proxy/api.conf").read_text()
    direct = configure(tmp_path, API_BASE="https://ca-playmakers-api.example.io", API_UPSTREAM="")
    assert direct.returncode == 0
    assert not (tmp_path / "proxy" / "api.conf").exists()
    assert (
        '"apiBase":"https://ca-playmakers-api.example.io"'
        in (tmp_path / "html" / "config.js").read_text()
    )


@pytest.mark.parametrize("upstream", ["api:8000", "http://api;evil", "ftp://api", "http://"])
def test_unsafe_upstreams_are_refused(tmp_path: Path, upstream: str) -> None:
    result = configure(tmp_path, API_BASE="/api", API_UPSTREAM=upstream)
    assert result.returncode == 1
    assert "Invalid API_UPSTREAM" in result.stderr


@pytest.mark.skipif(NGINX is None, reason="nginx is not installed")
def test_nginx_accepts_the_config_without_an_api_host(tmp_path: Path) -> None:
    assert configure(tmp_path, API_BASE="https://api.example.io", API_UPSTREAM="").returncode == 0
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = (
        (WEB / "nginx.conf")
        .read_text()
        .replace("/etc/nginx/playmakers", str(tmp_path / "proxy"))
        .replace("listen 80;", f"listen 127.0.0.1:{port};")
    )
    (tmp_path / "server.conf").write_text(server)
    (tmp_path / "nginx.conf").write_text(
        f"pid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/error.log;\n"
        "events {}\nhttp { access_log off; "
        + "".join(f"{name}_temp_path {tmp_path}/{name}; " for name in TEMP_PATHS)
        + f"include {tmp_path}/server.conf; }}\n"
    )
    command = [NGINX, "-t", "-p", str(tmp_path), "-c", str(tmp_path / "nginx.conf")]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
