/**
 * <cerebro-feedback> — Custom Element compartido entre apps Shift.
 *
 * Sirve UN solo componente que toda app del ecosistema Cerebro
 * (CL2, Studio, Eco, Sentinel) embebe igual. Captura señal RLHF
 * estandarizada que alimenta el dataset de fine-tune hacia 2027.
 *
 * Uso:
 *   <script type="module"
 *           src="https://shift-cerebro-production.up.railway.app/widget/cerebro-feedback.js">
 *   </script>
 *
 *   <cerebro-feedback
 *     message-id="msg-123"
 *     session-id="sess-456"
 *     app-id="studio"            <!-- studio | cl2 | eco | sentinel -->
 *     tenant-id="acme"
 *     user-id="auth0|xyz"        <!-- opcional; sin esto entra anon -->
 *     agent-id="valentina"
 *     upstream-model="moonshotai/kimi-k2.6"
 *     mode="message"             <!-- message | session-nps -->
 *   ></cerebro-feedback>
 *
 * Modo "message"   → 👍/👎. Si 👎 abre chips + textbox opcional.
 * Modo "session-nps" → "¿qué tal estuvo este chat?" 0-10 + textarea.
 *
 * Endpoint:
 *   POST <CEREBRO_BASE>/v1/feedback
 *   body: { message_id, session_id, app_id, tenant_id, user_id?,
 *           feedback_type, rating_value?, chip_key?, free_text?,
 *           agent_id?, upstream_model? }
 *
 * Hosted single-source: cualquier cambio acá llega a todas las
 * apps en el siguiente refresh sin redeploys.
 */
