import os
import json
import time
import uuid
import threading
import requests
import concurrent.futures
import yfinance as yf
from flask import Flask, request, render_template_string, redirect, url_for, jsonify

app = Flask(__name__)
CONFIG_FILE = '/data/config_acciones.json'

# --- 🔔 CONFIGURACIÓN DE NTFY ---
NTFY_TOPIC = "stocks_alerts"  # Cambia esto por tu canal de ntfy
NTFY_URL = f"https://ntfy.sh/stocks_alerts"

# --- ⏱️ FRECUENCIAS Y SINCRONIZACIÓN ---
CHECK_INTERVAL_SECONDS = 10
FRONTEND_POLL_MS = 500  # Bajado a 500ms (medio segundo) para que la interfaz web sea aún más instantánea

# Evento para forzar al vigilante a trabajar INMEDIATAMENTE sin esperar los 10 segundos
WAKE_UP_EVENT = threading.Event()

# Plantilla HTML — "Trading Sentinel" (Sin cambios, es perfecta)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Sentinel // Panel de Alertas</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #05070d;
            --bg-panel: #0b0f1a;
            --panel-border: rgba(140, 165, 255, 0.14);
            --panel-border-hover: rgba(140, 165, 255, 0.34);
            --text-primary: #eef2fb;
            --text-secondary: #7c8bad;
            --text-dim: #47506b;
            --cyan: #34e0f0;
            --cyan-dim: rgba(52, 224, 240, 0.14);
            --amber: #ffb640;
            --amber-dim: rgba(255, 182, 64, 0.14);
            --rose: #ff5c7a;
            --rose-dim: rgba(255, 92, 122, 0.14);
            --font-display: 'Space Grotesk', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
            --font-body: 'Inter', sans-serif;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        html { scroll-behavior: smooth; }

        body {
            background: var(--bg);
            color: var(--text-primary);
            font-family: var(--font-body);
            min-height: 100vh;
            padding-bottom: 120px;
            background-image:
                linear-gradient(rgba(140, 165, 255, 0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(140, 165, 255, 0.05) 1px, transparent 1px),
                radial-gradient(ellipse 80% 50% at 50% -10%, rgba(52, 224, 240, 0.10), transparent);
            background-size: 42px 42px, 42px 42px, 100% 100%;
        }

        /* ---------- Cinta de cotizaciones ---------- */
        .ticker-tape { width: 100%; overflow: hidden; background: var(--bg-panel); border-bottom: 1px solid var(--panel-border); white-space: nowrap; padding: 9px 0; }
        .ticker-tape .track { display: inline-block; font-family: var(--font-mono); font-size: 12px; letter-spacing: 0.3px; animation: scrollTape 32s linear infinite; }
        .ticker-tape .item { color: var(--text-secondary); padding: 0 22px; }
        .ticker-tape .item .sym { color: var(--text-primary); font-weight: 600; }
        .ticker-tape .item .val { color: var(--cyan); }
        @keyframes scrollTape { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        @media (prefers-reduced-motion: reduce) { .ticker-tape .track { animation: none; } }

        /* ---------- Cabecera ---------- */
        .header { max-width: 1120px; margin: 0 auto; padding: 44px 24px 30px 24px; display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; flex-wrap: wrap; }
        .header .eyebrow { font-family: var(--font-mono); font-size: 11px; color: var(--cyan); letter-spacing: 3px; text-transform: uppercase; display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
        .eyebrow .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 8px 2px var(--cyan); animation: blink 1.8s ease-in-out infinite; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.25; } }
        .header h1 { font-family: var(--font-display); font-size: 34px; font-weight: 700; letter-spacing: -0.5px; }
        .header .subtitle { font-size: 13px; color: var(--text-secondary); margin-top: 6px; max-width: 420px; }
        .header-stats { display: flex; gap: 28px; font-family: var(--font-mono); }
        .header-stats .stat-block { text-align: right; }
        .header-stats .stat-num { font-size: 26px; font-weight: 600; color: var(--text-primary); }
        .header-stats .stat-label { font-size: 10px; color: var(--text-dim); letter-spacing: 1.5px; text-transform: uppercase; margin-top: 2px; }

        /* ---------- Rejilla de tarjetas ---------- */
        .container { max-width: 1120px; margin: 0 auto; padding: 0 24px; display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 18px; }
        .card { position: relative; background: linear-gradient(180deg, var(--bg-panel), #080b13); border: 1px solid var(--panel-border); border-radius: 14px; padding: 22px 22px 20px 22px; transition: border-color 0.25s ease, transform 0.25s ease; }
        .card:hover { border-color: var(--panel-border-hover); transform: translateY(-3px); }
        .card::before, .card::after { content: ""; position: absolute; width: 14px; height: 14px; border-color: var(--text-dim); transition: border-color 0.25s ease; }
        .card::before { top: -1px; left: -1px; border-top: 2px solid; border-left: 2px solid; border-radius: 14px 0 0 0; }
        .card::after { bottom: -1px; right: -1px; border-bottom: 2px solid; border-right: 2px solid; border-radius: 0 0 14px 0; }
        .card:hover::before, .card:hover::after { border-color: var(--cyan); }
        .card.is-triggered-up { border-color: rgba(255, 182, 64, 0.4); }
        .card.is-triggered-down { border-color: rgba(255, 92, 122, 0.4); }
        .card-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
        .ticker-symbol { font-family: var(--font-mono); font-size: 22px; font-weight: 700; letter-spacing: 0.5px; }
        .status-pill { font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; padding: 5px 10px 5px 8px; border-radius: 20px; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
        .status-pill .sdot { width: 6px; height: 6px; border-radius: 50%; }
        .status-watching { background: var(--cyan-dim); color: var(--cyan); border: 1px solid rgba(52, 224, 240, 0.3); }
        .status-watching .sdot { background: var(--cyan); box-shadow: 0 0 6px 1px var(--cyan); animation: blink 1.8s ease-in-out infinite; }
        .status-up { background: var(--amber-dim); color: var(--amber); border: 1px solid rgba(255, 182, 64, 0.35); }
        .status-up .sdot { background: var(--amber); box-shadow: 0 0 6px 1px var(--amber); }
        .status-down { background: var(--rose-dim); color: var(--rose); border: 1px solid rgba(255, 92, 122, 0.35); }
        .status-down .sdot { background: var(--rose); box-shadow: 0 0 6px 1px var(--rose); }
        .price-row { display: flex; align-items: baseline; gap: 8px; margin-bottom: 20px; }
        .price-row .price-label { font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); letter-spacing: 1.5px; text-transform: uppercase; }
        .price-value { font-family: var(--font-mono); font-size: 32px; font-weight: 600; color: var(--text-primary); }
        .price-value.loading { font-size: 15px; color: var(--text-dim); font-weight: 400; }
        .gauge { margin-top: 4px; }
        .gauge-track { position: relative; height: 6px; border-radius: 4px; background: linear-gradient(90deg, var(--rose), var(--text-dim) 50%, var(--amber)); opacity: 0.55; }
        .gauge-marker { position: absolute; top: 50%; width: 12px; height: 12px; border-radius: 50%; background: var(--text-primary); border: 2px solid var(--bg); box-shadow: 0 0 0 2px var(--cyan), 0 0 10px 2px var(--cyan-dim); transform: translate(-50%, -50%); transition: left 0.4s ease; }
        .gauge-labels { display: flex; justify-content: space-between; margin-top: 9px; font-family: var(--font-mono); font-size: 11px; }
        .gauge-labels .low { color: var(--rose); }
        .gauge-labels .high { color: var(--amber); }
        .card-footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--panel-border); }
        .btn-icon { background: transparent; border: 1px solid var(--panel-border); color: var(--text-secondary); width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s; font-size: 13px; }
        .btn-icon:hover { border-color: var(--cyan); color: var(--cyan); }
        .btn-icon.delete:hover { border-color: var(--rose); color: var(--rose); }

        /* ---------- Botón flotante ---------- */
        .fab { position: fixed; bottom: 32px; right: 32px; height: 52px; padding: 0 22px 0 18px; background: var(--bg-panel); border: 1px solid var(--cyan); border-radius: 10px; color: var(--cyan); font-family: var(--font-mono); font-size: 13px; font-weight: 600; letter-spacing: 1px; display: flex; align-items: center; gap: 8px; cursor: pointer; box-shadow: 0 0 0 0 rgba(52, 224, 240, 0.4); transition: all 0.2s ease; z-index: 100; }
        .fab:hover { background: var(--cyan); color: #04141a; box-shadow: 0 0 24px 2px rgba(52, 224, 240, 0.45); }
        .fab .plus { font-size: 17px; }

        /* ---------- Estado vacío ---------- */
        .empty-state { grid-column: 1 / -1; text-align: center; padding: 70px 20px; color: var(--text-secondary); background: var(--bg-panel); border: 1px dashed var(--panel-border); border-radius: 14px; }
        .empty-state .glyph { font-family: var(--font-mono); font-size: 12px; color: var(--cyan); letter-spacing: 2px; margin-bottom: 14px; }
        .empty-state h3 { font-family: var(--font-display); font-size: 19px; color: var(--text-primary); font-weight: 600; }
        .empty-state p { margin-top: 8px; font-size: 13px; }

        /* ---------- Modal ---------- */
        .modal-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(3, 5, 10, 0.8); backdrop-filter: blur(6px); display: none; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
        .modal-body { background: var(--bg-panel); border: 1px solid var(--panel-border-hover); border-radius: 16px; width: 100%; max-width: 420px; box-shadow: 0 30px 70px rgba(0,0,0,0.7); overflow: hidden; }
        .modal-titlebar { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--panel-border); }
        .modal-title { font-family: var(--font-mono); font-size: 13px; font-weight: 600; letter-spacing: 1px; color: var(--cyan); text-transform: uppercase; }
        .modal-close { background: none; border: none; color: var(--text-secondary); font-size: 18px; cursor: pointer; line-height: 1; }
        .modal-close:hover { color: var(--rose); }
        .modal-form { padding: 22px 20px 20px 20px; }
        .form-group { margin-bottom: 16px; }
        .form-group label { display: flex; gap: 6px; font-family: var(--font-mono); font-size: 11px; font-weight: 500; color: var(--text-secondary); margin-bottom: 7px; letter-spacing: 0.5px; }
        .form-group label .prompt { color: var(--cyan); }
        .form-control { width: 100%; padding: 11px 13px; background: #05070d; border: 1px solid var(--panel-border); border-radius: 8px; color: var(--text-primary); font-family: var(--font-mono); font-size: 14px; outline: none; transition: border-color 0.2s; }
        .form-control::placeholder { color: var(--text-dim); }
        .form-control:focus { border-color: var(--cyan); }
        .modal-actions { display: flex; gap: 10px; margin-top: 22px; }
        .btn { flex: 1; padding: 12px; border-radius: 8px; border: 1px solid transparent; font-family: var(--font-mono); font-weight: 600; font-size: 12px; letter-spacing: 0.8px; text-transform: uppercase; cursor: pointer; transition: all 0.2s; }
        .btn-primary { background: var(--cyan); color: #04141a; }
        .btn-primary:hover { box-shadow: 0 0 18px rgba(52, 224, 240, 0.4); }
        .btn-secondary { background: transparent; border-color: var(--panel-border); color: var(--text-secondary); }
        .btn-secondary:hover { border-color: var(--text-secondary); color: var(--text-primary); }
        @media (max-width: 600px) { .header { padding: 32px 18px 24px 18px; } .header-stats { gap: 18px; } .container { padding: 0 18px; grid-template-columns: 1fr; } }
    </style>
</head>
<body>

    {% if alerts %}
    <div class="ticker-tape">
        <div class="track" id="tickerTrack">
            {% for i in range(2) %}
                {% for alert in alerts %}
                <span class="item" data-tape-ticker="{{ alert.ticker }}"><span class="sym">{{ alert.ticker }}</span> <span class="val">{% if alert.precio_actual %}${{ "%.2f"|format(alert.precio_actual) }}{% else %}--.--{% endif %}</span></span>
                {% endfor %}
            {% endfor %}
        </div>
    </div>
    {% endif %}

    <div class="header">
        <div>
            <div class="eyebrow"><span class="dot"></span>Sistema en vivo</div>
            <h1>Trading Sentinel</h1>
            <div class="subtitle">Vigilancia de precios en tiempo real, con aviso directo a tu móvil en cuanto una acción cruza tu rango.</div>
        </div>
        <div class="header-stats">
            <div class="stat-block">
                <div class="stat-num" id="statVigiladas">{{ alerts|length }}</div>
                <div class="stat-label">Vigiladas</div>
            </div>
            <div class="stat-block">
                <div class="stat-num" id="statDisparadas">{{ alerts|selectattr("notificado")|list|length }}</div>
                <div class="stat-label">Disparadas</div>
            </div>
        </div>
    </div>

    <div class="container" id="cardsContainer">
        {% if alerts %}
            {% for alert in alerts %}
            <div class="card {% if alert.notificado and alert.tipo_notificacion == 'Alcanzó Subida' %}is-triggered-up{% elif alert.notificado and alert.tipo_notificacion == 'Alcanzó Bajada' %}is-triggered-down{% endif %}" data-card-id="{{ alert.id }}">
                <div class="card-top">
                    <span class="ticker-symbol">{{ alert.ticker }}</span>
                    {% if alert.notificado and alert.tipo_notificacion == 'Alcanzó Subida' %}
                        <span class="status-pill status-up" data-role="badge"><span class="sdot"></span>Disparada ▲</span>
                    {% elif alert.notificado and alert.tipo_notificacion == 'Alcanzó Bajada' %}
                        <span class="status-pill status-down" data-role="badge"><span class="sdot"></span>Disparada ▼</span>
                    {% else %}
                        <span class="status-pill status-watching" data-role="badge"><span class="sdot"></span>Vigilando</span>
                    {% endif %}
                </div>

                <div class="price-row">
                    <span class="price-label">Precio</span>
                    {% if alert.precio_actual %}
                        <span class="price-value" data-role="price">${{ "%.2f"|format(alert.precio_actual) }}</span>
                    {% else %}
                        <span class="price-value loading" data-role="price">cargando…</span>
                    {% endif %}
                </div>

                <div class="gauge">
                    <div class="gauge-track">
                        <div class="gauge-marker" data-role="marker" style="left: {{ alert.pct }}%;"></div>
                    </div>
                    <div class="gauge-labels">
                        <span class="low">${{ "%.2f"|format(alert.precio_bajo) }}</span>
                        <span class="high">${{ "%.2f"|format(alert.precio_alto) }}</span>
                    </div>
                </div>

                <div class="card-footer">
                    <button class="btn-icon" title="Editar" onclick="abrirModalEditar('{{ alert.id }}', '{{ alert.ticker }}', '{{ alert.precio_alto }}', '{{ alert.precio_bajo }}')">✎</button>
                    <form action="/delete/{{ alert.id }}" method="POST" style="margin:0;">
                        <button type="submit" class="btn-icon delete" title="Borrar" onclick="return confirm('¿Eliminar esta alerta de {{ alert.ticker }}?')">✕</button>
                    </form>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="empty-state">
                <div class="glyph">// SIN SEÑAL</div>
                <h3>Todavía no vigilas ninguna acción</h3>
                <p>Pulsa <strong>+ Nueva alerta</strong> abajo a la derecha para añadir tu primer ticker.</p>
            </div>
        {% endif %}
    </div>

    <button class="fab" onclick="abrirModalCrear()" title="Añadir Alerta"><span class="plus">+</span>Nueva alerta</button>

    <div class="modal-overlay" id="modalAlert">
        <div class="modal-body">
            <div class="modal-titlebar">
                <span class="modal-title" id="modalTitle">// Nueva alerta</span>
                <button type="button" class="modal-close" onclick="cerrarModal()">✕</button>
            </div>
            <form id="alertForm" class="modal-form" method="POST" action="/add">
                <input type="hidden" name="alert_id" id="alertId">

                <div class="form-group">
                    <label><span class="prompt">#</span>Ticker</label>
                    <input type="text" name="ticker" id="inputTicker" class="form-control" placeholder="AAPL" required style="text-transform:uppercase;">
                </div>

                <div class="form-group">
                    <label><span class="prompt">▲</span>Take-profit (avisa por encima de)</label>
                    <input type="number" step="0.01" name="precio_alto" id="inputAlto" class="form-control" placeholder="150.00" required>
                </div>

                <div class="form-group">
                    <label><span class="prompt">▼</span>Stop-loss (avisa por debajo de)</label>
                    <input type="number" step="0.01" name="precio_bajo" id="inputBajo" class="form-control" placeholder="100.00" required>
                </div>

                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="cerrarModal()">Cancelar</button>
                    <button type="submit" class="btn btn-primary">Guardar</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        function abrirModalCrear() {
            document.getElementById('modalTitle').innerText = '// Nueva alerta';
            document.getElementById('alertForm').action = '/add';
            document.getElementById('alertId').value = '';
            document.getElementById('inputTicker').value = '';
            document.getElementById('inputAlto').value = '';
            document.getElementById('inputBajo').value = '';
            document.getElementById('modalAlert').style.display = 'flex';
        }

        function abrirModalEditar(id, ticker, alto, bajo) {
            document.getElementById('modalTitle').innerText = '// Editar alerta';
            document.getElementById('alertForm').action = '/edit/' + id;
            document.getElementById('alertId').value = id;
            document.getElementById('inputTicker').value = ticker;
            document.getElementById('inputAlto').value = alto;
            document.getElementById('inputBajo').value = bajo;
            document.getElementById('modalAlert').style.display = 'flex';
        }

        function cerrarModal() {
            document.getElementById('modalAlert').style.display = 'none';
        }

        document.getElementById('modalAlert').addEventListener('click', function(e) {
            if (e.target === this) cerrarModal();
        });

        // Polling ultrarrápido (500ms) para respuesta instantánea de la UI
        const FRONTEND_POLL_MS = {{ frontend_poll_ms }};
        let idsConocidos = null;

        function formatoPrecio(v) {
            return v === null ? 'cargando…' : '$' + Number(v).toFixed(2);
        }

        function actualizarUI(alertas) {
            const idsActuales = alertas.map(a => a.id).sort().join(',');

            if (idsConocidos !== null && idsConocidos !== idsActuales) {
                window.location.reload();
                return;
            }
            idsConocidos = idsActuales;

            let disparadas = 0;

            alertas.forEach(alert => {
                if (alert.notificado) disparadas++;

                const card = document.querySelector(`[data-card-id="${alert.id}"]`);
                if (!card) return;

                const priceEl = card.querySelector('[data-role="price"]');
                priceEl.textContent = formatoPrecio(alert.precio_actual);
                priceEl.classList.toggle('loading', alert.precio_actual === null);

                const markerEl = card.querySelector('[data-role="marker"]');
                markerEl.style.left = alert.pct + '%';

                const badgeEl = card.querySelector('[data-role="badge"]');
                card.classList.remove('is-triggered-up', 'is-triggered-down');
                badgeEl.classList.remove('status-watching', 'status-up', 'status-down');

                if (alert.notificado && alert.tipo_notificacion === 'Alcanzó Subida') {
                    card.classList.add('is-triggered-up');
                    badgeEl.classList.add('status-up');
                    badgeEl.innerHTML = '<span class="sdot"></span>Disparada ▲';
                } else if (alert.notificado && alert.tipo_notificacion === 'Alcanzó Bajada') {
                    card.classList.add('is-triggered-down');
                    badgeEl.classList.add('status-down');
                    badgeEl.innerHTML = '<span class="sdot"></span>Disparada ▼';
                } else {
                    badgeEl.classList.add('status-watching');
                    badgeEl.innerHTML = '<span class="sdot"></span>Vigilando';
                }

                document.querySelectorAll(`[data-tape-ticker="${alert.ticker}"] .val`).forEach(el => {
                    el.textContent = alert.precio_actual === null ? '--.--' : '$' + Number(alert.precio_actual).toFixed(2);
                });
            });

            document.getElementById('statVigiladas').textContent = alertas.length;
            document.getElementById('statDisparadas').textContent = disparadas;
        }

        function poll() {
            fetch('/api/alerts')
                .then(r => r.json())
                .then(actualizarUI)
                .catch(err => console.error('Error al refrescar datos:', err));
        }

        if (document.getElementById('cardsContainer').children.length && document.querySelector('[data-card-id]')) {
            idsConocidos = Array.from(document.querySelectorAll('[data-card-id]'))
                .map(el => el.dataset.cardId).sort().join(',');
        }

        setInterval(poll, FRONTEND_POLL_MS);
    </script>
</body>
</html>
"""

# --- FUNCIONES DE BASE DE DATOS Y LÓGICA ---
def cargar_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_config(data):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def calcular_pct(alerta):
    precio_actual = alerta.get('precio_actual')
    bajo = float(alerta['precio_bajo'])
    alto = float(alerta['precio_alto'])
    rango = alto - bajo
    if precio_actual is None or rango <= 0:
        return 50
    raw = (precio_actual - bajo) / rango * 100
    return max(0, min(100, raw))

def alertas_con_pct():
    alertas = cargar_config()
    for a in alertas:
        a['pct'] = round(calcular_pct(a), 1)
    return alertas

# --- OBTENCIÓN DE PRECIO ULTRA-RÁPIDA ---
def obtener_precio_rapido(ticker):
    """Obtiene el precio de forma instantánea usando métodos ligeros de yfinance."""
    t = yf.Ticker(ticker)
    try:
        # Método 1: ultra rápido, devuelve solo metadata
        return ticker, float(t.fast_info['lastPrice'])
    except Exception:
        try:
            # Método 2: rápido
            return ticker, float(t.info['currentPrice'])
        except Exception:
            try:
                # Método 3: fallback estándar
                return ticker, float(t.history(period="1d", interval="1m")['Close'].iloc[-1])
            except Exception:
                return ticker, None

# --- NOTIFICACIONES NTFY ---
def enviar_notificacion(mensaje, ticker):
    try:
        r = requests.post(
            NTFY_URL,
            data=mensaje.encode('utf-8'),
            headers={
                "Title": f"Alerta de Bolsa: {ticker}".encode('utf-8'),
                "Priority": "high",
                "Tags": "chart_with_upwards_trend,moneybag"
            },
            timeout=10
        )
        r.raise_for_status()
        print(f"[{time.strftime('%H:%M:%S')}] ✅ Notificación enviada para {ticker}")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ Error enviando notificación: {e}")

# --- MOTOR EN SEGUNDO PLANO (AHORA CONCURRENTE E INSTANTÁNEO) ---
def vigilar_precios():
    while True:
        alertas = cargar_config()
        hubo_cambios = False

        if alertas:
            # Descargar los precios de todas las acciones A LA VEZ en paralelo
            precios_actuales = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futuros = [executor.submit(obtener_precio_rapido, alerta['ticker']) for alerta in alertas]
                for f in concurrent.futures.as_completed(futuros):
                    t, p = f.result()
                    precios_actuales[t] = p

            for alerta in alertas:
                ticker = alerta['ticker']
                precio_actual = precios_actuales.get(ticker)
                
                if precio_actual is not None:
                    # Solo marcamos que hubo cambios si el precio es diferente al guardado
                    if alerta.get('precio_actual') != precio_actual:
                        alerta['precio_actual'] = precio_actual
                        hubo_cambios = True

                    precio_alto = float(alerta['precio_alto'])
                    precio_bajo = float(alerta['precio_bajo'])

                    # 1. Comprobar Subida
                    if precio_actual >= precio_alto:
                        if not alerta.get('notificado') or alerta.get('tipo_notificacion') != "Alcanzó Subida":
                            msg = f"¡{ticker} ha SUPERADO tu límite! Precio actual: ${precio_actual:.2f} (Objetivo: >${precio_alto:.2f})"
                            enviar_notificacion(msg, ticker)
                            alerta['notificado'] = True
                            alerta['tipo_notificacion'] = "Alcanzó Subida"
                            hubo_cambios = True

                    # 2. Comprobar Bajada
                    elif precio_actual <= precio_bajo:
                        if not alerta.get('notificado') or alerta.get('tipo_notificacion') != "Alcanzó Bajada":
                            msg = f"¡{ticker} ha CAÍDO por debajo de tu límite! Precio actual: ${precio_actual:.2f} (Objetivo: <${precio_bajo:.2f})"
                            enviar_notificacion(msg, ticker)
                            alerta['notificado'] = True
                            alerta['tipo_notificacion'] = "Alcanzó Bajada"
                            hubo_cambios = True
                            
                    # 3. ZONA SEGURA (Auto-Reinicio Instantáneo)
                    else:
                        if alerta.get('notificado'):
                            # El precio ha vuelto a la normalidad, reiniciamos el estado
                            alerta['notificado'] = False
                            alerta['tipo_notificacion'] = None
                            hubo_cambios = True

        if hubo_cambios:
            guardar_config(alertas)

        # En lugar de usar sleep(), usamos wait(). 
        # Esto permite que si tú editas o añades algo, podamos "despertar" al hilo 
        # antes de que pasen los 10 segundos, consiguiendo una respuesta en vivo real.
        WAKE_UP_EVENT.wait(CHECK_INTERVAL_SECONDS)
        WAKE_UP_EVENT.clear()

# --- RUTAS FLASK ---
@app.route('/')
def index():
    alertas = alertas_con_pct()
    return render_template_string(HTML_TEMPLATE, alerts=alertas, frontend_poll_ms=FRONTEND_POLL_MS)

@app.route('/api/alerts')
def api_alerts():
    return jsonify(alertas_con_pct())

@app.route('/add', methods=['POST'])
def add_alert():
    ticker = request.form['ticker'].strip().upper()
    precio_alto = float(request.form['precio_alto'])
    precio_bajo = float(request.form['precio_bajo'])

    # Intentamos conseguir el precio inicial al instante para que no salga "cargando..."
    _, precio_inicial = obtener_precio_rapido(ticker)

    alertas = cargar_config()
    nueva_alerta = {
        "id": str(uuid.uuid4())[:8],
        "ticker": ticker,
        "precio_alto": precio_alto,
        "precio_bajo": precio_bajo,
        "precio_actual": precio_inicial,
        "notificado": False,
        "tipo_notificacion": None
    }
    alertas.append(nueva_alerta)
    guardar_config(alertas)
    
    # Despertamos al vigilante inmediatamente
    WAKE_UP_EVENT.set()
    return redirect(url_for('index'))

@app.route('/edit/<alert_id>', methods=['POST'])
def edit_alert(alert_id):
    alertas = cargar_config()
    for alerta in alertas:
        if alerta['id'] == alert_id:
            alerta['ticker'] = request.form['ticker'].strip().upper()
            alerta['precio_alto'] = float(request.form['precio_alto'])
            alerta['precio_bajo'] = float(request.form['precio_bajo'])
            alerta['notificado'] = False 
            alerta['tipo_notificacion'] = None
            break
    guardar_config(alertas)
    
    # Despertamos al vigilante inmediatamente para que recálcule con los nuevos límites
    WAKE_UP_EVENT.set()
    return redirect(url_for('index'))

@app.route('/delete/<alert_id>', methods=['POST'])
def delete_alert(alert_id):
    alertas = cargar_config()
    alertas = [a for a in alertas if a['id'] != alert_id]
    guardar_config(alertas)
    return redirect(url_for('index'))

if __name__ == '__main__':
    # 1. ARRANCAR EL HILO DE VIGILANCIA (Obligatorio para que funcione en segundo plano)
    hilo_vigilante = threading.Thread(target=vigilar_precios, daemon=True)
    hilo_vigilante.start()

    # 2. Arrancar la aplicación Flask en el puerto de Railway
    puerto = int(os.environ.get("PORT", 5050))
    app.run(host='0.0.0.0', port=puerto, debug=False)
