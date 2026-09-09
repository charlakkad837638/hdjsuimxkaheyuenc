from pathlib import Path

import pytest

from app.config import ConfigError, Settings


def test_settings_derive_rp_id_and_defaults(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "PUBLIC_ORIGIN": "https://door.example.ts.net",
            "ADMIN_HOSTS": "door.local,192.168.178.20",
            "DATA_DIR": str(tmp_path),
        }
    )

    assert settings.rp_id == "door.example.ts.net"
    assert str(settings.lan_network) == "192.168.178.0/24"
    assert settings.allowed_hosts == (
        "door.example.ts.net",
        "door.local",
        "192.168.178.20",
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PUBLIC_ORIGIN", ""),
        ("PUBLIC_ORIGIN", "http://door.example.ts.net"),
        ("PUBLIC_ORIGIN", "https://door.example.ts.net/"),
        ("ADMIN_HOSTS", ""),
        ("LAN_CIDR", "not-a-network"),
        ("DATA_DIR", "relative"),
    ],
)
def test_settings_reject_invalid_values(tmp_path: Path, name: str, value: str) -> None:
    environ = {
        "PUBLIC_ORIGIN": "https://door.example.ts.net",
        "ADMIN_HOSTS": "door.local",
        "LAN_CIDR": "192.168.178.0/24",
        "DATA_DIR": str(tmp_path),
    }
    environ[name] = value

    with pytest.raises(ConfigError):
        Settings.from_env(environ)
