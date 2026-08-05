// Gemeinsame Anzeige-Formatierung.
//
// Vorher lagen `fmtDuration` dreimal und `fmtDate` zweimal im Baum, mit
// unterschiedlichem Verhalten — die Fassung in der Sprecherliste hatte gar
// keinen Stunden-Zweig und zeigte 97 Minuten Redezeit als "97 min 12s" an.
// Ebenso gab es zwei Sätze Stufen-Beschriftungen, die gleichzeitig sichtbar
// waren (Banner oben, Warteschlange links) und verschieden lauteten.

/** Dauer in deutscher Schreibweise.
 *
 * `sekunden: true` hängt den Sekundenanteil an — für Detailansichten, in
 * denen es auf die genaue Länge ankommt. Listen bleiben ohne.
 */
export function fmtDuration(
  ms: number,
  opts: { sekunden?: boolean } = {},
): string {
  const gesamt = Math.floor((ms || 0) / 1000);
  if (gesamt < 60) return `${gesamt}s`;
  const minuten = Math.floor(gesamt / 60);
  if (minuten < 60) {
    return opts.sekunden
      ? `${minuten} min ${String(gesamt % 60).padStart(2, "0")}s`
      : `${minuten} min`;
  }
  return `${Math.floor(minuten / 60)} h ${minuten % 60} min`;
}

/** Datum und Uhrzeit (Detailansichten). */
export function fmtDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("de-AT", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** Nur Tag und Monat (Listen). */
export function fmtDateShort(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("de-AT", {
      day: "2-digit",
      month: "short",
    });
  } catch {
    return "";
  }
}

/** Beschriftung der fünf Pipeline-Stufen — eine Fassung für die ganze App. */
export const STAGE_LABEL: Record<string, string> = {
  decode: "Audio lesen",
  transcribe: "Transkribieren",
  diarize: "Sprecher erkennen",
  merge: "Zusammenführen",
  persist: "Speichern",
};
