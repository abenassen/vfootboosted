"""LE OSSERVAZIONI DI CAMPO, nel linguaggio che la ricerca legge.

Ogni riga qui dentro e' una cosa vista guardando una partita, non una regola
generale: le regole generali ("chi entra e segna non supera chi ha giocato tutta
la partita") sono violabili in troppi casi specifici, e imporle vorrebbe dire
mettere nel modello una legge che il calcio non ha. Le osservazioni puntuali
invece non pretendono di spiegare: dicono soltanto dove il voto e' finito storto,
e lasciano che sia la ricerca a dedurre in che direzione muovere i pesi.

DUE FORME, e la prima e' meglio della seconda:

* ORDINE — "A sta sotto B nella stessa partita". Non ha bordi: confronta due
  numeri continui e resta vero comunque cada la griglia dei mezzi punti. Misurato
  il 01/09/2026: tre dei quindici bersagli in forma di soglia stavano a 0.01-0.03
  dall'arrotondamento, e si ribaltavano se la media dei voti si spostava di due
  millesimi.
* SOGLIA — "il voto di X sta sotto questo numero". Si tiene dove un ordinamento
  non c'e' (nessun compagno a cui appoggiarsi), e si valuta sul GREZZO con un
  margine, mai sul voto arrotondato.

Piu' gli INVARIANTI, che non vengono dal campo ma dal buon senso, e servono a
impedire che la ricerca migliori ogni media peggiorando il calcio (v.
tests_rare_events e il cruscotto in vote_tuning); e il PAVIMENTO sui giudici, che
e' cio' che tiene tutto ancorato a diecimila partite invece che a venti casi.
"""

# (nome, giornata, frammento del cognome) -> la presenza a cui il vincolo si
# riferisce. Il frammento e non l'id: gli id dei giocatori non sono portabili fra
# le installazioni, i cognomi si.
ORDINI = [
    # Fiorentina 0-3 Frosinone. Raimondo segna DUE gol e resta sotto due difensori
    # della sua squadra. E' il caso piu' netto che abbiamo, e ne chiude due (era
    # anche "Monterisi <= 7").
    ("Raimondo sopra Monterisi", ("raimondo", 2), ("monterisi", 2), 0.10),
    ("Raimondo sopra Bracaglia", ("raimondo", 2), ("bracaglia", 2), 0.10),
    # Lecce 0-4 Roma. Dybala prende piu' di Malen e Soule', che hanno segnato,
    # e nei suoi novanta minuti la cosa piu' evidente e' un gol sbagliato.
    ("Malen sopra Dybala", ("malen", 2), ("dybala", 2), 0.10),
    # Cagliari 0-1 Inter.
    ("Barella sopra Dimarco", ("barella", 2), ("dimarco", 2), 0.10),
    # Genoa 0-2 Napoli.
    ("Vergara sopra Rrahmani", ("vergara", 1), ("rrahmani", 1), 0.10),
]

# FUORI DALLA RICERCA, e non per dimenticanza: "Skorupski nettamente sotto
# Martinez" (Atalanta-Bologna contro Cagliari-Inter) mette a confronto DUE
# PORTIERI, e il portiere ha un canale di feature suo, pesi suoi e una sigma sua —
# verificato: la ritaratura dei ruoli di movimento del 01/09/2026 ha lasciato la
# sigma dei portieri a 2.0288 contro 2.0295, cioe' ferma. Quel margine e' percio'
# COSTANTE rispetto a tutto cio' che questa ricerca puo' muovere: non e' un
# vincolo, e' un no-op che occuperebbe una riga della matrice J per restituire
# sempre zero. Resta vero (0.80 di margine) e resta scritto qui perche' il giorno
# in cui si tarera' il canale del portiere sara' il primo da riprendere.

# (nome, giornata, frammento, verso, valore, margine)
SOGLIE = [
    ("Tavares",       2, "tavares",      "<=", 7.75, 0.10),
    ("Conceicao",     2, "conceicao",    "<=", 7.25, 0.10),
    ("Dybala g1",     1, "dybala",       ">=", 6.75, 0.10),
    ("N. Gonzalez",   2, "gonzalez",     "<=", 7.75, 0.10),
    ("Bernardeschi",  1, "bernardeschi", "<=", 7.25, 0.10),
    ("Berardi",       2, "berardi",      "<=", 7.25, 0.10),
    ("Goncalo Ramos", 2, "ramos",        "<=", 7.25, 0.10),
    ("Piotrowski",    2, "piotrowski",   "<=", 7.75, 0.10),
    ("Romero",        2, "romero",       "<=", 6.75, 0.10),
]

# Quanto vale UNA occorrenza, in punti di voto. Le grandezze che si possono
# giudicare a occhio — e l'unica difesa contro un ottimizzatore che migliora ogni
# media peggiorando il calcio. Il rigore concesso e' il 76,4% del costo di causare
# un gol, perche' tanti sono i rigori segnati (81 su 106 nella 25-26).
INVARIANTI = [
    ("1 clearances_off_line",  0.300, 0.06),
    ("1 penalties_won",        0.510, 0.06),
    ("1 penalties_conceded",  -0.455, 0.06),
    ("1 errors_led_to_goal",  -0.596, 0.06),
    ("1 errors_led_to_shot",  -0.170, 0.06),
]
