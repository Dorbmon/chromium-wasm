// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// The package host is intentionally only a loader and narrow Ozone bridge. It
// does not synthesize browser UI, open a debugging protocol, or paper over an
// unavailable platform feature. VERSION.json marks the resulting package as
// pre-release until M7/M8/M9 have their own evidence.

import {ChromiumWasmTrustedPointerInput} from "./chromium-wasm-pointer-input.js";
import {ChromiumWasmTrustedClipboardInput} from "./chromium-wasm-clipboard-input.js";
import {ChromiumWasmTrustedFilePicker} from "./chromium-wasm-file-picker.js";
import {ChromiumWasmOuterOriginStorageEstimate} from "./chromium-wasm-storage-estimate.js";
import {ChromiumWasmTrustedTextInput} from "./chromium-wasm-text-input.js";
import {loadReleaseWispConfiguration} from "./chromium-wasm-release-wisp-config.js";

const HOST_PROTOCOL = 1;
const MAX_FRAME_DIMENSION = 16384;
const MAX_LOG_LINES = 32;
const MAX_LOG_LINE_CHARS = 512;
const MAX_STATUS_BYTES = 64 * 1024;
const MAX_VERSION_JSON_BYTES = 64 * 1024;
const PACKAGE_SCHEMA_VERSION = 4;
const PACKAGE_METADATA_PROTOCOL = 1;
const PRODUCT_NAME = "chromium-wasm";
const PACKAGE_INPUT_MODULE_NAME = "chrome_wasm";
const LOADER_ARTIFACT_PATH = "chromium-wasm.js";
const RELEASE_STATUS = "pre_m7_m8_not_releasable";
const WASM_ARTIFACT_PATH = "chromium-wasm.wasm";
const ALLOWED_ARTIFACT_SOURCE_PROVENANCE = new Set([
  "unverified",
  "local_clean_build_attested",
]);
const EXPECTED_GATE_STATE = Object.freeze({
  persistent_profile_complete: false,
  page_webassembly_enabled: false,
  m8_complete: false,
  m9_release_complete: false,
});
const EXPECTED_VERSION_KEYS = Object.freeze([
  "artifacts",
  "build",
  "gate_state",
  "host",
  "known_limitations",
  "product",
  "release_status",
  "schema_version",
  "toolchain_manifest",
  "versions",
]);
const EXPECTED_BUILD_KEYS = Object.freeze([
  "artifact_source_provenance",
  "gn_args",
  "gn_args_sha256",
  "input_module_name",
  "resource_delivery",
  "staging_checkout",
]);
const EXPECTED_VERSION_REVISION_KEYS = Object.freeze([
  "chromium",
  "emscripten",
  "v8",
]);
const EXPECTED_HOST_KEYS = Object.freeze([
  "bridge_protocol",
  "mime_types",
  "required_headers",
]);
const EXPECTED_TOOLCHAIN_MANIFEST_KEYS = Object.freeze(["path", "sha256"]);
const EXPECTED_ARTIFACT_KEYS = Object.freeze(["path", "sha256", "size_bytes"]);
const EXPECTED_MIME_TYPES = Object.freeze({
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".wasm": "application/wasm",
});
const EXPECTED_REQUIRED_HEADERS = Object.freeze({
  "Cross-Origin-Embedder-Policy": "require-corp",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-origin",
  "X-Content-Type-Options": "nosniff",
});
const EXPECTED_PACKAGE_ARTIFACT_PATHS = Object.freeze([
  "LICENSES/Chromium-LICENSE.txt",
  "LICENSES/PRE_RELEASE_NOTICE.txt",
  "LICENSES/THIRD_PARTY_NOTICES.txt",
  "README.txt",
  "TOOLCHAIN.json",
  "chromium-wasm-clipboard-input.js",
  "chromium-wasm-file-picker.js",
  "chromium-wasm-host.js",
  "chromium-wasm-pointer-input.js",
  "chromium-wasm-release-wisp-config.js",
  "chromium-wasm-storage-estimate.js",
  "chromium-wasm-text-input.js",
  LOADER_ARTIFACT_PATH,
  WASM_ARTIFACT_PATH,
  "index.html",
]);

function appendBounded(records, record) {
  records.push(record);
  if (records.length > MAX_LOG_LINES) {
    records.shift();
  }
}

function asReport(value, description) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${description} must be an object`);
  }
  return value;
}

function asNonemptyString(value, description) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${description} must be a nonempty string`);
  }
  return value;
}

function requireExactKeys(value, expectedKeys, description) {
  const report = asReport(value, description);
  const observedKeys = Object.keys(report);
  if (observedKeys.length !== expectedKeys.length ||
      !expectedKeys.every((key) => Object.hasOwn(report, key))) {
    throw new Error(`${description} keys are invalid`);
  }
  return report;
}

function asSha256(value, description) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${description} must be a lowercase SHA-256`);
  }
  return value;
}

function asRevision(value, description) {
  if (typeof value !== "string" || !/^[0-9a-f]{40}$/.test(value)) {
    throw new Error(`${description} must be a lowercase Git revision`);
  }
  return value;
}

function canonicalJsonString(value) {
  let result = "\"";
  for (let index = 0; index < value.length; ++index) {
    const code = value.charCodeAt(index);
    switch (code) {
      case 8:
        result += "\\b";
        break;
      case 9:
        result += "\\t";
        break;
      case 10:
        result += "\\n";
        break;
      case 12:
        result += "\\f";
        break;
      case 13:
        result += "\\r";
        break;
      case 34:
        result += "\\\"";
        break;
      case 92:
        result += "\\\\";
        break;
      default:
        if (code < 0x20 || code > 0x7e) {
          result += `\\u${code.toString(16).padStart(4, "0")}`;
        } else {
          result += String.fromCharCode(code);
        }
        break;
    }
  }
  return `${result}\"`;
}

