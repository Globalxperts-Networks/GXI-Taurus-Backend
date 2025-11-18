# utils/csv_reader.py
import csv
from io import TextIOWrapper, BytesIO
import logging
from io import TextIOWrapper, BytesIO, StringIO
import openpyxl
import xlrd

logger = logging.getLogger(__name__)

ENCODINGS_TO_TRY = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]

def read_csv_file(uploaded_file):
    raw = uploaded_file.read()
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    for enc in ENCODINGS_TO_TRY:
        try:
            text = raw.decode(enc)
        except Exception as e:
            logger.debug("Decoding with %s failed: %s", enc, e)
            continue

        try:
            sample = text[:8192]
            dialect = csv.Sniffer().sniff(sample)
        except Exception:
            dialect = csv.excel

        try:
            f = StringIO(text)
            reader = csv.DictReader(f, dialect=dialect)
            return list(reader)
        except Exception as e:
            logger.debug("CSV parsing with %s failed: %s", enc, e)

    # fallback
    text = raw.decode("latin-1", errors="replace")
    f = StringIO(text)
    reader = csv.DictReader(f)
    return list(reader)

# ---------- XLSX READER ----------
def read_xlsx_file(uploaded_file):
    wb = openpyxl.load_workbook(uploaded_file, data_only=True)
    ws = wb.active

    rows = list(ws.values)
    if not rows:
        return []

    header = [str(h).strip() if h else "" for h in rows[0]]
    result = []

    for row in rows[1:]:
        row_dict = {}
        for key, value in zip(header, row):
            row_dict[key] = value if value is not None else ""
        result.append(row_dict)

    return result

# ---------- XLS READER ----------
def read_xls_file(uploaded_file):
    book = xlrd.open_workbook(file_contents=uploaded_file.read())
    sheet = book.sheet_by_index(0)

    header = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    result = []

    for row_idx in range(1, sheet.nrows):
        row_dict = {}
        for col_idx, key in enumerate(header):
            value = sheet.cell_value(row_idx, col_idx)
            row_dict[key] = value if value else ""
        result.append(row_dict)

    return result

# ---------- MASTER READER ----------
def read_uploaded_file(uploaded_file):
    filename = uploaded_file.name.lower()

    if filename.endswith(".csv"):
        return read_csv_file(uploaded_file)

    elif filename.endswith(".xlsx"):
        return read_xlsx_file(uploaded_file)

    elif filename.endswith(".xls"):
        return read_xls_file(uploaded_file)

    else:
        raise ValueError("Unsupported file type. Only CSV, XLSX, and XLS are allowed.")

from create_job.models import add_job

def get_or_create_job_by_title(title):

    if not title:
        return None

    job = add_job.objects.filter(title__iexact=title.strip()).first()

    if job:
        return job

    job = add_job.objects.create(
        title=title.strip(),
        Description="Auto-created from CSV import",
        Salary_range="Not Specified",
        Experience_required="Not Specified",
        no_opening=1,  # default minimal
        is_active=True
    )

    return job
