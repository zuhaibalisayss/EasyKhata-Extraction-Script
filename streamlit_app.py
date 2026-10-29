import bisect
import re
import unicodedata
from io import BytesIO

import pandas as pd
import pdfplumber
import streamlit as st

st.set_page_config(page_title="EasyKhata Ledger Extractor", page_icon="📄", layout="wide")

st.title("EasyKhata Ledger Extractor")
st.write("Upload an EasyKhata ledger PDF, extract its entries, review the results, and download a CSV.")

with st.expander("Settings", expanded=False):
    dash_as_zero = st.checkbox("Export missing Debit/Credit values as 0 instead of -", value=False)
    line_tol = st.slider("Vertical line tolerance (pixels)", min_value=1, max_value=8, value=4)
    boundary_hint = st.number_input(
        "Name/Tafseel boundary X (optional; 0 = auto-detect)",
        min_value=0.0, max_value=2000.0, value=0.0, step=1.0
    )

uploaded = st.file_uploader("Choose a ledger PDF", type=["pdf"])

ARABIC = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
LTR_RUN = re.compile(r'[A-Za-z0-9][A-Za-z0-9.,:/+\-]*')
MARKS = re.compile(r'[\u200b-\u200f\u202a-\u202e\u2066-\u2069]')
DAY = re.compile(r'^\d{1,2}(st|nd|rd|th)$')
MON = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec),?$')
YR = re.compile(r'^\d{2}$')
NUM = re.compile(r'^([-\u2212\u2013]|\d[\d,]*(\.\d+)?)$')
DASH = re.compile(r'^[-\u2212\u2013]$')
AD_WORDS = {'Sadiq', 'uthaein', 'ghata,', 'Abhi', 'download', 'karein', 'Khata', 'DOWNLOAD', 'Easy'}


def prep_chars(page):
    for char in page.chars:
        t = char["text"]
        if ARABIC.search(t) or len(t) > 1:
            normalized = unicodedata.normalize("NFKC", t)
            if len(normalized) > 1 and ARABIC.search(normalized):
                normalized = normalized[::-1]
            char["text"] = normalized


def fix_line(text):
    text = MARKS.sub("", text)
    if not ARABIC.search(text):
        return text.strip()
    text = text[::-1]
    return LTR_RUN.sub(lambda match: match.group(0)[::-1], text).strip()


def cell_text(words, tolerance):
    if not words:
        return ""
    words = sorted(words, key=lambda word: word["y"])
    lines, current = [], [words[0]]
    for word in words[1:]:
        if word["y"] - current[-1]["y"] <= tolerance:
            current.append(word)
        else:
            lines.append(current)
            current = [word]
    lines.append(current)
    output = []
    for line in lines:
        output.append(fix_line(" ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"]))))
    return " ".join(value for value in output if value)


def is_ad_char(obj):
    font = obj.get("fontname") or ""
    return abs((obj.get("size") or 0) - 10.5) < 0.3 and "Static" not in font and "Roboto" in font


def strip_footer(page):
    footer_char = None
    chars = sorted(page.chars, key=lambda char: (round(char["top"]), char["x0"]))
    for index in range(len(chars) - 3):
        if "".join(char["text"] for char in chars[index:index + 4]) == "Page":
            footer_char = chars[index]
            break

    def keep(obj):
        if obj.get("object_type") != "char":
            return True
        if is_ad_char(obj):
            return False
        if footer_char is not None and obj["x0"] >= footer_char["x0"] - 1 \
                and abs(obj["top"] - footer_char["top"]) < 0.3 \
                and abs((obj["bottom"] - obj["top"]) - (footer_char["bottom"] - footer_char["top"])) < 0.3:
            return False
        return True

    return page.filter(keep)


