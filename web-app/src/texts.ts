// All user-facing text of the web app, in Dutch (the language of the participants and
// the client). Code and identifiers stay in English; keep new UI text in this file.

export const texts = {
  appTitle: 'Smart Energie Stolp',
  pageTitle: 'Beheer',

  import: {
    title: 'Meterdata importeren',
    intro: 'Kies de CSV-export van de netbeheerder. De import draait op de achtergrond.',
    chooseFile: 'CSV-bestand',
    submit: 'Importeren',
    uploading: 'Bestand wordt verstuurd…',
    processing: 'Bezig met importeren…',
    succeeded: (rows: number, newMeters: number) =>
      `Import geslaagd: ${rows.toLocaleString('nl-NL')} rijen opgeslagen, ${newMeters} nieuwe meters.`,
    failed: (message: string | null) => `Import mislukt${message ? `: ${message}` : '.'}`,
    duplicate: 'Dit bestand is al eerder geïmporteerd.',
  },

  dashboard: {
    title: 'Gelijktijdigheid',
    explanation:
      'Het deel van de teruggeleverde zonnestroom dat in hetzelfde kwartier binnen de Stolp is gebruikt.',
    from: 'Van',
    to: 'Tot en met',
    invalidPeriod: 'De einddatum moet op of na de begindatum liggen.',
    loading: 'Gegevens laden…',
    empty: 'Geen gegevens in deze periode. Importeer meterdata of kies een andere periode.',
    heroLabel: 'Gelijktijdigheid over de periode',
    sharedLabel: 'Lokaal gedeeld',
    toGridLabel: 'Teruggeleverd',
    fromGridLabel: 'Afgenomen',
    chartTitle: 'Gelijktijdigheid per dag',
    chartLabel: (from: string, to: string) => `Staafdiagram van de gelijktijdigheid per dag, ${from} tot en met ${to}`,
    noFeedIn: 'geen teruglevering',
    showTable: 'Toon als tabel',
    columns: {
      day: 'Dag',
      simultaneity: 'Gelijktijdigheid',
      shared: 'Gedeeld (kWh)',
      toGrid: 'Teruggeleverd (kWh)',
      fromGrid: 'Afgenomen (kWh)',
    },
  },

  history: {
    title: 'Laatste imports',
    empty: 'Nog geen imports.',
    columns: { started: 'Gestart', file: 'Bestand', status: 'Status', rows: 'Rijen', period: 'Periode' },
    status: { running: 'bezig', succeeded: 'geslaagd', failed: 'mislukt' },
  },

  errors: {
    unreachable: 'De Frontend API is niet bereikbaar. Draait de dev container?',
    noDemoAccount: 'Geen demo-account ingesteld: vul VITE_DEMO_EMAIL en VITE_DEMO_PASSWORD in .env.local in.',
    loginFailed: 'Inloggen met het demo-account is mislukt. Controleer VITE_DEMO_EMAIL en VITE_DEMO_PASSWORD.',
    generic: (status: number) => `Er ging iets mis (HTTP ${status}).`,
  },
} as const
