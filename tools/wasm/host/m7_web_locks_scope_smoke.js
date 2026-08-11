// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Isolated host Web Locks capability probe. It establishes only that sibling
// same-origin dedicated workers in one top-level document can contend for a
// named lock, release it, and observe reacquisition after holder termination.
// Web Locks are per storage bucket; this is neither an origin-wide nor a
// cross-document proof. It does not use OPFS or claim any filesystem,
// database, profile, or persistence semantics.

const HOST_PROTOCOL = 1;
const CASE = "m7_web_locks_scope";
const SCOPE =
    "isolated-host-web-locks-same-top-level-document-sibling-dedicated-workers-only";
const HOST_ROOT = "/__m7_web_locks_scope__";
const WORKER_SCRIPT = "m7_web_locks_scope_smoke_worker.js";
const HOLDER_ROLE = "holder";
const CONTENDER_ROLE = "contender";
const EXPLICIT_PURPOSE = "explicit";
const TERMINATION_PURPOSE = "termination";
const MAX_TIMEOUT_MS = 180000;
const MAX_TRACE_EVENTS = 32;
const RUN_NAMESPACE_RE = /^[A-Za-z0-9_-]{16,128}$/;
const EXPECTED_ORDER_FIELDS = Object.freeze([
  "holderExplicitHeld",
  "contenderIfAvailable",
  "contenderExplicitQueued",
  "contenderExplicitBlocked",
  "explicitReleaseCommand",
  "holderExplicitReleased",
  "contenderExplicitGranted",
  "contenderExplicitReleased",
  "holderTerminationHeld",
  "contenderTerminationQueued",
  "contenderTerminationBlocked",
  "holderTerminationCommand",
  "contenderTerminationGranted",
  "contenderTerminationReleased",
]);

function isPlainObject(value) {
  return value !== null && typeof value === "object" &&
      (Object.getPrototypeOf(value) === Object.prototype ||
       Object.getPrototypeOf(value) === null);
}

function oneQueryValue(query, name) {
  const values = query.getAll(name);
  if (values.length !== 1 || values[0] === "") {
    throw new Error("M7 Web Locks query parameter is invalid");
  }
  return values[0];
}

function parseTimeout(value) {
  if (!/^[0-9]+$/.test(value)) {
    throw new Error("M7 Web Locks timeout is invalid");
  }
  const timeoutMs = Number(value);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1000 ||
      timeoutMs > MAX_TIMEOUT_MS) {
    throw new Error("M7 Web Locks timeout is out of range");
  }
  return timeoutMs;
}

function parseContext(query) {
  for (const name of query.keys()) {
    if (name !== "token" && name !== "run" && name !== "timeoutMs") {
      throw new Error("M7 Web Locks query contains an unexpected parameter");
    }
  }
  const token = oneQueryValue(query, "token");
  const runNamespace = oneQueryValue(query, "run");
  if (!RUN_NAMESPACE_RE.test(token) || !RUN_NAMESPACE_RE.test(runNamespace)) {
    throw new Error("M7 Web Locks token or namespace is invalid");
  }
  return {
    token,
    runNamespace,
    timeoutMs: parseTimeout(oneQueryValue(query, "timeoutMs")),
  };
}

function redact(value, context) {
  return String(value).split(context.token).join("<token>")
      .split(context.runNamespace).join("<run-namespace>");
}

function requireCondition(condition, stage) {
  if (!condition) {
    throw new Error("M7 Web Locks " + stage + " failed");
  }
}

function createDeadline(context) {
  return performance.now() + context.timeoutMs;
}

function remainingDeadlineMs(deadline, stage) {
  const remaining = deadline - performance.now();
  if (remaining <= 0) {
    throw new Error("M7 Web Locks " + stage + " timed out");
  }
  return Math.ceil(remaining);
}

function nextTask() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function makeLockName(context, purpose) {
  return "chromium-wasm-m7-web-locks-" + purpose + "-" +
      context.runNamespace;
}