function canonicalJson(value, indentation = "") {
  if (value === null) {
    return "null";
  }
  switch (typeof value) {
    case "boolean":
      return value ? "true" : "false";
    case "number":
      if (!Number.isSafeInteger(value)) {
        throw new Error("VERSION.json contains an unsafe number");
      }
      return String(value);
    case "string":
      return canonicalJsonString(value);
    case "object":
      break;
    default:
      throw new Error("VERSION.json contains an unsupported value");
  }

  const childIndentation = `${indentation}  `;
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return "[]";
    }
    return `[\n${value.map((item) =>
        `${childIndentation}${canonicalJson(item, childIndentation)}`).join(",\n")}
${indentation}]`;
  }
  if (Object.getPrototypeOf(value) !== Object.prototype) {
    throw new Error("VERSION.json contains an unsupported object");
  }
  const keys = Object.keys(value).sort();
  if (keys.length === 0) {
    return "{}";
  }
  return `{\n${keys.map((key) =>
      `${childIndentation}${canonicalJsonString(key)}: ` +
      canonicalJson(value[key], childIndentation)).join(",\n")}
${indentation}}`;
}

function requireExactCanonicalObject(value, expected, description) {
  const report = requireExactKeys(value, Object.keys(expected), description);
  if (canonicalJson(report) !== canonicalJson(expected)) {
    throw new Error(`${description} values are invalid`);
  }
  return report;
}

function parseCanonicalVersionJson(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0 ||
      bytes.byteLength > MAX_VERSION_JSON_BYTES) {
    throw new Error("VERSION.json has an invalid bounded byte length");
  }
  if (typeof TextDecoder !== "function") {
    throw new Error("UTF-8 decoding is unavailable for VERSION.json");
  }
  let text;
  let version;
  try {
    // Preserve a leading BOM so canonical-byte comparison rejects it. The
    // package verifier decodes raw bytes with Python UTF-8 and likewise does
    // not accept a BOM-prefixed JSON document as canonical metadata.
    text = new TextDecoder("utf-8", {fatal: true, ignoreBOM: true}).decode(bytes);
  } catch (error) {
    throw new Error(`VERSION.json is invalid: ${String(error)}`);
  }
  if (text.charCodeAt(0) === 0xfeff) {
    throw new Error("VERSION.json is not canonical deterministic JSON");
  }
  try {
    version = JSON.parse(text);
  } catch (error) {
    throw new Error(`VERSION.json is invalid: ${String(error)}`);
  }
  // Regenerating the full deterministic bytes rejects duplicate object keys:
  // JSON.parse otherwise keeps only their last value. It also prevents this
  // bounded status from being derived from a noncanonical metadata document.
  if (`${canonicalJson(version)}\n` !== text) {
    throw new Error("VERSION.json is not canonical deterministic JSON");
  }
  return requireExactKeys(version, EXPECTED_VERSION_KEYS, "VERSION.json");
}

async function sha256Hex(bytes, description = "VERSION.json") {
  if (!(bytes instanceof Uint8Array)) {
    throw new Error(`${description} bytes are invalid`);
  }
  const subtle = globalThis.crypto?.subtle;
  if (!subtle || typeof subtle.digest !== "function") {
    throw new Error(`WebCrypto SHA-256 is unavailable for ${description}`);
  }
  let digest;
  try {
    digest = await subtle.digest("SHA-256", bytes);
  } catch (error) {
    throw new Error(`${description} SHA-256 failed: ${String(error)}`);
  }
  if (!(digest instanceof ArrayBuffer)) {
    throw new Error(`WebCrypto SHA-256 returned an invalid digest for ${description}`);
  }
  return Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0")).join("");
}

function requireArtifactResponseHeaders(response, contentType, description) {
  const actualContentType = response?.headers?.get("Content-Type")
      ?.split(";", 1)[0].trim().toLowerCase();
  const expectedHeaders = {
    "Cache-Control": "no-store",
    ...EXPECTED_REQUIRED_HEADERS,
  };
  if (actualContentType !== contentType ||
      Object.entries(expectedHeaders).some(([name, value]) =>
        response?.headers?.get(name) !== value)) {
    throw new Error(`${description} response headers are invalid`);
  }
}

async function fetchVerifiedArtifact(url, identity, contentType, description) {
  const response = await fetch(url.href, {
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
  });
  if (!response || !response.ok || response.url !== url.href) {
    throw new Error(`${description} request was not exact`);
  }
  requireArtifactResponseHeaders(response, contentType, description);
  let buffer;
  try {
    buffer = await response.arrayBuffer();
  } catch (error) {
    throw new Error(`${description} response bytes failed: ${String(error)}`);
  }
  if (!(buffer instanceof ArrayBuffer)) {
    throw new Error(`${description} response bytes are invalid`);
  }
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength !== identity.bytes ||
      await sha256Hex(bytes, description) !== identity.sha256) {
    throw new Error(`${description} disagrees with VERSION.json artifact identity`);
  }
  return bytes;
}

function validateGateState(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("VERSION.json gate_state must be an object");
  }
  const expectedKeys = Object.keys(EXPECTED_GATE_STATE);
  const observedKeys = Object.keys(value);
  if (observedKeys.length !== expectedKeys.length ||
      !expectedKeys.every((key) => Object.hasOwn(value, key))) {
    throw new Error("VERSION.json gate_state keys are invalid");
  }
  for (const key of expectedKeys) {
    if (typeof value[key] !== "boolean") {
      throw new Error("VERSION.json gate_state values must be booleans");
    }
    if (value[key] !== EXPECTED_GATE_STATE[key]) {
      throw new Error("VERSION.json gate_state must retain false values");
    }
  }
  // Do not retain untrusted metadata objects after validation. The rendered
  // release-state section is always the canonical false-only declaration.
  return EXPECTED_GATE_STATE;
}

