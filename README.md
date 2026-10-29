# EasyKhata Report Data Extraction

A Python-based solution (built as a Jupyter Notebook) designed to parse, clean, and transform unstructured financial report PDFs from the **Easy Khata** app into structured, analysis-ready CSV files.

---

##  Overview

The **EasyKhata-Extraction-Script** simplifies financial tracking and bookkeeping by bridging the gap between raw PDF exports and spreadsheet software (such as Microsoft Excel or Google Sheets). While ledger applications export portable PDF summaries, analyzing transactions, calculating totals, or auditing data becomes tedious without clean tabular formats. This repository automates that extraction and cleaning workflow.

---

##  Features

* **PDF Parsing:** Extracts raw textual data or tables from EasyKhata app report exports.
* **Data Cleaning & Formatting:** Cleans raw extracted strings, standardizes date formats, and converts text-based currency fields into proper numerical data types for calculations.
* **CSV Export:** Outputs a structured, clean CSV file ready for import into Excel, Google Sheets, or custom accounting dashboards.
* **Interactive Notebook:** Built inside a Jupyter Notebook environment (`easykhata-report-data-extraction.ipynb`), making it easy to step through, audit, and modify transformations interactively.

---

##  Project Structure

```text
EasyKhata-Extraction-Script/
│
├── easykhata-report-data-extraction.ipynb   # Main Jupyter Notebook containing the extraction & cleaning logic
├── LICENSE                                  # Apache-2.0 License file
└── README.md                                # Project documentation