function baseResult(context) {
  const eventOrder = {};
  for (const field of EXPECTED_ORDER_FIELDS) {
    eventOrder[field] = null;
  }
  return {
    protocol: HOST_PROTOCOL,
    case: CASE,
    scope: SCOPE,
    status: "fail",
    runNamespace: context.runNamespace,
    origin: location.origin,
    secureContext: globalThis.isSecureContext === true,
    crossOriginIsolated: globalThis.crossOriginIsolated === true,
    sharedArrayBuffer: typeof SharedArrayBuffer === "function",
    sameTopLevelDocumentSiblingDedicatedWorkersProven: false,
    holderWorkerWebLocksAvailable: false,
    contenderWorkerWebLocksAvailable: false,
    ifAvailableReturnedNull: false,
    contenderPendingBeforeExplicitRelease: false,
    explicitReleaseQueuedGrantProven: false,
    contenderPendingBeforeHolderTermination: false,
    holderTerminationQueuedGrantProven: false,
    holderWorkerTerminated: false,
    webLocksScopeLimitation:
        "per-storage-bucket-not-origin-wide-or-cross-document-proof",
    terminationReacquisitionLimitation:
        "observed-current-browser-behavior-not-profile-recovery",
    workerEventTrace: [],
    eventOrder,
    // Explicitly negative boundaries: this capability probe is not M7 profile
    // persistence or a substitute for POSIX/database locking.
    opfsTouched: false,
    syncAccessHandleCoordinated: false,
    syncAccessHandleWriterExclusivityProven: false,
    posixFcntlLocksProven: false,
    byteRangeLocksProven: false,
    sqliteLeveldbLockSemanticsProven: false,
    profilePersistenceProven: false,
    atomicRecoveryProven: false,
    crashRecoveryProven: false,
    gracefulRuntimeShutdownProven: false,
    gracefulProfileShutdownProven: false,
    m7GateComplete: false,
    failureDiagnostics: null,
    error: null,
  };
}

class WorkerMailbox {
  constructor(context, role, recordEvent) {
    this.context = context;
    this.role = role;
    this.recordEvent = recordEvent;
    this.messages = [];
    this.waiters = [];
    this.failure = null;
    this.terminated = false;
    const workerUrl = new URL(WORKER_SCRIPT, location.href);
    if (workerUrl.origin !== location.origin ||
        workerUrl.pathname !== HOST_ROOT + "/" + WORKER_SCRIPT) {
      throw new Error("M7 Web Locks worker URL is not same-origin");
    }
    this.worker = new Worker(workerUrl, {
      name: "chromium-wasm-m7-web-locks-" + role,
      type: "module",
    });
    this.worker.addEventListener("message", (event) => this.receive(event));
    this.worker.addEventListener("messageerror", () => {
      this.fail("message-error");
    });
    this.worker.addEventListener("error", (event) => {
      event.preventDefault();
      if (!this.terminated) {
        this.fail("worker-error");
      }
    });
    this.send("init");
  }

  receive(event) {
    if (this.terminated) {
      return;
    }
    const value = event.data;
    if (!isPlainObject(value) || value.protocol !== HOST_PROTOCOL ||
        value.role !== this.role ||
        value.runNamespace !== this.context.runNamespace ||
        typeof value.event !== "string") {
      this.fail("invalid-worker-message");
      return;
    }
    if (value.event === "failure") {
      this.fail("worker-reported-failure");
      return;
    }
    const message = {
      event: value.event,
      purpose: value.purpose,
      available: value.available,
      held: value.held,
      pending: value.pending,
      dedicatedWorker: value.dedicatedWorker,
      secureContext: value.secureContext,
      crossOriginIsolated: value.crossOriginIsolated,
      webLocksAvailable: value.webLocksAvailable,
      origin: value.origin,
      ordinal: this.recordEvent(this.role, value.event, value.purpose),
    };
    this.messages.push(message);
    this.flushWaiters();
  }

  fail(stage) {
    if (this.failure !== null) {
      return;
    }
    this.failure = new Error("M7 Web Locks " + this.role + " " + stage);
    this.flushWaiters();
  }

  flushWaiters() {
    if (this.failure !== null) {
      for (const waiter of this.waiters.splice(0)) {
        clearTimeout(waiter.timeoutId);
        waiter.reject(this.failure);
      }
      return;
    }
    for (let index = this.waiters.length - 1; index >= 0; --index) {
      const waiter = this.waiters[index];
      const messageIndex = this.messages.findIndex(waiter.predicate);
      if (messageIndex < 0) {
        continue;
      }
      const [message] = this.messages.splice(messageIndex, 1);
      this.waiters.splice(index, 1);
      clearTimeout(waiter.timeoutId);
      waiter.resolve(message);
    }
  }

