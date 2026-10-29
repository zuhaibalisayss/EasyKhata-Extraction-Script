"""Converted from a Kaggle Jupyter notebook.
EasyKhata ledger PDF data extraction.

Note: This notebook contained two alternative extraction scripts; both are preserved below.
Run one section at a time and configure its PDF path/settings before use.
"""
from __future__ import annotations

# --- Markdown cell 1 ---
# <a href="https://www.kaggle.com/code/zuhaibalisays/easykhata-report-data-extraction?scriptVersionId=359622322" target="_blank"><img align="left" alt="Kaggle" title="Open in Kaggle" src="https://kaggle.com/static/images/open-in-kaggle.svg"></a>

# ==================== Code cell 2 ====================
import subprocess, sys, os, re, glob, bisect, unicodedata
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"])
import pdfplumber
import pandas as pd

# ------------------------- settings -------------------------
PDF = None                       # None = auto-find the first PDF under /kaggle/input
OUT = "/kaggle/working/extracted_ledger.csv"
NAME_TAFSEEL_X = None            # manual x for the Name|Tafseel border (normally auto-detected)
DASH_AS_ZERO = False             # True -> write 0 instead of "-" in Debit/Credit
LINE_TOL = 4                     # words closer than this (px) vertically = same text line
# ------------------------------------------------------------

if PDF is None:
    found = sorted(glob.glob("/kaggle/input/**/*.pdf", recursive=True))
    assert found, "No PDF under /kaggle/input - set PDF = '/kaggle/input/.../file.pdf'"
    PDF = found[0]
print("PDF:", PDF)

ARABIC  = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
LTR_RUN = re.compile(r'[A-Za-z0-9][A-Za-z0-9.,:/+\-]*')
MARKS   = re.compile(r'[\u200b-\u200f\u202a-\u202e\u2066-\u2069]')
DAY = re.compile(r'^\d{1,2}(st|nd|rd|th)$')
MON = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),?$')
YR  = re.compile(r'^\d{2}$')
NUM = re.compile(r'^([-\u2212\u2013]|\d[\d,]*(\.\d+)?)$')
DASH = re.compile(r'^[-\u2212\u2013]$')
AD_WORDS = {'Sadiq', 'uthaein', 'ghata,', 'Abhi', 'download', 'karein', 'Khata', 'DOWNLOAD', 'Easy'}


def prep_chars(page):
    """Normalise Urdu glyphs. Multi-letter glyphs (e.g. lam-alef) are flipped here so the
    later whole-line reversal puts them back in the right order."""
    for c in page.chars:
        t = c['text']
        if ARABIC.search(t) or len(t) > 1:
            n = unicodedata.normalize('NFKC', t)
            if len(n) > 1 and ARABIC.search(n):
                n = n[::-1]
            c['text'] = n


def fix_line(s):
    """Visual (left-to-right) line -> logical Urdu; English/digit runs stay readable."""
    s = MARKS.sub('', s)
    if not ARABIC.search(s):
        return s.strip()
    s = s[::-1]
    return LTR_RUN.sub(lambda m: m.group(0)[::-1], s).strip()


def cell_text(ws):
    if not ws:
        return ''
    ws = sorted(ws, key=lambda w: w['y'])
    lines, cur = [], [ws[0]]
    for w in ws[1:]:
        if w['y'] - cur[-1]['y'] <= LINE_TOL:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
    lines.append(cur)
    out = []
    for ln in lines:                                   # top -> bottom, each line fixed on its own
        out.append(fix_line(" ".join(w['text'] for w in sorted(ln, key=lambda w: w['x0']))))
    return " ".join(x for x in out if x)


def is_ad_char(o):
    """Advertisement text ('Na uthaein ghata, Abhi download karein...') uses grey Roboto 10.5pt,
    ledger rows use black RobotoStatic 12pt. On some pages the ad overlaps the last rows."""
    fn = o.get('fontname') or ''
    return abs((o.get('size') or 0) - 10.5) < 0.3 and 'Static' not in fn and 'Roboto' in fn


