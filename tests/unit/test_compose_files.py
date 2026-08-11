"""docker-compose.split.yml duplicates a little of docker-compose.yml on
purpose — YAML anchors cannot span files, and compose `extends:` would make the
split services inherit `command:` and `ports:` that both have to be overridden.

The duplication that actually matters is the image reference: bump it in one
file, forget the other, and the split layout quietly runs a different build.
These lock that down rather than relying on remembering."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text())


def _images(doc: dict) -> set[str]:
    return {
        svc["image"]
        for svc in doc["services"].values()
        if isinstance(svc.get("image"), str) and svc["image"].startswith("ghcr.io/")
    }


def test_split_and_base_reference_the_same_image():
    assert _images(_load("docker-compose.yml")) == _images(_load("docker-compose.split.yml"))


def test_base_defines_exactly_one_service():
    """The whole point of the change. A second service reappearing here means
    the collapse was partially reverted."""
    assert list(_load("docker-compose.yml")["services"]) == ["yas"]


def test_split_defines_the_two_container_layout():
    assert sorted(_load("docker-compose.split.yml")["services"]) == ["yas-api", "yas-worker"]


def test_overlays_target_the_base_service_name():
    """Compose ADDS a service an override names but the base lacks rather than
    erroring, so a stale name here yields a phantom service — dev.yml's would
    even carry `build:`, letting a local-source check pass while the real
    service still pulls from GHCR."""
    base = set(_load("docker-compose.yml")["services"])
    for overlay in ("docker-compose.dev.yml", "docker-compose.macos.yml"):
        named = set(_load(overlay)["services"])
        assert named <= base, f"{overlay} names services absent from the base: {named - base}"


def test_base_runs_all_mode():
    """Single-container deployment depends on `all`; `api` or `worker` here
    would silently ship half the system."""
    assert _load("docker-compose.yml")["services"]["yas"]["command"] == [
        "python",
        "-m",
        "yas",
        "all",
    ]
