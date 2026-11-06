import os
import html
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from parser import parse_expense_message
from sheets_service import SheetsService
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


class DummyHealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot Finanze e' attivo e funzionante!")

    def log_message(self, format, *args):
        return  # disabilita i log HTTP per non sporcare il terminale


def start_health_server():
    port_env = os.getenv("PORT")
    if port_env:
        try:
            port = int(port_env)
            server = HTTPServer(("0.0.0.0", port), DummyHealthCheck)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            print(f"Server health check avviato sulla porta {port} per hosting cloud.")
        except Exception as e:
            print(f"Avviso avvio server web: {e}")


# 1. Carichiamo le variabili dal file .env
load_dotenv()

TOKEN = os.getenv("telegram_token") or os.getenv("TELEGRAM_TOKEN")
SPREADSHEET_CASA = os.getenv("SPREADSHEET_CASA") or os.getenv("SPREADSHEET_NAME", "finanze_casa")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")

# Fogli personali dedicati
SPREADSHEET_GIUSEPPE = os.getenv("SPREADSHEET_GIUSEPPE", os.getenv("SPREADSHEET_PERSONALE", "finanze_personale"))
SPREADSHEET_CARMEN = os.getenv("SPREADSHEET_CARMEN", "finanze_carmen")

USER_GIUSEPPE_ID = int(os.getenv("USER_GIUSEPPE_ID", "132279185")) if os.getenv("USER_GIUSEPPE_ID", "132279185").isdigit() else 132279185
USER_CARMEN_ID = int(os.getenv("USER_CARMEN_ID")) if os.getenv("USER_CARMEN_ID", "").isdigit() else None

# Parsing mappa fogli personali (es. "132279185:finanze_personale,987654321:finanze_carmen")
PERSONAL_SHEETS_MAP: Dict[int, str] = {}
raw_personal = os.getenv("PERSONAL_SHEETS", "")
for entry in raw_personal.split(","):
    if ":" in entry:
        uid, sname = entry.split(":", 1)
        uid_clean = uid.strip()
        sname_clean = sname.strip()
        if uid_clean.isdigit() and sname_clean:
            PERSONAL_SHEETS_MAP[int(uid_clean)] = sname_clean

# Aggiungi Giuseppe e Carmen alla mappa
if USER_GIUSEPPE_ID:
    PERSONAL_SHEETS_MAP[USER_GIUSEPPE_ID] = SPREADSHEET_GIUSEPPE
if USER_CARMEN_ID:
    PERSONAL_SHEETS_MAP[USER_CARMEN_ID] = SPREADSHEET_CARMEN

# Parsing utenti autorizzati
raw_allowed = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = set()
for item in raw_allowed.split(","):
    item_clean = item.strip()
    if item_clean.isdigit():
        ALLOWED_USER_IDS.add(int(item_clean))

# Include automaticamente tutti gli utenti presenti nella mappa fogli personali
for uid in PERSONAL_SHEETS_MAP.keys():
    ALLOWED_USER_IDS.add(uid)

# Cache dei servizi Google Sheets per ciascun foglio
sheets_instances: Dict[str, SheetsService] = {}


def get_sheets_service(sheet_name: str) -> SheetsService:
    """Restituisce (o istanzia se nuovo) il servizio per il foglio specificato."""
    if sheet_name not in sheets_instances:
        sheets_instances[sheet_name] = SheetsService(
            credentials_path=CREDENTIALS_FILE,
            spreadsheet_name=sheet_name
        )
    return sheets_instances[sheet_name]


def get_user_personal_sheet(user_id: int, user_first_name: str = "") -> Optional[str]:
    """
    Identifica il foglio personale dell'utente in base a:
    1. ID Telegram registrato in PERSONAL_SHEETS_MAP
    2. Fallback sul nome Carmen se il suo ID non è ancora stato registrato
    3. Fallback sul foglio personale generico
    """
    if user_id in PERSONAL_SHEETS_MAP:
        return PERSONAL_SHEETS_MAP[user_id]

    # Fallback per nome nel caso Carmen scriva prima di aver impostato USER_CARMEN_ID
    if "carmen" in (user_first_name or "").lower():
        return SPREADSHEET_CARMEN

    # Se c'è solo un utente registrato, fallback
    if len(PERSONAL_SHEETS_MAP) == 1:
        return list(PERSONAL_SHEETS_MAP.values())[0]

    return None


