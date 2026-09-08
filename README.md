# hdjsuimxkaheyuenc

#### tailscale
```
sudo systemctl enable tailscaled
sudo systemctl start tailscaled
```

#### ufw

configure-firewall

/usr/local/sbin/configure-firewall
```
#!/bin/bash
set -e

# WARNING: Remove all existing UFW rules.
ufw --force reset

# Default policy
ufw default deny incoming
ufw default allow outgoing

# Allow SSH through private Tailscale.
ufw allow in on tailscale0 to any port 22 proto tcp \
    comment 'SSH through Tailscale'

# Allow SSH from the home LAN through Wi-Fi.
ufw allow in on wlan0 from 192.168.178.0/24 to any port 22 proto tcp \
    comment 'SSH from home LAN'

# HTTP
ufw allow in on tailscale0 to any port 80 proto tcp \
    comment 'HTTP through Tailscale'

ufw allow in on wlan0 from 192.168.178.0/24 to any port 80 proto tcp \
    comment 'HTTP from home LAN'

# Enable the firewall.
ufw --force enable

ufw status verbose
```

#### users
```
sudo adduser \
  --system \
  --group \
  --home /srv/door \
  --shell /usr/sbin/nologin \
  door
```

#### webservice daemon file setup:

/etc/systemd/system/webserver.service
```
[Unit]
Description=web interface
After=network.target

[Service]
Type=simple
User=door
Group=door
WorkingDirectory=/srv/door
ExecStart=/usr/bin/python3 /srv/door/server.py

Restart=on-failure
RestartSec=5

AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
```

```
sudo systemctl daemon-reload
sudo systemctl enable --now webserver.service
```

server file permissions / ownership setup:
```
sudo cp /home/my-user/server.py /srv/door/server.py
sudo chown door:door /srv/door/server.py
sudo chmod 750 /srv/door/server.py
```
