import re
from typing import Tuple, Optional, Dict, Any

# Mappatura delle parole chiave per ciascun metodo di pagamento
PAYMENT_KEYWORDS = {
    'Carta': ['carta', 'carte', 'bancomat', 'pos', 'debito', 'credito', 'card'],
    'Contanti': ['contanti', 'contante', 'cash', 'cassa'],
    'Bonifico': ['bonifico', 'bonif']
}

# Categorie predefinite con sinonimi e parole chiave comuni
CATEGORIES = {
    'Stipendio ed Entrate': [
        'stipendio', 'stipendi', 'busta paga', 'paga', 'accredito', 'bonifico ricevuto',
        'fattura', 'compenso', 'parcella', 'rimborso', 'vincita', 'regalo ricevuto',
        'cashback', 'dividendo', 'dividendi', 'rendita', 'vendita', 'incasso', 'entrata', 'premio'
    ],
    'Spesa e Supermercato': [
        'spesa', 'supermercato', 'esselunga', 'conad', 'coop', 'lidl', 'carrefour',
        'eurospin', 'md', 'crai', 'alimentari', 'frutta', 'verdura', 'carne', 'pesce',
        'panificio', 'pane', 'latte', 'forno', 'alimentare', 'panetteria', 'salumeria'
    ],
    'Ristorazione e Bar': [
        'pranzo', 'cena', 'colazione', 'aperitivo', 'apericena', 'bar', 'caffe', 'caffè',
        'pizza', 'pizzeria', 'ristorante', 'pub', 'sushi', 'mcdonald', 'burger', 'panino',
        'piadina', 'gelato', 'pasticceria', 'glovo', 'deliveroo', 'just eat', 'poke', 'birra', 'trattoria'
    ],
    'Trasporti e Auto': [
        'benzina', 'diesel', 'carburante', 'gpl', 'metano', 'rifornimento', 'autostrada',
        'telepass', 'pedaggio', 'parcheggio', 'strisce blu', 'garage', 'treno', 'trenitalia',
        'italo', 'metro', 'bus', 'autobus', 'taxi', 'uber', 'meccanico', 'tagliando',
        'revisione', 'bollo', 'assicurazione', 'gomme', 'gommista', 'multa'
    ],
    'Casa e Utenze': [
        'affitto', 'condominio', 'bolletta', 'bollette', 'luce', 'gas', 'enel', 'eni plenitude',
        'a2a', 'acqua', 'tari', 'rifiuti', 'internet', 'wifi', 'fibra', 'tim', 'vodafone',
        'iliad', 'fastweb', 'mutuo', 'ikea', 'leroy merlin', 'ferramenta', 'arredo', 'casa'
    ],
    'Salute e Cura': [
        'farmacia', 'farmaci', 'medicine', 'dottore', 'medico', 'visita', 'dentista',
        'analisi', 'ospedale', 'ticket', 'occhiali', 'lenti', 'parrucchiere', 'barbiere',
        'estetista', 'crema', 'cosmetici', 'profumeria', 'terapia', 'dentifricio'
    ],
    'Animali': [
        'veterinario', 'cane', 'gatto', 'crocchette', 'pet shop', 'arcaplanet',
        'animali', 'lettiera', 'cibo gatto', 'cibo cane'
    ],
    'Shopping e Abbigliamento': [
        'vestiti', 'abbigliamento', 'scarpe', 'zara', 'h&m', 'primark', 'amazon',
        'giacca', 'pantaloni', 'maglia', 'camicia', 'negozio', 'shopping', 'vestito', 'borsa'
    ],
    'Svago e Tempo Libero': [
        'cinema', 'film', 'concerto', 'teatro', 'museo', 'vacanza', 'hotel', 'b&b',
        'volo', 'ryanair', 'easyjet', 'libri', 'libro', 'kindle', 'netflix', 'spotify',
        'disney', 'prime', 'videogiochi', 'playstation', 'xbox', 'steam', 'palestra',
        'calcetto', 'sport', 'piscina', 'abbonamento'
    ]
}


def classify_movement(text: str, explicit_sign: Optional[str] = None) -> Tuple[str, str]:
    """
    Determina se il movimento è un'Entrata o un'Uscita e assegna la categoria opportuna.
    Ritorna: (tipo: 'Entrata'|'Uscita', categoria: str)
    """
    text_lower = text.lower()

    # 1. Riconoscimento Tipo (Entrata vs Uscita)
    if explicit_sign == '+':
        movement_type = 'Entrata'
    elif explicit_sign == '-':
        movement_type = 'Uscita'
    else:
        # Cerca parole chiave tipiche di entrate/guadagni
        is_income = any(
            re.search(r'\b' + re.escape(w) + r'\b', text_lower)
            for w in CATEGORIES['Stipendio ed Entrate']
        )
        movement_type = 'Entrata' if is_income else 'Uscita'

    # 2. Riconoscimento Categoria
    if movement_type == 'Entrata':
        detected_category = 'Stipendio ed Entrate'
    else:
        detected_category = 'Altro'
        for cat_name, keywords in CATEGORIES.items():
            if cat_name == 'Stipendio ed Entrate':
                continue
            if any(re.search(r'\b' + re.escape(w) + r'\b', text_lower) for w in keywords):
                detected_category = cat_name
                break

    return movement_type, detected_category


