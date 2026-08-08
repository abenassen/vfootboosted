"""La valuta della lega, dal lato del server.

Il gemello di ``vfoot-frontend/src/utils/currency.ts``, e serve perché una parte
dei testi che parlano di soldi NON li scrive il browser: la riga di news di un
acquisto e i messaggi che rifiutano un'offerta nascono qui, e prima dicevano
"crediti" mentre la pagina accanto diceva "€". Due copie di una costante sono
poco eleganti, ma l'alternativa — mandare la parola al browser a ogni richiesta —
sarebbe un campo in più in ogni risposta per un valore che non cambia mai.

Il simbolo sta attaccato ai numeri, la parola sta nelle frasi: sono due mestieri
diversi, e le due funzioni esistono per non doverci pensare ogni volta.
"""
from __future__ import annotations

SYMBOL = "ṿƒ"
NAME = "vfooty"
NAME_PLURAL = "vfooties"


def price(value) -> str:
    """`28 ṿƒ` — il simbolo DOPO e staccato, come si scrive un prezzo in italiano."""
    return f"{int(round(float(value)))} {SYMBOL}"


def amount(value) -> str:
    """`28 vfooties` — per stare dentro una frase."""
    n = int(round(float(value)))
    return f"{n} {NAME if n == 1 else NAME_PLURAL}"
