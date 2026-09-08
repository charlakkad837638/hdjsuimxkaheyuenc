#!/usr/bin/env python3

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Listen on every network interface:
# - 127.0.0.1
# - wlan0 (local network)
# - tailscale0 (private Tailscale network)
HOST = "0.0.0.0"
PORT = 80


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return

        body = b"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Raspberry Pi IoT Device</title>
</head>
<body>
  <h1>It works!</h1>
  <p>This page is being served by the Raspberry Pi.</p>
</body>
</html>
"""

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(
            f"{self.client_address[0]} - {format % args}",
            flush=True,
        )


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Listening on http://{HOST}:{PORT}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
