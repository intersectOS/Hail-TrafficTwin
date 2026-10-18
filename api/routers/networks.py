"""Edge index endpoints (binary geometry and attributes), keyed by network hash."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from api.edges import ensure_edge_index, index_dir
from api.runs import HEX_RE, network_for_hash, not_available

router = APIRouter(prefix="/api/networks", tags=["networks"])


def _index_file(network_hash: str, name: str) -> FileResponse:
    if not HEX_RE.match(network_hash):
        raise not_available("network")
    path = index_dir(network_hash) / name
    if not path.is_file():
        ensure_edge_index(network_for_hash(network_hash), network_hash)
    media = "application/octet-stream" if name.endswith(".bin") else "application/json"
    return FileResponse(path, media_type=media)


@router.get("/{network_hash}/edges.bin")
def edges_bin(network_hash: str) -> FileResponse:
    return _index_file(network_hash, "edges.bin")


@router.get("/{network_hash}/edges.json")
def edges_json(network_hash: str) -> FileResponse:
    return _index_file(network_hash, "edges.json")
