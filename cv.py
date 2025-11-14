# ============================
# File: cv_extractor_save.py
# ============================
"""
Enhanced CV extractor that explicitly extracts:
- LANGUAGES
- CONTACT (emails, phones, address-like lines)
- PROJECTS (title + description)
- EXPERIENCE (entries with role/company/dates if possible)
- EDUCATION (degree / institute / year heuristics)
- SKILLS (list)

Exports:
- process_file(path, phone_region=None, out_dir=None) -> result_meta (writes <stem>_CV.json and CV.json)
- extract_all(text, phone_region=None) -> dict (structured)
"""

import sys
import re
import json
import argparse
from pathlib import Path
from collections import Counter

# OCR & PDF
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
from PyPDF2 import PdfReader

# NLP & utilities
import spacy
import phonenumbers
import dateparser
from dateutil import parser as date_parser

nlp = spacy.load("en_core_web_sm")

# ---------------- regex / keywords ----------------
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
YEAR_RANGE_RE = re.compile(r"\b(19|20)\d{2}(?:\s*[-–—]\s*(?:19|20)\d{2})?\b")
SINGLE_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

SECTION_HEADERS = [
    "contact", "contact info", "contact information",
    "languages", "language",
    "projects", "personal projects", "selected projects",
    "experience", "work experience", "professional experience", "employment history",
    "education", "qualifications", "academic",
    "skills", "technical skills", "key skills", "core skills",
    "summary", "profile", "objective"
]

# Additional heuristics:
ADDRESS_KEYWORDS = ["address", "location", "city", "state", "country", "pin", "zipcode", "postal"]


# ---------------- PDF / OCR helpers ----------------
def pdf_has_text(path: Path) -> bool:
    try:
        reader = PdfReader(str(path))
        for p in reader.pages:
            txt = p.extract_text()
            if txt and txt.strip():
                return True
        return False
    except Exception:
        return False


def extract_text_from_pdf(path: Path):
    try:
        reader = PdfReader(str(path))
        pages = [p.extract_text() for p in reader.pages]
        text = "\n\n".join([p for p in pages if p])
        if text.strip():
            return text
    except Exception:
        pass
    return ocr_pdf(path)


def ocr_pdf(path: Path, dpi=300):
    pages = convert_from_path(str(path), dpi=dpi)
    parts = []
    for page in pages:
        parts.append(pytesseract.image_to_string(page))
    return "\n\n".join(parts)


def load_text_file(path: Path):
    return path.read_text(encoding="utf-8", errors="ignore")


def load_file(path: Path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        if pdf_has_text(path):
            print("PDF has selectable text — extracting without OCR.")
        else:
            print("No selectable text detected — using OCR on PDF.")
        return extract_text_from_pdf(path)
    if ext in (".txt", ".md"):
        return load_text_file(path)
    # try image
    try:
        img = Image.open(str(path))
        return pytesseract.image_to_string(img)
    except Exception:
        raise ValueError("Unsupported file type. Provide PDF/TXT/Image.")


# ---------------- basic extractors ----------------
def extract_emails(text: str):
    return list(dict.fromkeys(re.findall(EMAIL_RE, text)))


def extract_phones(text: str, region_hint: str = None):
    phones = []
    for m in phonenumbers.PhoneNumberMatcher(text, region_hint):
        formatted = phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164)
        if formatted not in phones:
            phones.append(formatted)
    return phones


def extract_urls(text: str):
    return list(dict.fromkeys(re.findall(r"https?://[^\s,)\]]+", text)))


def extract_names(text: str, top_n=5):
    doc = nlp(text)
    people = [ent.text.strip() for ent in doc.ents if ent.label_ == "PERSON"]
    freq = Counter(people)
    return [name for name, _ in freq.most_common(top_n)]


# ---------------- section helper ----------------
def find_section(lines, start_idx):
    """Return section block from start_idx until next likely section header.
    lines: list of stripped lines.
    start_idx: index of header line."""
    block = []
    for i in range(start_idx + 1, len(lines)):
        ln = lines[i]
        # if next line looks like another header -> stop
        low = ln.strip().lower()
        # treat lines that look like headers: short and alphabetic OR contain one of known section keywords
        if (len(ln.split()) <= 4 and ln.isupper()) or any(h in low for h in SECTION_HEADERS):
            break
        block.append(ln)
    return block