(() => {
  // Same-origin con el script. Soporta override via data-attribute si
  // alguna app necesita apuntar a un Cerebro de staging.
  const SCRIPT_EL = document.currentScript || (() => {
    const all = document.querySelectorAll('script[src*="cerebro-feedback"]');
    return all[all.length - 1];
  })();
  const DEFAULT_BASE = SCRIPT_EL
    ? new URL(SCRIPT_EL.src).origin
    : 'https://shift-cerebro-production.up.railway.app';

  // Taxonomía de chips para dislikes — fija en TODAS las apps para
  // que el dataset de razones sea agregable cross-app.
  const DISLIKE_CHIPS = [
    { key: 'hallucinated', label: 'Inventó algo' },
    { key: 'wrong_tone',   label: 'Tono equivocado' },
    { key: 'vague',        label: 'Muy genérico' },
    { key: 'missed_point', label: 'No entendió' },
    { key: 'too_long',     label: 'Demasiado largo' },
    { key: 'outdated',     label: 'Info desactualizada' },
  ];

  class CerebroFeedback extends HTMLElement {
    static get observedAttributes() {
      return [
        'message-id', 'session-id', 'app-id', 'tenant-id',
        'user-id', 'agent-id', 'upstream-model', 'mode',
        'cerebro-base',
      ];
    }

    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._sent = new Set();   // dedupe per-instance
      this._mode = 'message';
    }

    connectedCallback() {
      this._mode = (this.getAttribute('mode') || 'message').toLowerCase();
      this.render();
    }

    attributeChangedCallback() {
      if (this.shadowRoot) this.render();
    }

    get base() {
      return this.getAttribute('cerebro-base') || DEFAULT_BASE;
    }

    payloadBase() {
      const userId = this.getAttribute('user-id');
      return {
        message_id: this.getAttribute('message-id') || null,
        session_id: this.getAttribute('session-id') || 'anon-session',
        app_id:     this.getAttribute('app-id') || 'unknown',
        tenant_id:  this.getAttribute('tenant-id') || 'unknown',
        user_id:    userId || null,
        user_anonymous: !userId,
        agent_id:   this.getAttribute('agent-id') || null,
        upstream_model: this.getAttribute('upstream-model') || null,
        user_agent: navigator.userAgent.slice(0, 200),
      };
    }

    async post(extra) {
      const body = JSON.stringify({ ...this.payloadBase(), ...extra });
      try {
        await fetch(`${this.base}/v1/feedback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
        });
      } catch (e) {
        // Silencioso — no queremos errores de feedback rompiendo UX.
        console.warn('[cerebro-feedback]', e);
      }
    }

    render() {
      if (this._mode === 'session-nps') {
        this.renderSessionNPS();
      } else {
        this.renderMessage();
      }
    }

    // ───────── per-message: 👍 / 👎 + chips opcionales
    renderMessage() {
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: inline-block;
            font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
            font-size: 13px;
            line-height: 1.4;
            color: var(--cerebro-fb-fg, #444);
          }
          .row {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            opacity: 0.55;
            transition: opacity 0.15s ease;
          }
          .row:hover, .row.active { opacity: 1; }
          button.btn {
            background: transparent;
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 4px 8px;
            cursor: pointer;
            font-size: 14px;
            line-height: 1;
            color: inherit;
            transition: background 0.12s ease, border-color 0.12s ease;
          }
          button.btn:hover { background: rgba(0,0,0,0.05); border-color: rgba(0,0,0,0.08); }
          button.btn.selected { background: rgba(0,0,0,0.08); border-color: rgba(0,0,0,0.18); }
          button.btn.up.selected { color: #16a34a; }
          button.btn.down.selected { color: #dc2626; }
          .panel {
            margin-top: 8px;
            padding: 10px 12px;
            background: var(--cerebro-fb-panel, rgba(0,0,0,0.04));
            border-radius: 8px;
            max-width: 480px;
          }
          .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
          .chip {
            font-size: 11.5px;
            padding: 4px 8px;
            border: 1px solid rgba(0,0,0,0.15);
            border-radius: 999px;
            background: white;
            cursor: pointer;
            color: inherit;
            transition: background 0.12s, border-color 0.12s;
          }
          .chip:hover { background: rgba(0,0,0,0.05); }
          .chip.selected {
            background: #1e3a8a;
            color: white;
            border-color: #1e3a8a;
          }
          textarea {
            width: 100%;
            box-sizing: border-box;
            min-height: 56px;
            border: 1px solid rgba(0,0,0,0.15);
            border-radius: 6px;
            padding: 6px 8px;
            font: inherit;
            resize: vertical;
            font-size: 12.5px;
          }
          .send {
            margin-top: 6px;
            padding: 4px 10px;
            font-size: 11.5px;
            background: #1e3a8a;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
          }
          .send:disabled { opacity: 0.4; cursor: default; }
          .thanks {
            font-size: 11.5px;
            color: #16a34a;
            margin-left: 6px;
          }
        </style>

        <div class="row" part="row">
          <button class="btn up" data-action="like"     title="Útil">👍</button>
          <button class="btn down" data-action="dislike" title="No útil">👎</button>
          <span class="thanks" data-thanks hidden></span>
        </div>
        <div class="panel" data-panel hidden>
          <div class="chips">
            ${DISLIKE_CHIPS.map(c => `
              <button class="chip" data-chip="${c.key}">${c.label}</button>
            `).join('')}
          </div>
          <textarea data-text placeholder="¿Qué hubiera sido mejor? (opcional)"></textarea>
          <button class="send" data-send disabled>Enviar</button>
        </div>
      `;

      const $ = (sel) => this.shadowRoot.querySelector(sel);
      const thanks = $('[data-thanks]');
      const panel = $('[data-panel]');
      const upBtn = $('[data-action="like"]');
      const downBtn = $('[data-action="dislike"]');
      const sendBtn = $('[data-send]');
      const textArea = $('[data-text]');
      const chips = this.shadowRoot.querySelectorAll('.chip');
      const selectedChips = new Set();

      const showThanks = (msg = '✓ Gracias') => {
        thanks.textContent = msg;
        thanks.hidden = false;
        setTimeout(() => { thanks.hidden = true; thanks.textContent = ''; }, 2400);
      };

      upBtn.addEventListener('click', () => {
        if (this._sent.has('like')) return;
        this._sent.add('like');
        upBtn.classList.add('selected');
        downBtn.classList.remove('selected');
        panel.hidden = true;
        this.post({ feedback_type: 'like' });
        showThanks();
      });

      downBtn.addEventListener('click', () => {
        if (this._sent.has('dislike')) {
          panel.hidden = !panel.hidden;
          return;
        }
        this._sent.add('dislike');
        downBtn.classList.add('selected');
        upBtn.classList.remove('selected');
        panel.hidden = false;
        sendBtn.disabled = false;
        this.post({ feedback_type: 'dislike' });
      });

      chips.forEach(chip => {
        chip.addEventListener('click', () => {
          const key = chip.dataset.chip;
          if (selectedChips.has(key)) {
            selectedChips.delete(key);
            chip.classList.remove('selected');
          } else {
            selectedChips.add(key);
            chip.classList.add('selected');
            // Disparamos un event por cada chip seleccionado (dataset
            // append-only, fácil de agregar después).
            this.post({ feedback_type: 'chip', chip_key: key });
          }
        });
      });

      sendBtn.addEventListener('click', async () => {
        const txt = textArea.value.trim();
        if (txt) {
          await this.post({ feedback_type: 'free_text', free_text: txt });
        }
        sendBtn.disabled = true;
        panel.hidden = true;
        showThanks('✓ Gracias por el detalle');
      });
    }

    // ───────── per-session: NPS 0-10 + opcional textarea
    renderSessionNPS() {
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
            font-size: 13px;
            color: var(--cerebro-fb-fg, #444);
            max-width: 520px;
          }
          .title { font-weight: 600; margin-bottom: 10px; font-size: 14px; }
          .scale {
            display: grid;
            grid-template-columns: repeat(11, 1fr);
            gap: 4px;
            margin-bottom: 10px;
          }
          .scale button {
            border: 1px solid rgba(0,0,0,0.15);
            background: white;
            padding: 8px 0;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            transition: background 0.12s;
          }
          .scale button:hover { background: rgba(0,0,0,0.05); }
          .scale button.selected {
            background: #1e3a8a;
            color: white;
            border-color: #1e3a8a;
          }
          .legend {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            opacity: 0.6;
            margin-bottom: 10px;
          }
          textarea {
            width: 100%;
            box-sizing: border-box;
            min-height: 64px;
            border: 1px solid rgba(0,0,0,0.15);
            border-radius: 6px;
            padding: 6px 8px;
            font: inherit;
            resize: vertical;
            font-size: 12.5px;
          }
          .send {
            margin-top: 8px;
            padding: 6px 14px;
            font-size: 12.5px;
            background: #1e3a8a;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
          }
          .send:disabled { opacity: 0.4; cursor: default; }
          .thanks { color: #16a34a; font-size: 12.5px; }
        </style>
        <div class="title">¿Qué tal estuvo este chat?</div>
        <div class="scale">
          ${Array.from({ length: 11 }).map((_, i) => `
            <button data-score="${i}">${i}</button>
          `).join('')}
        </div>
        <div class="legend">
          <span>Muy mal</span>
          <span>Excelente</span>
        </div>
        <textarea data-text placeholder="¿Por qué? (opcional)"></textarea>
        <div>
          <button class="send" data-send disabled>Enviar</button>
          <span class="thanks" data-thanks hidden>✓ Gracias</span>
        </div>
      `;

      let score = null;
      const $ = (sel) => this.shadowRoot.querySelector(sel);
      const thanks = $('[data-thanks]');
      const sendBtn = $('[data-send]');
      const textArea = $('[data-text]');

      this.shadowRoot.querySelectorAll('.scale button').forEach(btn => {
        btn.addEventListener('click', () => {
          this.shadowRoot.querySelectorAll('.scale button')
            .forEach(b => b.classList.remove('selected'));
          btn.classList.add('selected');
          score = Number(btn.dataset.score);
          sendBtn.disabled = false;
        });
      });

      sendBtn.addEventListener('click', async () => {
        if (this._sent.has('nps')) return;
        this._sent.add('nps');
        sendBtn.disabled = true;
        await this.post({
          feedback_type: 'session_nps',
          rating_value: score,
          free_text: textArea.value.trim() || null,
        });
        thanks.hidden = false;
      });
    }
  }

  if (!customElements.get('cerebro-feedback')) {
    customElements.define('cerebro-feedback', CerebroFeedback);
  }
})();
