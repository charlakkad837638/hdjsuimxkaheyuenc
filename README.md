# hdjsuimxkaheyuenc

## Cloudflare Tunnel

Public access uses the remotely managed Cloudflare Tunnel. The dashboard route forwards only
that hostname to `http://127.0.0.1:80`, ends with an `http_status:404` rule,
and has WARP routing disabled.

The checked-in `cloudflared.service` runs as an unprivileged account, receives
the root-owned tunnel token through systemd credentials, and exposes its
readiness endpoint only at `http://127.0.0.1:60123/ready`.

```sh
sudo adduser \
  --system \
  --group \
  --home /nonexistent \
  --no-create-home \
  --shell /usr/sbin/nologin \
  cloudflared
sudo install -o root -g root -m 0644 \
  cloudflared.service /etc/systemd/system/cloudflared.service
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared.service
curl -fsS http://127.0.0.1:60123/ready
```

Keep `/etc/cloudflared/token` owned by root with mode `0600`; never commit or
print it. Update the package through APT and restart the service during a
maintenance window. Rotating the public hostname requires re-enrolling all
passkeys because WebAuthn credentials are bound to the hostname.

Protect the Cloudflare account with MFA and narrowly scoped API tokens. The Pi
needs only its tunnel token. If rate limiting is enabled, apply conservative
limits to the authentication and registration POST routes; do not apply
browser challenges to those JSON routes or the OLED health probe.

## Firewall

`configure-firewall` resets UFW and permits SSH and HTTP only from the home LAN
on `wlan0`. Cloudflare Tunnel makes outbound connections and requires no
inbound firewall rule.

```sh
sudo install -o root -g root -m 0755 \
  configure-firewall /usr/local/sbin/configure-firewall
sudo /usr/local/sbin/configure-firewall
```

## Service users
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

## door relay

The Adafruit STEMMA non-latching relay uses connections separate from the OLED:

- red/VCC: physical pin 17 (3.3V);
- black/GND: physical pin 9;
- white/signal: physical pin 11 (BCM GPIO17).

After successful `/open` authentication, the webserver pulses active-high
BCM GPIO17 for five seconds and always restores it LOW. BCM GPIO2 and GPIO3
remain reserved for the OLED's I²C connection.

Install the updated dependencies and unit when deploying:

```sh
sudo /srv/door/.venv/bin/pip install -r /srv/door/requirements.txt
sudo install -o root -g root -m 0644 \
  webserver.service /etc/systemd/system/webserver.service
sudo systemctl daemon-reload
sudo systemctl restart webserver.service
```

The webserver unit receives the `gpio` supplementary group and access only to
`/dev/gpiochip0`. The OLED unit remains restricted to `/dev/i2c-1`.

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

## local webserver check

Run this on the Raspberry Pi:

```sh
curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' \
  -H 'Host: 192.168.178.33' \
  http://127.0.0.1/door
```

The expected response is `HTTP 200`. An explicit allowed `Host` header is
required because `localhost` is not listed in `ADMIN_HOSTS`.

## OLED system status display

The SSD1306 display switches through three pages:

```text
~~NETWORK~~
WiFi: -57 dBm
LAN: 192.168.178.33
Tunnel: connected
Public: online
```

```text
~~SYSTEM~~
CPU: 18%
Memory: 43%
Uptime: 3d 6h
12.3G used / 45.7G free
```

```text
~~WEBSERVER~~
State: active
Process: running
Uptime: 2h 14m
Restarts: 0
```

Known negative states are written explicitly, such as `WiFi: down`,
`Tunnel: down`, `Public: down`, or `State: inactive`. A value that cannot be
read or parsed is shown as the literal `[UNKOWN]`. CPU usage shows
`measuring...` until two samples are available.

The implementation assumes:

- an SSD1306 128×64 display on I²C bus 1 at address `0x3C`;
- the Wi-Fi interface is named `wlan0`;
- the web service is named `webserver.service`;
- the cloudflared readiness endpoint is listening on loopback port `60123`;
- `ip` and `systemctl` are installed.

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
sudo install -o root -g root -m 0600 \
  oled-display.env.example /etc/oled-display.env
sudoedit /etc/oled-display.env
```

```ini
OLED_PAGE_SECONDS=4
OLED_TUNNEL_READY_URL=http://127.0.0.1:60123/ready
OLED_PUBLIC_HEALTH_URL=https://tunnel.url
```

Values from 1 through 300 seconds are accepted, including decimal values. A
missing or invalid value produces one journal warning and uses the four-second
default. The tunnel URL must use loopback HTTP, while the public health URL
must use HTTPS.

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

CPU is sampled every 2 seconds, memory and uptime every 5 seconds, and local
network, tunnel readiness, and webserver status every 10 seconds. Public HTTPS
health is checked every 60 seconds. Root-filesystem used and free storage are
shown in decimal GiB and refreshed every 10 minutes. The eight-step countdown
bar updates at most twice per second. The SSD1306 adapter transfers only
changed pages and columns after the first frame, avoiding unnecessary
full-frame I²C writes.

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


# copy installed code

`sudo rsync -a --delete \
  --exclude .git \
  --exclude .venv \
  --exclude .env \
  ./ /srv/door/`