def locate_section_by_keywords(lines, keywords):
    """Return tuple (start_index, header_line) or (None, None)."""
    for i, ln in enumerate(lines):
        low = ln.lower()
        for k in keywords:
            if k in low:
                return i, ln
    return None, None


# ---------------- parse specific sections ----------------
def parse_contact(text, region_hint=None):
    emails = extract_emails(text)
    phones = extract_phones(text, region_hint)
    # Heuristic address extraction: lines containing address keywords or long lines near top of resume
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    address_lines = []
    # search near top for lines containing address keywords or numbers (pin)
    for ln in lines[:12]:
        low = ln.lower()
        if any(k in low for k in ADDRESS_KEYWORDS) or re.search(r"\b\d{5,6}\b", ln):
            address_lines.append(ln)
    # fallback: lines between name/header and "Summary" or "Experience"
    if not address_lines and len(lines) >= 6:
        # take lines 1..4 as probable contact block (after name)
        candidate = lines[1:6]
        # keep only lines that are not just single words like "Profile"
        for ln in candidate:
            if len(ln) > 8:
                address_lines.append(ln)
    return {"emails": emails, "phones": phones, "addresses": list(dict.fromkeys(address_lines))}


def parse_skills(block_lines):
    # block_lines: list of lines under Skills header
    combined = " ".join(block_lines)
    # split by bullets, semicolons, commas, pipes, or newlines
    tokens = re.split(r"[\n•\-\*;|]|,", combined)
    skills = [t.strip() for t in tokens if t and len(t.strip()) > 1]
    # deduplicate while preserving order
    seen = set()
    out = []
    for s in skills:
        lower = s.lower()
        if lower not in seen:
            seen.add(lower)
            out.append(s)
    return out


def parse_languages(block_lines):
    combined = " ".join(block_lines)
    tokens = re.split(r"[,;/\n•\-\*|]", combined)
    langs = [t.strip() for t in tokens if t and len(t.strip()) > 1]
    return list(dict.fromkeys(langs))


def parse_education(block_lines):
    # Return each non-empty line as an education item; attempt to parse degree, institute, year
    items = []
    for ln in block_lines:
        if not ln.strip():
            continue
        year = None
        yr_match = SINGLE_YEAR_RE.search(ln)
        if yr_match:
            year = yr_match.group(0)
        items.append({"text": ln.strip(), "year": year})
    return items


def split_experience_entries(block_lines):
    """
    Try to split experience block into entries.
    Heuristics:
    - split on lines that contain year ranges or bullet markers or are in Title Case and short (possible company/role).
    """
    entries = []
    current = []
    for ln in block_lines:
        if re.search(r"^[\-\u2022\*]\s+", ln):  # bullet
            # bullet likely starts a new item
            if current:
                entries.append(current)
            current = [re.sub(r"^[\-\u2022\*]\s+", "", ln)]
            continue
        if YEAR_RANGE_RE.search(ln) and current:
            # date line; attach to current
            current.append(ln)
            continue
        # if line looks like a company/role heading (short, titlecase)
        if len(ln.split()) <= 6 and ln[0].isupper() and ln.isalpha() is False:
            # can't rely purely on isalpha; instead use heuristics: if there's a dash or comma maybe role/company
            if current and len(current) > 0 and len(current[-1]) > 0:
                # continue same entry
                current.append(ln)
            else:
                if current:
                    entries.append(current)
                current = [ln]
        else:
            current.append(ln)
    if current:
        entries.append(current)
    # convert to strings
    return ["\n".join(e).strip() for e in entries if e]