def strip_footer(page):
    """Remove (at CHARACTER level, before words are built) the ad text and the 'Page X of 99'
    footer. The footer overlaps the last row's amounts (its '99' even touches the Credit '-')."""
    foot = None
    cs = sorted(page.chars, key=lambda c: (round(c['top']), c['x0']))
    for i in range(len(cs) - 3):
        if ''.join(c['text'] for c in cs[i:i + 4]) == 'Page':
            foot = cs[i]
            break

    def keep(o):
        if o.get('object_type') != 'char':
            return True
        if is_ad_char(o):
            return False
        if foot is not None and o['x0'] >= foot['x0'] - 1 and abs(o['top'] - foot['top']) < 0.3 \
                and abs((o['bottom'] - o['top']) - (foot['bottom'] - foot['top'])) < 0.3:
            return False
        return True
    return page.filter(keep)


def read_page(page, pno):
    page = strip_footer(page)
    prep_chars(page)
    ws = page.extract_words(x_tolerance=1.0)           # Urdu words have no space glyph, only a ~2.6px gap
    for i, w in enumerate(ws):
        w['y'] = (w['top'] + w['bottom']) / 2
        w['i'] = i

    # 1) drop everything above/at the header row (titles, totals, "Report Generated on ...")
    hdr = [w for w in ws if w['text'] == 'Tafseel']
    hdr_x = hdr[0]['x0'] if hdr else None
    if hdr:
        band = [h['y'] for h in hdr]                   # also removes repeated headers mid-page
        top_y = min(band)
        ws = [w for w in ws if w['y'] > top_y + 1 and all(abs(w['y'] - b) > 6 for b in band)]
    gen = [w['y'] for w in ws if w['text'] == 'Generated']
    ws = [w for w in ws if all(abs(w['y'] - g) > 6 for g in gen)]

    # 2) cut the advertisement footer
    ad = [w for w in ws if w['text'] in ('uthaein', 'DOWNLOAD', 'karein')]
    if ad:
        ft = min(w['top'] for w in ad)
        sad = [w for w in ws if w['text'] == 'Sadiq' and 0 < ft - w['top'] < 80]
        if sad:
            ft = min(ft, min(w['top'] for w in sad))
        ws = [w for w in ws if w['top'] < ft - 1]
    ws = [w for w in ws if w['text'] not in AD_WORDS]

    # 3) each row starts with a date  ->  anchors
    anchors = []
    for w in ws:
        if DAY.match(w['text']):
            nxt = sorted((v for v in ws if abs(v['y'] - w['y']) <= 3 and v['x0'] > w['x0']),
                         key=lambda v: v['x0'])[:2]
            if len(nxt) == 2 and MON.match(nxt[0]['text']) and YR.match(nxt[1]['text']):
                anchors.append(dict(y=w['y'],
                                    date=f"{w['text']} {nxt[0]['text']} {nxt[1]['text']}",
                                    ids={w['i'], nxt[0]['i'], nxt[1]['i']}))
    if not anchors:
        return [], hdr_x
    anchors.sort(key=lambda a: a['y'])

    # 4) rows are vertically centred, so name/tafseel lines sit above AND below the date line.
    #    Between two dates, the biggest vertical gap is the row border.
    ys = sorted(w['y'] for w in ws)
    cuts = []
    for a, b in zip(anchors, anchors[1:]):
        seg = [y for y in ys if a['y'] - 1e-6 <= y <= b['y'] + 1e-6]
        k = max(range(len(seg) - 1), key=lambda j: seg[j + 1] - seg[j])
        cuts.append((seg[k] + seg[k + 1]) / 2)

    taken = set().union(*[a['ids'] for a in anchors])
    buckets = [[] for _ in anchors]
    for w in ws:
        if w['i'] not in taken:
            buckets[bisect.bisect(cuts, w['y'])].append(w)

    rows = []
    for a, b in zip(anchors, buckets):
        nums = sorted((w for w in b if NUM.match(w['text'])), key=lambda w: w['x0'])
        money = nums[-2:]                              # two right-most numbers/dashes = Debit, Credit
        rest = [w for w in b if all(w is not m for m in money)]
        rows.append(dict(page=pno, date=a['date'], money=[m['text'] for m in money], rest=rest))
    return rows, hdr_x