  next(predicate, timeoutMs) {
    if (this.failure !== null) {
      return Promise.reject(this.failure);
    }
    const messageIndex = this.messages.findIndex(predicate);
    if (messageIndex >= 0) {
      return Promise.resolve(this.messages.splice(messageIndex, 1)[0]);
    }
    return new Promise((resolve, reject) => {
      const waiter = {predicate, resolve, reject, timeoutId: null};
      waiter.timeoutId = setTimeout(() => {
        const index = this.waiters.indexOf(waiter);
        if (index >= 0) {
          this.waiters.splice(index, 1);
        }
        reject(new Error("M7 Web Locks worker response timed out"));
      }, timeoutMs);
      this.waiters.push(waiter);
    });
  }

  send(command, fields = {}) {
    if (this.terminated) {
      throw new Error("M7 Web Locks sent a command to a terminated worker");
    }
    this.worker.postMessage({
      protocol: HOST_PROTOCOL,
      command,
      role: this.role,
      runNamespace: this.context.runNamespace,
      ...fields,
    });
  }

  terminate() {
    if (!this.terminated) {
      this.terminated = true;
      this.worker.terminate();
      this.fail("worker-terminated");
    }
  }
}

class ProbeRuntime {
  constructor(context, result) {
    this.context = context;
    this.result = result;
    this.nextOrdinal = 0;
    this.holder = new WorkerMailbox(context, HOLDER_ROLE,
        (role, event, purpose) => this.recordEvent(role, event, purpose));
    this.contender = new WorkerMailbox(context, CONTENDER_ROLE,
        (role, event, purpose) => this.recordEvent(role, event, purpose));
  }

  recordEvent(role, event, purpose) {
    if (this.result.workerEventTrace.length >= MAX_TRACE_EVENTS) {
      throw new Error("M7 Web Locks worker event trace exceeded its bound");
    }
    const marker = role + ":" + event +
        (typeof purpose === "string" ? ":" + purpose : "");
    this.nextOrdinal += 1;
    this.result.workerEventTrace.push({marker, ordinal: this.nextOrdinal});
    return this.nextOrdinal;
  }

  recordParentEvent(marker) {
    if (this.result.workerEventTrace.length >= MAX_TRACE_EVENTS) {
      throw new Error("M7 Web Locks worker event trace exceeded its bound");
    }
    this.nextOrdinal += 1;
    this.result.workerEventTrace.push({
      marker: "parent:" + marker,
      ordinal: this.nextOrdinal,
    });
    return this.nextOrdinal;
  }

  wait(mailbox, event, purpose, deadline) {
    return mailbox.next(
        (message) => message.event === event && message.purpose === purpose,
        remainingDeadlineMs(deadline, event + "-" + purpose));
  }

  waitReady(mailbox, deadline) {
    return mailbox.next(
        (message) => message.event === "ready",
        remainingDeadlineMs(deadline, "worker-ready"));
  }

  dispose() {
    this.holder.terminate();
    this.contender.terminate();
  }
}

async function verifyReadyWorkers(runtime, result, deadline) {
  const holder = await runtime.waitReady(runtime.holder, deadline);
  const contender = await runtime.waitReady(runtime.contender, deadline);
  for (const worker of [holder, contender]) {
    requireCondition(worker.dedicatedWorker === true,
                     "worker is not dedicated");
    requireCondition(worker.secureContext === true,
                     "worker secure context is unavailable");
    requireCondition(worker.crossOriginIsolated === true,
                     "worker cross-origin isolation is unavailable");
    requireCondition(worker.webLocksAvailable === true,
                     "worker Web Locks API is unavailable");
    requireCondition(worker.origin === location.origin,
                     "worker origin mismatch");
  }
  result.sameTopLevelDocumentSiblingDedicatedWorkersProven = true;
  result.holderWorkerWebLocksAvailable = holder.webLocksAvailable === true;
  result.contenderWorkerWebLocksAvailable = contender.webLocksAvailable === true;
}