def read_page(page, page_number, tolerance):
    page = strip_footer(page)
    prep_chars(page)
    words = page.extract_words(x_tolerance=1.0)
    for index, word in enumerate(words):
        word["y"] = (word["top"] + word["bottom"]) / 2
        word["i"] = index

    headers = [word for word in words if word["text"] == "Tafseel"]
    header_x = headers[0]["x0"] if headers else None
    if headers:
        bands = [word["y"] for word in headers]
        top_y = min(bands)
        words = [word for word in words if word["y"] > top_y + 1 and all(abs(word["y"] - band) > 6 for band in bands)]
    generated = [word["y"] for word in words if word["text"] == "Generated"]
    words = [word for word in words if all(abs(word["y"] - y) > 6 for y in generated)]

    ads = [word for word in words if word["text"] in ("uthaein", "DOWNLOAD", "karein")]
    if ads:
        footer_top = min(word["top"] for word in ads)
        sadiq = [word for word in words if word["text"] == "Sadiq" and 0 < footer_top - word["top"] < 80]
        if sadiq:
            footer_top = min(footer_top, min(word["top"] for word in sadiq))
        words = [word for word in words if word["top"] < footer_top - 1]
    words = [word for word in words if word["text"] not in AD_WORDS]

    anchors = []
    for word in words:
        if DAY.match(word["text"]):
            next_words = sorted(
                (other for other in words if abs(other["y"] - word["y"]) <= 3 and other["x0"] > word["x0"]),
                key=lambda other: other["x0"]
            )[:2]
            if len(next_words) == 2 and MON.match(next_words[0]["text"]) and YR.match(next_words[1]["text"]):
                anchors.append({
                    "y": word["y"],
                    "date": f'{word["text"]} {next_words[0]["text"]} {next_words[1]["text"]}',
                    "ids": {word["i"], next_words[0]["i"], next_words[1]["i"]}
                })

    if not anchors:
        return [], header_x
    anchors.sort(key=lambda anchor: anchor["y"])

    ys = sorted(word["y"] for word in words)
    cuts = []
    for first, second in zip(anchors, anchors[1:]):
        segment = [y for y in ys if first["y"] - 1e-6 <= y <= second["y"] + 1e-6]
        if len(segment) < 2:
            cuts.append((first["y"] + second["y"]) / 2)
        else:
            gap_index = max(range(len(segment) - 1), key=lambda idx: segment[idx + 1] - segment[idx])
            cuts.append((segment[gap_index] + segment[gap_index + 1]) / 2)

    taken = set().union(*(anchor["ids"] for anchor in anchors))
    buckets = [[] for _ in anchors]
    for word in words:
        if word["i"] not in taken:
            buckets[bisect.bisect(cuts, word["y"])].append(word)

    rows = []
    for anchor, bucket in zip(anchors, buckets):
        numbers = sorted((word for word in bucket if NUM.match(word["text"])), key=lambda word: word["x0"])
        money = numbers[-2:]
        rest = [word for word in bucket if all(word is not amount for amount in money)]
        rows.append({"page": page_number, "date": anchor["date"], "money": [m["text"] for m in money], "rest": rest})
    return rows, header_x


def find_boundary(rows, hint):
    intervals = sorted((word["x0"], word["x1"]) for row in rows for word in row["rest"])
    if not intervals:
        return None
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1.5:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    gaps = [
        (merged[index + 1][0] - merged[index][1], (merged[index][1] + merged[index + 1][0]) / 2)
        for index in range(len(merged) - 1)
    ]
    gaps = [gap for gap in gaps if gap[0] >= 4]
    if not gaps:
        return None
    if hint is not None:
        return min(gaps, key=lambda gap: abs(gap[1] - hint))[1]
    return max(gaps)[1]


def extract_ledger(pdf_file, tolerance, manual_boundary):
    pdf_file.seek(0)
    all_rows, hint, expected_debit, expected_credit, empty_pages = [], None, None, None, []
    with pdfplumber.open(pdf_file) as pdf:
        first_page_text = pdf.pages[0].extract_text() or ""
        totals = re.findall(r"Rs\.?\s*([\d,]+)", first_page_text)
        if len(totals) >= 2:
            expected_debit = float(totals[0].replace(",", ""))
            expected_credit = float(totals[1].replace(",", ""))

        for page_number, page in enumerate(pdf.pages, 1):
            rows, header_x = read_page(page, page_number, tolerance)
            if hint is None and header_x is not None:
                hint = header_x
            if not rows:
                empty_pages.append(page_number)
            all_rows.extend(rows)

    boundary = manual_boundary if manual_boundary > 0 else find_boundary(all_rows, hint)
    if boundary is None:
        boundary = hint if hint is not None else 0

    records, problems = [], []
    for row in all_rows:
        names = [word for word in row["rest"] if (word["x0"] + word["x1"]) / 2 < boundary]
        details = [word for word in row["rest"] if (word["x0"] + word["x1"]) / 2 >= boundary]
        money = ["-" if DASH.match(token) else token.replace(",", "") for token in row["money"]]
        if len(money) < 2:
            money += ["-"] * (2 - len(money))
            problems.append((row["page"], row["date"], "Fewer than two amount tokens found"))
        elif (money[0] == "-") == (money[1] == "-"):
            problems.append((row["page"], row["date"], f"Debit/Credit values may be incorrect: {money}"))
        records.append([row["date"], cell_text(names, tolerance) or "-", cell_text(details, tolerance) or "-", money[0], money[1]])

    frame = pd.DataFrame(records, columns=["Date", "Name", "Tafseel", "Debit", "Credit"])
    return frame, expected_debit, expected_credit, empty_pages, problems, boundary


