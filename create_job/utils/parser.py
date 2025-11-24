import re

def clean_text(text):
    return re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()

def extract_name(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return None

    for line in lines[:5]:
        if 2 <= len(line.split()) <= 4 and re.match(r'^[A-Za-z ]+$', line):
            return line.title()

    return None

def extract_email(text):
    match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else None

def extract_phone(text):
    phone_patterns = [
        r'\+?\d{10,12}',
        r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',
        r'\b\d{5}[-.\s]?\d{5}\b'
    ]
    for pattern in phone_patterns:
        match = re.search(pattern, text)
        if match:
            num = match.group(0)
            if not re.match(r'^\d{4}\s*[-/]\s*\d{2}$', num):  
                return num
    return None

import re

def extract_education(text):
    education_data = []

    # Normalize text
    clean = text.replace("\n", " ")
    clean = re.sub(r"\s+", " ", clean)

    # Patterns for degrees with specialization
    degree_patterns = [
        r"(Bachelor[’'s]* degree in [A-Za-z ]+)",
        r"(Master[’'s]* degree in [A-Za-z ]+)",
        r"(Bachelor of [A-Za-z ]+)",
        r"(Master of [A-Za-z ]+)",
        r"\bB\.?Tech\b",
        r"\bM\.?Tech\b",
        r"\bB\.?E\b",
        r"\bM\.?E\b",
        r"\bB\.?Sc\b",
        r"\bM\.?Sc\b",
        r"\bMCA\b",
        r"\bBCA\b",
        r"\bMBA\b",
        r"\bBBA\b"
    ]

    university_patterns = [
        r"[A-Za-z ,]*University",
        r"[A-Za-z ,]*Institute",
        r"[A-Za-z ,]*College",
        r"[A-Za-z ,]*Academy"
    ]

    # 1️⃣ Extract degree text
    degree_found = None
    for pattern in degree_patterns:
        m = re.search(pattern, clean, re.IGNORECASE)
        if m:
            degree_found = m.group(0).strip()
            break

    # 2️⃣ Extract university/institute
    university_found = None
    for pattern in university_patterns:
        u = re.search(pattern, clean, re.IGNORECASE)
        if u:
            university_found = u.group(0).strip()
            break

    # 3️⃣ Build final education object
    if degree_found:
        education_data.append({
            "degree": degree_found,
            "university": university_found
        })

    return education_data

def extract_experience(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    experiences = []

    pattern = r"(.+?),\s*(\d{2}/\d{4})\s*[-–]\s*(\d{2}/\d{4}|Present|present)"

    for i, line in enumerate(lines):
        m = re.search(pattern, line)
        if m:
            role = m.group(1).strip()
            start = m.group(2)
            end = m.group(3)

            # Company name is usually the next non-empty line
            company = None
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                # Ignore lines starting with "--" or bullets
                if not next_line.startswith("--") and len(next_line.split()) > 1:
                    company = next_line

            experiences.append({
                "role": role,
                "company": company,
                "from": start,
                "to": end
            })

    return experiences


def parse_resume(text):

    return {
        "name": extract_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text),
        "education": extract_education(text),
        "experience": extract_experience(text),
        "raw_text": text[:2000]
    }
