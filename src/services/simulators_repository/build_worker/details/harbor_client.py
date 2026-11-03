import base64
import http.client
from typing import Optional
from urllib.parse import urlparse


def _parse_registry(registry: str) -> tuple[str, str]:
    if registry.startswith("http://") or registry.startswith("https://"):
        parsed = urlparse(registry)
    else:
        parsed = urlparse(f"http://{registry}")
    scheme = parsed.scheme or "https"
    host = parsed.netloc or parsed.path
    return scheme, host


def get_manifest_digest(
    registry: str,
    project: str,
    repository: str,
    tag: str,
    username: str,
    password: str,
) -> Optional[str]:
    scheme, host = _parse_registry(registry)
    if scheme == "https":
        conn = http.client.HTTPSConnection(host)
    else:
        conn = http.client.HTTPConnection(host)

    repo_path = f"{project}/{repository}".strip("/")
    path = f"/v2/{repo_path}/manifests/{tag}"

    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    headers = {
        "Authorization": f"Basic {token}",
        "Accept": (
            "application/vnd.oci.image.manifest.v1+json,"
            "application/vnd.docker.distribution.manifest.v2+json"
        ),
    }

    conn.request("HEAD", path, headers=headers)
    resp = conn.getresponse()
    if resp.status >= 400:
        conn.close()
        raise RuntimeError(f"Registry digest lookup failed: {resp.status} {resp.reason}")

    digest = resp.getheader("Docker-Content-Digest")
    conn.close()
    return digest
