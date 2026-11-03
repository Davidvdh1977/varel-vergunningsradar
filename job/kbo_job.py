#!/usr/bin/env python3
"""
Varel Vergunningsradar - dagelijkse KBO-verrijking.

1. Haalt de recente aanvragen op uit de Mercator-lagen lu:lu_omv_gd_v2 en
   lu:lu_omv_iioa_v2 en verzamelt de ondernemingsnummers van de aanvragers en
   exploitanten (zelfde regels als de tool).
2. Logt in op KBO Open Data (KBO_USER / KBO_PASS), downloadt het nieuwste
   volledige bestand en haalt per onderneming de zetel, vestigingen,
   NACE-activiteiten, telefoon, e-mail en website op.
3. Ontbreekt het telefoonnummer, dan zoekt het script het op de bedrijfswebsite
   (website uit de KBO, anders afgeleid uit het e-maildomein).
4. Schrijft kbo-data.json (en kbo-data.js) voor de tool.

Enkel de standaardbibliotheek van Python 3.9+.

Gebruik:
  python3 kbo_job.py --out out/            # alles
  python3 kbo_job.py --zip bestaand.zip    # bestaande download hergebruiken
Omgeving: KBO_USER, KBO_PASS (verplicht), DAYS (standaard 120),
          KEEP_DAYS (standaard 365), WEB_LOOKUPS (max. nieuwe websites per run, standaard 600)
"""
import argparse, concurrent.futures as cf, csv, datetime as dt, gzip, html, http.cookiejar, io, json, os, re
import sys, tempfile, time, urllib.parse, urllib.request, zipfile

WFS = "https://www.mercator.vlaanderen.be/raadpleegdienstenmercatorpubliek/wfs"
LAYERS = ["lu:lu_omv_iioa_v2", "lu:lu_omv_gd_v2"]
KBO = "https://kbopub.economie.fgov.be/kbo-open-data"
UA = "Mozilla/5.0 (compatible; VarelVergunningsradar/1.0)"
MAX_EST = 30          # vestigingen per onderneming in het databestand
WEB_RECHECK_DAYS = 30  # website opnieuw doorzoeken na zoveel dagen

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

# ---------------------------------------------------------------- HTTP
def opener_with_cookies():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    return op

def get(url, op=None, data=None, timeout=60, tries=4):
    op = op or urllib.request.build_opener()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with op.open(req, timeout=timeout) as r:
                return r.read(), r.geturl()
        except Exception as e:
            last = e
            time.sleep(2 ** (i + 1))
    raise last

# ---------------------------------------------------------------- 1. ondernemingsnummers uit het Omgevingsloket
APP_RE = re.compile(r"^(.*?)\s*\(\s*(?:BE)?\s*([01][\d.\s]{9,13})\s*\)\s*$", re.I)

def parse_applicants(s):
    out = []
    for p in re.split(r"\s*;\s*", s or ""):
        m = APP_RE.match(p.strip())
        if m:
            k = re.sub(r"\D", "", m.group(2))
            if len(k) == 10:
                out.append((k, m.group(1).strip()))
    return out

def wfs_kbos(days):
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    found = {}
    for layer in LAYERS:
        props = "projectnummer,aanvrager,datum_indiening" + (",exploitant" if "iioa" in layer else "")
        start, page = 0, 1000
        while True:
            q = urllib.parse.urlencode({
                "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": layer,
                "outputFormat": "application/json", "propertyName": props, "sortBy": "datum_indiening DESC",
                "CQL_FILTER": f"datum_indiening >= '{since}'", "count": page, "startIndex": start})
            body, _ = get(f"{WFS}?{q}", timeout=120)
            feats = json.loads(body).get("features", [])
            for f in feats:
                p = f.get("properties") or {}
                for k, name in parse_applicants(p.get("aanvrager")) + parse_applicants(p.get("exploitant")):
                    e = found.setdefault(k, {"naam": name, "dossiers": set(), "laatsteDossier": ""})
                    if p.get("projectnummer"): e["dossiers"].add(p["projectnummer"])
                    d = (p.get("datum_indiening") or "")[:10]
                    if d > e["laatsteDossier"]: e["laatsteDossier"] = d
            log(f"  {layer}: {start + len(feats)} dossiers")
            if len(feats) < page: break
            start += page
    return found