def find_boundary(rows, hint):
    iv = sorted((w['x0'], w['x1']) for r in rows for w in r['rest'])
    if not iv:
        return None
    merged = []
    for a, b in iv:
        if merged and a <= merged[-1][1] + 1.5:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    gaps = [(merged[i + 1][0] - merged[i][1], (merged[i][1] + merged[i + 1][0]) / 2)
            for i in range(len(merged) - 1)]
    gaps = [g for g in gaps if g[0] >= 4]
    if not gaps:
        return None
    if hint is not None:
        return min(gaps, key=lambda g: abs(g[1] - hint))[1]
    return max(gaps)[1]


# ------------------------- run -------------------------
all_rows, hint, exp_deb, exp_cred, empty_pages = [], None, None, None, []
with pdfplumber.open(PDF) as pdf:
    t1 = pdf.pages[0].extract_text() or ""
    tot = re.findall(r"Rs\.?\s*([\d,]+)", t1)           # "Rs 2,279,792 Rs 2,238,150 Rs 41,642"
    exp_deb = float(tot[0].replace(",", "")) if len(tot) >= 2 else None
    exp_cred = float(tot[1].replace(",", "")) if len(tot) >= 2 else None

    for pno, page in enumerate(pdf.pages, 1):
        rows, hx = read_page(page, pno)
        if hint is None and hx is not None:
            hint = hx
        if not rows:
            empty_pages.append(pno)
        all_rows.extend(rows)

XB = NAME_TAFSEEL_X if NAME_TAFSEEL_X is not None else find_boundary(all_rows, hint)
print(f"Name|Tafseel border x = {XB}   (header 'Tafseel' starts at x = {hint})")
if XB is None:
    XB = hint if hint is not None else 0

records, problems = [], []
for r in all_rows:
    nm = [w for w in r['rest'] if (w['x0'] + w['x1']) / 2 < XB]
    tf = [w for w in r['rest'] if (w['x0'] + w['x1']) / 2 >= XB]
    m = ['-' if DASH.match(t) else t.replace(',', '') for t in r['money']]
    if len(m) < 2:
        m = m + ['-'] * (2 - len(m))
        problems.append((r['page'], r['date'], "less than 2 amount tokens"))
    elif (m[0] == '-') == (m[1] == '-'):
        problems.append((r['page'], r['date'], f"Debit/Credit = {m}"))
    records.append([r['date'], cell_text(nm) or '-', cell_text(tf) or '-', m[0], m[1]])

df = pd.DataFrame(records, columns=["Date", "Name", "Tafseel", "Debit", "Credit"])


def val(t):
    return 0.0 if t == '-' else float(t)


sd = sum(val(x) for x in df["Debit"])
sc = sum(val(x) for x in df["Credit"])
if DASH_AS_ZERO:
    df[["Debit", "Credit"]] = df[["Debit", "Credit"]].replace('-', '0')

df.to_csv(OUT, index=False, encoding="utf-8-sig")

print(f"\nRows extracted : {len(df)}   (pages with no rows: {empty_pages})")
print(f"Debit  sum     : {sd:,.0f}   | PDF total: {exp_deb:,.0f}   -> {'OK' if exp_deb == sd else 'MISMATCH'}" if exp_deb else f"Debit sum: {sd:,.0f}")
print(f"Credit sum     : {sc:,.0f}   | PDF total: {exp_cred:,.0f}   -> {'OK' if exp_cred == sc else 'MISMATCH'}" if exp_cred else f"Credit sum: {sc:,.0f}")
if problems:
    print(f"\n{len(problems)} suspicious rows (first 10):")
    for p in problems[:10]:
        print("  page", p[0], "|", p[1], "|", p[2])
print("\nSaved:", OUT)
display(df.head(20))

# ==================== Code cell 3 ====================
import re, unicodedata, bisect
import pandas as pd
import pdfplumber

PDF = "/kaggle/input/datasets/zuhaibalisays/ledger-pdf/Khata_Report_1792245023769.pdf"
OUT = "/kaggle/working/extracted_ledger.csv"

