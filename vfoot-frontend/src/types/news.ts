// Le novità del prodotto — GET /news. Corte per costruzione: il titolo deve
// reggere da solo, perché su un telefono è spesso l'unica riga che si legge.
export interface NewsItem {
  id: number;
  title: string;
  body: string;
  published_at: string; // ISO 8601
}

export interface NewsResponse {
  items: NewsItem[];
}
