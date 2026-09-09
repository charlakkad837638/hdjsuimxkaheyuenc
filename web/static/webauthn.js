(function () {
  "use strict";

  function base64UrlToBytes(value) {
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(base64);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  }

  function bytesToBase64Url(value) {
    const bytes = new Uint8Array(value);
    let binary = "";
    for (const byte of bytes) {
      binary += String.fromCharCode(byte);
    }
    return btoa(binary)
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/g, "");
  }

  function creationOptionsFromJSON(options) {
    return {
      ...options,
      challenge: base64UrlToBytes(options.challenge),
      user: {
        ...options.user,
        id: base64UrlToBytes(options.user.id),
      },
      excludeCredentials: (options.excludeCredentials || []).map((credential) => ({
        ...credential,
        id: base64UrlToBytes(credential.id),
      })),
    };
  }

  function requestOptionsFromJSON(options) {
    return {
      ...options,
      challenge: base64UrlToBytes(options.challenge),
      allowCredentials: (options.allowCredentials || []).map((credential) => ({
        ...credential,
        id: base64UrlToBytes(credential.id),
      })),
    };
  }

  function credentialToJSON(credential) {
    const base = {
      id: credential.id,
      rawId: bytesToBase64Url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(),
    };
    if ("attestationObject" in credential.response) {
      return {
        ...base,
        response: {
          clientDataJSON: bytesToBase64Url(credential.response.clientDataJSON),
          attestationObject: bytesToBase64Url(credential.response.attestationObject),
          transports:
            typeof credential.response.getTransports === "function"
              ? credential.response.getTransports()
              : [],
        },
      };
    }
    return {
      ...base,
      response: {
        clientDataJSON: bytesToBase64Url(credential.response.clientDataJSON),
        authenticatorData: bytesToBase64Url(credential.response.authenticatorData),
        signature: bytesToBase64Url(credential.response.signature),
        userHandle: credential.response.userHandle
          ? bytesToBase64Url(credential.response.userHandle)
          : null,
      },
    };
  }

  async function fetchJSON(url, options) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
    });
    let body = {};
    try {
      body = await response.json();
    } catch (_error) {
      body = {};
    }
    if (!response.ok) {
      const message = body.error && body.error.message;
      throw new Error(message || `Request failed (${response.status})`);
    }
    return body;
  }

  function isSupported() {
    return Boolean(window.PublicKeyCredential && navigator.credentials);
  }

  window.DoorWebAuthn = {
    creationOptionsFromJSON,
    requestOptionsFromJSON,
    credentialToJSON,
    fetchJSON,
    isSupported,
  };
})();
