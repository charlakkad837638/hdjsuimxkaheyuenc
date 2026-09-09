(function () {
  "use strict";

  const form = document.getElementById("registration-form");
  const button = form.querySelector("button");
  const displayName = document.getElementById("display-name");
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

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    button.disabled = true;
    showStatus("Preparing passkey registration…");
    try {
      const options = await window.DoorWebAuthn.fetchJSON("/new_user/options", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: displayName.value }),
      });
      const credential = await navigator.credentials.create({
        publicKey: window.DoorWebAuthn.creationOptionsFromJSON(options),
      });
      if (!credential) {
        throw new Error("No passkey was created.");
      }
      await window.DoorWebAuthn.fetchJSON("/new_user/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(window.DoorWebAuthn.credentialToJSON(credential)),
      });
      displayName.disabled = true;
      showStatus("Passkey registered successfully.", "success");
    } catch (error) {
      if (error.name === "NotAllowedError" || error.name === "AbortError") {
        showStatus("Passkey registration was canceled. You can try again.", "error");
      } else {
        showStatus(error.message || "Passkey registration failed.", "error");
      }
      button.disabled = false;
    }
  });
})();
