import os
import json
from datetime import datetime
from collections import defaultdict
from typing import Tuple, Optional, Dict, Any, List

import gspread
from google.oauth2.service_account import Credentials

DEFAULT_HEADERS = ["Data", "Utente", "Tipo", "Categoria", "Importo (€)", "Motivo Spesa", "Modalità Pagamento"]

MESI_ITALIANI = {
    1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile",
    5: "Maggio", 6: "Giugno", 7: "Luglio", 8: "Agosto",
    9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre"
}


def to_float(val: Any) -> float:
    """Converte un valore in float gestendo sia formato italiano (virgola) che standard (punto)."""
    if isinstance(val, (int, float)):
        return float(val)
    if not val:
        return 0.0
    s = str(val).replace('€', '').replace(' ', '').strip()
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    else:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


class SheetsService:
    def __init__(self, credentials_path: str, spreadsheet_name: Optional[str] = None, spreadsheet_id: Optional[str] = None):
        self.credentials_path = credentials_path
        self.spreadsheet_name = spreadsheet_name
        self.spreadsheet_id = spreadsheet_id
        self._client = None
        self._spreadsheet = None

    def is_configured(self) -> Tuple[bool, str]:
        """Verifica se i file di configurazione essenziali sono presenti."""
        has_file = os.path.exists(self.credentials_path)
        has_env = bool(os.getenv("GOOGLE_CREDENTIALS_JSON"))
        if not has_file and not has_env:
            return False, f"File credenziali '{self.credentials_path}' non trovato e GOOGLE_CREDENTIALS_JSON non impostata."
        if not self.spreadsheet_name and not self.spreadsheet_id:
            return False, "Nessun nome o ID foglio configurato in .env (SPREADSHEET_NAME o SPREADSHEET_ID)."
        return True, "Configurazione presente."

    def _get_spreadsheet(self):
        """Autentica con Service Account e apre il documento Google Spreadsheet."""
        if self._spreadsheet is not None:
            return self._spreadsheet

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        google_json_env = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if google_json_env:
            try:
                info = json.loads(google_json_env)
                creds = Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                raise ValueError(f"Errore nel parsing di GOOGLE_CREDENTIALS_JSON: {e}")
        elif os.path.exists(self.credentials_path):
            creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
        else:
            raise FileNotFoundError(f"File credenziali '{self.credentials_path}' non trovato.")

        self._client = gspread.authorize(creds)

        if self.spreadsheet_id:
            self._spreadsheet = self._client.open_by_key(self.spreadsheet_id)
        elif self.spreadsheet_name:
            self._spreadsheet = self._client.open(self.spreadsheet_name)
        else:
            raise ValueError("Specificare SPREADSHEET_ID o SPREADSHEET_NAME nel file .env.")

        return self._spreadsheet

    def get_or_create_monthly_sheet(self, date_obj: Optional[datetime] = None) -> gspread.Worksheet:
        """
        Restituisce il foglio mensile per la data specificata (default mese corrente).
        Se non esiste, lo crea senza toccare i mesi precedenti.
        Formato titolo: 'Mese Anno' (es. 'Novembre 2026') oppure riconosce 'YYYY-MM'.
        """
        if date_obj is None:
            date_obj = datetime.now()

        month_str = MESI_ITALIANI[date_obj.month]
        sheet_title = f"{month_str} {date_obj.year}"
        alt_title = f"{date_obj.year}-{date_obj.month:02d}"

        spreadsheet = self._get_spreadsheet()
        worksheets = spreadsheet.worksheets()

        # 1. Cerca se esiste già con formato 'Mese Anno' o 'YYYY-MM'
        for ws in worksheets:
            if ws.title in (sheet_title, alt_title):
                return ws

        # 2. Se c'è solo un foglio generico vuoto (es. 'Foglio 1' o 'Sheet1'), rinominalo
        if len(worksheets) == 1:
            first_ws = worksheets[0]
            if first_ws.title in ("Foglio 1", "Foglio1", "Sheet1", "Sheet 1"):
                first_row = first_ws.row_values(1)
                if not first_row:
                    first_ws.update_title(sheet_title)
                    first_ws.append_row(DEFAULT_HEADERS, value_input_option="USER_ENTERED")
                    return first_ws

        # 3. Altrimenti crea un nuovo foglio mensile dedicato
        new_ws = spreadsheet.add_worksheet(title=sheet_title, rows=200, cols=10)
        new_ws.append_row(DEFAULT_HEADERS, value_input_option="USER_ENTERED")
        return new_ws

    def append_expense(
        self,
        date_str: str,
        user_name: str,
        movement_type: str,
        category: str,
        amount: float,
        reason: str,
        payment_method: str,
        date_obj: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Aggiunge una riga nel foglio mensile corrispondente.
        Colonne: Data, Utente, Tipo, Categoria, Importo, Motivo, Metodo
        """
        configured, msg = self.is_configured()
        if not configured:
            return False, msg

        try:
            sheet = self.get_or_create_monthly_sheet(date_obj)
            row = [date_str, user_name, movement_type, category, amount, reason, payment_method]
            sheet.append_row(row, value_input_option="USER_ENTERED")
            return True, "Registrata con successo"
        except Exception as e:
            self._spreadsheet = None
            self._client = None
            return False, f"Errore Google Sheets: {str(e)}"

    def delete_last_expense(self, date_obj: Optional[datetime] = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Cancella l'ultima riga inserita nel foglio del mese corrente.
        Ritorna: (successo, dati_riga_cancellata, messaggio)
        """
        configured, msg = self.is_configured()
        if not configured:
            return False, None, msg

        try:
            sheet = self.get_or_create_monthly_sheet(date_obj)
            all_values = sheet.get_all_values()

            # Se ci sono solo intestazioni o il foglio è vuoto
            if len(all_values) <= 1:
                return False, None, "Nessun movimento registrato da cancellare in questo mese."

            last_row_index = len(all_values)
            last_row = all_values[-1]

            # Estrai i dettagli della riga prima di eliminarla
            deleted_info = {
                "data": last_row[0] if len(last_row) > 0 else "",
                "utente": last_row[1] if len(last_row) > 1 else "",
                "tipo": last_row[2] if len(last_row) > 2 else "Uscita",
                "categoria": last_row[3] if len(last_row) > 3 else "Altro",
                "importo": to_float(last_row[4]) if len(last_row) > 4 else 0.0,
                "motivo": last_row[5] if len(last_row) > 5 else "",
                "metodo": last_row[6] if len(last_row) > 6 else ""
            }

            sheet.delete_rows(last_row_index)
            return True, deleted_info, f"Operazione cancellata con successo dal foglio '{sheet.title}'."
        except Exception as e:
            self._spreadsheet = None
            self._client = None
            return False, None, f"Errore durante l'annullamento: {str(e)}"

    def get_monthly_summary(self, date_obj: Optional[datetime] = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Elabora il riepilogo aggregato del mese:
        - Totale entrate
        - Totale uscite
        - Bilancio
        - Suddivisione uscite per categoria
        - Totali per utente
        """
        configured, msg = self.is_configured()
        if not configured:
            return False, None, msg

        try:
            sheet = self.get_or_create_monthly_sheet(date_obj)
            all_values = sheet.get_all_values()

            if len(all_values) <= 1:
                return True, {"is_empty": True, "sheet_title": sheet.title}, "Nessun movimento trovato per questo mese."

            total_entrate = 0.0
            total_uscite = 0.0
            categories_uscite = defaultdict(float)
            users_summary = defaultdict(lambda: {"entrate": 0.0, "uscite": 0.0})

            # Righe dati (esclusa la riga 0 delle intestazioni)
            for row in all_values[1:]:
                if not row or not any(row):
                    continue

                if len(row) >= 7:
                    utente = row[1]
                    tipo = row[2]
                    categoria = row[3]
                    importo = to_float(row[4])
                elif len(row) >= 5:
                    # Compatibilità per fogli con formato a 5 colonne precedente
                    utente = row[1]
                    tipo = "Uscita"
                    categoria = "Altro"
                    importo = to_float(row[2])
                else:
                    continue

                if tipo.lower() == "entrata":
                    total_entrate += importo
                    users_summary[utente]["entrate"] += importo
                else:
                    total_uscite += importo
                    categories_uscite[categoria] += importo
                    users_summary[utente]["uscite"] += importo

            saldo = total_entrate - total_uscite

            summary_data = {
                "is_empty": False,
                "sheet_title": sheet.title,
                "total_entrate": total_entrate,
                "total_uscite": total_uscite,
                "saldo": saldo,
                "categories": sorted(categories_uscite.items(), key=lambda x: x[1], reverse=True),
                "users": dict(users_summary)
            }
            return True, summary_data, "Riepilogo generato con successo."
        except Exception as e:
            self._spreadsheet = None
            self._client = None
            return False, None, f"Errore nel calcolo del riepilogo: {str(e)}"