def parse_experience(block_lines):
    entries_text = split_experience_entries(block_lines)
    parsed = []
    for e in entries_text:
        # Try to extract dates and role/company
        dates = YEAR_RANGE_RE.findall(e)
        # find first year-range or single years
        date_hit = YEAR_RANGE_RE.search(e)
        if not date_hit:
            date_hit = SINGLE_YEAR_RE.search(e)
        date_text = date_hit.group(0) if date_hit else None

        # Try to split first line by "—" or "-" or " at " or "," to get role and company
        first_line = e.splitlines()[0] if e.splitlines() else e
        role = None
        company = None
        # common patterns: "Senior Dev at Company", "Company — Role", "Role, Company"
        if " at " in first_line.lower():
            parts = re.split(r"\s+at\s+", first_line, flags=re.I)
            role = parts[0].strip()
            company = parts[1].strip() if len(parts) > 1 else None
        elif "—" in first_line or "–" in first_line or "-" in first_line:
            parts = re.split(r"[—–\-]", first_line, maxsplit=1)
            role = parts[0].strip()
            company = parts[1].strip() if len(parts) > 1 else None
        elif "," in first_line:
            parts = first_line.split(",", 1)
            role = parts[0].strip()
            company = parts[1].strip() if len(parts) > 1 else None
        else:
            # fallback: if contains 'Manager', 'Engineer', treat as role
            if re.search(r"\b(Manager|Engineer|Developer|Lead|Consultant|Analyst|Architect|Head|Officer)\b", first_line, flags=re.I):
                role = first_line.strip()
            else:
                company = first_line.strip()

        parsed.append({
            "raw": e,
            "role": role,
            "company": company,
            "dates": date_text,
        })
    return parsed


def parse_projects(block_lines):
    projects = []
    # treat bullets or blank lines as separators
    current_title = None
    current_desc = []
    for ln in block_lines:
        ln = ln.strip()
        if not ln:
            continue
        # If line looks like "ProjectName - description" or starts with "•" or "-" treat as new project
        if re.match(r"^[\-\u2022\*]\s+", ln) or (" - " in ln and len(ln.split(" - ")[0].split()) <= 6):
            # new project
            title_desc = re.sub(r"^[\-\u2022\*]\s+", "", ln)
            parts = title_desc.split(" - ", 1)
            title = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            projects.append({"title": title, "description": desc})
        else:
            # if line contains ":" and left side short -> likely title
            if ":" in ln and len(ln.split(":")[0].split()) <= 6:
                title, desc = ln.split(":", 1)
                projects.append({"title": title.strip(), "description": desc.strip()})
            else:
                # otherwise append to last project's description or create a loose project
                if projects and len(projects[-1]["description"]) < 500:
                    projects[-1]["description"] = (projects[-1]["description"] + " " + ln).strip()
                else:
                    projects.append({"title": ln, "description": ""})
    return projects


# ---------------- overall extraction ----------------
def find_sections_blocks(text: str):
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    # make lower map for quick header detection
    lower_lines = [l.lower() for l in lines]
    sections = {}
    # For each header we care about, try to find it
    desired = {
        "contact": ["contact", "contact information", "contact info"],
        "languages": ["languages", "language"],
        "projects": ["projects", "personal projects", "selected projects"],
        "experience": ["experience", "work experience", "professional experience", "employment history", "work history"],
        "education": ["education", "academic", "qualifications", "qualification"],
        "skills": ["skills", "technical skills", "key skills", "core skills"],
        "profile": ["profile", "summary", "professional summary", "objective"]
    }
    # find indices
    header_indices = {}
    for i, low in enumerate(lower_lines):
        for key, kws in desired.items():
            for kw in kws:
                if kw in low:
                    # prefer first occurrence
                    if key not in header_indices:
                        header_indices[key] = i
    # Now capture blocks for each header using find_section logic
    for key, idx in header_indices.items():
        block = find_section(lines, idx)
        sections[key] = {"header": lines[idx], "lines": block}
    # Also return whole lines for fallback parsing
    return sections, lines


