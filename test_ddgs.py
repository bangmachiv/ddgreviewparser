# Full staged diagnostic across all 5 DDGS versions (standard library only; add openpyxl for .xlsx)
python -u ddgs_diagnostic.py

# Fast smoke test across selected versions
python -u ddgs_diagnostic.py --quick --versions 9.14.4 9.16.1 latest

# Merge & rank outputs collected from a Python 3.10 / 3.11 / 3.12 CI matrix
python -u ddgs_diagnostic.py --merge-only ./all_artifacts --output-dir ./final_report
