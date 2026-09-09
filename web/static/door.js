(function () {
  "use strict";

  const button = document.getElementById("open-door");
  const status = document.getElementById("status");

  function showStatus(message, kind) {
    status.textContent = message;
    status.className = `status ${kind || ""}`;
  }

  if (!window.DoorWebAuthn.isSupported()) {
    button.disabled = true;
    showStatus("This browser does not support passkeys.", "error");
    return;
  }

  button.addEventListener("click", async function () {
    button.disabled = true;
    showStatus("Waiting for passkey…");
    try {
      const options = await window.DoorWebAuthn.fetchJSON("/open/options", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const credential = await navigator.credentials.get({
        publicKey: window.DoorWebAuthn.requestOptionsFromJSON(options),
      });
      if (!credential) {
        throw new Error("No passkey was returned.");
      }
      await window.DoorWebAuthn.fetchJSON("/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(window.DoorWebAuthn.credentialToJSON(credential)),
      });
      showStatus(
        "Authentication succeeded. The door action is currently disabled.",
        "success",
      );
    } catch (error) {
      if (error.name === "NotAllowedError" || error.name === "AbortError") {
        showStatus("Passkey authentication was canceled.", "error");
      } else {
        showStatus(error.message || "Passkey authentication failed.", "error");
      }
    } finally {
      button.disabled = false;
    }
  });
})();