async function runExplicitReleaseCase(runtime, context, result, deadline) {
  const name = makeLockName(context, EXPLICIT_PURPOSE);
  runtime.holder.send("hold", {purpose: EXPLICIT_PURPOSE, name});
  const holderHeld = await runtime.wait(
      runtime.holder, "held", EXPLICIT_PURPOSE, deadline);
  result.eventOrder.holderExplicitHeld = holderHeld.ordinal;

  runtime.contender.send("if_available", {purpose: EXPLICIT_PURPOSE, name});
  const ifAvailable = await runtime.wait(
      runtime.contender, "if_available", EXPLICIT_PURPOSE, deadline);
  result.eventOrder.contenderIfAvailable = ifAvailable.ordinal;
  requireCondition(ifAvailable.available === false,
                   "ifAvailable did not return null while holder was live");
  result.ifAvailableReturnedNull = true;

  runtime.contender.send("wait", {purpose: EXPLICIT_PURPOSE, name});
  const queued = await runtime.wait(
      runtime.contender, "wait_queued", EXPLICIT_PURPOSE, deadline);
  result.eventOrder.contenderExplicitQueued = queued.ordinal;
  await nextTask();
  runtime.contender.send("state", {purpose: EXPLICIT_PURPOSE});
  const blocked = await runtime.wait(
      runtime.contender, "state", EXPLICIT_PURPOSE, deadline);
  result.eventOrder.contenderExplicitBlocked = blocked.ordinal;
  requireCondition(blocked.held === false && blocked.pending === true,
                   "contender was not pending before explicit release");
  result.contenderPendingBeforeExplicitRelease = true;

  result.eventOrder.explicitReleaseCommand =
      runtime.recordParentEvent("explicit-release-command");
  runtime.holder.send("release", {purpose: EXPLICIT_PURPOSE});
  const holderReleased = await runtime.wait(
      runtime.holder, "released", EXPLICIT_PURPOSE, deadline);
  result.eventOrder.holderExplicitReleased = holderReleased.ordinal;
  const contenderGranted = await runtime.wait(
      runtime.contender, "held", EXPLICIT_PURPOSE, deadline);
  result.eventOrder.contenderExplicitGranted = contenderGranted.ordinal;
  requireCondition(contenderGranted.ordinal > result.eventOrder.explicitReleaseCommand,
                   "contender acquired before explicit release command");
  result.explicitReleaseQueuedGrantProven = true;

  runtime.contender.send("release", {purpose: EXPLICIT_PURPOSE});
  const contenderReleased = await runtime.wait(
      runtime.contender, "released", EXPLICIT_PURPOSE, deadline);
  result.eventOrder.contenderExplicitReleased = contenderReleased.ordinal;
}

async function runTerminationCase(runtime, context, result, deadline) {
  const name = makeLockName(context, TERMINATION_PURPOSE);
  runtime.holder.send("hold", {purpose: TERMINATION_PURPOSE, name});
  const holderHeld = await runtime.wait(
      runtime.holder, "held", TERMINATION_PURPOSE, deadline);
  result.eventOrder.holderTerminationHeld = holderHeld.ordinal;

  runtime.contender.send("wait", {purpose: TERMINATION_PURPOSE, name});
  const queued = await runtime.wait(
      runtime.contender, "wait_queued", TERMINATION_PURPOSE, deadline);
  result.eventOrder.contenderTerminationQueued = queued.ordinal;
  await nextTask();
  runtime.contender.send("state", {purpose: TERMINATION_PURPOSE});
  const blocked = await runtime.wait(
      runtime.contender, "state", TERMINATION_PURPOSE, deadline);
  result.eventOrder.contenderTerminationBlocked = blocked.ordinal;
  requireCondition(blocked.held === false && blocked.pending === true,
                   "contender was not pending before holder termination");
  result.contenderPendingBeforeHolderTermination = true;

  result.eventOrder.holderTerminationCommand =
      runtime.recordParentEvent("holder-termination-command");
  runtime.holder.terminate();
  result.holderWorkerTerminated = true;
  const contenderGranted = await runtime.wait(
      runtime.contender, "held", TERMINATION_PURPOSE, deadline);
  result.eventOrder.contenderTerminationGranted = contenderGranted.ordinal;
  requireCondition(
      contenderGranted.ordinal > result.eventOrder.holderTerminationCommand,
      "contender acquired before holder termination command");
  result.holderTerminationQueuedGrantProven = true;

  runtime.contender.send("release", {purpose: TERMINATION_PURPOSE});
  const contenderReleased = await runtime.wait(
      runtime.contender, "released", TERMINATION_PURPOSE, deadline);
  result.eventOrder.contenderTerminationReleased = contenderReleased.ordinal;
}

