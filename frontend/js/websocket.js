/**
 * WebSocket client for real-time scan updates.
 * Connects to /ws/{scan_id} and dispatches events to registered handlers.
 */

class OSINTWebSocket {
  constructor(scanId) {
    this.scanId = scanId;
    this.ws = null;
    this.handlers = {};
    this.reconnectAttempts = 0;
    this.maxReconnects = 3;
    this.isIntentionallyClosed = false;
  }

  connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const url = `${protocol}//${host}/ws/${this.scanId}`;

    console.log(`[WS] Connecting to ${url}`);
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log(`[WS] Connected for scan ${this.scanId}`);
      this.reconnectAttempts = 0;
      this._emit('connected', {});
    };

    this.ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        console.log('[WS] Event:', payload.event, payload.data);
        this._emit(payload.event, payload.data);
        this._emit('*', payload); // wildcard handler
      } catch (e) {
        console.error('[WS] Parse error:', e);
      }
    };

    this.ws.onclose = (event) => {
      console.log(`[WS] Closed (code=${event.code})`);
      this._emit('disconnected', { code: event.code });

      if (!this.isIntentionallyClosed && this.reconnectAttempts < this.maxReconnects) {
        this.reconnectAttempts++;
        const delay = this.reconnectAttempts * 2000;
        console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connect(), delay);
      }
    };

    this.ws.onerror = (err) => {
      console.error('[WS] Error:', err);
      this._emit('error', { error: 'WebSocket error' });
    };
  }

  on(event, handler) {
    if (!this.handlers[event]) this.handlers[event] = [];
    this.handlers[event].push(handler);
    return this; // chainable
  }

  off(event) {
    delete this.handlers[event];
  }

  _emit(event, data) {
    (this.handlers[event] || []).forEach(fn => {
      try { fn(data); } catch (e) { console.error(`[WS] Handler error (${event}):`, e); }
    });
  }

  close() {
    this.isIntentionallyClosed = true;
    if (this.ws) this.ws.close();
  }
}

window.OSINTWebSocket = OSINTWebSocket;