# ---------------------------------------------------------------- 2. KBO Open Data
def kbo_login():
    user, pw = os.environ.get("KBO_USER"), os.environ.get("KBO_PASS")
    if not user or not pw:
        sys.exit("KBO_USER en KBO_PASS moeten ingesteld zijn.")
    op = opener_with_cookies()
    get(f"{KBO}/login", op)
    data = urllib.parse.urlencode({"j_username": user, "j_password": pw}).encode()
    body, url = get(f"{KBO}/static/j_spring_security_check", op, data=data)
    if "login" in url or b"j_password" in body:
        sys.exit("KBO-login mislukt: controleer KBO_USER / KBO_PASS.")
    log("KBO-login gelukt")
    return op

def kbo_latest_full(op):
    body, _ = get(f"{KBO}/affiliation/xml/?files", op)
    files = sorted(set(re.findall(r'files/(KboOpenData_\d+_\d{4}_\d{2}_\d{2}_Full\.zip)', body.decode("utf-8", "replace"))))
    if not files:
        sys.exit("Geen KBO-bestanden gevonden (is het abonnement nog actief?).")
    return files[-1]

def kbo_download(op, name, dest):
    url = f"{KBO}/affiliation/xml/files/{name}"
    for i in range(4):
        try:
            with op.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r, open(dest, "wb") as f:
                n = 0
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b); n += len(b)
            if zipfile.is_zipfile(dest):
                log(f"Gedownload: {name} ({n/1e6:.0f} MB)")
                return
        except Exception as e:
            log("Download mislukt, nieuwe poging:", e)
        time.sleep(2 ** (i + 2))
    sys.exit("KBO-download mislukt.")

def rows(z, name, keep=None):
    """CSV-rijen; met keep wordt eerst snel op het eerste veld gefilterd."""
    with z.open(name) as fh:
        t = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
        next(t)
        for line in t:
            if keep is not None:
                first = line[:line.find(",")].strip('"')
                if first not in keep: continue
            yield next(csv.reader([line]))

def dotted(k):  # 0408053660 -> 0408.053.660
    return f"{k[:4]}.{k[4:7]}.{k[7:]}"

def fmt_addr(r):
    # EntityNumber,TypeOfAddress,CountryNL,CountryFR,Zipcode,MunicipalityNL,MunicipalityFR,StreetNL,StreetFR,HouseNumber,Box,ExtraAddressInfo,DateStrikingOff
    if r[12]: return None
    straat = r[7] or r[8]
    nr = r[9] + (f" bus {r[10]}" if r[10] else "")
    gem = r[5] or r[6]
    land = r[2] if r[2] and r[2].lower() != "belgië" else ""
    s = " ".join(x for x in [straat, nr] if x).strip()
    s2 = " ".join(x for x in [r[4], gem] if x).strip()
    return ", ".join(x for x in [s, s2, land] if x)

def lang_rank(l):  # NL eerst
    return {"2": 0, "0": 1, "1": 2, "4": 3, "3": 4}.get(l, 9)

