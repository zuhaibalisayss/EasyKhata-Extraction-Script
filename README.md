# EasyKhata Ledger Extractor (Streamlit)

A Streamlit interface for extracting ledger rows from text-based EasyKhata PDF reports.

## Deploy free on Streamlit Community Cloud

1. Create a GitHub repository, for example `easykhata-streamlit`.
2. Upload `streamlit_app.py`, `requirements.txt`, and `README.md` to the repository root.
3. Open https://share.streamlit.io/ and sign in with GitHub.
4. Select **Create app**, choose your repository and branch, and set the main file path to `streamlit_app.py`.
5. Click **Deploy**.

## Run locally (optional)

```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Important limitations

- The extraction logic is designed for text-based EasyKhata ledger PDFs and date strings such as `1st Jan, 25`.
- Scanned/image-only PDFs are not OCR-processed.
- Verify extracted rows and totals before using them for accounting.
- Do not upload confidential financial documents to a public app unless access and privacy requirements are appropriate.