def parse_expense_message(text: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Analizza un messaggio di testo per estrarre:
    - importo (float)
    - motivo (str)
    - metodo di pagamento (str: Contanti, Carta, Bonifico)
    - tipo (str: Entrata o Uscita)
    - categoria (str)
    - destinazione (str: 'casa' o 'personale')
    
    Ritorna:
        (success, data_dict, error_message)
    """
    if not text or not text.strip():
        return False, None, "Il messaggio è vuoto. Scrivi ad esempio: '15 pizza contanti' o '20 scarpe carta pers'"

    text_clean = text.strip()

    # 0. Riconosci se la spesa è destinata al foglio personale (parola chiave 'pers' o 'personale')
    pers_pattern = r'(?:\b|#)(?:pers|personale)\b'
    if re.search(pers_pattern, text_clean, re.IGNORECASE):
        target = 'personale'
        text_clean = re.sub(pers_pattern, '', text_clean, flags=re.IGNORECASE).strip()
    else:
        target = 'casa'

    # Riconosci eventuale segno esplicito all'inizio o vicino all'importo (+ o -)
    explicit_sign = None
    if text_clean.startswith('+') or re.search(r'(?<=\s)\+(?=\d)', text_clean):
        explicit_sign = '+'
    elif text_clean.startswith('-') or re.search(r'(?<=\s)\-(?=\d)', text_clean):
        explicit_sign = '-'

    # 1. Riconosci la modalità di pagamento
    found_method = None
    method_span = None

    for method_name, keywords in PAYMENT_KEYWORDS.items():
        pattern = r'\b(' + '|'.join(keywords) + r')\b'
        match = re.search(pattern, text_clean, re.IGNORECASE)
        if match:
            found_method = method_name
            method_span = match.span()
            break

    if not found_method:
        return False, None, (
            "❌ Manca la <b>modalità di pagamento</b>.\n"
            "Specifica se hai pagato in: <i>contanti</i>, <i>carta</i> o <i>bonifico</i>.\n\n"
            "Esempi:\n"
            "• <code>15 pizza contanti</code> (Foglio Casa)\n"
            "• <code>20 farmacia carta pers</code> (Foglio Personale)"
        )

    # Rimuovi il metodo di pagamento trovato per isolare importo e motivo
    text_without_method = text_clean[:method_span[0]] + ' ' + text_clean[method_span[1]:]

    # 2. Cerca l'importo (numeri, con o senza decimali e simbolo € / euro / segno)
    pattern = re.compile(
        r'(?P<sign>[+-])?\s*(?P<prefix>€\s*)?(?P<num>\b\d+(?:[.,]\d{1,2})?\b)(?P<suffix>\s*(?:€|euro|euri)\b)?',
        re.IGNORECASE
    )
    matches = list(pattern.finditer(text_without_method))

    candidates = []
    for m in matches:
        num_str = m.group('num')
        matched_sign = m.group('sign')
        has_currency = bool(m.group('prefix') or m.group('suffix'))
        has_decimals = ('.' in num_str or ',' in num_str)
        try:
            val = float(num_str.replace(',', '.'))
            if val > 0:
                candidates.append({
                    'match': m,
                    'val': val,
                    'sign': matched_sign,
                    'has_currency': has_currency,
                    'has_decimals': has_decimals,
                    'is_start': (m.start() == 0 or text_without_method[:m.start()].strip() == '')
                })
        except ValueError:
            continue

    if not candidates:
        return False, None, (
            "❌ Manca l'<b>importo</b> del movimento.\n"
            "Inserisci una cifra (es. <code>15</code> oppure <code>15.50</code>).\n\n"
            "Esempio: <code>15 pizza contanti</code>"
        )

    # Ordina i candidati per priorità
    candidates.sort(
        key=lambda c: (c['has_currency'], c['has_decimals'], c['is_start'], c['val']),
        reverse=True
    )

    best = candidates[0]
    amount = round(best['val'], 2)
    if not explicit_sign and best['sign']:
        explicit_sign = best['sign']

    m = best['match']

    # 3. Estrai e pulisci il motivo
    start, end = m.span()
    text_without_amount = text_without_method[:start] + ' ' + text_without_method[end:]

    cleaned_reason = re.sub(r'\b(euro|euri)\b|[€+]', '', text_without_amount, flags=re.IGNORECASE)
    cleaned_reason = re.sub(r'[\s\-_,;]+', ' ', cleaned_reason).strip()

    if not cleaned_reason:
        return False, None, (
            "❌ Manca il <b>motivo della spesa</b> o entrata.\n"
            "Spiega per cosa hai speso (es. <code>pizza</code>, <code>supermercato</code>, <code>stipendio</code>).\n\n"
            "Esempio: <code>15 pizza contanti</code>"
        )

    # 4. Determina Tipo (Entrata/Uscita) e Categoria
    movement_type, category = classify_movement(cleaned_reason, explicit_sign)

    return True, {
        'importo': amount,
        'motivo': cleaned_reason.capitalize(),
        'metodo': found_method,
        'tipo': movement_type,
        'categoria': category,
        'destinazione': target
    }, None
