# Varel Vergunningsradar

**Tool:** https://davidvdh1977.github.io/varel-vergunningsradar/

Publieke tool met nieuwe omgevingsvergunningsaanvragen in Vlaanderen, aangevuld met KBO-gegevens van de aanvragende bedrijven. De tool vraagt geen login. Je kunt de link delen, of `index.html` als los bestand doorsturen: de tool haalt het databestand dan zelf op.

## Hoe het werkt

| Wat | Waar | Wanneer |
|---|---|---|
| Aanvragers ophalen uit het Omgevingsloket (`lu:lu_omv_gd_v2`, `lu:lu_omv_iioa_v2`, laatste 120 dagen). KBO Open Data downloaden en per ondernemingsnummer de zetel, de vestigingen, de NACE-activiteiten, en telefoon, e-mail en website opzoeken (`job/kbo_job.py`). Publiceren op de branch `gh-pages` (`job/publish.sh`). | Geplande taak in Claude Code (cloud). Daar staat de KBO-login; die komt nooit op GitHub. | Elke dag om 6u30 (Brussel) |
| Bedrijven zonder telefoonnummer: het nummer zoeken op de bedrijfswebsite (`kbo_job.py --enrich`). | GitHub Actions (`.github/workflows/kbo.yml`). Er zijn geen secrets nodig. | Meteen na elke nieuwe publicatie |
| Tool en `kbo-data.json` online zetten | GitHub Pages (branch `gh-pages`) | Automatisch |

In de tool gaat een zelf ingevuld telefoonnummer, e-mailadres of website altijd voor op de automatische waarde. Wat gebruikers zelf invullen (contactgegevens, notities, opvolging), blijft in hun eigen browser.

## Goed om te weten

- **Privacy.** Het databestand is publiek. Het bevat alleen KBO Open Data en gegevens van bedrijfswebsites. Eenmanszaken (natuurlijke personen) worden weggelaten.
- **KBO-stand.** De FOD Economie publiceert het KBO-bestand van de dag rond 9u20. Om 6u30 gebruikt de job dus de stand van de vorige dag.
- **Websitezoektocht.** Een site zonder nummer wordt pas na 30 dagen opnieuw doorzocht. Een site die onbereikbaar was, wordt de volgende dag opnieuw geprobeerd.
- **Tool aanpassen.** Wijzig `index.html` op `main`. De volgende ochtendrun zet de nieuwe versie online.

## Beheer

- **Geplande taak:** "Varel KBO-job" in Claude (claude.ai → Code → Scheduled tasks). Draait elke dag om 6u30 Brusselse tijd, met een paar minuten spreiding.
- **Vaste sessie:** de taak start telkens in de sessie **"Varel KBO-job (dagelijks)"**. Die sessie heeft deze repo als bron en heeft de KBO-login in haar omgeving (`KBO_USER`, `KBO_PASS`). **Archiveer of verwijder die sessie niet**, anders kan de taak niet meer publiceren. Gebeurt dat toch, maak dan een nieuwe sessie met deze repo als bron, geef ze de opdracht uit stap 1 tot 5 hieronder en koppel de geplande taak aan die nieuwe sessie.
- **Opdracht van de dagelijkse run:**
  1. `main` bijwerken.
  2. Het vorige `kbo-data.json` ophalen van `gh-pages`.
  3. `WEB_LOOKUPS=0 python3 job/kbo_job.py --out /tmp/varel-out` draaien.
  4. `job/publish.sh /tmp/varel-out` draaien.
  5. Eindigen met één regel resultaat.
- **Controle:** onder de filters toont de tool de KBO-stand en het tijdstip van de laatste update. Staat daar "meer dan 3 dagen oud", dan is de dagelijkse run mislukt.
- **Handmatig draaien:** start de geplande taak met "Run now", of geef de vaste sessie de opdracht opnieuw.
- **Toolversie:** staat in `index.html` (`TOOL_VERSION`) en is zichtbaar onder de filters. Verhoog ze bij elke wijziging.
- **Archief:** `archief/varel-vergunningsradar-origineel.html` is de versie van vóór de KBO-koppeling.
