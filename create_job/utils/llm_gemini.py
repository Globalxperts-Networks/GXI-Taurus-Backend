from django.conf import settings

import os



from google import genai
import os

def call_gemini_llm(prompt):
    api_key = os.getenv("GEMINI_API_KEY")

    try:
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        

        return response.text

    except Exception as e:
        return {"error": str(e)}

