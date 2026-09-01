"""La UI provata guidandola, non leggendola.

Apre il guscio a due riquadri in un browser vero, scrive nella chat, e controlla
che la conversazione si riempia e che il riquadro di destra carichi la vista.

Il browser che guida la prova e' lo stesso che il prodotto pilota: se la UI si
rompe sotto invisible_playwright, si rompe anche per chi la usa.

Segnato `e2e` perche' avvia due processi veri (il server e un browser) e scarica
il motore la prima volta. Si salta da solo se il server non e' in ascolto, cosi'
la suite ordinaria resta veloce e non finge di aver provato qualcosa.
"""
import json
import os
import socket
import sys

import pytest

URL = os.environ.get("AIHAWK_UI_URL", "http://127.0.0.1:8765/")


def _server_in_ascolto(url: str) -> bool:
    from urllib.parse import urlparse
    u = urlparse(url)
    try:
        with socket.create_connection((u.hostname, u.port or 80), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _server_in_ascolto(URL),
                       reason=f"nessun server su {URL}; avvialo con STEALTHFOX_MCP_TRANSPORT=http"),
]


@pytest.fixture(scope="module")
def pagina():
    from invisible_playwright import InvisiblePlaywright
    with InvisiblePlaywright(seed=4242, headless=True) as browser:
        ctx = browser.new_context()
        pg = ctx.new_page()
        pg.goto(URL, wait_until="load", timeout=30_000)
        yield pg
        ctx.close()


def test_i_due_riquadri_ci_sono(pagina):
    """Il guscio: la colonna della chat, il campo, e l'inquadratura a destra."""
    assert pagina.locator("#log").count() == 1
    assert pagina.locator("#i").count() == 1
    assert pagina.locator("iframe").count() == 1
    src = pagina.locator("iframe").get_attribute("src")
    assert src and "live" in src


def test_il_riquadro_destro_carica_la_vista(pagina):
    """L'iframe deve servire davvero la pagina della vista, non un 404."""
    frame = pagina.frame_locator("iframe")
    assert frame.locator("#f, #empty").count() >= 1


def test_la_vista_prende_davvero_un_fotogramma(pagina):
    """Che l'iframe esista non dice niente.

    Misurato: i cinque test precedenti erano tutti verdi mentre il riquadro
    destro mostrava `error 404` a ogni giro. La pagina della vista chiedeva
    `frame` RELATIVO, che da `/live` risolve a `/frame` e non esiste. Nessuna
    asserzione sulla struttura poteva vederlo: bisogna guardare cosa dice lo
    stato e se l'immagine ha dei pixel.
    """
    pagina.fill("#i", "go https://example.com")
    pagina.press("#i", "Enter")

    # Si aspetta la CONDIZIONE, non un tempo. Un'attesa fissa e' fragile per
    # costruzione: su un server appena riavviato la sessione non esiste ancora e
    # Firefox deve nascere, quindi il primo fotogramma puo' arrivare molto dopo
    # di quando arriva su un browser gia' caldo. Un test che sceglie un numero
    # riporta un difetto del prodotto ogni volta che la macchina e' lenta.
    def frame_vista():
        # Si passa dal frame direttamente invece che da `frame_locator`:
        # quest'ultimo alza "Cannot find object with id" su questo client, che e'
        # un difetto suo e non della pagina.
        v = [x for x in pagina.frames if x.url.rstrip("/").endswith("/live")]
        return v[0] if v else None

    stato = "connecting"
    for _ in range(60):
        pagina.wait_for_timeout(1_000)
        f = frame_vista()
        if f is None:
            continue
        stato = f.evaluate("() => document.getElementById('state').textContent")
        assert not stato.startswith("error"), f"la vista risponde: {stato}"
        if stato == "live":
            break
    else:
        raise AssertionError(f"nessun fotogramma dopo 60s; ultimo stato: {stato}")

    f = frame_vista()

    larghezza = f.evaluate("() => document.getElementById('f').naturalWidth")
    assert larghezza and larghezza > 0, "l'immagine della vista non ha pixel"

    # E deve essere VISIBILE. `naturalWidth` e' vero anche su un display:none, ed
    # e' esattamente cosi' che il riquadro e' rimasto nero mentre lo stato diceva
    # `live` e i test passavano: il codice faceva `style.display = ''`, che toglie
    # lo stile inline e ricade sulla regola del foglio, che era `none`.
    box = f.evaluate("""() => {
        const i = document.getElementById('f');
        const r = i.getBoundingClientRect();
        return {w: Math.round(r.width), h: Math.round(r.height),
                display: getComputedStyle(i).display};
    }""")
    assert box["display"] != "none", "l'immagine c'e' ma e' nascosta dal CSS"
    assert box["w"] > 100 and box["h"] > 100, f"l'immagine non occupa spazio: {box}"


def test_nessuna_richiesta_della_vista_finisce_in_404(pagina):
    """Il difetto in forma diretta: si osservano le risposte, non l'aspetto."""
    fallite = []
    pagina.on("response", lambda r: fallite.append(r.url) if r.status == 404 and "frame" in r.url else None)
    pagina.wait_for_timeout(3_000)
    assert not fallite, f"la vista chiede un percorso che non esiste: {fallite[:2]}"


def test_una_riga_scritta_compare_nella_conversazione(pagina):
    """Il giro completo del guscio: scrivo, invio, e la conversazione cresce."""
    prima = pagina.locator("#log .msg").count()
    pagina.fill("#i", "questa e' una prova")
    pagina.press("#i", "Enter")
    pagina.wait_for_function(
        "n => document.querySelectorAll('#log .msg').length > n",
        arg=prima, timeout=15_000,
    )
    testo = pagina.locator("#log").inner_text()
    assert "questa e' una prova" in testo


def test_lo_stub_dice_di_essere_uno_stub(pagina):
    """Chi guarda deve poter capire che non c'e' ancora nessun modello.

    E' la ragione per cui lo stub risponde cosi': un segnaposto travestito da
    agente e' la cosa che si dimostra bene e su cui non si costruisce.
    """
    pagina.fill("#i", "trovami un volo per Lisbona sotto i 200 euro")
    pagina.press("#i", "Enter")
    pagina.wait_for_function(
        "() => document.querySelector('#log').innerText.toLowerCase().includes('placeholder')",
        timeout=15_000,
    )


def test_il_campo_si_svuota_dopo_l_invio(pagina):
    """Piccolo, ma e' il difetto che si nota al secondo messaggio."""
    pagina.fill("#i", "ciao")
    pagina.press("#i", "Enter")
    pagina.wait_for_function("() => document.querySelector('#i').value === ''", timeout=5_000)
