
import os
from google import genai


def draft_email(job_title, company, email_type):
    """Generate an email using Google's Gemini AI."""

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("Gemini API key is missing.")

    client = genai.Client(api_key=api_key)

    if email_type == "followup":
        purpose = "Follow up on a submitted job application."
    elif email_type == "interest":
        purpose = "Express interest in a job opportunity."
    else:
        raise ValueError("Invalid email type.")

    prompt = f"""
    You are a professional career assistant.

    Write a short, professional job application email.

    Job title: {job_title}
    Company: {company}
    Email purpose: {purpose}

    Requirements:
    - Include a subject line.
    - Include a professional greeting.
    - Keep the email concise and friendly.
    - Do not invent experience, qualifications,
      application dates, or recruiter names.
    - Use placeholders for missing information.
    - End with a professional closing.
    """

    response = client.models.generate_content(
       model="gemini-3.5-flash-lite",
        contents=prompt
    )

    if not response.text:
        raise ValueError("Gemini returned an empty response.")

    return response.text
