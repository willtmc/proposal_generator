import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI
from dotenv import load_dotenv
import json

# Import database functions
from database import init_db, get_db, create_proposal, add_proposal_data, Proposal # Add necessary imports

# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Initialize OpenAI client
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY not found in environment variables. Please set it in your .env file.")

client = OpenAI(api_key=openai_api_key)

# --- Pydantic Models ---

class TextInput(BaseModel):
    text: str = Field(..., min_length=1, description="The input text to process.")

class ExtractedData(BaseModel):
    data: dict = Field(..., description="Extracted key-value pairs from the text.")


# --- Helper Function ---

def extract_structured_data(text_input: str) -> dict:
    """
    Uses OpenAI's GPT-4o to extract structured key-value pairs from text.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # Ensure you have access to this model
            messages=[
                {"role": "system", "content": "You are an expert assistant specialized in extracting structured information from text into key-value pairs. Your output MUST be a valid JSON object."},
                {"role": "user", "content": f"Extract the key information from the following text and return it as a JSON object. Text: ```{text_input}```"}
            ],
            temperature=0.2, # Lower temperature for more deterministic output
            response_format={ "type": "json_object" } # Request JSON output
        )
        # print(response.choices[0].message.content) # Debug print
        # Attempt to parse the JSON string from the response content
        extracted_json = json.loads(response.choices[0].message.content)
        return extracted_json

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from OpenAI response: {e}")
        print(f"Raw response content: {response.choices[0].message.content}") # Log raw response
        raise HTTPException(status_code=500, detail="Failed to parse structured data from OpenAI response.")
    except Exception as e:
        print(f"An unexpected error occurred during OpenAI API call: {e}") # Log other errors
        raise HTTPException(status_code=500, detail=f"An error occurred processing the text: {e}")


# --- API Endpoint ---

@app.post("/extract-context", response_model=ExtractedData)
async def extract_context_endpoint(input_data: TextInput):
    """
    Receives text input and returns extracted structured data as JSON.
    """
    extracted_data = extract_structured_data(input_data.text)
    return ExtractedData(data=extracted_data)


# --- Database Initialization Hook ---
@app.on_event("startup")
def on_startup():
    print("Running DB initialization...")
    init_db()


# --- Run with Uvicorn (for local development) ---
# You would typically run this using: uvicorn main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 