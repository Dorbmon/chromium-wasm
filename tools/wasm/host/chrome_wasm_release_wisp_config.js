// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This is the public, versioned release-host configuration boundary for WISP.
// An operator may install this exact global data property before starting the
// release host. There is intentionally no endpoint default: an omitted input
// leaves Chromium networking unavailable, and this module never substitutes
// the page Fetch API for Chromium networking.
export const RELEASE_WISP_CONFIGURATION_GLOBAL =
    "__chromiumWasmReleaseWispV1";
export const RELEASE_WISP_CONFIGURATION_VERSION = 1;

const MAX_ENDPOINT_CHARACTERS = 2048;
const ALLOWED_CONFIGURATION_FIELDS = new Set([
  "version",
  "endpoint",
]);

function requiredDataProperty(configuration, name) {
  const descriptor = Object.getOwnPropertyDescriptor(configuration, name);
  if (descriptor === undefined) {
    throw new Error(`release WISP configuration is missing ${name}`);
  }
  if (!Object.hasOwn(descriptor, "value")) {
    throw new Error(`release WISP configuration ${name} must be a data property`);
  }
  return descriptor.value;
}

// Normalize an operator-controlled JSON-shaped value before it becomes an
// Emscripten Module option. The WISP bridge owns its runtime limits; this
// public release input only selects a secure, credential-free carrier.
export function normalizeReleaseWispConfiguration(configuration) {
  if (configuration === undefined) {
    return undefined;
  }
  if (!configuration || typeof configuration !== "object" ||
      Array.isArray(configuration)) {
    throw new Error("release WISP configuration must be an object");
  }
  const prototype = Object.getPrototypeOf(configuration);
  if (prototype !== Object.prototype && prototype !== null) {
    throw new Error("release WISP configuration must be a plain object");
  }
  if (Object.getOwnPropertySymbols(configuration).length !== 0) {
    throw new Error("release WISP configuration must not contain symbols");
  }
  for (const field of Object.getOwnPropertyNames(configuration)) {
    if (!ALLOWED_CONFIGURATION_FIELDS.has(field)) {
      throw new Error("release WISP configuration field is not allowed");
    }
  }

  const version = requiredDataProperty(configuration, "version");
  if (version !== RELEASE_WISP_CONFIGURATION_VERSION) {
    throw new Error("release WISP configuration version is unsupported");
  }
  const endpointValue = requiredDataProperty(configuration, "endpoint");
  if (typeof endpointValue !== "string" || endpointValue.length === 0 ||
      endpointValue.length > MAX_ENDPOINT_CHARACTERS) {
    throw new Error("release WISP endpoint must be a bounded URL string");
  }

  let endpoint;
  try {
    endpoint = new URL(endpointValue);
  } catch (_) {
    throw new Error("release WISP endpoint is not a valid absolute URL");
  }
  if (endpoint.protocol !== "wss:" || !endpoint.hostname ||
      endpoint.username || endpoint.password || endpoint.search ||
      endpoint.hash || !endpoint.pathname.endsWith("/") ||
      endpoint.href.length > MAX_ENDPOINT_CHARACTERS) {
    throw new Error("release WISP endpoint violates the transport policy");
  }

  const normalized = {
    version: RELEASE_WISP_CONFIGURATION_VERSION,
    endpoint: endpoint.href,
  };
  return Object.freeze(normalized);
}

// Reads only an own data property. An inherited or accessor-backed value is
// not an explicit release-host input and is rejected instead of being invoked.
export function loadReleaseWispConfiguration(globalObject = globalThis) {
  if (!globalObject || (typeof globalObject !== "object" &&
                        typeof globalObject !== "function")) {
    throw new Error("release WISP configuration global is invalid");
  }
  const descriptor = Object.getOwnPropertyDescriptor(
      globalObject, RELEASE_WISP_CONFIGURATION_GLOBAL);
  if (descriptor === undefined) {
    return undefined;
  }
  if (!Object.hasOwn(descriptor, "value")) {
    throw new Error("release WISP configuration global must be a data property");
  }
  return normalizeReleaseWispConfiguration(descriptor.value);
}
