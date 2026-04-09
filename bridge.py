import logging
import os
import uuid
import time
from collections import deque
from flask import Flask, request, jsonify

app = Flask(__name__)

# Désactiver les logs Flask par défaut pour que la console reste propre
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# ── Configuration ────────────────────────────────────────────────────────────
# Token d'authentification partagé entre Gemini et le serveur.
# Peut être défini via la variable d'environnement BRIDGE_TOKEN,
# sinon un token aléatoire est généré au démarrage.
AUTH_TOKEN = os.environ.get("BRIDGE_TOKEN", uuid.uuid4().hex)

# Port du serveur (configurable via variable d'environnement)
PORT = int(os.environ.get("BRIDGE_PORT", 5000))

# ── File d'attente & résultats ───────────────────────────────────────────────
# deque est O(1) pour popleft() contrairement à list.pop(0) qui est O(n)
script_queue = deque()

# Stockage des résultats d'exécution, indexés par script_id
# Structure : { script_id: { "status": "pending"|"success"|"error", "result": ..., "timestamp": ... } }
results = {}


def _check_auth():
    """Vérifie le header Authorization: Bearer <token>."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != AUTH_TOKEN:
        return False
    return True


@app.route('/execute', methods=['POST'])
def execute_script():
    """Endpoint utilisé par Gemini pour envoyer des scripts Python vers C4D."""
    if not _check_auth():
        return jsonify({"error": "Unauthorized – invalid or missing token"}), 401

    data = request.json
    if not data or 'script' not in data:
        return jsonify({"error": "No script provided in 'script' field"}), 400

    # Génération d'un identifiant unique pour suivre ce script
    script_id = data.get("id", uuid.uuid4().hex[:12])
    script = data['script']

    script_queue.append({"id": script_id, "script": script})
    results[script_id] = {"status": "pending", "result": None, "timestamp": time.time()}

    print(f"[Gemini -> C4D] Script '{script_id}' reçu en file d'attente. (Total: {len(script_queue)})")

    return jsonify({"status": "queued", "script_id": script_id}), 200


@app.route('/poll', methods=['GET'])
def poll_script():
    """Endpoint interrogé régulièrement par Cinema 4D pour récupérer le prochain script."""
    if not _check_auth():
        return jsonify({"error": "Unauthorized"}), 401

    if script_queue:
        entry = script_queue.popleft()
        print(f"[C4D -> Serveur] Script '{entry['id']}' extrait par C4D. (Restants: {len(script_queue)})")
        return jsonify({"has_script": True, "script_id": entry["id"], "script": entry["script"]}), 200

    return jsonify({"has_script": False}), 200


@app.route('/result', methods=['POST'])
def post_result():
    """Endpoint utilisé par C4D pour renvoyer le résultat d'exécution d'un script."""
    if not _check_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    if not data or 'script_id' not in data:
        return jsonify({"error": "Missing 'script_id'"}), 400

    script_id = data['script_id']
    status = data.get('status', 'unknown')  # "success" ou "error"
    result = data.get('result', '')

    results[script_id] = {
        "status": status,
        "result": result,
        "timestamp": time.time()
    }

    emoji = "✅" if status == "success" else "❌"
    print(f"[C4D -> Serveur] {emoji} Résultat pour '{script_id}': {status}")

    return jsonify({"status": "received"}), 200


@app.route('/result/<script_id>', methods=['GET'])
def get_result(script_id):
    """Endpoint utilisé par Gemini pour consulter le résultat d'un script donné."""
    if not _check_auth():
        return jsonify({"error": "Unauthorized"}), 401

    if script_id not in results:
        return jsonify({"error": "Unknown script_id"}), 404

    return jsonify(results[script_id]), 200


@app.route('/health', methods=['GET'])
def health():
    """Endpoint de health-check (pas d'auth requise)."""
    return jsonify({
        "status": "running",
        "queue_size": len(script_queue),
        "results_count": len(results)
    }), 200


if __name__ == '__main__':
    print("==========================================================")
    print("  Gemini <-> C4D Bridge Server est en cours d'exécution !")
    print(f"     Port:       {PORT}")
    print(f"     Token:      {AUTH_TOKEN}")
    print("  --------------------------------------------------------")
    print(f"     POST /execute          – Envoyer un script")
    print(f"     GET  /poll             – Récupérer un script (C4D)")
    print(f"     POST /result           – Poster un résultat (C4D)")
    print(f"     GET  /result/<id>      – Consulter un résultat")
    print(f"     GET  /health           – Health check")
    print("==========================================================")
    app.run(host='127.0.0.1', port=PORT, debug=False)
