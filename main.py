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
    # Define the EXACT keys the current templates might need (as flat keys)
    # This list should be updated if templates change significantly
    required_keys = [
        "proposal_date", "client_first_name", "client_last_name", "client_company",
        "client_street_address", "client_city", "client_state", "client_postal_code",
        "client_salutation_name", "property_description", "auction_end_date",
        "deposit_percentage", "escrow_agent_name", "closing_date", "contract_date",
        "advertising_start_date", "marketing_facebook_cost", "marketing_google_cost",
        "marketing_mail_cost", "marketing_drone_cost", "marketing_sign_cost",
        "buyers_premium_percentage",
        # Add any other flat keys your templates might eventually use
    ]
    keys_string = ", ".join(required_keys)

    system_prompt = (
        "You are an expert assistant specialized in extracting specific, flat key-value pairs "
        "from text to populate a proposal template. Your output MUST be a valid, flat JSON object. "
        "Do NOT use nested objects or lists. If information for a key is not found, omit the key or use an empty string. "
        f"Extract ONLY the following keys if present: {keys_string}"
    )
    user_prompt = f"Extract the required key information from the following text and return it as a flat JSON object. Text: ```{text_input}```"

    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"), # Use environment variable for model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1, # Slightly lower temperature for more structured output
            response_format={ "type": "json_object" } 
        )
        extracted_json = json.loads(response.choices[0].message.content)
        # Optional: Validate that the response is actually flat
        # if any(isinstance(v, (dict, list)) for v in extracted_json.values()):
        #     print("Warning: AI returned nested data despite instructions.")
        #     # Potentially attempt flattening here, or just return as is
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