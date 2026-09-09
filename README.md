# hdjsuimxkaheyuenc


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

```
sudo systemctl daemon-reload
sudo systemctl enable --now webserver.service
```

server file permissions / ownership setup:
```
sudo chown door:door /srv/door/server.py
sudo chmod 750 /srv/door/server.py
```

## shut down the pi
```
sudo shutdown -h now
```

## install for the first time
```
cd ~/hdjsuimxkaheyuenc
git pull --ff-only
sudo systemctl stop webserver.service
sudo rsync -a --delete \
  --exclude .git \
  --exclude .venv \
  --exclude .env \
  ./ /srv/door/
```

## restarting / pulling

```
git -C ~/hdjsuimxkaheyuenc pull --ff-only
```

```
sudo systemctl start webserver.service
sudo systemctl status webserver.service
```