def kbo_extract(zip_path, kbos):
    z = zipfile.ZipFile(zip_path)
    meta = {r[0]: r[1] for r in rows(z, "meta.csv")}
    codes = {}
    for cat, code, lang, desc in rows(z, "code.csv"):
        if lang == "NL" or (cat, code) not in codes:
            codes[(cat, code)] = desc
    ents = {dotted(k): {} for k in kbos}
    keep = set(ents)

    for r in rows(z, "enterprise.csv", keep):
        e = ents[r[0]]
        e["status"] = codes.get(("Status", r[1]), r[1])
        e["situatie"] = codes.get(("JuridicalSituation", r[2]), r[2])
        e["_type"] = r[3]
        e["rechtsvorm"] = codes.get(("JuridicalForm", r[4]), r[4]) if r[4] else ""
        e["start"] = r[6]
    log(f"  enterprise.csv: {sum(1 for e in ents.values() if 'status' in e)}/{len(ents)} gevonden")

    est_of = {}
    for r in rows(z, "establishment.csv"):
        if r[2] in keep:
            est_of[r[0]] = r[2]
            ents[r[2]].setdefault("_est", {})[r[0]] = {"nr": r[0], "start": r[1]}
    keep_all = keep | set(est_of)
    log(f"  establishment.csv: {len(est_of)} vestigingen")

    def target(num):
        if num in ents: return ents[num], None
        ent = ents[est_of[num]]
        return ent, ent["_est"][num]

    names = {}
    for num, lang, typ, den in rows(z, "denomination.csv", keep_all):
        names.setdefault(num, []).append((typ, lang_rank(lang), den))
    for num, lst in names.items():
        ent, est = target(num)
        lst.sort()
        if est is not None:
            est["naam"] = lst[0][2]
        else:
            off = [d for t, _, d in lst if t == "001"]
            ent["naam"] = off[0] if off else lst[0][2]
            ent["afkorting"] = next((d for t, _, d in lst if t == "002"), "")
            ent["handelsnamen"] = list(dict.fromkeys(d for t, _, d in lst if t == "003"))[:5]

    for r in rows(z, "address.csv", keep_all):
        a = fmt_addr(r)
        if not a: continue
        ent, est = target(r[0])
        if est is not None: est["adres"] = a
        elif r[1] == "REGO" or "zetel" not in ent: ent["zetel"] = a

    for num, _, typ, value in rows(z, "contact.csv", keep_all):
        ent, est = target(num)
        key = {"TEL": "tel", "EMAIL": "mail", "WEB": "web"}.get(typ)
        if not key: continue
        tgt = est if est is not None else ent
        value = value.strip()
        if key == "tel": value = norm_phone(value) or value
        if key == "web": value = re.sub(r"^https?://", "", value, flags=re.I).rstrip("/")
        tgt.setdefault(key, value)

    acts = {}
    for num, group, ver, code, cls in rows(z, "activity.csv", keep_all):
        acts.setdefault(num, []).append((ver, code, cls))
    order = {"MAIN": 0, "SECO": 1, "ANCI": 2}
    nace_desc = {}
    def nace_list(lst):
        ver = max(v for v, _, _ in lst)
        seen, out = set(), []
        for v, code, cls in sorted(lst, key=lambda x: (order.get(x[2], 9), x[1])):
            if v != ver or code in seen: continue
            seen.add(code)
            nace_desc.setdefault(code, codes.get((f"Nace{ver}", code), ""))
            out.append([code, cls])
        return out
    for num, lst in acts.items():
        ent, est = target(num)
        if est is not None: est["nace"] = [c for c, _ in nace_list(lst)][:5]
        else: ent["nace"] = nace_list(lst)[:15]

    out, skipped_np = {}, []
    for num, e in ents.items():
        if "status" not in e: continue
        if e.get("_type") == "1":  # natuurlijk persoon (eenmanszaak): persoonsgegevens, niet publiceren
            skipped_np.append(num); continue
        e.pop("_type", None)
        ests = sorted(e.pop("_est", {}).values(), key=lambda x: x.get("start", ""), reverse=True)
        e["aantalVestigingen"] = len(ests)
        e["vestigingen"] = ests[:MAX_EST]
        # contact van de onderneming, anders van een vestiging
        e["bron"] = {}
        for key in ("tel", "mail", "web"):
            if e.get(key):
                e["bron"][key] = "KBO"
            else:
                v = next((x[key] for x in ests if x.get(key)), None)
                if v:
                    e[key] = v; e["bron"][key] = "KBO (vestiging)"
        out[num.replace(".", "")] = e
    log(f"  {len(skipped_np)} eenmanszaken (natuurlijke personen) weggelaten")
    return out, meta, nace_desc

# ---------------------------------------------------------------- 3. telefoon op de website
GENERIC_MAIL = re.compile(r"@(gmail|googlemail|hotmail|outlook|live|msn|yahoo|icloud|me|mac|telenet|skynet|proximus|"
                          r"belgacom|scarlet|pandora|gmx|web|online|orange|voo|edpnet|base|mail|protonmail|proton)\.", re.I)
PHONE = re.compile(r"(?<![\d+])(?:\+|00)32[\s.\-/]*\(?0?\)?[\s.\-/]*[1-9](?:[\s.\-/]*\d){7,8}(?!\d)|(?<![\d+])0[1-9](?:[\s.\-/]*\d){7,8}(?!\d)")
VAT = re.compile(r"(?:\b(?:BE|BTW|VAT|TVA|KBO|BCE|RPR|RPM|ondernemings\w*|enterprise)\W{0,6})[01]\d{3}[.\s]?\d{3}[.\s]?\d{3}|\b[01]\d{3}\.\d{3}\.\d{3}\b", re.I)
TEL_HREF = re.compile(r'href=["\']tel:([^"\']+)["\']', re.I)
CONTACT_LINK = re.compile(r'href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', re.I | re.S)

