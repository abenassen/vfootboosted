// La valuta della lega, in un posto solo.
//
// Prima non esisteva un posto solo, ed è per questo che dentro la STESSA scheda
// rosa il prezzo di un giocatore era «€28» e il totale del reparto due righe
// sopra «48 crediti»: due parole per la stessa cosa, scelte da due persone in
// due momenti. Un euro poi è una moneta vera, e nel listone ce n'è davvero uno —
// il valore di mercato Transfermarkt — quindi lo stesso segno diceva due cose
// diverse a due centimetri di distanza.
//
// IL SIMBOLO E LA PAROLA FANNO DUE MESTIERI. Il simbolo sta attaccato a un
// numero, dove lo spazio è quello di una colonna e nessuno legge, guarda:
// `ṿƒ28`. La parola serve dove si sta parlando — «hai 137 vfooties», «offerta in
// vfooties» — e lì un glifo di due caratteri sarebbe un rebus. Non sono
// intercambiabili, e le due funzioni qui sotto esistono per non doverci pensare
// ogni volta.
export const CURRENCY_SYMBOL = 'ṿƒ';
export const CURRENCY_NAME = 'vfooty';
export const CURRENCY_NAME_PLURAL = 'vfooties';

/** Un prezzo col suo simbolo dopo: `28 ṿƒ`. Per colonne e tabelle.
 *
 *  DOPO e staccato, come si scrive un prezzo parlando italiano (30 €, non € 30):
 *  in una colonna allineata a destra il numero resta il primo a essere letto e le
 *  cifre restano incolonnate, mentre il simbolo davanti spingeva i numeri a
 *  destra di larghezze diverse a seconda che fossero due o tre cifre. */
export function price(amount: number): string {
  return `${Math.round(amount)} ${CURRENCY_SYMBOL}`;
}

/** Una cifra detta a parole: `28 vfooties`. Per le frasi. */
export function amount(value: number): string {
  const n = Math.round(value);
  return `${n} ${n === 1 ? CURRENCY_NAME : CURRENCY_NAME_PLURAL}`;
}