function validateEventOrder(result) {
  const order = result.eventOrder;
  for (const field of EXPECTED_ORDER_FIELDS) {
    requireCondition(Number.isSafeInteger(order[field]) && order[field] > 0,
                     "event order is incomplete");
  }
  requireCondition(
      order.holderExplicitHeld < order.contenderIfAvailable &&
      order.contenderIfAvailable < order.contenderExplicitQueued &&
      order.contenderExplicitQueued < order.contenderExplicitBlocked &&
      order.contenderExplicitBlocked < order.explicitReleaseCommand &&
      order.explicitReleaseCommand < order.contenderExplicitGranted &&
      order.holderExplicitHeld < order.holderExplicitReleased &&
      order.explicitReleaseCommand < order.holderExplicitReleased &&
      order.contenderExplicitGranted < order.contenderExplicitReleased &&
      order.contenderExplicitReleased < order.holderTerminationHeld &&
      order.holderTerminationHeld < order.contenderTerminationQueued &&
      order.contenderTerminationQueued < order.contenderTerminationBlocked &&
      order.contenderTerminationBlocked < order.holderTerminationCommand &&
      order.holderTerminationCommand < order.contenderTerminationGranted &&
      order.contenderTerminationGranted < order.contenderTerminationReleased,
      "event ordering is invalid");
}

async function executeProbe(context) {
  const result = baseResult(context);
  const deadline = createDeadline(context);
  let runtime = null;
  let stage = "document-prerequisites";
  try {
    requireCondition(result.secureContext, "document secure context is unavailable");
    requireCondition(result.crossOriginIsolated,
                     "document cross-origin isolation is unavailable");
    requireCondition(result.sharedArrayBuffer,
                     "document SharedArrayBuffer is unavailable");
    requireCondition(typeof Worker === "function", "dedicated Worker is unavailable");
    stage = "create-workers";
    runtime = new ProbeRuntime(context, result);
    stage = "verify-workers";
    await verifyReadyWorkers(runtime, result, deadline);
    stage = "explicit-release";
    await runExplicitReleaseCase(runtime, context, result, deadline);
    stage = "holder-termination";
    await runTerminationCase(runtime, context, result, deadline);
    validateEventOrder(result);
    result.status = "pass";
  } catch (error) {
    result.error = redact(error instanceof Error ? error.message : error, context);
    result.failureDiagnostics = {
      stage,
      workerEventTrace: result.workerEventTrace.slice(),
    };
  } finally {
    runtime?.dispose();
  }
  return result;
}

function updateVisibleState(result) {
  const root = document.querySelector("#m7-web-locks-scope-root");
  const status = document.querySelector("#m7-web-locks-scope-status");
  if (root instanceof HTMLElement) {
    root.dataset.state = result.status;
  }
  if (status instanceof HTMLElement) {
    status.textContent = JSON.stringify({
      ...result,
      runNamespace: "<redacted>",
    }, null, 2);
  }
}

async function postResult(context, result) {
  const endpoint = new URL(
      "./result/" + encodeURIComponent(context.token), location.href);
  if (endpoint.origin !== location.origin ||
      endpoint.pathname !== HOST_ROOT + "/result/" +
          encodeURIComponent(context.token)) {
    throw new Error("M7 Web Locks result endpoint is not same-origin");
  }
  const response = await fetch(endpoint.href, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(result),
  });
  if (response.status !== 204) {
    throw new Error("M7 Web Locks result upload failed");
  }
}

export async function runM7WebLocksScopeSmokeFromQuery() {
  const context = parseContext(new URLSearchParams(location.search));
  const result = await executeProbe(context);
  updateVisibleState(result);
  await postResult(context, result);
  return result;
}