# ---- EDIT IF NEEDED ----
BOUNDS  = [110, 260, 420, 500]   # keep the values you used before
COLUMNS = ["Date", "Name", "Tafseel", "Debit", "Credit"]
GAP = 10                 # words closer than this (px) belong to the same phrase
REVERSE_URDU = True
ROW_TOL = 3
MERGE_NAME_TAFSEEL = False   # set True if Name is really always empty in the PDF
DEBUG = True             # prints the first rows' cells with x-positions
# ------------------------

DATE_RE = re.compile(r'^\d{1,2}(st|nd|rd|th)\s+[A-Za-z]{3},?\s+\d{2}$')
ARABIC  = re.compile(r'[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]')
NUM_RE  = re.compile(r'^[\d,\.]+$')
LTR_RUN = re.compile(r'[A-Za-z0-9][A-Za-z0-9.,:/\-]*')

def fix_urdu(s):
    s = unicodedata.normalize('NFKC', s)
    if not ARABIC.search(s) or not REVERSE_URDU:
        return s.strip()
    s = s[::-1]
    s = LTR_RUN.sub(lambda m: m.group(0)[::-1], s)
    return s.strip()

def group_rows(words):
    words = sorted(words, key=lambda w: (w['top'], w['x0']))
    rows, cur, cur_top = [], [], None
    for w in words:
        if cur_top is None or abs(w['top'] - cur_top) <= ROW_TOL:
            if cur_top is None: cur_top = w['top']
            cur.append(w)
        else:
            rows.append(cur); cur, cur_top = [w], w['top']
    if cur: rows.append(cur)
    return rows

def make_cells(words):
    """Join neighbouring words into phrases; a new cell starts only at a big gap."""
    ws = sorted(words, key=lambda w: w['x0'])
    if not ws: return []
    groups, cur = [], [ws[0]]
    for w in ws[1:]:
        if w['x0'] - max(c['x1'] for c in cur) > GAP:
            groups.append(cur); cur = [w]
        else:
            cur.append(w)
    groups.append(cur)
    return [{'text': " ".join(w['text'] for w in g),
             'x0': min(w['x0'] for w in g),
             'x1': max(w['x1'] for w in g)} for g in groups]

def col_index(cell):
    t = cell['text']
    if ARABIC.search(t):
        x = cell['x1'] - 2                       # Urdu is right-anchored -> use RIGHT edge
    else:
        x = (cell['x0'] + cell['x1']) / 2        # numbers/English -> use centre
    return bisect.bisect(BOUNDS, x)

rows_out, shown = [], 0
with pdfplumber.open(PDF) as pdf:
    for page in pdf.pages:
        words = page.extract_words(keep_blank_chars=False)
        for row in group_rows(words):
            date_words = [w for w in row if (w['x0'] + w['x1']) / 2 < BOUNDS[0]]
            date = " ".join(w['text'] for w in sorted(date_words, key=lambda w: w['x0'])).strip()
            if not DATE_RE.match(date):          # skips ads, headers, page numbers
                continue

            rest  = [w for w in row if w not in date_words]
            cells = make_cells(rest)
            if DEBUG and shown < 12:
                print(date, [(c['text'], round(c['x0']), round(c['x1'])) for c in cells])
                shown += 1

            buckets = {i: [] for i in range(1, len(COLUMNS))}
            for c in cells:
                if c['text'].strip() == '-':
                    continue
                buckets[col_index(c)].append(c)

            rec = {"Date": date}
            for i in range(1, len(COLUMNS)):
                cs = sorted(buckets[i], key=lambda c: c['x0'])
                rec[COLUMNS[i]] = " ".join(c['text'] for c in cs)

            if MERGE_NAME_TAFSEEL:
                rec["Tafseel"] = (rec["Name"] + " " + rec["Tafseel"]).strip()
                rec["Name"] = ""

            rec["Name"]    = fix_urdu(rec["Name"]) or "-"
            rec["Tafseel"] = fix_urdu(rec["Tafseel"]) or "-"
            for k in ("Debit", "Credit"):
                rec[k] = rec[k].replace(",", "").strip() or "-"
            rows_out.append(rec)

df = pd.DataFrame(rows_out)[COLUMNS]
df.to_csv(OUT, index=False, encoding="utf-8-sig")
print(len(df), "rows saved to", OUT)
display(df.head(15))
