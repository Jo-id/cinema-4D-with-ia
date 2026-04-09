"""
Gemini <-> Cinema 4D Bridge Plugin
Un vrai plugin C4D qui écoute le serveur bridge et exécute les scripts envoyés par Gemini.
"""

import c4d
import json
import os
import traceback

# Gestion de la compatibilité Python 2 et Python 3 pour urllib
try:
    import urllib.request as urllib_request
    from urllib.error import URLError
except ImportError:
    import urllib2 as urllib_request
    from urllib2 import URLError

# ── Configuration ────────────────────────────────────────────────────────────
# Identifiants uniques du plugin (à générer via https://developers.maxon.net)
PLUGIN_ID = 1060500  # Remplacer par un vrai ID enregistré chez Maxon
PLUGIN_NAME = "Gemini Bridge"
PLUGIN_HELP = "Écoute le serveur Gemini Bridge et exécute les scripts reçus"

# Paramètres par défaut (modifiables dans le dialogue)
DEFAULT_SERVER_URL = "http://127.0.0.1:5000"
DEFAULT_POLL_INTERVAL = 2000  # ms
DEFAULT_TOKEN = ""

# ── IDs des éléments UI ─────────────────────────────────────────────────────
ID_GROUP_MAIN      = 10000
ID_LABEL_STATUS    = 10001
ID_LABEL_URL       = 10002
ID_LABEL_COUNT     = 10003
ID_BTN_STOP        = 10004
ID_GROUP_SETTINGS  = 10010
ID_EDIT_URL        = 10011
ID_EDIT_TOKEN      = 10012
ID_EDIT_INTERVAL   = 10013
ID_BTN_APPLY       = 10014


