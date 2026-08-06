# M5 public HTTPS/WISP evidence run

`run_m5_public_https_suite.py` is the M5 evidence gate for public HTTPS. It
drives each configured document through a fresh Chromium profile, host page,
and WISP carrier, then stores a redacted result artifact. It does not use a
host `fetch()` path for the document load.

This run needs operator-owned infrastructure. Do not commit an endpoint,
probe URL, credential, or completed diagnostics artifact to this repository.

## Prerequisites

- A credential-free, publicly reachable WISP v2.1 WebSocket endpoint. It must
  negotiate the exact `wisp` subprotocol, use `wss://`, and have a public DNS
  hostname. The endpoint cannot have a query string, fragment, or credentials.
- Two to four project-controlled, publicly trusted HTTPS documents on distinct
  DNS hostnames. Each document must be a direct, nonredirecting `200` response
  at the default HTTPS port. Together, the documents must cover `h2` and
  `http/1.1`. The `http/1.1` lane must have a live Chromium response that
  reports `http/1.1`; advertising only `h2` from that origin does not satisfy
  the evidence gate.
- Gateway policy that permits TCP port 443 to every probe hostname and rejects
  TCP port 444 for those same hostnames. The runner verifies the denial before
  it starts the allowed navigation.
- A clean checkout and an existing output directory generated from the pinned
  `m3_content_gn_args`. The suite checks the output configuration, relinks its
  dedicated public target, and verifies the resulting artifact provenance.

## Manifest

Copy
[`m5_public_https_suite_manifest.example.json`](testdata/m5_public_https_suite_manifest.example.json)
to an operator-controlled path outside this checkout, replace every
`.example.invalid` placeholder, and keep the completed file private. The
example is intentionally rejected by the runner until it is replaced.

The external JSON file is limited to 16 KiB and has exactly these fields:

```json
{
  "schema_version": 1,
  "public_wisp_endpoint": "wss://gateway.example.invalid/wisp/",
  "probes": [
    {
      "public_probe_url": "https://site-h2.example.invalid/m5-h2",
      "expected_status": 200,
      "expected_protocol": "h2"
    },
    {
      "public_probe_url": "https://site-http1.example.invalid/m5-http1",
      "expected_status": 200,
      "expected_protocol": "http/1.1"
    }
  ]
}
```

Each probe object must contain exactly `public_probe_url`, `expected_status`,
and `expected_protocol`. URLs and hostnames must be unique. `expected_status`
is always `200`; `expected_protocol` is either `h2` or `http/1.1`.

## Protocol lanes

The `h2` probe starts the inner Wasm Chromium normally. For the `http/1.1`
probe, the host starts a fresh inner Wasm Chromium instance with
`--disable-http2` supplied to its Emscripten module factory before Chromium
starts. This is intentionally not an argument to the outer browser that hosts
the page. The run still requires the inner Chromium CDP record to report the
configured protocol exactly, together with the WISP completion evidence; a
host-browser response or a synthetic protocol label cannot satisfy the gate.

## Run

From a clean checkout with the public target's output directory already
generated, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/wasm/run_m5_public_https_suite.py \
  --suite-manifest /absolute/operator-controlled/m5-public-suite.json \
  --browser /path/to/browser \
  --out-dir out/wasm-content-m3 \
  --timeout-per-probe 120
```

`--browser` may be omitted when the runner can find a supported browser.
Use `--no-sandbox` only in an isolated environment that requires it. Do not
override the module name: the suite deliberately uses its dedicated public
M5 target.

On success the runner prints `CHROMIUM_WASM_M5_PUBLIC_HTTPS_SUITE:PASS` and
writes a redacted, provenance-bound artifact below the configured diagnostics
directory. A failure artifact contains no configured endpoint or probe URL;
retain it with the operator's deployment records rather than committing it.