def is_user_authorized(user_id: int, user_first_name: str = "") -> bool:
    """Verifica se l'utente è autorizzato."""
    if not ALLOWED_USER_IDS:
        return True
    if user_id in ALLOWED_USER_IDS:
        return True
    if "carmen" in (user_first_name or "").lower():
        return True
    return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start: mostra messaggio di benvenuto, ID utente e guida rapida personalizzata."""
    user = update.effective_user
    user_id = user.id
    first_name = html.escape(user.first_name or "amico")
    personal_sheet = get_user_personal_sheet(user_id, user.first_name) or "Non ancora configurato"

    welcome_text = (
        f"👋 Ciao <b>{first_name}</b>!\n\n"
        f"Sono il tuo <b>Bot Finanze</b> per la gestione delle spese.\n\n"
        f"🆔 <b>Il tuo Telegram ID:</b> <code>{user_id}</code>\n\n"
        f"📊 <b>I tuoi Fogli Google:</b>\n"
        f"• 🏠 <b>Casa (comune):</b> <code>{html.escape(SPREADSHEET_CASA)}</code>\n"
        f"• 👤 <b>Il tuo Personale:</b> <code>{html.escape(personal_sheet)}</code> (aggiungendo la parola chiave <code>pers</code>)\n\n"
        f"✍️ <b>Esempi di inserimento:</b>\n"
        f"• <code>15 pizza contanti</code> → Spesa <b>Casa</b>\n"
        f"• <code>45 scarpe carta pers</code> → Spesa <b>Personale ({html.escape(personal_sheet)})</b>\n"
        f"• <code>bonifico 120 affitto</code> → Spesa <b>Casa</b>\n"
        f"• <code>+1500 stipendio bonifico pers</code> → Entrata <b>Personale</b>\n\n"
        f"📌 <b>Comandi utili:</b>\n"
        f"• /mese - Riepilogo del mese (Casa)\n"
        f"• <code>/mese pers</code> - Il tuo riepilogo personale\n"
        f"• /annulla - Cancella l'ultima spesa (Casa)\n"
        f"• <code>/annulla pers</code> - Cancella l'ultima spesa (Personale)\n"
        f"• /help - Guida rapida"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help: mostra le istruzioni dettagliate."""
    help_text = (
        "ℹ️ <b>Guida all'uso del Bot Finanze</b>\n\n"
        "<b>1. Come registrare un movimento:</b>\n"
        "Invia un messaggio contenente:\n"
        "• <b>Importo:</b> es. <code>15</code>, <code>25.50</code>, <code>40€</code>\n"
        "• <b>Motivo:</b> es. <code>cena</code>, <code>benzina</code>, <code>spesa</code>\n"
        "• <b>Pagamento:</b> <i>contanti</i>, <i>carta</i> o <i>bonifico</i>\n"
        "• <b>Destinazione:</b> se scrivi <code>pers</code> va nel tuo foglio personale, altrimenti in quello Casa.\n\n"
        "<b>2. Comandi disponibili:</b>\n"
        "• /mese oppure <code>/mese pers</code> - Mostra bilancio e categorie\n"
        "• /annulla oppure <code>/annulla pers</code> - Cancella l'ultimo movimento registrato"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def mese_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /mese: visualizza il riepilogo del mese per Casa o per il proprio foglio Personale (/mese pers)."""
    user = update.effective_user
    user_id = user.id
    if not is_user_authorized(user_id, user.first_name):
        await update.message.reply_text("⛔ Non sei autorizzato a usare questo comando.", parse_mode=ParseMode.HTML)
        return

    is_pers = bool(context.args and any("pers" in arg.lower() for arg in context.args))

    if is_pers:
        target_sheet_name = get_user_personal_sheet(user_id, user.first_name)
        if not target_sheet_name:
            await update.message.reply_text(
                f"⚠️ Non ho trovato un foglio personale configurato per il tuo ID (<code>{user_id}</code>).",
                parse_mode=ParseMode.HTML
            )
            return
        target_service = get_sheets_service(target_sheet_name)
        label_foglio = f"Personale ({target_sheet_name})"
    else:
        target_service = get_sheets_service(SPREADSHEET_CASA)
        label_foglio = f"Casa ({SPREADSHEET_CASA})"

    ok, summary, msg = target_service.get_monthly_summary()
    if not ok:
        await update.message.reply_text(f"⚠️ Impossibile generare il riepilogo per <b>{html.escape(label_foglio)}</b>:\n<code>{html.escape(msg)}</code>", parse_mode=ParseMode.HTML)
        return

    if summary.get("is_empty"):
        await update.message.reply_text(
            f"📊 <b>{html.escape(label_foglio)} ({html.escape(summary['sheet_title'])})</b>\n\nNessun movimento registrato finora per questo mese.",
            parse_mode=ParseMode.HTML
        )
        return

    sheet_title = summary["sheet_title"]
    tot_entrate = summary["total_entrate"]
    tot_uscite = summary["total_uscite"]
    saldo = summary["saldo"]

    saldo_str = f"+{saldo:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if saldo >= 0 else f"{saldo:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    entrate_str = f"+{tot_entrate:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    uscite_str = f"-{tot_uscite:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    testo = [
        f"📊 <b>Riepilogo {html.escape(label_foglio)}: {html.escape(sheet_title)}</b>\n",
        f"🟢 <b>Entrate:</b> {entrate_str}",
        f"🔴 <b>Uscite:</b> {uscite_str}",
        f"💰 <b>Bilancio:</b> <b>{saldo_str}</b>\n",
        "━━━━━━━━━━━━━━━━━━━━",
        "🏷️ <b>Uscite per Categoria:</b>"
    ]

    categories = summary["categories"]
    if categories:
        for cat, amount in categories:
            perc = (amount / tot_uscite * 100) if tot_uscite > 0 else 0
            imp_formatted = f"{amount:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
            testo.append(f"• <b>{html.escape(cat)}:</b> {imp_formatted} ({perc:.1f}%)")
    else:
        testo.append("<i>Nessuna uscita registrata</i>")

    users = summary["users"]
    if users and not is_pers:
        testo.append("\n━━━━━━━━━━━━━━━━━━━━")
        testo.append("👥 <b>Dettaglio Utenti:</b>")
        for u_name, vals in users.items():
            u_usc = f"{vals['uscite']:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
            u_ent = f"{vals['entrate']:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
            testo.append(f"• <b>{html.escape(u_name)}:</b> Uscite {u_usc} | Entrate {u_ent}")

    await update.message.reply_text("\n".join(testo), parse_mode=ParseMode.HTML)


async def annulla_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /annulla: cancella l'ultima operazione nel foglio Casa o nel proprio Personale (/annulla pers)."""
    user = update.effective_user
    user_id = user.id
    if not is_user_authorized(user_id, user.first_name):
        await update.message.reply_text("⛔ Non sei autorizzato a usare questo comando.", parse_mode=ParseMode.HTML)
        return

    is_pers = bool(context.args and any("pers" in arg.lower() for arg in context.args))

    if is_pers:
        target_sheet_name = get_user_personal_sheet(user_id, user.first_name)
        if not target_sheet_name:
            await update.message.reply_text(
                f"⚠️ Non ho trovato un foglio personale configurato per il tuo ID (<code>{user_id}</code>).",
                parse_mode=ParseMode.HTML
            )
            return
        target_service = get_sheets_service(target_sheet_name)
        label_foglio = f"Personale ({target_sheet_name})"
    else:
        target_service = get_sheets_service(SPREADSHEET_CASA)
        label_foglio = f"Casa ({SPREADSHEET_CASA})"

    ok, deleted_info, msg = target_service.delete_last_expense()
    if not ok:
        await update.message.reply_text(f"⚠️ Impossibile annullare in <b>{html.escape(label_foglio)}</b>:\n{html.escape(msg)}", parse_mode=ParseMode.HTML)
        return

    raw_imp = abs(deleted_info['importo'])
    segno_del = "+" if deleted_info['tipo'].lower() == "entrata" else "-"
    imp_str = f"{segno_del}{raw_imp:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    simbolo_tipo = "🟢 Entrata" if deleted_info['tipo'].lower() == "entrata" else "🔴 Uscita"

    testo = (
        f"🗑️ <b>Operazione annullata dal foglio {html.escape(label_foglio)}!</b>\n\n"
        f"📅 <b>Data:</b> {html.escape(deleted_info['data'])}\n"
        f"👤 <b>Utente:</b> {html.escape(deleted_info['utente'])}\n"
        f"🔖 <b>Tipo:</b> {simbolo_tipo}\n"
        f"🏷️ <b>Categoria:</b> {html.escape(deleted_info['categoria'])}\n"
        f"💰 <b>Importo:</b> {imp_str}\n"
        f"📝 <b>Motivo:</b> {html.escape(deleted_info['motivo'])}\n"
        f"💳 <b>Pagamento:</b> {html.escape(deleted_info['metodo'])}"
    )
    await update.message.reply_text(testo, parse_mode=ParseMode.HTML)


async def gestisci_messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestore principale per tutti i messaggi di testo ordinari."""
    user = update.effective_user
    user_id = user.id

    # 1. Controllo autorizzazione utente
    if not is_user_authorized(user_id, user.first_name):
        msg = (
            f"⛔ <b>Accesso non autorizzato.</b>\n\n"
            f"Il tuo ID Telegram è: <code>{user_id}</code>\n"
            f"Aggiungilo alla variabile <code>ALLOWED_USER_IDS</code> nel file <code>.env</code> per abilitare l'accesso."
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    text = update.message.text
    if not text:
        return

    # 2. Analisi e parsing del messaggio
    success, data, error_msg = parse_expense_message(text)
    if not success:
        await update.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
        return

    # 3. Dati automatici: Data odierna e Nome utente
    now = datetime.now()
    today_str = now.strftime("%d/%m/%Y")
    user_display_name = user.first_name or "Utente"
    if user.last_name:
        user_display_name += f" {user.last_name}"

    importo = data['importo']
    motivo = data['motivo']
    metodo = data['metodo']
    tipo = data['tipo']
    categoria = data['categoria']
    destinazione = data['destinazione']  # 'casa' o 'personale'

    # 4. Selezione del foglio di destinazione
    if destinazione == 'personale':
        target_sheet_name = get_user_personal_sheet(user_id, user.first_name)
        if not target_sheet_name:
            await update.message.reply_text(
                f"⚠️ Non ho trovato un foglio personale configurato per il tuo ID (<code>{user_id}</code>).\n"
                f"Aggiungi il tuo ID a <code>PERSONAL_SHEETS</code> nel file <code>.env</code>!",
                parse_mode=ParseMode.HTML
            )
            return
        target_service = get_sheets_service(target_sheet_name)
        nome_foglio_label = f"Personale ({target_sheet_name})"
    else:
        target_service = get_sheets_service(SPREADSHEET_CASA)
        nome_foglio_label = f"Casa ({SPREADSHEET_CASA})"

    # 5. Scrittura su Google Sheets
    sheets_ok, sheets_msg = target_service.append_expense(
        date_str=today_str,
        user_name=user_display_name,
        movement_type=tipo,
        category=categoria,
        amount=importo,
        reason=motivo,
        payment_method=metodo,
        date_obj=now
    )

    if tipo.lower() == "uscita":
        segno_str = "-"
        simbolo_tipo = "🔴 Uscita"
    else:
        segno_str = "+"
        simbolo_tipo = "🟢 Entrata"

    imp_str = f"{segno_str}{abs(importo):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    if sheets_ok:
        conferma = (
            f"✅ <b>Movimento registrato su {html.escape(nome_foglio_label)}!</b>\n\n"
            f"📅 <b>Data:</b> {today_str}\n"
            f"👤 <b>Utente:</b> {html.escape(user_display_name)}\n"
            f"🔖 <b>Tipo:</b> {simbolo_tipo}\n"
            f"🏷️ <b>Categoria:</b> {html.escape(categoria)}\n"
            f"💰 <b>Importo:</b> {imp_str}\n"
            f"📝 <b>Motivo:</b> {html.escape(motivo)}\n"
            f"💳 <b>Pagamento:</b> {metodo}\n\n"
            f"<i>💡 Usa /annulla {'pers' if destinazione == 'personale' else ''} se vuoi cancellarlo.</i>"
        )
    else:
        conferma = (
            f"⚠️ <b>Movimento compreso ma non salvato su {html.escape(nome_foglio_label)}:</b>\n"
            f"<code>{html.escape(sheets_msg)}</code>\n\n"
            f"<b>Riepilogo dati estratti:</b>\n"
            f"• Destinazione: {html.escape(nome_foglio_label)}\n"
            f"• Data: {today_str}\n"
            f"• Utente: {html.escape(user_display_name)}\n"
            f"• Tipo: {simbolo_tipo}\n"
            f"• Categoria: {html.escape(categoria)}\n"
            f"• Importo: {imp_str}\n"
            f"• Motivo: {html.escape(motivo)}\n"
            f"• Metodo: {metodo}\n\n"
            f"<i>Verifica di aver condiviso il foglio con l'email del service account!</i>"
        )

    await update.message.reply_text(conferma, parse_mode=ParseMode.HTML)


def main():
    if not TOKEN:
        print("ERRORE: Token Telegram non trovato nel file .env!")
        return

    start_health_server()

    print(f"Foglio Casa: '{SPREADSHEET_CASA}'")
    print(f"Fogli Personali mappati: {PERSONAL_SHEETS_MAP}")

    if ALLOWED_USER_IDS:
        print(f"Utenti autorizzati: {ALLOWED_USER_IDS}")
    else:
        print("AVVISO: Nessun ID in ALLOWED_USER_IDS. Tutti gli utenti possono usare il bot.")

    app = ApplicationBuilder().token(TOKEN).build()

    # Comandi
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mese", mese_command))
    app.add_handler(CommandHandler("annulla", annulla_command))

    # Messaggi di testo ordinari
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), gestisci_messaggio))

    print("Bot avviato con successo! In ascolto dei messaggi...")
    app.run_polling()


if __name__ == "__main__":
    main()
