// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Dedicated-worker half of the isolated M7 Web Locks scope probe. This file
// deliberately never opens OPFS, creates a SyncAccessHandle, or exposes a
// filesystem operation. It exercises only browser-owned named Web Locks.

const PROTOCOL = 1;
const HOLDER_ROLE = "holder";
const CONTENDER_ROLE = "contender";
const EXPLICIT_PURPOSE = "explicit";
const TERMINATION_PURPOSE = "termination";
const RUN_NAMESPACE_RE = /^[A-Za-z0-9_-]{16,128}$/;
const LOCK_NAME_RE = /^chromium-wasm-m7-web-locks-[A-Za-z0-9._:/-]{16,256}$/;

const state = {
  initialized: false,
  role: null,
  runNamespace: null,
  active: new Map(),
};

function isPlainObject(value) {
  return value !== null && typeof value === "object" &&
      (Object.getPrototypeOf(value) === Object.prototype ||
       Object.getPrototypeOf(value) === null);
}

function isPurpose(value) {
  return value === EXPLICIT_PURPOSE || value === TERMINATION_PURPOSE;
}

function hasWebLocks() {
  return typeof navigator === "object" && navigator !== null &&
      typeof navigator.locks === "object" && navigator.locks !== null &&
      typeof navigator.locks.request === "function";
}

function workerIsDedicated() {
  return typeof DedicatedWorkerGlobalScope !== "undefined" &&
      self instanceof DedicatedWorkerGlobalScope;
}

function post(event, fields = {}) {
  self.postMessage({
    protocol: PROTOCOL,
    event,
    role: state.role,
    runNamespace: state.runNamespace,
    ...fields,
  });
}

function fail(stage) {
  post("failure", {stage});
}

function validEnvelope(value) {
  return isPlainObject(value) && value.protocol === PROTOCOL &&
      typeof value.command === "string";
}

function validLockCommand(value) {
  return isPurpose(value.purpose) && typeof value.name === "string" &&
      LOCK_NAME_RE.test(value.name);
}

function beginHeldRequest(command, purpose, name) {
  if (!hasWebLocks() || state.active.has(purpose)) {
    fail("begin-held-request");
    return;
  }

  let release = null;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const record = {granted: false, release};
  state.active.set(purpose, record);

  let request;
  try {
    request = navigator.locks.request(name, {mode: "exclusive"}, (lock) => {
      if (lock === null) {
        fail("unexpected-unavailable-lock");
        return undefined;
      }
      record.granted = true;
      post("held", {purpose});
      return gate;
    });
  } catch {
    state.active.delete(purpose);
    fail("request-threw");
    return;
  }

  if (command === "wait") {
    // navigator.locks.request() has been invoked before this acknowledgement.
    post("wait_queued", {purpose});
  }
  Promise.resolve(request).then(
      () => {
        if (state.active.get(purpose) === record) {
          state.active.delete(purpose);
        }
        post("released", {purpose});
      },
      () => {
        if (state.active.get(purpose) === record) {
          state.active.delete(purpose);
        }
        fail("request-rejected");
      });
}

function beginIfAvailableRequest(purpose, name) {
  if (!hasWebLocks()) {
    fail("if-available-without-web-locks");
    return;
  }
  try {
    const request = navigator.locks.request(
        name, {mode: "exclusive", ifAvailable: true}, (lock) => {
          post("if_available", {purpose, available: lock !== null});
          return undefined;
        });
    Promise.resolve(request).catch(() => fail("if-available-rejected"));
  } catch {
    fail("if-available-threw");
  }
}

function releasePurpose(purpose) {
  const record = state.active.get(purpose);
  if (record === undefined || !record.granted || typeof record.release !== "function") {
    fail("release-without-held-lock");
    return;
  }
  record.release();
}

function reportState(purpose) {
  const record = state.active.get(purpose);
  post("state", {
    purpose,
    held: record !== undefined && record.granted === true,
    pending: record !== undefined && record.granted !== true,
  });
}

function initialize(value) {
  if (state.initialized ||
      (value.role !== HOLDER_ROLE && value.role !== CONTENDER_ROLE) ||
      typeof value.runNamespace !== "string" ||
      !RUN_NAMESPACE_RE.test(value.runNamespace)) {
    fail("invalid-init");
    return;
  }
  state.initialized = true;
  state.role = value.role;
  state.runNamespace = value.runNamespace;
  post("ready", {
    dedicatedWorker: workerIsDedicated(),
    secureContext: self.isSecureContext === true,
    crossOriginIsolated: self.crossOriginIsolated === true,
    webLocksAvailable: hasWebLocks(),
    origin: self.location.origin,
  });
}

self.addEventListener("message", (event) => {
  const value = event.data;
  if (!validEnvelope(value)) {
    fail("invalid-envelope");
    return;
  }
  if (value.command === "init") {
    initialize(value);
    return;
  }
  if (!state.initialized || value.runNamespace !== state.runNamespace ||
      value.role !== state.role) {
    fail("invalid-session");
    return;
  }
  if (value.command === "hold" || value.command === "wait") {
    if (!validLockCommand(value)) {
      fail("invalid-lock-command");
      return;
    }
    beginHeldRequest(value.command, value.purpose, value.name);
    return;
  }
  if (value.command === "if_available") {
    if (!validLockCommand(value)) {
      fail("invalid-if-available-command");
      return;
    }
    beginIfAvailableRequest(value.purpose, value.name);
    return;
  }
  if (value.command === "release" || value.command === "state") {
    if (!isPurpose(value.purpose)) {
      fail("invalid-purpose-command");
      return;
    }
    if (value.command === "release") {
      releasePurpose(value.purpose);
    } else {
      reportState(value.purpose);
    }
    return;
  }
  fail("unknown-command");
});
