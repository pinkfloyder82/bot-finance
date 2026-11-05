import os
import json
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_CASA = os.getenv("SPREADSHEET_CASA") or os.getenv("SPREADSHEET_NAME", "finanze_casa")
SPREADSHEET_PERSONALE = os.getenv("SPREADSHEET_PERSONALE", "finanze_personale")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")


def test_single_sheet(service, sheet_label: str):
    print(f"\n--- Test Foglio: {sheet_label} ('{service.spreadsheet_name}') ---")
    try:
        sh = service._get_spreadsheet()
        print(f"   ✅ Connessione riuscita al foglio '{sh.title}'")
    except Exception as e:
        print(f"   ❌ Errore connessione a '{service.spreadsheet_name}': {e}")
        print("   👉 Assicurati di aver condiviso anche questo foglio con l'email del Service Account come Editor!")
        return False

    now = datetime.now()
    try:
        ws = service.get_or_create_monthly_sheet(now)
        print(f"   ✅ Scheda mensile attiva: '{ws.title}' (righe: {len(ws.get_all_values())})")
    except Exception as e:
        print(f"   ❌ Errore scheda mensile: {e}")
        return False

    # Scrittura riga di prova
    ok, msg = service.append_expense(
        date_str=now.strftime("%d/%m/%Y"),
        user_name="Test Bot",
        movement_type="Uscita",
        category="Ristorazione e Bar",
        amount=1.50,
        reason="Test Connessione",
        payment_method="Carta",
        date_obj=now
    )
    if not ok:
        print(f"   ❌ Scrittura fallita: {msg}")
        return False
    print("   ✅ Riga di test scritta con successo!")

    # Rimozione riga di prova
    ok_del, del_info, msg_del = service.delete_last_expense(now)
    if ok_del and del_info.get("motivo") == "Test Connessione":
        print(f"   ✅ Riga di test rimossa con successo!")
    else:
        print(f"   ⚠️ Nota rimozione: {msg_del}")

    return True


def run_test():
    print("=" * 60)
    print("🧪 TEST CONNESSIONE GOOGLE SHEETS (CASA E PERSONALE)")
    print("=" * 60)

    if not os.path.exists(CREDENTIALS_FILE):
        print(f"\n❌ ERRORE: File '{CREDENTIALS_FILE}' non trovato!")
        sys.exit(1)

    try:
        with open(CREDENTIALS_FILE, "r") as f:
            cred_data = json.load(f)
            client_email = cred_data.get("client_email")
        print(f"• Email Service Account:\n  👉 \033[1;32m{client_email}\033[0m")
        print("\n⚠️  Ricordati di condividere ENTRAMBI i fogli con questa email:")
        print(f"   1. {SPREADSHEET_CASA}")
        print(f"   2. {SPREADSHEET_PERSONALE}\n")
    except Exception as e:
        print(f"❌ Errore lettura credenziali: {e}")
        sys.exit(1)

    from sheets_service import SheetsService

    service_casa = SheetsService(CREDENTIALS_FILE, spreadsheet_name=SPREADSHEET_CASA)
    test_single_sheet(service_casa, "CASA")

    service_pers = SheetsService(CREDENTIALS_FILE, spreadsheet_name=SPREADSHEET_PERSONALE)
    test_single_sheet(service_pers, "PERSONALE")

    print("\n" + "=" * 60)
    print("🎉 TEST TERMINATO!")
    print("=" * 60)


if __name__ == "__main__":
    run_test()