def extract_all(text: str, phone_region: str = None):
    # basic normalizations
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    result = {}
    # basic fields
    result["emails"] = extract_emails(text)
    result["phones"] = extract_phones(text, phone_region)
    result["urls"] = extract_urls(text)
    result["name_candidates"] = extract_names(text, top_n=8)

    # find section blocks
    sections_map, all_lines = find_sections_blocks(text)

    # CONTACT
    contact_data = parse_contact(text, phone_region)
    # prefer contact block lines if present
    contact_block = sections_map.get("contact", {}).get("lines")
    if contact_block:
        # extract emails/phones from specifically the contact block first
        cb_text = "\n".join(contact_block)
        cb_emails = extract_emails(cb_text)
        cb_phones = extract_phones(cb_text, phone_region)
        if cb_emails:
            contact_data["emails"] = cb_emails
        if cb_phones:
            contact_data["phones"] = cb_phones
        # capture address-like lines
        addr = []
        for ln in contact_block:
            low = ln.lower()
            if any(k in low for k in ADDRESS_KEYWORDS) or re.search(r"\d{5,6}", ln) or (len(ln.split()) > 3 and any(c.isdigit() for c in ln)):
                addr.append(ln)
        if addr:
            contact_data["addresses"] = list(dict.fromkeys(addr))

    result["sections"] = {}
    # LANGUAGES
    lang_lines = sections_map.get("languages", {}).get("lines", [])
    if lang_lines:
        result["sections"]["languages"] = parse_languages(lang_lines)
    else:
        # fallback: search for a line "Languages: English, Hindi"
        m = re.search(r"languages?:\s*(.+)", text, flags=re.I)
        if m:
            result["sections"]["languages"] = [s.strip() for s in re.split(r"[,/;|]", m.group(1)) if s.strip()]
        else:
            result["sections"]["languages"] = []

    # SKILLS
    skills_lines = sections_map.get("skills", {}).get("lines", [])
    result["sections"]["skills"] = parse_skills(skills_lines) if skills_lines else []
    # fallback: inline "Skills: python, django, ..."
    if not result["sections"]["skills"]:
        m = re.search(r"skills?:\s*(.+)", text, flags=re.I)
        if m:
            result["sections"]["skills"] = parse_skills([m.group(1)])

    # EDUCATION
    edu_lines = sections_map.get("education", {}).get("lines", [])
    result["sections"]["education"] = parse_education(edu_lines) if edu_lines else []

    # EXPERIENCE
    exp_lines = sections_map.get("experience", {}).get("lines", [])
    result["sections"]["experience"] = parse_experience(exp_lines) if exp_lines else []

    # PROJECTS
    proj_lines = sections_map.get("projects", {}).get("lines", [])
    result["sections"]["projects"] = parse_projects(proj_lines) if proj_lines else []

    # PROFILE / SUMMARY
    prof_lines = sections_map.get("profile", {}).get("lines", [])
    if prof_lines:
        result["sections"]["profile_summary"] = " ".join(prof_lines)[:1200]
    else:
        # fallback to top lines
        head = "\n".join(all_lines[:6])
        result["sections"]["profile_summary"] = head[:1200]

    # CONTACT (final attach)
    result["sections"]["contact"] = contact_data

    return result


# ---------------- save / process ----------------
def process_file(path, phone_region=None, out_dir=None):
    path = Path(path)
    out_dir = Path(out_dir) if out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    text = load_file(path)
    fields = extract_all(text, phone_region)

    result_meta = {
        "source_file": str(path),
        "extracted_with": "cv_extractor_save.py (enhanced sections)",
        "fields": fields
    }

    per_file = out_dir / f"{path.stem}_CV.json"
    generic = out_dir / "CV.json"
    with per_file.open("w", encoding="utf-8") as f:
        json.dump(result_meta, f, indent=2, ensure_ascii=False)
    with generic.open("w", encoding="utf-8") as f:
        json.dump(result_meta, f, indent=2, ensure_ascii=False)

    return result_meta


# ---------------- CLI ----------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to PDF/TXT/Image resume")
    parser.add_argument("--phone-region", default=None, help="Phone region hint e.g., IN, US")
    parser.add_argument("--output-dir", default=None, help="Directory to save JSON outputs")
    args = parser.parse_args()

    meta = process_file(args.path, phone_region=args.phone_region, out_dir=args.output_dir)
    print(json.dumps(meta, indent=2, ensure_ascii=False))