function validateVersionMetadata(version) {
  const report = requireExactKeys(
      version, EXPECTED_VERSION_KEYS, "VERSION.json");
  if (report.schema_version !== PACKAGE_SCHEMA_VERSION ||
      report.product !== PRODUCT_NAME || report.release_status !== RELEASE_STATUS) {
    throw new Error("VERSION.json package declaration is invalid");
  }

  const gateState = validateGateState(report.gate_state);
  const versions = requireExactKeys(
      report.versions, EXPECTED_VERSION_REVISION_KEYS, "VERSION.json versions");
  for (const name of EXPECTED_VERSION_REVISION_KEYS) {
    asRevision(versions[name], `VERSION.json ${name}`);
  }

  const build = requireExactKeys(
      report.build, EXPECTED_BUILD_KEYS, "VERSION.json build");
  if (!Array.isArray(build.gn_args) || build.gn_args.length === 0 ||
      !build.gn_args.every((value) => typeof value === "string")) {
    throw new Error("VERSION.json GN arguments are invalid");
  }
  asSha256(build.gn_args_sha256, "VERSION.json GN arguments");
  if (build.input_module_name !== PACKAGE_INPUT_MODULE_NAME ||
      build.resource_delivery !== "embedded-in-wasm-current-build" ||
      !ALLOWED_ARTIFACT_SOURCE_PROVENANCE.has(
          build.artifact_source_provenance)) {
    throw new Error("VERSION.json build metadata is invalid");
  }
  asRevision(build.staging_checkout, "VERSION.json staging checkout");

  requireExactCanonicalObject(report.host, {
    bridge_protocol: HOST_PROTOCOL,
    mime_types: EXPECTED_MIME_TYPES,
    required_headers: EXPECTED_REQUIRED_HEADERS,
  }, "VERSION.json host requirements");

  const manifest = requireExactKeys(
      report.toolchain_manifest, EXPECTED_TOOLCHAIN_MANIFEST_KEYS,
      "VERSION.json toolchain manifest");
  if (manifest.path !== "TOOLCHAIN.json") {
    throw new Error("VERSION.json toolchain manifest identity is invalid");
  }
  asSha256(manifest.sha256, "VERSION.json toolchain manifest");

  if (!Array.isArray(report.known_limitations) ||
      report.known_limitations.length < 4 ||
      !report.known_limitations.every((value) =>
        typeof value === "string" && value.length > 0)) {
    throw new Error("VERSION.json known limitations are invalid");
  }

  if (!Array.isArray(report.artifacts) || report.artifacts.length === 0 ||
      report.artifacts.length !== EXPECTED_PACKAGE_ARTIFACT_PATHS.length) {
    throw new Error("VERSION.json artifact list is invalid");
  }
  let loaderArtifact = null;
  let wasmArtifact = null;
  for (let index = 0; index < report.artifacts.length; ++index) {
    const artifact = requireExactKeys(
        report.artifacts[index], EXPECTED_ARTIFACT_KEYS,
        "VERSION.json artifact record");
    if (artifact.path !== EXPECTED_PACKAGE_ARTIFACT_PATHS[index]) {
      throw new Error("VERSION.json artifacts are not complete and ordered");
    }
    asSha256(artifact.sha256, "VERSION.json artifact hash");
    if (!Number.isSafeInteger(artifact.size_bytes) || artifact.size_bytes <= 0) {
      throw new Error("VERSION.json artifact size is invalid");
    }
    const identity = Object.freeze({
      bytes: artifact.size_bytes,
      sha256: artifact.sha256,
    });
    if (artifact.path === LOADER_ARTIFACT_PATH) {
      loaderArtifact = identity;
    } else if (artifact.path === WASM_ARTIFACT_PATH) {
      wasmArtifact = identity;
    }
  }
  const toolchainManifestArtifact = report.artifacts.find(
      (artifact) => artifact.path === manifest.path);
  if (!toolchainManifestArtifact ||
      toolchainManifestArtifact.sha256 !== manifest.sha256) {
    throw new Error("VERSION.json toolchain manifest artifact identity is invalid");
  }
  if (loaderArtifact === null || wasmArtifact === null) {
    throw new Error("VERSION.json executable artifact identities are missing");
  }
  return {
    build,
    executableArtifacts: Object.freeze({
      loader: loaderArtifact,
      wasm: wasmArtifact,
    }),
    gateState,
    versions,
  };
}

function isReadinessReport(value) {
  return value && typeof value === "object" &&
      typeof value.shellReady === "boolean" &&
      typeof value.surfaceReady === "boolean" &&
      typeof value.firstVisuallyNonEmptyPaint === "boolean";
}

