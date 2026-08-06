// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This is deliberately a polling bridge. Emscripten's stock WebSocket helper
// invokes C callbacks on the browser main thread, while TCPSocketWasm lives on
// a Chromium IO sequence. The C++ socket therefore polls this JavaScript-owned
// state synchronously through proxied imports. No WebSocket event directly
// invokes Chromium code.
//
// Every call touching HEAPU8 copies before it returns. In particular, queue
// entries never retain a typed-array view into Wasm memory because memory
// growth can replace that view.
//
// The WISP packet framing implemented here is v2.1:
// https://github.com/MercuryWorkshop/wisp-protocol/blob/v2/protocol.md
mergeInto(LibraryManager.library, {
  $ChromiumWasmWispTransport: {
    // These values are part of the C++ bridge ABI. Keep them synchronized with
    // net/socket/tcp_socket_wasm.cc rather than deriving state from a browser
    // WebSocket readyState.
    states: Object.freeze({
      disabled: 0,
      connecting: 1,
      open: 2,
      eof: 3,
      failed: 4,
    }),

    // Values mirror net/base/net_error_list.h. The JavaScript layer returns
    // concrete net errors so that the socket can preserve Chromium's error
    // semantics instead of treating a WISP close as a successful operation.
    errors: Object.freeze({
      ok: 0,
      failed: -2,
      aborted: -3,
      invalidArgument: -4,
      timedOut: -7,
      accessDenied: -10,
      notImplemented: -11,
      insufficientResources: -12,
      socketNotConnected: -15,
      blockedByAdministrator: -22,
      connectionClosed: -100,
      connectionReset: -101,
      connectionRefused: -102,
      connectionAborted: -103,
      connectionFailed: -104,
      nameNotResolved: -105,
      internetDisconnected: -106,
      addressInvalid: -108,
      addressUnreachable: -109,
      connectionTimedOut: -118,
      messageTooBig: -142,
    }),

    packetTypes: Object.freeze({
      connect: 0x01,
      data: 0x02,
      continue: 0x03,
      close: 0x04,
      info: 0x05,
    }),

    closeReasons: Object.freeze({
      unspecified: 0x01,
      voluntary: 0x02,
      networkError: 0x03,
      incompatibleExtensions: 0x04,
      invalidStream: 0x41,
      unreachable: 0x42,
      streamTimedOut: 0x43,
      refused: 0x44,
      transferTimedOut: 0x47,
      blocked: 0x48,
      throttled: 0x49,
      clientReceiveError: 0x81,
      authenticationFailed: 0xc0,
      signatureFailed: 0xc1,
      authenticationRequired: 0xc2,
    }),

    extensionIds: Object.freeze({
      passwordAuthentication: 0x02,
      publicKeyAuthentication: 0x03,
      streamOpenConfirmation: 0x05,
    }),

    phases: Object.freeze({
      idle: 0,
      openingWebSocket: 1,
      awaitingServerInfo: 2,
      awaitingServerContinue: 3,
      ready: 4,
      failed: 5,
    }),

    defaults: Object.freeze({
      maxStreams: 1024,
      maxHostnameBytes: 253,
      maxDataFrameBytes: 16 * 1024,
      maxInboundStreamBytes: 1024 * 1024,
      maxOutboundStreamBytes: 1024 * 1024,
      maxInboundBytes: 16 * 1024 * 1024,
      maxOutboundBytes: 16 * 1024 * 1024,
      maxWebSocketBufferedBytes: 4 * 1024 * 1024,
      maxIncomingPacketBytes: 1024 * 1024 + 5,
      handshakeTimeoutMs: 15 * 1000,
      streamOpenTimeoutMs: 30 * 1000,
      flushDelayMs: 10,
    }),

    config: undefined,
    configRead: false,
    streams: new Map(),
    controlQueue: [],
    totalInboundBytes: 0,
    totalOutboundBytes: 0,
    websocket: null,
    phase: 0,
    connectionGeneration: 0,
    webSocketOpenCount: 0,
    readyConnectionCount: 0,
    confirmedStreamCount: 0,
    diagnosticEvidenceEpoch: 0,
    diagnosticEvidenceWindowEpoch: null,
    diagnosticEvidenceWindowTarget: null,
    diagnosticEvidenceWindowConfirmed: false,
    handshakeTimer: null,
    flushTimer: null,

    // Test-only reset hook. Production code owns one module instance and never
    // calls this; it lets the Node contract test exercise independent peers.
    resetForTesting() {
      const websocket = this.websocket;
      this._clearTimer(this.handshakeTimer);
      this._clearTimer(this.flushTimer);
      for (const stream of this.streams.values()) {
        this._clearTimer(stream.openTimer);
      }
      this.config = undefined;
      this.configRead = false;
      this.streams.clear();
      this.controlQueue = [];
      this.totalInboundBytes = 0;
      this.totalOutboundBytes = 0;
      this.websocket = null;
      this.phase = this.phases.idle;
      this.connectionGeneration += 1;
      this.webSocketOpenCount = 0;
      this.readyConnectionCount = 0;
      this.confirmedStreamCount = 0;
      this.diagnosticEvidenceEpoch = 0;
      this.diagnosticEvidenceWindowEpoch = null;
      this.diagnosticEvidenceWindowTarget = null;
      this.diagnosticEvidenceWindowConfirmed = false;
      this.handshakeTimer = null;
      this.flushTimer = null;
      if (websocket && typeof websocket.close === 'function') {
        try {
          websocket.close();
        } catch (_) {
          // The test hook only releases local state.
        }
      }
    },

    isConfigured() {
      return this._readConfig() ? 1 : 0;
    },

    diagnosticsCompletionFlags() {
      if (!this._readConfig()) {
        return -1;
      }
      let flags = 0;
      if (this.webSocketOpenCount > 0) {
        flags |= 1;
      }
      if (this.readyConnectionCount > 0) {
        flags |= 2;
      }
      if (this.confirmedStreamCount > 0 &&
          (this.diagnosticEvidenceWindowEpoch === null ||
           this.diagnosticEvidenceWindowConfirmed)) {
        flags |= 4;
      }
      return flags;
    },

    beginDiagnosticsEvidenceWindow(hostnamePointer, hostnameLength, port) {
      if (!this._readConfig()) {
        return 0;
      }
      const hostname = this._readHostname(hostnamePointer, hostnameLength);
      if (hostname === null || !Number.isSafeInteger(port) || port <= 0 ||
          port > 65535) {
        return 0;
      }
      this.diagnosticEvidenceEpoch += 1;
      this.diagnosticEvidenceWindowEpoch = this.diagnosticEvidenceEpoch;
      this.diagnosticEvidenceWindowTarget = Object.freeze({
        hostname: hostname.toLowerCase(),
        port,
      });
      this.diagnosticEvidenceWindowConfirmed = false;
      return 1;
    },

    open(streamId, hostnamePointer, hostnameLength, port) {
      const config = this._readConfig();
      if (!config) {
        return 0;
      }

      const id = this._unsigned32(streamId);
      const hostname = this._readHostname(hostnamePointer, hostnameLength);
      if (id === null || id === 0 || hostname === null ||
          !Number.isSafeInteger(port) || port <= 0 || port > 65535 ||
          this.streams.has(id) || this.streams.size >= config.maxStreams) {
        return 0;
      }

      const stream = {
        id,
        hostname,
        port,
        state: this.states.connecting,
        error: this.errors.ok,
        inbound: [],
        inboundBytes: 0,
        outbound: [],
        outboundBytes: 0,
        remoteCredit: 0,
        connectQueued: false,
        connectSent: false,
        closedLocally: false,
        diagnosticEvidenceEpoch: this.diagnosticEvidenceEpoch,
        openTimer: null,
      };
      this.streams.set(id, stream);

      if (!this._ensureConnection()) {
        this._failStream(stream, this.errors.connectionFailed,
                         /*closeReason=*/null);
        return 1;
      }
      if (this.phase === this.phases.ready) {
        this._queueConnect(stream);
      }
      this._flush();
      return 1;
    },

    state(streamId) {
      if (!this._readConfig()) {
        return this.states.disabled;
      }
      this._flush();
      const stream = this.streams.get(this._unsigned32OrZero(streamId));
      return stream ? stream.state : this.states.failed;
    },

    error(streamId) {
      if (!this._readConfig()) {
        return this.errors.notImplemented;
      }
      const stream = this.streams.get(this._unsigned32OrZero(streamId));
      return stream ? stream.error : this.errors.aborted;
    },

    available(streamId) {
      this._flush();
      const stream = this.streams.get(this._unsigned32OrZero(streamId));
      return stream ? stream.inboundBytes : 0;
    },

    read(streamId, destinationPointer, maximumBytes) {
      const stream = this.streams.get(this._unsigned32OrZero(streamId));
      const destination = this._memoryRange(destinationPointer, maximumBytes);
      if (!stream || !destination || maximumBytes === 0 ||
          stream.inboundBytes === 0) {
        return 0;
      }

      let copied = 0;
      let destinationOffset = destination.start;
      let remaining = Math.min(maximumBytes, stream.inboundBytes);
      while (remaining > 0 && stream.inbound.length > 0) {
        const chunk = stream.inbound[0];
        const count = Math.min(remaining, chunk.length);
        // `chunk` is JavaScript-owned. The target view is looked up only for
        // this synchronous copy and is not retained afterward.
        const heap = this._currentHeap();
        if (destination.end > heap.length) {
          return copied;
        }
        heap.set(chunk.subarray(0, count), destinationOffset);
        copied += count;
        destinationOffset += count;
        remaining -= count;
        stream.inboundBytes -= count;
        this.totalInboundBytes -= count;
        if (count === chunk.length) {
          stream.inbound.shift();
        } else {
          stream.inbound[0] = chunk.slice(count);
        }
      }
      return copied;
    },

    write(streamId, sourcePointer, sourceLength) {
      const stream = this.streams.get(this._unsigned32OrZero(streamId));
      const source = this._memoryRange(sourcePointer, sourceLength);
      if (!stream || !source || sourceLength === 0 ||
          stream.state !== this.states.open) {
        return 0;
      }

      const config = this.config;
      const streamCapacity = config.maxOutboundStreamBytes -
          stream.outboundBytes;
      const globalCapacity = config.maxOutboundBytes - this.totalOutboundBytes;
      const accepted = Math.min(sourceLength, streamCapacity, globalCapacity);
      if (accepted <= 0) {
        this._scheduleFlush();
        return 0;
      }

      // This creates JavaScript-owned chunks before returning to C++. It is
      // also the only point that turns a large Chromium write into bounded
      // WISP DATA frames.
      let offset = source.start;
      let remaining = accepted;
      while (remaining > 0) {
        const count = Math.min(remaining, config.maxDataFrameBytes);
        const heap = this._currentHeap();
        if (source.end > heap.length) {
          return accepted - remaining;
        }
        const chunk = heap.slice(offset, offset + count);
        stream.outbound.push(chunk);
        stream.outboundBytes += count;
        this.totalOutboundBytes += count;
        offset += count;
        remaining -= count;
      }
      this._flush();
      return accepted;
    },

    close(streamId, closeReason) {
      const id = this._unsigned32(streamId);
      if (id === null) {
        return 0;
      }
      const stream = this.streams.get(id);
      if (!stream) {
        return 0;
      }

      stream.closedLocally = true;
      this._clearTimer(stream.openTimer);
      this._discardInbound(stream);
      this._discardOutbound(stream);
      this._removeQueuedConnect(id);
      if (stream.connectSent && this.phase === this.phases.ready) {
        this._queueClose(id, this._validCloseReason(closeReason));
      }
      this.streams.delete(id);
      this._flush();
      return 1;
    },

    _readConfig() {
      if (this.configRead) {
        return this.config;
      }
      this.configRead = true;
      const raw = Module['chromiumWasmWisp'];
      if (!raw || typeof raw !== 'object' || raw.version !== 1 ||
          !this._hasOnlyAllowedConfigFields(raw) ||
          this._hasCredentialFields(raw)) {
        this.config = null;
        return null;
      }

      if (typeof raw.endpoint !== 'string' || raw.endpoint.length === 0 ||
          raw.endpoint.length > 2048) {
        this.config = null;
        return null;
      }
      let endpoint;
      try {
        endpoint = new URL(raw.endpoint);
      } catch (_) {
        this.config = null;
        return null;
      }
      if ((endpoint.protocol !== 'wss:' &&
           !(endpoint.protocol === 'ws:' &&
             this._isLoopbackHost(endpoint.hostname))) ||
          endpoint.username || endpoint.password || endpoint.search ||
          endpoint.hash || !endpoint.pathname.endsWith('/')) {
        this.config = null;
        return null;
      }

      const subprotocol = raw.subprotocol === undefined ? 'wisp' :
          raw.subprotocol;
      if (typeof subprotocol !== 'string' || subprotocol.length === 0 ||
          !/^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/.test(subprotocol)) {
        this.config = null;
        return null;
      }

      const maxStreams = this._boundedOption(
          raw, 'maxStreams', this.defaults.maxStreams, 1, 4096);
      const maxHostnameBytes = this._boundedOption(
          raw, 'maxHostnameBytes', this.defaults.maxHostnameBytes, 1, 253);
      const maxDataFrameBytes = this._boundedOption(
          raw, 'maxDataFrameBytes', this.defaults.maxDataFrameBytes,
          1, 1024 * 1024);
      const maxInboundStreamBytes = this._boundedOption(
          raw, 'maxInboundStreamBytes', this.defaults.maxInboundStreamBytes,
          1, 64 * 1024 * 1024);
      const maxOutboundStreamBytes = this._boundedOption(
          raw, 'maxOutboundStreamBytes', this.defaults.maxOutboundStreamBytes,
          1, 64 * 1024 * 1024);
      const maxInboundBytes = this._boundedOption(
          raw, 'maxInboundBytes', this.defaults.maxInboundBytes,
          1, 256 * 1024 * 1024);
      const maxOutboundBytes = this._boundedOption(
          raw, 'maxOutboundBytes', this.defaults.maxOutboundBytes,
          1, 256 * 1024 * 1024);
      const maxWebSocketBufferedBytes = this._boundedOption(
          raw, 'maxWebSocketBufferedBytes',
          this.defaults.maxWebSocketBufferedBytes, 6, 64 * 1024 * 1024);
      const maxIncomingPacketBytes = this._boundedOption(
          raw, 'maxIncomingPacketBytes',
          this.defaults.maxIncomingPacketBytes, 5, 64 * 1024 * 1024);
      const handshakeTimeoutMs = this._boundedOption(
          raw, 'handshakeTimeoutMs', this.defaults.handshakeTimeoutMs,
          1000, 120 * 1000);
      const streamOpenTimeoutMs = this._boundedOption(
          raw, 'streamOpenTimeoutMs', this.defaults.streamOpenTimeoutMs,
          1000, 120 * 1000);
      if ([maxStreams, maxHostnameBytes, maxDataFrameBytes,
           maxInboundStreamBytes, maxOutboundStreamBytes, maxInboundBytes,
           maxOutboundBytes, maxWebSocketBufferedBytes,
           maxIncomingPacketBytes, handshakeTimeoutMs,
           streamOpenTimeoutMs].some((value) => value === null) ||
          maxWebSocketBufferedBytes < maxDataFrameBytes + 5 ||
          maxIncomingPacketBytes < 5) {
        this.config = null;
        return null;
      }

      this.config = Object.freeze({
        endpoint: endpoint.href,
        subprotocol,
        maxStreams,
        maxHostnameBytes,
        maxDataFrameBytes,
        maxInboundStreamBytes,
        maxOutboundStreamBytes,
        maxInboundBytes,
        maxOutboundBytes,
        maxWebSocketBufferedBytes,
        maxIncomingPacketBytes,
        handshakeTimeoutMs,
        streamOpenTimeoutMs,
        flushDelayMs: this.defaults.flushDelayMs,
        // Each stream can contribute at most one CONNECT and one CLOSE. A
        // fixed INFO packet is the only connection-level control entry.
        // Retaining completed streams until C++ closes them keeps this bound
        // valid even while the browser WebSocket is backpressured.
        maxControlQueueEntries: maxStreams * 2 + 1,
      });
      return this.config;
    },

    _boundedOption(raw, name, fallback, minimum, maximum) {
      if (raw[name] === undefined) {
        return fallback;
      }
      const value = raw[name];
      if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
        return null;
      }
      return value;
    },

    _hasCredentialFields(raw) {
      return [
        'auth',
        'authorization',
        'credentials',
        'password',
        'token',
        'username',
      ].some((name) => Object.prototype.hasOwnProperty.call(raw, name));
    },

    _hasOnlyAllowedConfigFields(raw) {
      const allowed = new Set([
        'version',
        'endpoint',
        'subprotocol',
        'maxStreams',
        'maxHostnameBytes',
        'maxDataFrameBytes',
        'maxInboundStreamBytes',
        'maxOutboundStreamBytes',
        'maxInboundBytes',
        'maxOutboundBytes',
        'maxWebSocketBufferedBytes',
        'maxIncomingPacketBytes',
        'handshakeTimeoutMs',
        'streamOpenTimeoutMs',
      ]);
      return Object.getOwnPropertyNames(raw).every((name) => allowed.has(name));
    },

    _isLoopbackHost(hostname) {
      const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, '');
      if (normalized === 'localhost' || normalized.endsWith('.localhost') ||
          normalized === '::1') {
        return true;
      }
      const octets = normalized.split('.');
      return octets.length === 4 && octets.every((octet) =>
        /^\d{1,3}$/.test(octet) && Number(octet) <= 255) &&
          Number(octets[0]) === 127;
    },

    _readHostname(pointer, length) {
      const range = this._memoryRange(pointer, length);
      if (!range || length === 0 || length > this.config.maxHostnameBytes) {
        return null;
      }
      let hostname;
      try {
        const heap = this._currentHeap();
        if (range.end > heap.length) {
          return null;
        }
        hostname = new TextDecoder('utf-8', {fatal: true}).decode(
            heap.slice(range.start, range.end));
      } catch (_) {
        return null;
      }
      if (hostname.length === 0 || hostname.trim() !== hostname ||
          /[\u0000-\u001f\u007f\s]/.test(hostname)) {
        return null;
      }
      return hostname;
    },

    _memoryRange(pointer, length) {
      if (!Number.isSafeInteger(length) || length < 0 ||
          length > 0x7fffffff) {
        return null;
      }
      const start = this._unsigned32(pointer);
      if (start === null) {
        return null;
      }
      const end = start + length;
      if (!Number.isSafeInteger(end) || end < start ||
          end > this._currentHeap().length) {
        return null;
      }
      return {start, end};
    },

    _currentHeap() {
      // A pthread can grow Wasm memory while the main thread owns WebSocket
      // callbacks. Refresh Emscripten's local view before every access and
      // still avoid retaining the returned view beyond this synchronous call.
      if (typeof growMemViews === 'function') {
        growMemViews();
      }
      return HEAPU8;
    },

    _unsigned32(value) {
      if (!Number.isSafeInteger(value) || value < -0x80000000 ||
          value > 0xffffffff) {
        return null;
      }
      return value >>> 0;
    },

    _unsigned32OrZero(value) {
      const unsigned = this._unsigned32(value);
      return unsigned === null ? 0 : unsigned;
    },

    _ensureConnection() {
      if (this.websocket) {
        return true;
      }
      const WebSocketConstructor = globalThis['WebSocket'];
      if (typeof WebSocketConstructor !== 'function') {
        return false;
      }

      const generation = this.connectionGeneration + 1;
      this.connectionGeneration = generation;
      this.phase = this.phases.openingWebSocket;
      let websocket;
      try {
        websocket = new WebSocketConstructor(
            this.config.endpoint, this.config.subprotocol);
        websocket.binaryType = 'arraybuffer';
      } catch (_) {
        this.phase = this.phases.failed;
        return false;
      }
      this.websocket = websocket;
      websocket.onopen = () => this._onWebSocketOpen(generation, websocket);
      websocket.onmessage = (event) =>
        this._onWebSocketMessage(generation, websocket, event);
      websocket.onerror = () =>
        this._onWebSocketFailure(generation, websocket,
                                 this.errors.connectionFailed,
                                 /*closeSocket=*/true);
      websocket.onclose = () =>
        this._onWebSocketFailure(generation, websocket,
                                 this.errors.internetDisconnected);
      return true;
    },

    _onWebSocketOpen(generation, websocket) {
      if (!this._isCurrentConnection(generation, websocket)) {
        return;
      }
      // Supplying a requested subprotocol does not require a server to select
      // one. WISP framing is valid only after the exact configured protocol
      // was negotiated, so do not treat an otherwise-open carrier as usable
      // when the upgrade omitted it.
      if (websocket.protocol !== this.config.subprotocol) {
        this._failConnection(this.errors.notImplemented,
                             /*closeSocket=*/true);
        return;
      }
      this.webSocketOpenCount += 1;
      this.phase = this.phases.awaitingServerInfo;
      this._clearTimer(this.handshakeTimer);
      this.handshakeTimer = this._scheduleTimer(() => {
        if (this._isCurrentConnection(generation, websocket) &&
            this.phase !== this.phases.ready) {
          this._failConnection(this.errors.timedOut, /*closeSocket=*/true);
        }
      }, this.config.handshakeTimeoutMs);
    },

    _onWebSocketMessage(generation, websocket, event) {
      if (!this._isCurrentConnection(generation, websocket)) {
        return;
      }
      let bytes;
      if (event && event.data instanceof ArrayBuffer) {
        bytes = new Uint8Array(event.data);
      } else if (event && ArrayBuffer.isView(event.data)) {
        bytes = new Uint8Array(
            event.data.buffer, event.data.byteOffset, event.data.byteLength);
      } else {
        this._rejectHandshake(this.errors.failed);
        return;
      }
      if (bytes.length < 5) {
        this._rejectHandshake(this.errors.failed);
        return;
      }

      const type = bytes[0];
      const streamId = this._readUint32(bytes, 1);
      if (bytes.length > this.config.maxIncomingPacketBytes) {
        const stream = type === this.packetTypes.data && streamId !== 0 ?
            this.streams.get(streamId) : null;
        if (stream) {
          this._failStream(stream, this.errors.messageTooBig,
                           this.closeReasons.clientReceiveError);
        } else {
          this._rejectHandshake(this.errors.messageTooBig);
        }
        return;
      }
      const payload = bytes.subarray(5);
      switch (type) {
        case this.packetTypes.info:
          this._onInfo(streamId, payload);
          break;
        case this.packetTypes.continue:
          this._onContinue(streamId, payload);
          break;
        case this.packetTypes.data:
          this._onData(streamId, payload);
          break;
        case this.packetTypes.close:
          this._onClose(streamId, payload);
          break;
        default:
          this._rejectHandshake(this.errors.failed);
          break;
      }
    },

    _onWebSocketFailure(generation, websocket, error, closeSocket = false) {
      if (this._isCurrentConnection(generation, websocket)) {
        this._failConnection(error, closeSocket);
      }
    },

    _isCurrentConnection(generation, websocket) {
      return this.connectionGeneration === generation &&
          this.websocket === websocket;
    },

    _onInfo(streamId, payload) {
      if (streamId !== 0 || this.phase !== this.phases.awaitingServerInfo) {
        this._rejectHandshake(this.errors.failed);
        return;
      }
      const parsed = this._parseInfo(payload);
      if (!parsed || parsed.major !== 2 ||
          !parsed.extensions.has(this.extensionIds.streamOpenConfirmation) ||
          parsed.extensions.get(this.extensionIds.streamOpenConfirmation).length !== 0) {
        this._rejectHandshake(this.errors.notImplemented,
                              this.closeReasons.incompatibleExtensions);
        return;
      }
      if (this._requiresUnsupportedAuthentication(parsed.extensions)) {
        this._rejectHandshake(this.errors.accessDenied,
                              this.closeReasons.authenticationRequired);
        return;
      }

      this.phase = this.phases.awaitingServerContinue;
      const extension = new Uint8Array(5);
      extension[0] = this.extensionIds.streamOpenConfirmation;
      // The remaining four bytes are the little-endian zero metadata length.
      const infoPayload = new Uint8Array(2 + extension.length);
      infoPayload[0] = 2;
      infoPayload[1] = 1;
      infoPayload.set(extension, 2);
      if (!this._queueControl({
        kind: 'info',
        packet: this._packet(this.packetTypes.info, 0, infoPayload),
      })) {
        return;
      }
      this._flush();
    },

    _parseInfo(payload) {
      if (payload.length < 2) {
        return null;
      }
      const extensions = new Map();
      let offset = 2;
      while (offset < payload.length) {
        if (payload.length - offset < 5) {
          return null;
        }
        const id = payload[offset];
        const length = this._readUint32(payload, offset + 1);
        offset += 5;
        const end = offset + length;
        if (!Number.isSafeInteger(end) || end < offset ||
            end > payload.length || extensions.has(id)) {
          return null;
        }
        extensions.set(id, payload.slice(offset, end));
        offset = end;
      }
      return {major: payload[0], minor: payload[1], extensions};
    },

    _requiresUnsupportedAuthentication(extensions) {
      for (const id of [
        this.extensionIds.passwordAuthentication,
        this.extensionIds.publicKeyAuthentication,
      ]) {
        const metadata = extensions.get(id);
        if (metadata && (metadata.length === 0 || metadata[0] !== 0)) {
          return true;
        }
      }
      return false;
    },

    _onContinue(streamId, payload) {
      if (payload.length !== 4) {
        this._rejectHandshake(this.errors.failed);
        return;
      }
      const bufferRemaining = this._readUint32(payload, 0);
      if (streamId === 0) {
        if (this.phase === this.phases.awaitingServerInfo) {
          // WISP v1 begins with this packet. Do not silently fall back: the
          // TCP layer relies on v2 stream-open confirmation for Connect().
          this._rejectHandshake(this.errors.notImplemented,
                                this.closeReasons.incompatibleExtensions);
          return;
        }
        if (this.phase !== this.phases.awaitingServerContinue) {
          this._rejectHandshake(this.errors.failed);
          return;
        }
        this._clearTimer(this.handshakeTimer);
        this.handshakeTimer = null;
        this.phase = this.phases.ready;
        this.readyConnectionCount += 1;
        for (const stream of this.streams.values()) {
          if (stream.state === this.states.connecting) {
            this._queueConnect(stream);
          }
        }
        this._flush();
        return;
      }

      if (this.phase !== this.phases.ready) {
        this._rejectHandshake(this.errors.failed);
        return;
      }
      const stream = this.streams.get(streamId);
      if (!stream || stream.closedLocally) {
        return;
      }
      if (!stream.connectSent ||
          (stream.state !== this.states.connecting &&
           stream.state !== this.states.open)) {
        this._failStream(stream, this.errors.failed,
                         this.closeReasons.clientReceiveError);
        return;
      }
      stream.remoteCredit = bufferRemaining;
      if (stream.state === this.states.connecting) {
        stream.state = this.states.open;
        this.confirmedStreamCount += 1;
        const target = this.diagnosticEvidenceWindowTarget;
        if (target !== null &&
            stream.diagnosticEvidenceEpoch ===
                this.diagnosticEvidenceWindowEpoch &&
            stream.hostname.toLowerCase() === target.hostname &&
            stream.port === target.port) {
          this.diagnosticEvidenceWindowConfirmed = true;
        }
        this._clearTimer(stream.openTimer);
        stream.openTimer = null;
      }
      this._flush();
    },

    _onData(streamId, payload) {
      if (this.phase !== this.phases.ready || streamId === 0) {
        this._rejectHandshake(this.errors.failed);
        return;
      }
      const stream = this.streams.get(streamId);
      if (!stream || stream.closedLocally || stream.state === this.states.eof ||
          stream.state === this.states.failed) {
        return;
      }
      if (stream.state !== this.states.open ||
          payload.length + 5 > this.config.maxIncomingPacketBytes ||
          payload.length > this.config.maxInboundStreamBytes ||
          stream.inboundBytes + payload.length >
              this.config.maxInboundStreamBytes ||
          this.totalInboundBytes + payload.length >
              this.config.maxInboundBytes) {
        this._failStream(stream, this.errors.insufficientResources,
                         this.closeReasons.clientReceiveError);
        return;
      }
      if (payload.length === 0) {
        return;
      }
      const copy = payload.slice();
      stream.inbound.push(copy);
      stream.inboundBytes += copy.length;
      this.totalInboundBytes += copy.length;
    },

    _onClose(streamId, payload) {
      if (payload.length !== 1) {
        this._rejectHandshake(this.errors.failed);
        return;
      }
      const closeReason = payload[0];
      if (streamId === 0) {
        const error = this._errorForCloseReason(closeReason);
        this._failConnection(
            error === this.errors.ok ? this.errors.connectionClosed : error,
            /*closeSocket=*/true);
        return;
      }
      const stream = this.streams.get(streamId);
      if (!stream || stream.closedLocally) {
        return;
      }

      this._clearTimer(stream.openTimer);
      stream.openTimer = null;
      this._discardOutbound(stream);
      const error = this._errorForCloseReason(closeReason);
      if (error === this.errors.ok && stream.state === this.states.open) {
        stream.state = this.states.eof;
        stream.error = this.errors.ok;
        return;
      }
      this._failStream(stream,
                       error === this.errors.ok ? this.errors.connectionFailed :
                                                  error,
                       /*closeReason=*/null);
    },

    _errorForCloseReason(closeReason) {
      switch (closeReason) {
        case this.closeReasons.unspecified:
        case this.closeReasons.voluntary:
          return this.errors.ok;
        case this.closeReasons.networkError:
          return this.errors.connectionReset;
        case this.closeReasons.incompatibleExtensions:
          return this.errors.notImplemented;
        case this.closeReasons.invalidStream:
          return this.errors.addressInvalid;
        case this.closeReasons.unreachable:
          return this.errors.addressUnreachable;
        case this.closeReasons.streamTimedOut:
          return this.errors.connectionTimedOut;
        case this.closeReasons.refused:
          return this.errors.connectionRefused;
        case this.closeReasons.transferTimedOut:
          return this.errors.timedOut;
        case this.closeReasons.blocked:
          return this.errors.blockedByAdministrator;
        case this.closeReasons.throttled:
          return this.errors.insufficientResources;
        case this.closeReasons.authenticationFailed:
        case this.closeReasons.signatureFailed:
        case this.closeReasons.authenticationRequired:
          return this.errors.accessDenied;
        default:
          return this.errors.connectionFailed;
      }
    },

    _queueConnect(stream) {
      if (stream.connectQueued || stream.connectSent || stream.closedLocally ||
          stream.state !== this.states.connecting) {
        return;
      }
      const hostnameBytes = new TextEncoder().encode(stream.hostname);
      const payload = new Uint8Array(3 + hostnameBytes.length);
      payload[0] = 0x01;  // TCP. UDP is deliberately unsupported.
      payload[1] = stream.port & 0xff;
      payload[2] = stream.port >>> 8;
      payload.set(hostnameBytes, 3);
      if (!this._queueControl({
        kind: 'connect',
        streamId: stream.id,
        packet: this._packet(this.packetTypes.connect, stream.id, payload),
      })) {
        return;
      }
      stream.connectQueued = true;
    },

    _queueClose(streamId, closeReason) {
      this._queueControl({
        kind: 'close',
        streamId,
        packet: this._packet(
            this.packetTypes.close, streamId, new Uint8Array([closeReason])),
      });
    },

    _queueControl(entry) {
      if (this.controlQueue.length >= this.config.maxControlQueueEntries) {
        this._failConnection(this.errors.insufficientResources,
                             /*closeSocket=*/true);
        return false;
      }
      this.controlQueue.push(entry);
      return true;
    },

    _removeQueuedConnect(streamId) {
      this.controlQueue = this.controlQueue.filter((entry) =>
        entry.kind !== 'connect' || entry.streamId !== streamId);
    },

    _flush() {
      const websocket = this.websocket;
      if (!websocket || websocket.readyState !== 1) {
        return;
      }

      while (this.controlQueue.length > 0) {
        const entry = this.controlQueue[0];
        if (entry.kind === 'connect') {
          const stream = this.streams.get(entry.streamId);
          if (!stream || stream.closedLocally || stream.connectSent ||
              stream.state !== this.states.connecting) {
            this.controlQueue.shift();
            continue;
          }
        }
        if (!this._trySend(entry.packet)) {
          this._scheduleFlush();
          return;
        }
        this.controlQueue.shift();
        if (entry.kind === 'connect') {
          const stream = this.streams.get(entry.streamId);
          if (stream) {
            stream.connectQueued = false;
            stream.connectSent = true;
            stream.openTimer = this._scheduleTimer(() => {
              if (stream.state === this.states.connecting &&
                  this.streams.get(stream.id) === stream) {
                this._failStream(stream, this.errors.connectionTimedOut,
                                 this.closeReasons.voluntary);
              }
            }, this.config.streamOpenTimeoutMs);
          }
        }
      }

      if (this.phase !== this.phases.ready) {
        return;
      }

      for (const stream of this.streams.values()) {
        if (stream.state !== this.states.open || stream.remoteCredit === 0) {
          continue;
        }
        while (stream.remoteCredit > 0 && stream.outbound.length > 0) {
          const chunk = stream.outbound[0];
          const packet = this._packet(this.packetTypes.data, stream.id, chunk);
          if (!this._trySend(packet)) {
            this._scheduleFlush();
            return;
          }
          stream.outbound.shift();
          stream.outboundBytes -= chunk.length;
          this.totalOutboundBytes -= chunk.length;
          stream.remoteCredit -= 1;
        }
      }

      if (this._hasSendableQueuedData()) {
        this._scheduleFlush();
      }
    },

    _trySend(packet) {
      const websocket = this.websocket;
      if (!websocket || websocket.readyState !== 1 ||
          packet.length > this.config.maxWebSocketBufferedBytes ||
          this._webSocketBufferedAmount(websocket) + packet.length >
              this.config.maxWebSocketBufferedBytes) {
        return false;
      }
      try {
        websocket.send(packet);
        return true;
      } catch (_) {
        this._failConnection(this.errors.connectionFailed,
                             /*closeSocket=*/true);
        return false;
      }
    },

    _webSocketBufferedAmount(websocket) {
      const amount = websocket.bufferedAmount;
      return Number.isSafeInteger(amount) && amount >= 0 ? amount : 0;
    },

    _hasSendableQueuedData() {
      for (const stream of this.streams.values()) {
        if (stream.state === this.states.open && stream.remoteCredit > 0 &&
            stream.outboundBytes > 0) {
          return true;
        }
      }
      return false;
    },

    _failStream(stream, error, closeReason) {
      if (!stream || stream.closedLocally || stream.state === this.states.failed) {
        return;
      }
      this._clearTimer(stream.openTimer);
      stream.openTimer = null;
      stream.state = this.states.failed;
      stream.error = error;
      this._discardOutbound(stream);
      // TCPSocketWasm observes terminal failure before it can consume queued
      // data. Retaining it would permanently charge the global inbound quota
      // until the socket owner happens to close the failed stream.
      this._discardInbound(stream);
      this._removeQueuedConnect(stream.id);
      if (closeReason !== null && stream.connectSent &&
          this.phase === this.phases.ready) {
        this._queueClose(stream.id, closeReason);
        this._flush();
      }
    },

    _failConnection(error, closeSocket) {
      const websocket = this.websocket;
      this._clearTimer(this.handshakeTimer);
      this._clearTimer(this.flushTimer);
      this.handshakeTimer = null;
      this.flushTimer = null;
      this.connectionGeneration += 1;
      this.websocket = null;
      this.phase = this.phases.failed;
      this.controlQueue = [];
      for (const stream of this.streams.values()) {
        if (stream.state === this.states.connecting ||
            stream.state === this.states.open) {
          this._clearTimer(stream.openTimer);
          stream.openTimer = null;
          stream.state = this.states.failed;
          stream.error = error;
          this._discardOutbound(stream);
          this._discardInbound(stream);
        }
      }
      if (closeSocket && websocket && typeof websocket.close === 'function') {
        try {
          websocket.close();
        } catch (_) {
          // State is already terminal; no further recovery is possible here.
        }
      }
    },

    _rejectHandshake(error, closeReason = this.closeReasons.incompatibleExtensions) {
      const websocket = this.websocket;
      if (websocket && websocket.readyState === 1) {
        try {
          // A protocol-rejection CLOSE must be sent even if normal queued DATA
          // is backpressured. It is a fixed six-byte terminal control packet.
          websocket.send(this._packet(
              this.packetTypes.close, 0, new Uint8Array([closeReason])));
        } catch (_) {
          // The connection is still made terminal below.
        }
      }
      this._failConnection(error, /*closeSocket=*/true);
    },

    _discardInbound(stream) {
      this.totalInboundBytes -= stream.inboundBytes;
      stream.inbound = [];
      stream.inboundBytes = 0;
    },

    _discardOutbound(stream) {
      this.totalOutboundBytes -= stream.outboundBytes;
      stream.outbound = [];
      stream.outboundBytes = 0;
    },

    _validCloseReason(closeReason) {
      return Number.isSafeInteger(closeReason) && closeReason >= 0 &&
          closeReason <= 0xff ? closeReason : this.closeReasons.voluntary;
    },

    _packet(type, streamId, payload) {
      const packet = new Uint8Array(5 + payload.length);
      packet[0] = type;
      packet[1] = streamId & 0xff;
      packet[2] = (streamId >>> 8) & 0xff;
      packet[3] = (streamId >>> 16) & 0xff;
      packet[4] = (streamId >>> 24) & 0xff;
      packet.set(payload, 5);
      return packet;
    },

    _readUint32(bytes, offset) {
      return (bytes[offset] | (bytes[offset + 1] << 8) |
          (bytes[offset + 2] << 16) | (bytes[offset + 3] << 24)) >>> 0;
    },

    _scheduleFlush() {
      if (this.flushTimer !== null || !this.websocket ||
          this.websocket.readyState !== 1 ||
          this.controlQueue.length === 0 && !this._hasSendableQueuedData()) {
        return;
      }
      this.flushTimer = this._scheduleTimer(() => {
        this.flushTimer = null;
        this._flush();
      }, this.config.flushDelayMs);
    },

    _scheduleTimer(callback, delay) {
      const timer = globalThis.setTimeout(callback, delay);
      // Do not make a Node source-contract test wait for a transport timeout.
      // Browser timer handles are numeric and do not provide unref().
      if (timer && typeof timer.unref === 'function') {
        timer.unref();
      }
      return timer;
    },

    _clearTimer(timer) {
      if (timer !== null && timer !== undefined) {
        globalThis.clearTimeout(timer);
      }
    },
  },

  chromium_wasm_wisp_stream_is_configured__deps: [
    '$ChromiumWasmWispTransport',
  ],
  chromium_wasm_wisp_stream_is_configured__proxy: 'sync',
  chromium_wasm_wisp_stream_is_configured: () =>
    ChromiumWasmWispTransport.isConfigured(),

  chromium_wasm_wisp_diagnostics_begin_evidence_window__deps: [
    '$ChromiumWasmWispTransport',
  ],
  chromium_wasm_wisp_diagnostics_begin_evidence_window__proxy: 'sync',
  chromium_wasm_wisp_diagnostics_begin_evidence_window: (
      hostnamePointer, hostnameLength, port) =>
    ChromiumWasmWispTransport.beginDiagnosticsEvidenceWindow(
        hostnamePointer, hostnameLength, port),

  chromium_wasm_wisp_diagnostics_completion_flags__deps: [
    '$ChromiumWasmWispTransport',
  ],
  chromium_wasm_wisp_diagnostics_completion_flags__proxy: 'sync',
  chromium_wasm_wisp_diagnostics_completion_flags: () =>
    ChromiumWasmWispTransport.diagnosticsCompletionFlags(),

  chromium_wasm_wisp_stream_open__deps: ['$ChromiumWasmWispTransport'],
  chromium_wasm_wisp_stream_open__proxy: 'sync',
  chromium_wasm_wisp_stream_open: (streamId, hostnamePointer, hostnameLength,
                                   port) => ChromiumWasmWispTransport.open(
      streamId, hostnamePointer, hostnameLength, port),

  chromium_wasm_wisp_stream_state__deps: ['$ChromiumWasmWispTransport'],
  chromium_wasm_wisp_stream_state__proxy: 'sync',
  chromium_wasm_wisp_stream_state: (streamId) =>
    ChromiumWasmWispTransport.state(streamId),

  chromium_wasm_wisp_stream_error__deps: ['$ChromiumWasmWispTransport'],
  chromium_wasm_wisp_stream_error__proxy: 'sync',
  chromium_wasm_wisp_stream_error: (streamId) =>
    ChromiumWasmWispTransport.error(streamId),

  chromium_wasm_wisp_stream_available__deps: ['$ChromiumWasmWispTransport'],
  chromium_wasm_wisp_stream_available__proxy: 'sync',
  chromium_wasm_wisp_stream_available: (streamId) =>
    ChromiumWasmWispTransport.available(streamId),

  chromium_wasm_wisp_stream_read__deps: ['$ChromiumWasmWispTransport'],
  chromium_wasm_wisp_stream_read__proxy: 'sync',
  chromium_wasm_wisp_stream_read: (streamId, destinationPointer,
                                    maximumBytes) =>
    ChromiumWasmWispTransport.read(
        streamId, destinationPointer, maximumBytes),

  chromium_wasm_wisp_stream_write__deps: ['$ChromiumWasmWispTransport'],
  chromium_wasm_wisp_stream_write__proxy: 'sync',
  chromium_wasm_wisp_stream_write: (streamId, sourcePointer, sourceLength) =>
    ChromiumWasmWispTransport.write(streamId, sourcePointer, sourceLength),

  chromium_wasm_wisp_stream_close__deps: ['$ChromiumWasmWispTransport'],
  chromium_wasm_wisp_stream_close__proxy: 'sync',
  chromium_wasm_wisp_stream_close: (streamId, closeReason) =>
    ChromiumWasmWispTransport.close(streamId, closeReason),
});
