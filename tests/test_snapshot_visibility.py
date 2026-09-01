"""Lo snapshot deve vedere cio' che c'e' e scartare cio' che non c'e'.

Misurato il 2026-09-02 contro la versione che usava `el.offsetParent !== null`:
su una pagina con cinque elementi ne riportava tre, e sbagliava in ENTRAMBE le
direzioni.

  bottone position:fixed   visibile   -> SCARTATO
  visibility:hidden        invisibile -> TENUTO
  left:-9999px             invisibile -> TENUTO
  div[role=button]         cliccabile -> MAI CERCATO

`offsetParent` e' `null` su qualunque elemento `position:fixed`, e quella non e'
una configurazione di laboratorio: e' il banner dei cookie, la barra appiccicata
in fondo, il pulsante del modale. Quando e' il modale a bloccare la pagina, il
modello non lo vede proprio, quindi il fallimento non e' locale, e' terminale.

Questi test girano sulla funzione di filtro isolata, senza browser: la logica sta
in una stringa JS, e per provarla qui la si esercita sulla forma dei dati che
quella stringa produce. Il controllo end-to-end col browser vero e' in
test_real_launch.py.
"""
import re

from invisible_playwright_mcp import actions


def _codice(js: str) -> str:
    """Il JS senza i commenti.

    Serve perche' il commento che spiega l'incidente NOMINA `offsetParent`, ed e'
    giusto che lo nomini: dice perche' quella riga non deve tornare. Un test che
    leggesse anche i commenti sarebbe rosso proprio per la documentazione del
    difetto che protegge. E' lo stesso errore, in questo progetto gia' visto piu'
    volte, di scrivere il controllo contro il commento invece che contro il
    codice: qui capita al rovescio.
    """
    return re.sub(r"//[^\n]*", "", js)


def test_the_filter_no_longer_asks_for_offsetparent():
    """La riga che causava il difetto non deve tornare."""
    assert "offsetParent" not in _codice(actions.SNAPSHOT_JS), (
        "offsetParent e' tornato nello snapshot: scarta ogni position:fixed, "
        "cioe' banner dei cookie, barre appiccicate e pulsanti dei modali"
    )


def test_the_filter_looks_at_what_actually_decides_visibility():
    js = actions.SNAPSHOT_JS
    for atteso in ("getBoundingClientRect", "visibility", "display"):
        assert atteso in js, f"lo snapshot non guarda {atteso}"


def test_the_query_reaches_elements_that_are_not_form_tags():
    """Meta' dei pulsanti del web non sono `<button>`.

    Un `div` con `role=button` e un gestore di click e' cliccabile quanto un
    bottone, e la lista chiusa di tag non lo cercava affatto.
    """
    js = actions.SNAPSHOT_JS
    assert 'role="button"' in js or "role='button'" in js or "[role=" in js
    assert "onclick" in js
    assert "tabindex" in js


def test_the_snapshot_still_reports_the_fields_a_caller_needs():
    js = actions.SNAPSHOT_JS
    for campo in ("tag", "text", "title", "url", "interactive_elements"):
        assert campo in js


def test_the_snapshot_does_not_write_to_the_page():
    """Sola lettura, e non e' un dettaglio estetico.

    Iniettare un attributo per numerare gli elementi muterebbe il DOM, cioe'
    creerebbe una superficie di rilevamento dentro un prodotto che esiste per non
    averne. Se un giorno si vorra' un indice stabile, quella scelta va fatta in
    chiaro, non introdotta di straforo qui.
    """
    js = actions.SNAPSHOT_JS
    for scrittura in ("setAttribute", "dataset.", "innerHTML =", "classList.add"):
        assert scrittura not in js, f"lo snapshot scrive nella pagina: {scrittura}"


def test_visibility_rules_are_expressed_once_each():
    """Una regola scritta due volte diverge. Questo e' un controllo di forma sul
    fatto che il filtro sia una funzione sola e non copiato per ramo."""
    js = actions.SNAPSHOT_JS
    assert js.count("getBoundingClientRect") <= 2