function cursorDescriptor(cursorType) {
  switch (cursorType) {
    case -1:
    case 0:
      return {cssCursor: "default", exact: true};
    case 1:
      return {cssCursor: "crosshair", exact: true};
    case 2:
      return {cssCursor: "pointer", exact: true};
    case 3:
      return {cssCursor: "text", exact: true};
    case 4:
      return {cssCursor: "wait", exact: true};
    case 5:
      return {cssCursor: "help", exact: true};
    case 6:
      return {cssCursor: "e-resize", exact: true};
    case 7:
      return {cssCursor: "n-resize", exact: true};
    case 8:
      return {cssCursor: "ne-resize", exact: true};
    case 9:
      return {cssCursor: "nw-resize", exact: true};
    case 10:
      return {cssCursor: "s-resize", exact: true};
    case 11:
      return {cssCursor: "se-resize", exact: true};
    case 12:
      return {cssCursor: "sw-resize", exact: true};
    case 13:
      return {cssCursor: "w-resize", exact: true};
    case 14:
      return {cssCursor: "ns-resize", exact: true};
    case 15:
      return {cssCursor: "ew-resize", exact: true};
    case 16:
      return {cssCursor: "nesw-resize", exact: true};
    case 17:
      return {cssCursor: "nwse-resize", exact: true};
    case 18:
      return {cssCursor: "col-resize", exact: true};
    case 19:
      return {cssCursor: "row-resize", exact: true};
    case 29:
      return {cssCursor: "move", exact: true};
    case 30:
      return {cssCursor: "vertical-text", exact: true};
    case 31:
      return {cssCursor: "cell", exact: true};
    case 32:
      return {cssCursor: "context-menu", exact: true};
    case 33:
      return {cssCursor: "alias", exact: true};
    case 34:
      return {cssCursor: "progress", exact: true};
    case 35:
      return {cssCursor: "no-drop", exact: true};
    case 36:
      return {cssCursor: "copy", exact: true};
    case 37:
      return {cssCursor: "none", exact: true};
    case 38:
      return {cssCursor: "not-allowed", exact: true};
    case 39:
      return {cssCursor: "zoom-in", exact: true};
    case 40:
      return {cssCursor: "zoom-out", exact: true};
    case 41:
      return {cssCursor: "grab", exact: true};
    case 42:
      return {cssCursor: "grabbing", exact: true};
    case 20:
    case 21:
    case 22:
    case 23:
    case 24:
    case 25:
    case 26:
    case 27:
    case 28:
    case 43:
    case 44:
      return {cssCursor: "all-scroll", exact: false};
    case 45:
      return {cssCursor: "default", exact: false};
    case 46:
      return {cssCursor: "no-drop", exact: false};
    case 47:
      return {cssCursor: "move", exact: false};
    case 48:
      return {cssCursor: "copy", exact: false};
    case 49:
      return {cssCursor: "alias", exact: false};
    case 50:
    case 51:
    case 52:
    case 53:
      return {cssCursor: "not-allowed", exact: false};
    default:
      return null;
  }
}

class ChromiumWasmPreReleaseHost {
  #canvas;
  #textProxy;
  #root;
  #status;
  #versionsElement;
  #gateStateElement;
  #shutdownButton;
  #module = null;
  #runtimeInitialized = false;
  #pointerInput = null;
  #textInput = null;
  #clipboardInput = null;
  #filePicker = null;
  #storageEstimate = null;
  #latestTextInputState = null;
  #records = [];
  // Records are intentionally bounded and may evict an earlier fatal entry.
  // Keep this independent, monotonic health signal so a later readiness report
  // cannot turn a failed host back into a healthy package-smoke observation.
  #fatalCount = 0;
  #readiness = null;
  #frameCount = 0;
  #runtimeExitCode = null;
  #processExitCode = null;
  #runtimeAbortObserved = false;
  #shutdownRequested = false;
  #runtimeArtifactsVerified = false;
  #wispConfigured = false;
  #gateState = null;
  #packageMetadata = null;
  #windowErrorHandler = null;
  #unhandledRejectionHandler = null;

  constructor(canvas, textProxy, root, status, versionsElement, gateStateElement,
      shutdownButton) {
    if (!(canvas instanceof HTMLCanvasElement) ||
        !(textProxy instanceof HTMLTextAreaElement) ||
        !(root instanceof HTMLElement) || !(status instanceof HTMLElement) ||
        !(versionsElement instanceof HTMLElement) ||
        !(gateStateElement instanceof HTMLElement) ||
        !(shutdownButton instanceof HTMLButtonElement)) {
      throw new Error("pre-release host page is missing a required element");
    }
    this.#canvas = canvas;
    this.#textProxy = textProxy;
    this.#root = root;
    this.#status = status;
    this.#versionsElement = versionsElement;
    this.#gateStateElement = gateStateElement;
    this.#shutdownButton = shutdownButton;
  }

