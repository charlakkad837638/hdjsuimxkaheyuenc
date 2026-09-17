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

## OLED system status display

The SSD1306 display switches through three pages:

```text
~~NETWORK~~
WiFi: -57 dBm
LAN: 192.168.178.33
Tailscale: connected
TS IP: 100.64.1.2
```

```text
~~SYSTEM~~
CPU: 18%
Memory: 43%
Uptime: 3d 6h
```

```text
~~WEBSERVER~~
State: active
Process: running
Uptime: 2h 14m
Restarts: 0
```

Known negative states are written explicitly, such as `WiFi: down`,
`Tailscale: down`, or `State: inactive`. A value that cannot be read or parsed
is shown as the literal `[UNKOWN]`. CPU usage shows `measuring...` until two
samples are available.

The implementation assumes:

- an SSD1306 128×64 display on I²C bus 1 at address `0x3C`;
- the Wi-Fi interface is named `wlan0`;
- the web service is named `webserver.service`;
- `ip`, `tailscale`, and `systemctl` are installed.

Enable I²C before installing the service. On Raspberry Pi OS this can be done
through `sudo raspi-config`; reboot if that tool requests it. Create the
unprivileged display account if it does not already exist:

```sh
sudo adduser \
  --system \
  --group \
  --home /nonexistent \
  --no-create-home \
  --shell /usr/sbin/nologin \
  oled
```

Set the number of seconds each page remains visible:

```sh
sudoedit /etc/oled-display.env
```

```ini
OLED_PAGE_SECONDS=4
```

Values from 1 through 300 seconds are accepted, including decimal values. A
missing or invalid value produces one journal warning and uses the four-second
default.

Install or update the unit after deploying the project to `/srv/door`:

```sh
sudo install -o root -g root -m 0644 \
  oled_display.service /etc/systemd/system/oled_display.service
sudo systemctl daemon-reload
sudo systemctl enable oled_display.service
sudo systemctl restart oled_display.service
sudo systemctl status oled_display.service --no-pager
```

Changing only `/etc/oled-display.env` requires a service restart, not
`daemon-reload` or a system reboot:

```sh
sudoedit /etc/oled-display.env
sudo systemctl restart oled_display.service
```

CPU is sampled every 2 seconds, memory and uptime every 5 seconds, and network,
Tailscale, and webserver status every 10 seconds. The eight-step countdown bar
updates at most twice per second. The SSD1306 adapter transfers only changed
pages and columns after the first frame, avoiding unnecessary full-frame I²C
writes.

The service logs startup, shutdown, state changes, unavailable values, and
recoveries to journald. It does not log routine polling or redraws. Journald
handles rotation and retention; no application log file or `logrotate`
configuration is required.

```sh
sudo journalctl -u oled_display.service -n 50 --no-pager
sudo journalctl -u oled_display.service -f
journalctl --disk-usage
```

For an initial hardware check:

```sh
sudo i2cdetect -y 1
```

The display should appear at address `3c`. To inspect steady-state resource
usage after the service has run for at least one minute:

```sh
pid="$(systemctl show -p MainPID --value oled_display.service)"
ps -p "$pid" -o pid,%cpu,rss,etime,cmd
```

Expected Raspberry Pi 4B usage is below 2% of one CPU core and below 64 MiB
RSS. Persistent repeated journal errors, higher steady-state use, or more than
two normal display redraws per second should be investigated before deployment.