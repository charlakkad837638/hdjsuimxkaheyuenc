from pathlib import Path

import pytest

from app.config import ConfigError, Settings


def test_settings_load_local_dotenv_without_overriding_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_env = tmp_path / ".env"
    local_env.write_text(
        "\n".join(
            (
                "PUBLIC_ORIGIN=https://file.example.ts.net",
                "ADMIN_HOSTS=door.local,192.168.178.20",
                "ADMIN_USERNAME=door-admin",
                "ADMIN_PASSWORD=test-password",
                "LAN_CIDR=10.0.0.0/24",
                f"DATA_DIR={tmp_path}",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.config.LOCAL_ENV_FILE", local_env)
    for name in (
        "PUBLIC_ORIGIN",
        "ADMIN_HOSTS",
        "ADMIN_USERNAME",
        "ADMIN_PASSWORD",
        "LAN_CIDR",
        "DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://environment.example.ts.net")

    settings = Settings.from_env()

    assert settings.public_origin == "https://environment.example.ts.net"
    assert settings.admin_hosts == ("door.local", "192.168.178.20")
    assert settings.admin_username == "door-admin"
    assert settings.admin_password == "test-password"
    assert str(settings.lan_network) == "10.0.0.0/24"
    assert settings.data_dir == tmp_path


def test_settings_derive_rp_id_and_defaults(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "PUBLIC_ORIGIN": "https://door.example.ts.net",
            "ADMIN_HOSTS": "door.local,192.168.178.20",
            "ADMIN_USERNAME": "door-admin",
            "ADMIN_PASSWORD": "test-password",
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
        ("ADMIN_USERNAME", ""),
        ("ADMIN_USERNAME", "admin:user"),
        ("ADMIN_PASSWORD", ""),
        ("LAN_CIDR", "not-a-network"),
        ("DATA_DIR", "relative"),
    ],
)
def test_settings_reject_invalid_values(tmp_path: Path, name: str, value: str) -> None:
    environ = {
        "PUBLIC_ORIGIN": "https://door.example.ts.net",
        "ADMIN_HOSTS": "door.local",
        "ADMIN_USERNAME": "door-admin",
        "ADMIN_PASSWORD": "test-password",
        "LAN_CIDR": "192.168.178.0/24",
        "DATA_DIR": str(tmp_path),
    }
    environ[name] = value

    with pytest.raises(ConfigError):
        Settings.from_env(environ)