  #record(kind, value) {
    appendBounded(this.#records, {
      kind,
      value: String(value).slice(0, MAX_LOG_LINE_CHARS),
    });
    this.#renderStatus();
  }

  #renderStatus() {
    const summary = {
      releaseStatus: RELEASE_STATUS,
      gateState: this.#gateState,
      packageMetadata: this.#packageMetadata,
      runtimeInitialized: this.#runtimeInitialized,
      framesPresented: this.#frameCount,
      readiness: this.#readiness,
      runtimeExitCode: this.#runtimeExitCode,
      processExitCode: this.#processExitCode,
      shutdownRequested: this.#shutdownRequested,
      runtimeArtifactsVerified: this.#runtimeArtifactsVerified,
      wispConfigured: this.#wispConfigured,
      fatalCount: this.#fatalCount,
      records: this.#records,
    };
    const text = JSON.stringify(summary, null, 2);
    this.#status.textContent = text.slice(0, MAX_STATUS_BYTES);
  }

  #renderVersions(version) {
    const versions = version?.versions;
    const build = version?.build;
    if (!versions || typeof versions !== "object" ||
        !build || typeof build !== "object") {
      throw new Error("VERSION.json does not contain revisions");
    }
    if (!ALLOWED_ARTIFACT_SOURCE_PROVENANCE.has(
        build.artifact_source_provenance)) {
      throw new Error(
          "VERSION.json has unsupported artifact source provenance");
    }
    this.#versionsElement.replaceChildren();
    const displayedValues = [
      ["chromium", versions.chromium],
      ["v8", versions.v8],
      ["emscripten", versions.emscripten],
      ["staging checkout", build.staging_checkout],
      ["artifact source provenance", build.artifact_source_provenance],
    ];
    for (const [name, value] of displayedValues) {
      const term = document.createElement("dt");
      const definition = document.createElement("dd");
      term.textContent = name;
      definition.textContent = asNonemptyString(value, `version ${name}`);
      this.#versionsElement.append(term, definition);
    }
  }

  #renderGateState(gateState) {
    this.#gateStateElement.replaceChildren();
    for (const [name, value] of Object.entries(gateState)) {
      const term = document.createElement("dt");
      const definition = document.createElement("dd");
      term.textContent = name;
      definition.textContent = String(value);
      this.#gateStateElement.append(term, definition);
    }
  }

  #reportFatal(value) {
    this.#fatalCount = Math.min(Number.MAX_SAFE_INTEGER, this.#fatalCount + 1);
    this.#root.dataset.state = "failed";
    this.#record("fatal", value);
  }

  #hasTerminalExit() {
    return this.#runtimeExitCode !== null || this.#processExitCode !== null;
  }

  #isExecutionQuiesced() {
    return this.#runtimeAbortObserved || this.#hasTerminalExit();
  }

  #verifyExitAgreement() {
    if (this.#runtimeExitCode !== null && this.#processExitCode !== null &&
        this.#runtimeExitCode !== this.#processExitCode) {
      this.#reportFatal("runtime and native process exit codes disagree");
    }
  }

  #quiesceRuntimeBridges() {
    // An abort or terminal exit can arrive after trusted adapters accepted
    // asynchronous outer-DOM work. Make every adapter see an unavailable
    // Module while it removes DOM routes so its normal cleanup cannot call
    // into an unavailable runtime. Do not restore it: an adapter whose DOM
    // removal threw might still retain its getModule closure, which must
    // remain unable to call terminal Wasm.
    const pointerInput = this.#pointerInput;
    const textInput = this.#textInput;
    const clipboardInput = this.#clipboardInput;
    const filePicker = this.#filePicker;
    const storageEstimate = this.#storageEstimate;
    this.#module = null;
    const dispose = (adapter, method, description) => {
      try {
        adapter?.[method]();
      } catch (_) {
        // Continue through every adapter even when a hostile or broken outer
        // DOM route rejects one removal. No outer exception text is retained.
        this.#reportFatal(`${description} bridge teardown failed`);
      }
    };
    dispose(pointerInput, "detach", "pointer input");
    dispose(textInput, "detach", "text input");
    dispose(clipboardInput, "detach", "clipboard input");
    dispose(filePicker, "detach", "file picker");
    dispose(storageEstimate, "dispose", "storage estimate");
    this.#pointerInput = null;
    this.#textInput = null;
    this.#clipboardInput = null;
    this.#filePicker = null;
    this.#storageEstimate = null;
    this.#latestTextInputState = null;
  }

  #reportRuntimeAbort(reason) {
    this.#runtimeAbortObserved = true;
    this.#shutdownButton.disabled = true;
    this.#quiesceRuntimeBridges();
    this.#reportFatal(`Wasm abort: ${String(reason)}`);
  }

  #reportRuntimeExit(value) {
    try {
      if (!Number.isSafeInteger(value) || this.#runtimeExitCode !== null) {
        throw new Error("runtime exit report is invalid or duplicated");
      }
      this.#runtimeExitCode = value;
      this.#shutdownButton.disabled = true;
      this.#quiesceRuntimeBridges();
      this.#record("runtime-exit", value);
      this.#verifyExitAgreement();
    } catch (error) {
      this.#reportFatal(`invalid runtime exit report: ${String(error)}`);
    }
  }

  #reportNativeProcessExit(value) {
    try {
      const report = requireExactKeys(
          value, ["protocol", "exitCode"], "native process-exit report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.exitCode) ||
          this.#processExitCode !== null) {
        throw new Error("native process-exit report is invalid or duplicated");
      }
      this.#processExitCode = report.exitCode;
      this.#shutdownButton.disabled = true;
      this.#quiesceRuntimeBridges();
      this.#record("native-process-exit", report.exitCode);
      this.#verifyExitAgreement();
    } catch (error) {
      this.#reportFatal(`invalid native process-exit report: ${String(error)}`);
    }
  }

  #reportFrame(value) {
    try {
      const report = asReport(value, "frame report");
      if (report.protocol !== HOST_PROTOCOL || !Number.isSafeInteger(report.id) ||
          report.id < 1 || !Number.isSafeInteger(report.width) ||
          report.width < 1 || report.width > MAX_FRAME_DIMENSION ||
          !Number.isSafeInteger(report.height) || report.height < 1 ||
          report.height > MAX_FRAME_DIMENSION ||
          !Number.isFinite(report.timestampMs) || report.timestampMs < 0) {
        throw new Error("frame report is invalid");
      }
      if (this.#isExecutionQuiesced()) {
        this.#reportFatal("frame report arrived after terminal state");
        return;
      }
      this.#frameCount += 1;
      this.#renderStatus();
    } catch (error) {
      this.#reportFatal(`invalid frame report: ${String(error)}`);
    }
  }

  #reportReadiness(value) {
    if (!isReadinessReport(value) || value.protocol !== HOST_PROTOCOL) {
      this.#reportFatal("invalid readiness report");
      return;
    }
    if (this.#isExecutionQuiesced()) {
      this.#reportFatal("readiness report arrived after terminal state");
      return;
    }
    this.#readiness = {
      shellReady: value.shellReady,
      surfaceReady: value.surfaceReady,
      firstVisuallyNonEmptyPaint: value.firstVisuallyNonEmptyPaint,
    };
    // A later readiness report may be valid, but it cannot erase a fatal
    // outcome that might already have aged out of the bounded record history.
    if (this.#fatalCount === 0) {
      this.#root.dataset.state = value.surfaceReady ? "running" : "starting";
    }
    this.#renderStatus();
  }

  #reportOzoneFocusState(value) {
    try {
      const report = asReport(value, "Ozone focus report");
      if (report.protocol !== HOST_PROTOCOL ||
          typeof report.keyboardTargetPresent !== "boolean" ||
          typeof report.active !== "boolean") {
        throw new Error("focus state is invalid");
      }
      this.#record("ozone-focus", `${report.keyboardTargetPresent}:${report.active}`);
    } catch (error) {
      this.#reportFatal(`invalid Ozone focus report: ${String(error)}`);
    }
  }

  #reportOzoneCursor(value) {
    try {
      const report = asReport(value, "Ozone cursor report");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.cursorType)) {
        throw new Error("cursor type is invalid");
      }
      const descriptor = cursorDescriptor(report.cursorType);
      if (!descriptor) {
        return false;
      }
      this.#canvas.style.cursor = descriptor.cssCursor;
      return descriptor.exact;
    } catch (error) {
      this.#reportFatal(`invalid Ozone cursor report: ${String(error)}`);
      return false;
    }
  }

  #reportOzoneTextInputState(value) {
    try {
      const report = asReport(value, "Ozone text-input state");
      if (report.protocol !== HOST_PROTOCOL ||
          typeof report.focusedClientPresent !== "boolean" ||
          typeof report.editable !== "boolean" ||
          typeof report.canComposeInline !== "boolean") {
        throw new Error("text-input state is invalid");
      }
      this.#latestTextInputState = report;
      this.#textInput?.handleOzoneTextInputState(report);
      this.#clipboardInput?.handleOzoneTextInputState(report);
    } catch (error) {
      this.#reportFatal(`invalid Ozone text-input state: ${String(error)}`);
    }
  }

  #reportOzoneTextInputDelivery(value) {
    // The common text adapter only needs this generic state in its test lane.
    // The regular browser-owned delivery below is the production bridge.
    try {
      const report = asReport(value, "Ozone text-input delivery");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.sequence) ||
          typeof report.accepted !== "boolean") {
        throw new Error("text-input delivery is invalid");
      }
      this.#record("ozone-text-delivery", report.sequence);
    } catch (error) {
      this.#reportFatal(`invalid Ozone text-input delivery: ${String(error)}`);
    }
  }

  #reportOzoneBrowserTextInputDelivery(value) {
    try {
      const report = asReport(value, "browser text-input delivery");
      if (report.protocol !== HOST_PROTOCOL || report.action !== 4 ||
          report.sessionId !== 0 || !Number.isSafeInteger(report.sequence) ||
          report.sequence < 1 || typeof report.accepted !== "boolean") {
        throw new Error("browser text-input delivery is invalid");
      }
      this.#textInput?.handleOzoneBrowserTextInputDelivery(report);
    } catch (error) {
      this.#reportFatal(`invalid browser text delivery: ${String(error)}`);
    }
  }

  #reportOzoneBrowserClipboardPasteDelivery(value) {
    try {
      const report = asReport(value, "browser clipboard-paste delivery");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.requestId) || report.requestId < 1 ||
          typeof report.accepted !== "boolean") {
        throw new Error("browser clipboard-paste delivery is invalid");
      }
      this.#clipboardInput?.handleOzoneBrowserClipboardPasteDelivery(report);
    } catch (error) {
      this.#reportFatal(`invalid browser clipboard delivery: ${String(error)}`);
    }
  }

  #reportOzoneBrowserFilePickerDelivery(value) {
    try {
      const report = asReport(value, "browser file-picker delivery");
      if (report.protocol !== HOST_PROTOCOL ||
          !Number.isSafeInteger(report.requestId) || report.requestId < 1 ||
          report.requestId > 0x7fffffff ||
          typeof report.accepted !== "boolean") {
        throw new Error("browser file-picker delivery is invalid");
      }
      this.#filePicker?.handleOzoneBrowserFilePickerDelivery(report);
    } catch (error) {
      this.#reportFatal(`invalid browser file-picker delivery: ${String(error)}`);
    }
  }

  #installBridge() {
    if (globalThis.__chromiumWasmHostBridgeV1 !== undefined) {
      throw new Error("a Chromium Wasm host bridge is already installed");
    }
    const host = this;
    globalThis.__chromiumWasmHostBridgeV1 = Object.freeze({
      protocol: HOST_PROTOCOL,
      reportFatal(value) {
        host.#reportFatal(value);
      },
      reportProcessExit(value) {
        host.#reportNativeProcessExit(value);
      },
      reportFrame(value) {
        host.#reportFrame(value);
      },
      reportReadiness(value) {
        host.#reportReadiness(value);
      },
      reportOzoneFocusState(value) {
        host.#reportOzoneFocusState(value);
      },
      reportOzoneCursor(value) {
        return host.#reportOzoneCursor(value);
      },
      reportOzoneTextInputState(value) {
        host.#reportOzoneTextInputState(value);
      },
      reportOzoneTextInputDelivery(value) {
        host.#reportOzoneTextInputDelivery(value);
      },
      reportOzoneBrowserTextInputDelivery(value) {
        host.#reportOzoneBrowserTextInputDelivery(value);
      },
      reportOzoneBrowserClipboardPasteDelivery(value) {
        host.#reportOzoneBrowserClipboardPasteDelivery(value);
      },
      requestOzoneBrowserFilePicker(value) {
        return host.#filePicker?.request(value) === true;
      },
      reportOzoneBrowserFilePickerDelivery(value) {
        host.#reportOzoneBrowserFilePickerDelivery(value);
      },
      requestOuterOriginStorageEstimate(value) {
        return host.#storageEstimate?.request(value) === true;
      },
    });
  }

  #capturePageErrors() {
    this.#windowErrorHandler = (event) => {
      this.#reportFatal(String(event.error || event.message || "window error"));
    };
    this.#unhandledRejectionHandler = (event) => {
      this.#reportFatal(`unhandled rejection: ${String(event.reason)}`);
    };
    addEventListener("error", this.#windowErrorHandler);
    addEventListener("unhandledrejection", this.#unhandledRejectionHandler);
  }

  #setModule(module) {
    if (this.#isExecutionQuiesced()) {
      this.#record("runtime", "initialization ignored after terminal state");
      return;
    }
    if (!module || typeof module !== "object" ||
        typeof module.ccall !== "function") {
      this.#reportFatal("onRuntimeInitialized did not supply a callable Module");
      return;
    }
    if (this.#runtimeInitialized) {
      this.#reportFatal("onRuntimeInitialized supplied multiple Module objects");
      return;
    }
    this.#module = module;
    this.#runtimeInitialized = true;
    this.#pointerInput = new ChromiumWasmTrustedPointerInput(this.#canvas, {
      getModule: () => this.#module,
      recordFatal: (message) => this.#reportFatal(message),
      maximumFrameDimension: MAX_FRAME_DIMENSION,
    });
    this.#pointerInput.attach();
    this.#textInput = new ChromiumWasmTrustedTextInput(
        this.#canvas, this.#textProxy, {
          getModule: () => this.#module,
          reportFatal: (message) => this.#reportFatal(message),
        });
    this.#textInput.attach();
    this.#clipboardInput = new ChromiumWasmTrustedClipboardInput(
        this.#textProxy, {
          getModule: () => this.#module,
          reportFatal: (message) => this.#reportFatal(message),
        });
    this.#clipboardInput.attach();
    this.#filePicker = new ChromiumWasmTrustedFilePicker({
      getModule: () => this.#module,
      reportFatal: (message) => this.#reportFatal(message),
    });
    this.#filePicker.attach();
    this.#storageEstimate = new ChromiumWasmOuterOriginStorageEstimate({
      getModule: () => this.#module,
      recordFatal: (message) => this.#reportFatal(message),
      onResult: (report) => this.#record("storage-estimate", report.status),
    });
    if (this.#latestTextInputState) {
      this.#textInput.handleOzoneTextInputState(this.#latestTextInputState);
      this.#clipboardInput.handleOzoneTextInputState(this.#latestTextInputState);
    }
    this.#shutdownButton.disabled = false;
    this.#record("runtime", "initialized");
  }

  #requestShutdown() {
    if (this.#shutdownRequested || this.#isExecutionQuiesced() || !this.#module ||
        typeof this.#module.ccall !== "function") {
      return;
    }
    try {
      const accepted = this.#module.ccall(
          "chromium_wasm_browser_host_request_shutdown", "number", [], []);
      // Emscripten can synchronously re-enter a host callback from this ABI.
      // An abort or exit observed there has already quiesced the runtime, so
      // do not record this now-stale request as an accepted shutdown.
      if (this.#isExecutionQuiesced()) {
        return;
      }
      if (accepted !== 1) {
        throw new Error(`shutdown ABI returned ${String(accepted)}`);
      }
      this.#shutdownRequested = true;
      this.#shutdownButton.disabled = true;
      this.#pointerInput?.releaseActivePointer("host-shutdown");
      this.#textInput?.releaseActiveInput("host-shutdown");
      this.#record("shutdown", "accepted");
    } catch (error) {
      if (this.#isExecutionQuiesced()) {
        return;
      }
      this.#reportFatal(`shutdown ABI failed: ${String(error)}`);
    }
  }

  async run(version, packageMetadata) {
    if (version?.schema_version !== PACKAGE_SCHEMA_VERSION) {
      throw new Error("VERSION.json has an unsupported package schema version");
    }
    if (version?.release_status !== RELEASE_STATUS) {
      throw new Error("VERSION.json does not declare this pre-release package");
    }
    const validatedVersion = validateVersionMetadata(version);
    const gateState = validatedVersion.gateState;
    const inputModuleName = validatedVersion.build.input_module_name;
    if (typeof inputModuleName !== "string" ||
        !/^[A-Za-z0-9_]+$/.test(inputModuleName)) {
      throw new Error("VERSION.json has an invalid input module name");
    }
    if (globalThis.crossOriginIsolated !== true ||
        typeof SharedArrayBuffer !== "function") {
      throw new Error("this package requires COOP/COEP cross-origin isolation");
    }
    if (!packageMetadata || typeof packageMetadata !== "object") {
      throw new Error("VERSION.json runtime metadata is invalid");
    }
    const wispConfiguration = loadReleaseWispConfiguration();
    this.#wispConfigured = wispConfiguration !== undefined;
    this.#gateState = gateState;
    this.#packageMetadata = packageMetadata;
    this.#renderVersions(version);
    this.#renderGateState(gateState);
    this.#capturePageErrors();
    this.#installBridge();
    this.#shutdownButton.addEventListener("click", () => this.#requestShutdown());
    this.#canvas.focus({preventScroll: true});
    if (document.activeElement !== this.#canvas) {
      throw new Error("browser canvas did not accept focus");
    }

    const loaderUrl = new URL(`./${LOADER_ARTIFACT_PATH}`, import.meta.url);
    const wasmUrl = new URL(`./${WASM_ARTIFACT_PATH}`, import.meta.url);
    const [loaderBytes, wasmBinary] = await Promise.all([
      fetchVerifiedArtifact(
          loaderUrl, validatedVersion.executableArtifacts.loader,
          "text/javascript", "generated loader"),
      fetchVerifiedArtifact(
          wasmUrl, validatedVersion.executableArtifacts.wasm,
          "application/wasm", "generated Wasm"),
    ]);
    if (typeof Blob !== "function" || typeof URL !== "function" ||
        typeof URL.createObjectURL !== "function" ||
        typeof URL.revokeObjectURL !== "function") {
      throw new Error("verified generated loader requires Blob URL support");
    }
    const mainScriptUrlOrBlob = new Blob([loaderBytes], {
      type: "text/javascript",
    });
    let namespace;
    const loaderImportUrl = URL.createObjectURL(mainScriptUrlOrBlob);
    try {
      namespace = await import(loaderImportUrl);
    } finally {
      // The module namespace has captured this import. Keep the Blob itself
      // alive in moduleOptions for Emscripten's worker bootstrap below.
      URL.revokeObjectURL(loaderImportUrl);
    }
    if (typeof namespace.default !== "function") {
      throw new Error("generated loader has no default factory export");
    }
    this.#runtimeArtifactsVerified = true;
    this.#record("artifacts", "verified");
    const host = this;
    const moduleOptions = {
      canvas: this.#canvas,
      noExitRuntime: false,
      mainScriptUrlOrBlob,
      locateFile(path) {
        if (path !== `${inputModuleName}.wasm` && path !== "chromium-wasm.wasm") {
          throw new Error(`unexpected generated sidecar ${String(path)}`);
        }
        return wasmUrl.href;
      },
      print(line) {
        host.#record("stdout", line);
      },
      printErr(line) {
        host.#record("stderr", line);
      },
      onRuntimeInitialized() {
        host.#setModule(this);
      },
      onAbort(reason) {
        host.#reportRuntimeAbort(reason);
      },
      onExit(code) {
        host.#reportRuntimeExit(code);
      },
      wasmBinary,
    };
    if (wispConfiguration !== undefined) {
      moduleOptions.chromiumWasmWisp = wispConfiguration;
    }
    this.#record("wisp", this.#wispConfigured ? "configured" : "unconfigured");
    Promise.resolve(namespace.default(moduleOptions)).catch((error) => {
      host.#reportFatal(`generated loader rejected: ${String(error)}`);
    });
    this.#record("loader", "started");
  }
}

