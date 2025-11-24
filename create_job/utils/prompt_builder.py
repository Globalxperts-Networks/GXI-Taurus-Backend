def build_resume_prompt(text):
    schema = """
        Return ONLY valid JSON. No explanation. No comments.

        {
        "name": "",
        "email": "",
        "phone": "",
        "education": [
            {"degree": "", "university": "", "year": ""}
        ],
        "experience": [
            {"role": "", "company": "", "from": "", "to": "", "description": ""}
        ],
        "total_experience": "",
        "skills": []
        }
    """

    return f"Extract the following structured JSON from the resume:\n{schema}\n\nRESUME TEXT:\n\"\"\"{text}\"\"\""
