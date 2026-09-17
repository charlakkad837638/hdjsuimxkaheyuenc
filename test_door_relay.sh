#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
GPIO_DEVICE=/dev/gpiochip0

if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
elif [ -x /srv/door/.venv/bin/python ]; then
    PYTHON=/srv/door/.venv/bin/python
else
    echo "Missing Python virtual environment in $PROJECT_DIR/.venv or /srv/door/.venv." >&2
    exit 1
fi

if ! "$PYTHON" -c "import gpiozero, lgpio" >/dev/null 2>&1; then
    echo "The selected virtual environment is missing gpiozero or lgpio." >&2
    echo "Install them with:" >&2
    echo "  sudo $PYTHON -m pip install -r $PROJECT_DIR/requirements.txt" >&2
    exit 1
fi

if [ ! -r "$GPIO_DEVICE" ] || [ ! -w "$GPIO_DEVICE" ]; then
    echo "Cannot access $GPIO_DEVICE; run this script with sudo." >&2
    exit 1
fi

if command -v systemctl >/dev/null 2>&1 \
    && systemctl is-active --quiet webserver.service; then
    echo "webserver.service owns GPIO17; stop it before running this test." >&2
    exit 1
fi

export GPIOZERO_PIN_FACTORY=lgpio
cd "$PROJECT_DIR"

echo "Pulsing the door relay on BCM GPIO17 for one second..."
"$PYTHON" - <<'PY'
from app.services.credentials import CredentialRecord
from app.services.door_action import RelayDoorAction


action = RelayDoorAction()
try:
    action.execute(
        CredentialRecord(
            user_id=b"manual-relay-test",
            display_name="Manual relay test",
            credential_id=b"manual-relay-test",
            credential_public_key=b"manual-relay-test",
            sign_count=0,
            transports=(),
            created_at="manual-test",
        )
    )
finally:
    action.close()
PY
echo "Relay test completed; GPIO17 is LOW."