function packageRuntimeMetadata(validatedVersion, versionBytes, versionJsonSha256) {
  const {build, gateState, versions} = validatedVersion;
  if (!(versionBytes instanceof Uint8Array)) {
    throw new Error("VERSION.json runtime bytes are invalid");
  }
  asSha256(versionJsonSha256, "VERSION.json runtime metadata");
  return Object.freeze({
    build: Object.freeze({
      artifactSourceProvenance: build.artifact_source_provenance,
      inputModuleName: build.input_module_name,
      resourceDelivery: build.resource_delivery,
      stagingCheckout: build.staging_checkout,
    }),
    gateState: Object.freeze({...gateState}),
    product: PRODUCT_NAME,
    protocol: PACKAGE_METADATA_PROTOCOL,
    releaseStatus: RELEASE_STATUS,
    schemaVersion: PACKAGE_SCHEMA_VERSION,
    versionJsonSha256,
    versions: Object.freeze({
      chromium: versions.chromium,
      emscripten: versions.emscripten,
      v8: versions.v8,
    }),
  });
}

export async function loadVersion() {
  const versionUrl = new URL("./VERSION.json", import.meta.url);
  const response = await fetch(versionUrl.href, {
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
  });
  if (!response || !response.ok || response.url !== versionUrl.href) {
    throw new Error("VERSION.json request was not exact");
  }
  requireArtifactResponseHeaders(response, "application/json", "VERSION.json");
  const contentLength = response.headers?.get("Content-Length");
  if (typeof contentLength !== "string" || !/^\d+$/.test(contentLength)) {
    throw new Error("VERSION.json response lacks a bounded Content-Length");
  }
  const byteLength = Number(contentLength);
  if (!Number.isSafeInteger(byteLength) || byteLength <= 0 ||
      byteLength > MAX_VERSION_JSON_BYTES) {
    throw new Error("VERSION.json response Content-Length is invalid");
  }
  const versionBytes = new Uint8Array(await response.arrayBuffer());
  if (versionBytes.byteLength !== byteLength) {
    throw new Error("VERSION.json response length does not match Content-Length");
  }
  const version = parseCanonicalVersionJson(versionBytes);
  const validatedVersion = validateVersionMetadata(version);
  const versionJsonSha256 = await sha256Hex(versionBytes);
  return {
    version,
    packageMetadata: packageRuntimeMetadata(
        validatedVersion, versionBytes, versionJsonSha256),
  };
}

export async function runChromiumWasmPreRelease() {
  const root = document.querySelector("#chrome-root");
  const canvas = document.querySelector("#browser-canvas");
  const textProxy = document.querySelector("#browser-text-proxy");
  const status = document.querySelector("#chrome-status");
  const versions = document.querySelector("#versions");
  const gateState = document.querySelector("#gate-state");
  const shutdownButton = document.querySelector("#shutdown");
  const host = new ChromiumWasmPreReleaseHost(
      canvas, textProxy, root, status, versions, gateState, shutdownButton);
  const loadedVersion = await loadVersion();
  await host.run(loadedVersion.version, loadedVersion.packageMetadata);
}
