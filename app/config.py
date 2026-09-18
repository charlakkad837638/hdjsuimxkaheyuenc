from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from dotenv import load_dotenv


LOCAL_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class ConfigError(ValueError):
    """Raised when required application configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    public_origin: str
    rp_id: str
    lan_network: ipaddress.IPv4Network | ipaddress.IPv6Network
    admin_hosts: tuple[str, ...]
    admin_username: str
    admin_password: str = field(repr=False)
    data_dir: Path

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.rp_id, *self.admin_hosts)))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        if environ is None:
            load_dotenv(LOCAL_ENV_FILE, override=False)
            values = os.environ
        else:
            values = environ

        public_origin = values.get("PUBLIC_ORIGIN", "").strip()
        if not public_origin:
            raise ConfigError("PUBLIC_ORIGIN is required")

        parsed = urlsplit(public_origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigError(
                "PUBLIC_ORIGIN must be an HTTPS origin without credentials, "
                "path, query, fragment, or trailing slash"
            )

        admin_hosts_value = values.get("ADMIN_HOSTS", "").strip()
        if not admin_hosts_value:
            raise ConfigError("ADMIN_HOSTS is required")
        admin_hosts = tuple(
            dict.fromkeys(host.strip().lower() for host in admin_hosts_value.split(",") if host.strip())
        )
        if not admin_hosts or any(
            "/" in host or "://" in host or any(char.isspace() for char in host)
            for host in admin_hosts
        ):
            raise ConfigError("ADMIN_HOSTS must be a comma-separated list of hostnames or IP addresses")

        admin_username = values.get("ADMIN_USERNAME", "")
        if not admin_username:
            raise ConfigError("ADMIN_USERNAME is required")
        if not admin_username.isascii() or ":" in admin_username:
            raise ConfigError("ADMIN_USERNAME must be ASCII and cannot contain ':'")

        admin_password = values.get("ADMIN_PASSWORD", "")
        if not admin_password:
            raise ConfigError("ADMIN_PASSWORD is required")
        if not admin_password.isascii():
            raise ConfigError("ADMIN_PASSWORD must be ASCII")

        lan_cidr = values.get("LAN_CIDR", "192.168.178.0/24").strip()
        try:
            lan_network = ipaddress.ip_network(lan_cidr, strict=False)
        except ValueError as exc:
            raise ConfigError(f"LAN_CIDR is invalid: {lan_cidr}") from exc

        data_dir = Path(values.get("DATA_DIR", "/var/lib/door")).expanduser()
        if not data_dir.is_absolute():
            raise ConfigError("DATA_DIR must be an absolute path")

        return cls(
            public_origin=public_origin,
            rp_id=parsed.hostname.lower(),
            lan_network=lan_network,
            admin_hosts=admin_hosts,
            admin_username=admin_username,
            admin_password=admin_password,
            data_dir=data_dir,
        )
