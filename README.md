# Varel Vergunningsradar

Publieke tool: nieuwe omgevingsvergunningsaanvragen in Vlaanderen, aangevuld met KBO-gegevens van de aanvragende bedrijven.

- `index.html`: de tool (één bestand, zonder login).
- `job/kbo_job.py`: de dagelijkse job. Die haalt de aanvragers van de laatste 120 dagen op uit het Omgevingsloket (`lu:lu_omv_gd_v2`, `lu:lu_omv_iioa_v2`). Daarna downloadt hij het volledige KBO Open Data-bestand en zet hij per ondernemingsnummer de zetel, de vestigingen, de NACE-activiteiten, en telefoon, e-mail en website op een rij. Ontbreekt het telefoonnummer, dan zoekt hij het op de bedrijfswebsite.
- `.github/workflows/kbo.yml`: draait de job elke dag om 6u30 (Brussel) en publiceert tool en databestand op GitHub Pages.

## Eenmalig instellen (gratis GitHub-account volstaat)

1. Maak op github.com een **publieke** repository aan, bv. `varel-vergunningsradar`.
2. Upload `index.html`, `README.md` en de map `job` met **Add file → Upload files**. Mappen die met een punt beginnen, zoals `.github`, verbergt je computer vaak. Maak de workflow daarom aan met **Add file → Create new file**: typ als naam `.github/workflows/kbo.yml` en plak de inhoud van dat bestand.
3. **Settings → Secrets and variables → Actions → New repository secret**: voeg `KBO_USER` en `KBO_PASS` toe (je login van KBO Open Data). Secrets zijn versleuteld. Niemand ziet ze: bezoekers niet, forks niet en gebruikers van de tool niet.
4. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
5. **Actions → KBO-gegevens bijwerken → Run workflow**. Na ongeveer 5 minuten staat de tool op `https://<gebruikersnaam>.github.io/varel-vergunningsradar/`.

Deel daarna die link. Je kunt `index.html` ook als los bestand doorsturen: de tool haalt het databestand dan zelf op bij GitHub Pages.

## Goed om te weten

- **Privacy.** Het databestand is publiek. Het bevat alleen KBO Open Data en contactgegevens van bedrijfswebsites. Eenmanszaken (natuurlijke personen) worden weggelaten. Wat gebruikers zelf invullen (telefoon, contactpersoon, notities), blijft in hun eigen browser.
- **Voorrang.** In de tool gaat een zelf ingevuld telefoonnummer, e-mailadres of website altijd voor op de automatische waarde. Maak het veld leeg om terug te gaan naar de KBO- of websitewaarde.
- **Actualiteit.** De FOD Economie publiceert het KBO-bestand van de dag rond 9u20. Om 6u30 gebruikt de job dus de stand van de vorige dag.
- **Planning.** GitHub start geplande runs soms 10 tot 30 minuten later dan gepland.
- **Geen activiteit.** Na 60 dagen zonder activiteit in de repo kan GitHub de planning uitschakelen. Je krijgt dan een e-mail, en met één klik op "Enable workflow" staat ze weer aan.
- **Websitezoektocht.** Elke run doorzoekt maximaal 600 nieuwe websites (`WEB_LOOKUPS`). Een site zonder nummer wordt pas na 30 dagen opnieuw doorzocht.