class GeminiBridgeDialog(c4d.gui.GeDialog):

    def __init__(self):
        super(GeminiBridgeDialog, self).__init__()
        self.server_url = DEFAULT_SERVER_URL
        self.auth_token = DEFAULT_TOKEN
        self.poll_interval = DEFAULT_POLL_INTERVAL
        self.scripts_executed = 0
        self.is_listening = False

    # ── Construction de l'interface ──────────────────────────────────────────

    def CreateLayout(self):
        self.SetTitle("Gemini C4D Bridge")

        # Groupe principal : statut
        self.GroupBegin(ID_GROUP_MAIN, c4d.BFH_SCALEFIT | c4d.BFV_TOP, 1, 0, "")
        self.GroupBorderSpace(10, 10, 10, 10)

        self.AddStaticText(ID_LABEL_STATUS, c4d.BFH_CENTER, name="Statut: En attente")
        self.AddStaticText(ID_LABEL_URL, c4d.BFH_CENTER, name=f"Serveur: {self.server_url}")
        self.AddStaticText(ID_LABEL_COUNT, c4d.BFH_CENTER, name="Scripts exécutés: 0")

        self.GroupEnd()

        # Groupe paramètres
        self.GroupBegin(ID_GROUP_SETTINGS, c4d.BFH_SCALEFIT | c4d.BFV_TOP, 2, 0, "Paramètres")
        self.GroupBorder(c4d.BORDER_GROUP_IN)
        self.GroupBorderSpace(10, 10, 10, 10)

        self.AddStaticText(0, c4d.BFH_LEFT, name="URL serveur:")
        self.AddEditText(ID_EDIT_URL, c4d.BFH_SCALEFIT, initw=250)

        self.AddStaticText(0, c4d.BFH_LEFT, name="Token:")
        self.AddEditText(ID_EDIT_TOKEN, c4d.BFH_SCALEFIT, initw=250)

        self.AddStaticText(0, c4d.BFH_LEFT, name="Intervalle (ms):")
        self.AddEditNumber(ID_EDIT_INTERVAL, c4d.BFH_LEFT, initw=80)

        self.GroupEnd()

        # Boutons
        self.AddButton(ID_BTN_APPLY, c4d.BFH_SCALEFIT, name="Démarrer l'écoute")
        self.AddButton(ID_BTN_STOP, c4d.BFH_SCALEFIT, name="Arrêter l'écoute")

        return True

    def InitValues(self):
        self.SetString(ID_EDIT_URL, self.server_url)
        self.SetString(ID_EDIT_TOKEN, self.auth_token or os.environ.get("BRIDGE_TOKEN", ""))
        self.SetInt32(ID_EDIT_INTERVAL, self.poll_interval)
        self.Enable(ID_BTN_STOP, False)
        return True

    # ── Commandes UI ─────────────────────────────────────────────────────────

    def Command(self, id, msg):
        if id == ID_BTN_APPLY:
            self._start_listening()
        elif id == ID_BTN_STOP:
            self._stop_listening()
        return True

    def _start_listening(self):
        self.server_url = self.GetString(ID_EDIT_URL).rstrip("/")
        self.auth_token = self.GetString(ID_EDIT_TOKEN)
        self.poll_interval = max(500, self.GetInt32(ID_EDIT_INTERVAL))  # Min 500ms

        self.SetTimer(self.poll_interval)
        self.is_listening = True

        self.SetString(ID_LABEL_STATUS, "Statut: En écoute...")
        self.SetString(ID_LABEL_URL, f"Serveur: {self.server_url}")
        self.Enable(ID_BTN_APPLY, False)
        self.Enable(ID_BTN_STOP, True)

        print(f"[Gemini Bridge] Écoute démarrée sur {self.server_url} (intervalle: {self.poll_interval}ms)")

    def _stop_listening(self):
        self.SetTimer(0)
        self.is_listening = False

        self.SetString(ID_LABEL_STATUS, "Statut: Arrêté")
        self.Enable(ID_BTN_APPLY, True)
        self.Enable(ID_BTN_STOP, False)

        print("[Gemini Bridge] Écoute arrêtée.")

    # ── Polling & Exécution ──────────────────────────────────────────────────

    def _make_request(self, path, method="GET", data=None):
        """Effectue une requête HTTP vers le serveur bridge avec authentification."""
        url = f"{self.server_url}{path}"
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        if data is not None:
            payload = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
            req = urllib_request.Request(url, data=payload, headers=headers)
        else:
            req = urllib_request.Request(url, headers=headers)

        # Forcer la méthode HTTP si nécessaire
        if method == "POST" and data is None:
            req.data = b""

        response = urllib_request.urlopen(req, timeout=2)
        return json.loads(response.read().decode("utf-8"))

    def Timer(self, msg):
        """Fonction appelée automatiquement à chaque intervalle du minuteur."""
        try:
            data = self._make_request("/poll")

            if data.get("has_script") and data.get("script"):
                script_id = data.get("script_id", "unknown")
                script_content = data["script"]

                print("=" * 50)
                print(f"[Gemini Bridge] Exécution du script '{script_id}':")
                print("=" * 50)

                c4d.StatusSetText(f"Gemini: exécution de '{script_id}'...")
                self._execute_and_report(script_id, script_content)
                c4d.StatusClear()

        except (URLError, Exception):
            # Serveur pas disponible — on ignore silencieusement
            pass

    def _execute_and_report(self, script_id, script_content):
        """Exécute le script Python dans le contexte C4D et renvoie le résultat au serveur."""
        current_doc = c4d.documents.GetActiveDocument()
        env = {
            'doc': current_doc,
            'op': current_doc.GetActiveObject(),
            'c4d': c4d,
            '__name__': '__main__'
        }

        status = "success"
        result_msg = ""

        try:
            current_doc.StartUndo()
            exec(script_content, env)
            c4d.EventAdd()
            current_doc.EndUndo()
            result_msg = "Script exécuté avec succès"
            self.scripts_executed += 1

        except Exception as e:
            status = "error"
            result_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            print(f"[Gemini Bridge] Erreur: {result_msg}")

            # IMPORTANT : fermer la transaction undo même en cas d'erreur
            try:
                current_doc.EndUndo()
            except Exception:
                pass

        # Mettre à jour le compteur dans l'UI
        self.SetString(ID_LABEL_COUNT, f"Scripts exécutés: {self.scripts_executed}")

        # Envoyer le résultat au serveur bridge
        try:
            self._make_request("/result", method="POST", data={
                "script_id": script_id,
                "status": status,
                "result": result_msg
            })
        except Exception:
            print(f"[Gemini Bridge] Impossible d'envoyer le résultat pour '{script_id}'")


# ── Enregistrement du plugin C4D ─────────────────────────────────────────────

class GeminiBridgeCommand(c4d.plugins.CommandData):
    """CommandData qui ouvre le dialogue du bridge."""

    dialog = None

    def Execute(self, doc):
        if self.dialog is None:
            self.dialog = GeminiBridgeDialog()

        return self.dialog.Open(
            dlgtype=c4d.DLG_TYPE_ASYNC,
            pluginid=PLUGIN_ID,
            defaultw=400,
            defaulth=250
        )

    def RestoreLayout(self, sec_ref):
        if self.dialog is None:
            self.dialog = GeminiBridgeDialog()
        return self.dialog.Restore(pluginid=PLUGIN_ID, secret=sec_ref)


def PluginMessage(id, data):
    return True


if __name__ == "__main__":
    c4d.plugins.RegisterCommandPlugin(
        id=PLUGIN_ID,
        str=PLUGIN_NAME,
        info=0,
        icon=None,  # Tu peux ajouter un BaseBitmap ici pour une icône
        help=PLUGIN_HELP,
        dat=GeminiBridgeCommand()
    )
    print(f"[Gemini Bridge] Plugin enregistré (ID: {PLUGIN_ID})")