def norm_phone(raw):
    d = re.sub(r"[^\d+]", "", raw)
    if d.startswith("+32"): d = "0" + d[3:]
    elif d.startswith("0032"): d = "0" + d[4:]
    if d.startswith("00"): d = d[1:]
    if not re.fullmatch(r"0[1-9]\d{7}|04\d{8}", d): return None  # 9 cijfers vast, 10 cijfers enkel gsm (04..)
    if d.startswith("0800") or d.startswith("090") or d.startswith("070"): return None
    if len(d) == 10:  # gsm 04xx
        return f"{d[:4]} {d[4:6]} {d[6:8]} {d[8:]}"
    if d[1] in "2349":  # zones met 1 cijfer
        return f"{d[:2]} {d[2:5]} {d[5:7]} {d[7:]}"
    return f"{d[:3]} {d[3:5]} {d[5:7]} {d[7:]}"

def site_url(e):
    w = (e.get("web") or "").strip()
    if w:
        return w if re.match(r"https?://", w, re.I) else "https://" + w.lstrip("/")
    m = e.get("mail") or ""
    if "@" in m and not GENERIC_MAIL.search(m):
        return "https://" + m.split("@", 1)[1].strip().lower()
    return None

def fetch_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "nl-BE,nl"})
    with urllib.request.urlopen(req, timeout=12) as r:
        if "html" not in (r.headers.get("Content-Type") or "html"): return "", r.geturl()
        b = r.read(1_500_000)
        if r.headers.get("Content-Encoding") == "gzip": b = gzip.decompress(b)
        cs = r.headers.get_content_charset() or "utf-8"
        return b.decode(cs, "replace"), r.geturl()

def phones_in(page):
    found = [norm_phone(x) for x in TEL_HREF.findall(page)]
    text = html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I))
    text = re.sub(r"<[^>]+>", " ", text)
    text = VAT.sub(" ", text)  # BTW-/ondernemingsnummers lijken op gsm-nummers
    nums = [norm_phone(x) for x in PHONE.findall(text)]
    found += [n for n in nums if n and not n.startswith("04")] + [n for n in nums if n and n.startswith("04")]
    return [p for p in dict.fromkeys(found) if p]

def website_phone(url):
    tried = []
    try:
        page, final = fetch_page(url)
    except Exception:
        if url.startswith("https://"):
            try: page, final = fetch_page("http://" + url[8:])
            except Exception as e: return None, None, f"site onbereikbaar ({type(e).__name__})"
        else:
            return None, None, "site onbereikbaar"
    tried.append(final)
    p = phones_in(page)
    # contactpagina: vaak staat het nummer daar (of het algemene nummer in de footer van de homepage)
    links = []
    for href, label in CONTACT_LINK.findall(page):
        lab = re.sub(r"<[^>]+>", " ", label)
        if re.search(r"contact|kontakt|over[- ]?ons|about|bereik|locatie|route", href + " " + lab, re.I):
            u = urllib.parse.urljoin(final, href.strip())
            if urllib.parse.urlparse(u).netloc == urllib.parse.urlparse(final).netloc and u not in links:
                links.append(u)
    for u in links[:2]:
        if p: break
        try:
            pg, f2 = fetch_page(u); tried.append(f2); p = phones_in(pg)
        except Exception:
            pass
    if p: return p[0], tried[-1], None
    return None, final, "geen nummer gevonden op de site"

def enrich_websites(data, prev, budget):
    today = dt.date.today()
    todo = []
    for k, e in data.items():
        if e.get("tel"): continue
        url = site_url(e)
        if not url: continue
        old = (prev.get(k) or {}).get("webzoektocht") or {}
        try: age = (today - dt.date.fromisoformat(old.get("datum", "2000-01-01"))).days
        except ValueError: age = 999
        stale_tel = old.get("tel") and norm_phone(old["tel"]) != old["tel"]  # strengere controle sinds de vorige run
        if old.get("url") == url and age < WEB_RECHECK_DAYS and not stale_tel and not (old.get("fout") or "").startswith("site onbereikbaar"):
            e["webzoektocht"] = old
            if old.get("tel"): e["tel"] = old["tel"]; e["bron"]["tel"] = "website"
            continue
        todo.append((k, url))
    log(f"Telefoon zoeken op {min(len(todo), budget)} van {len(todo)} websites")
    todo = todo[:budget]
    def job(t):
        k, url = t
        tel, page, err = website_phone(url)
        return k, url, tel, page, err
    hits = 0
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for k, url, tel, page, err in ex.map(job, todo):
            e = data[k]
            e["webzoektocht"] = {"url": url, "datum": today.isoformat(), "tel": tel, "pagina": page, "fout": err}
            if tel:
                hits += 1; e["tel"] = tel; e["bron"]["tel"] = "website"
                if not e.get("web"): e["web"] = url; e["bron"]["web"] = "e-maildomein"
    log(f"  telefoon gevonden op {hits} websites")