if uploaded is not None:
    st.info(f"Selected: {uploaded.name} · {uploaded.size / 1024:.1f} KB")
    if st.button("Extract ledger", type="primary"):
        try:
            with st.spinner("Reading PDF and extracting ledger rows..."):
                df, expected_debit, expected_credit, empty_pages, problems, boundary = extract_ledger(
                    BytesIO(uploaded.getvalue()), line_tol, boundary_hint
                )
            if df.empty:
                st.error("No ledger rows were detected. This script expects a text-based EasyKhata ledger PDF with dates like '1st Jan, 25'. Scanned/image-only PDFs may need OCR.")
            else:
                st.session_state["ledger_df"] = df
                st.session_state["ledger_filename"] = uploaded.name
                st.session_state["ledger_meta"] = {
                    "expected_debit": expected_debit,
                    "expected_credit": expected_credit,
                    "empty_pages": empty_pages,
                    "problems": problems,
                    "boundary": boundary,
                    "dash_as_zero": dash_as_zero,
                }
        except Exception as exc:
            st.error(f"Extraction failed: {exc}")
            st.exception(exc)

if "ledger_df" in st.session_state:
    df = st.session_state["ledger_df"].copy()
    meta = st.session_state["ledger_meta"]
    st.subheader("Extraction results")
    c1, c2, c3 = st.columns(3)
    c1.metric("Rows extracted", f"{len(df):,}")
    c2.metric("Debit total", f'{sum(0 if v == "-" else float(v) for v in df["Debit"]):,.2f}')
    c3.metric("Credit total", f'{sum(0 if v == "-" else float(v) for v in df["Credit"]):,.2f}')

    debit_sum = sum(0 if value == "-" else float(value) for value in df["Debit"])
    credit_sum = sum(0 if value == "-" else float(value) for value in df["Credit"])
    if meta["expected_debit"] is not None:
        status = "OK" if round(debit_sum, 2) == round(meta["expected_debit"], 2) else "MISMATCH"
        st.write(f"PDF debit total: **{meta['expected_debit']:,.2f}** — {status}")
    if meta["expected_credit"] is not None:
        status = "OK" if round(credit_sum, 2) == round(meta["expected_credit"], 2) else "MISMATCH"
        st.write(f"PDF credit total: **{meta['expected_credit']:,.2f}** — {status}")

    st.caption(f"Detected Name/Tafseel boundary: X = {meta['boundary']:.1f}. Pages without detected rows: {meta['empty_pages'] or 'None'}.")
    if meta["problems"]:
        with st.expander(f"Review {len(meta['problems'])} suspicious rows"):
            st.dataframe(pd.DataFrame(meta["problems"], columns=["Page", "Date", "Issue"]), use_container_width=True)
    st.write("Review the extracted table below. You can edit cells before downloading.")
    edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True, key="ledger_editor")
    export_df = edited_df.copy()
    if meta["dash_as_zero"]:
        export_df[["Debit", "Credit"]] = export_df[["Debit", "Credit"]].replace("-", "0")
    csv_data = export_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Download extracted CSV",
        data=csv_data,
        file_name="extracted_ledger.csv",
        mime="text/csv",
        type="primary"
    )
else:
    st.caption("Your PDF is processed when you click Extract ledger. Uploaded files are handled in the running app session; this app does not intentionally save them to a database.")