def write_doc(doc, out):
    doc["metTelefoon"] = sum(1 for e in doc["bedrijven"].values() if e.get("tel"))
    js = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out, "kbo-data.json"), "w", encoding="utf-8") as f: f.write(js)
    with open(os.path.join(out, "kbo-data.js"), "w", encoding="utf-8") as f: f.write("window.VAREL_KBO_DATA=" + js + ";\n")
    return js

def enrich_only(path, budget):
    doc = json.load(open(path, encoding="utf-8"))
    data = doc["bedrijven"]
    prev = json.loads(json.dumps(data))
    enrich_websites(data, prev, budget)
    doc["websitesDoorzocht"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    write_doc(doc, os.path.dirname(os.path.abspath(path)))
    log(f"Klaar: {doc['metTelefoon']} van {len(data)} bedrijven met telefoon")

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--zip", help="bestaande KBO Full-zip gebruiken")
    ap.add_argument("--prev", help="vorig kbo-data.json (standaard <out>/kbo-data.json)")
    ap.add_argument("--enrich", help="enkel telefoon zoeken op websites in dit bestaande kbo-data.json")
    a = ap.parse_args()
    if a.enrich:
        return enrich_only(a.enrich, int(os.environ.get("WEB_LOOKUPS", 600)))
    days = int(os.environ.get("DAYS", 120)); keep_days = int(os.environ.get("KEEP_DAYS", 365))
    budget = int(os.environ.get("WEB_LOOKUPS", 600))
    os.makedirs(a.out, exist_ok=True)
    prev_path = a.prev or os.path.join(a.out, "kbo-data.json")
    prev = {}
    if os.path.exists(prev_path):
        try: prev = json.load(open(prev_path, encoding="utf-8")).get("bedrijven", {})
        except Exception: pass

    log(f"Aanvragers ophalen (laatste {days} dagen)")
    found = wfs_kbos(days)
    cutoff = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
    for k, e in prev.items():  # oudere aanvragers blijven een jaar in het bestand
        if k not in found and (e.get("laatsteDossier") or "") >= cutoff:
            found[k] = {"naam": e.get("naam", ""), "dossiers": set(e.get("dossiers", [])), "laatsteDossier": e.get("laatsteDossier", "")}
    log(f"{len(found)} ondernemingsnummers")

    tmp = None
    if a.zip:
        zip_path, zip_name = a.zip, os.path.basename(a.zip)
    else:
        op = kbo_login()
        zip_name = kbo_latest_full(op)
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False); tmp.close()
        zip_path = tmp.name
        kbo_download(op, zip_name, zip_path)

    log("KBO-bestand verwerken")
    data, meta, nace_desc = kbo_extract(zip_path, found.keys())
    if tmp: os.unlink(tmp.name)
    for k, e in data.items():
        f = found[k]
        e["dossiers"] = sorted(f["dossiers"])[-20:]
        e["laatsteDossier"] = f["laatsteDossier"]
    enrich_websites(data, prev, budget)

    doc = {
        "tool": "varel-kbo-data", "versie": 1,
        "gegenereerd": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kboBestand": zip_name, "kboStand": meta.get("SnapshotDate", ""),
        "periodeDagen": days, "aantal": len(data),
        "kboStandTijd": meta.get("ExtractTimestamp", ""),
        "metTelefoon": sum(1 for e in data.values() if e.get("tel")),
        "nace": nace_desc,
        "bedrijven": data,
    }
    js = write_doc(doc, a.out)
    missing = len(found) - len(data)
    log(f"Klaar: {len(data)} bedrijven, {doc['metTelefoon']} met telefoon, {missing} niet in KBO (stopgezet of buitenlands), "
        f"{len(js)/1e6:.1f} MB")

if __name__ == "__main__":
    main()
