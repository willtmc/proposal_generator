import streamlit as st
import requests
import os
import sys
from pathlib import Path
import time  # For generating unique proposal names

# --- Configuration ---
# Add the project root to the Python path to allow importing modules
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# Assuming FastAPI runs on localhost:8000
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:8000")
EXTRACT_ENDPOINT = f"{FASTAPI_URL}/extract-context"

# Import database and generator functions
try:
    from database import SessionLocal, create_proposal, add_proposal_data, get_proposal_with_data, Proposal, init_db
    from proposal_generator import load_template, find_placeholders, fill_template, get_proposal_data_as_dict, TEMPLATE_DIR
except ImportError as e:
    st.error(f"Fatal Error: Could not import database or proposal_generator modules: {e}. "
             f"Ensure they exist in the project root ('{PROJECT_ROOT}') and that the Streamlit app is run from the project root. "
             f"Current sys.path: {sys.path}")
    st.stop()
except Exception as e:
    st.error(f"Fatal Error: An unexpected error occurred during module import: {e}")
    st.stop()


# --- Helper Functions ---

def get_available_templates() -> list[str]:
    """Gets a list of template names (without .md extension)."""
    if not TEMPLATE_DIR.is_dir():
        st.warning(f"Template directory '{TEMPLATE_DIR}' not found.")
        return []
    templates = [f.stem for f in TEMPLATE_DIR.glob("*.md")]
    if not templates:
        st.warning(f"No '.md' templates found in '{TEMPLATE_DIR}'.")
    return templates


# --- Database Initialization ---
# We need a way to ensure DB is initialized once per app load effectively
# Using a simple flag in session state.
if 'db_initialized' not in st.session_state:
    st.session_state.db_initialized = False

def ensure_db_initialized():
    if not st.session_state.db_initialized:
        try:
            print("Attempting to initialize database...")
            init_db() # Initialize DB on first interaction if needed
            st.session_state.db_initialized = True
            print("Database initialized successfully.")
        except Exception as e:
            st.error(f"Failed to initialize database: {e}")
            # We might want to stop the app if DB init fails critically
            st.stop()

# Call this early, e.g., before the first DB operation might occur.
ensure_db_initialized()


# --- Streamlit App ---

st.set_page_config(layout="wide")
st.title("AI Proposal Generator Assistant")

# --- State Initialization ---
# Use st.session_state to store data across reruns
if 'proposal_id' not in st.session_state:
    st.session_state.proposal_id = None
if 'proposal_name' not in st.session_state:
    st.session_state.proposal_name = None
if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = None
if 'uploaded_filename' not in st.session_state:
    st.session_state.uploaded_filename = None
if 'template_name' not in st.session_state:
    st.session_state.template_name = None
if 'template_content' not in st.session_state:
    st.session_state.template_content = None
if 'template_placeholders' not in st.session_state:
    st.session_state.template_placeholders = set()
if 'current_proposal_data' not in st.session_state: # Data currently in DB for the proposal
    st.session_state.current_proposal_data = {}
if 'missing_keys' not in st.session_state: # Keys needed by template but not in current_proposal_data
    st.session_state.missing_keys = set()
if 'interview_data' not in st.session_state: # Data collected via interview form
    st.session_state.interview_data = {}
if 'final_proposal_content' not in st.session_state:
    st.session_state.final_proposal_content = None


# --- Workflow Steps ---

# Step 1: File Upload and Context Extraction
st.header("1. Upload Context & Extract Data")
st.write("Upload a text file (.txt) containing the context for your proposal. The content will be sent to the AI for key information extraction.")
# TODO: Add support for PDF later
uploaded_file = st.file_uploader("Upload context document:", type=['txt'], key="file_uploader")

# Process uploaded file only if it's new or hasn't been processed yet
if uploaded_file is not None and uploaded_file.name != st.session_state.get('uploaded_filename'):
    # Reset state for new file processing
    st.session_state.proposal_id = None
    st.session_state.proposal_name = None
    st.session_state.extracted_data = None
    st.session_state.current_proposal_data = {}
    st.session_state.interview_data = {}
    st.session_state.missing_keys = set()
    st.session_state.final_proposal_content = None
    st.session_state.uploaded_filename = uploaded_file.name # Mark as processed

    st.info(f"Processing uploaded file: {uploaded_file.name}")

    try:
        file_content = uploaded_file.getvalue().decode("utf-8")
        if not file_content.strip():
             st.warning("Uploaded file is empty.")
        else:
            st.text_area("File Content Preview:", file_content, height=150, key="file_preview")

            # Call FastAPI endpoint for extraction
            with st.spinner("Sending text to AI for context extraction..."):
                try:
                    response = requests.post(EXTRACT_ENDPOINT, json={"text": file_content}, timeout=60) # Added timeout
                    response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                    extracted = response.json().get("data", {})
                    st.session_state.extracted_data = extracted if isinstance(extracted, dict) else {}
                    st.success("AI extraction successful!")

                    # Create a new proposal entry in the DB and save extracted data
                    db_session = SessionLocal()
                    try:
                        # Create a unique name (e.g., based on filename and timestamp)
                        proposal_name_base = Path(uploaded_file.name).stem
                        timestamp = int(time.time())
                        st.session_state.proposal_name = f"{proposal_name_base}_{timestamp}"

                        new_proposal = create_proposal(db_session, st.session_state.proposal_name)
                        st.session_state.proposal_id = new_proposal.id

                        if st.session_state.extracted_data:
                           add_proposal_data(db_session, new_proposal.id, st.session_state.extracted_data)
                           st.session_state.current_proposal_data = st.session_state.extracted_data # Initial data
                           st.success(f"Extracted data saved to new proposal '{st.session_state.proposal_name}' (ID: {st.session_state.proposal_id}).")
                        else:
                            st.warning("AI did not return any structured data.")
                            st.session_state.current_proposal_data = {}

                        # Trigger immediate rerun to move to the next stage
                        st.rerun()

                    except Exception as db_error:
                        st.error(f"Database error after extraction: {db_error}")
                        # Reset states critical for DB interaction if saving failed
                        st.session_state.proposal_id = None
                        st.session_state.proposal_name = None
                        st.session_state.current_proposal_data = {}
                    finally:
                        db_session.close()

                except requests.exceptions.Timeout:
                    st.error(f"Error calling extraction API: Request timed out. The AI might be taking too long.")
                except requests.exceptions.ConnectionError:
                     st.error(f"Error calling extraction API: Could not connect to the backend at {FASTAPI_URL}. Is the FastAPI server ('main.py') running?")
                except requests.exceptions.RequestException as e:
                    st.error(f"Error calling extraction API: {e}")
                except Exception as e:
                    st.error(f"An unexpected error occurred during extraction processing: {e}")

                # If extraction or DB saving failed, clear extracted data state
                if st.session_state.proposal_id is None:
                    st.session_state.extracted_data = None


    except Exception as e:
        st.error(f"Error reading or processing file: {e}")
        st.session_state.extracted_data = None
        st.session_state.uploaded_filename = None # Allow re-upload


# Step 2: Review Data and Select Template (only if proposal exists in state)
if st.session_state.proposal_id is not None:
    st.header("2. Review Data & Select Template")
    st.info(f"Working with Proposal: **{st.session_state.proposal_name}** (ID: {st.session_state.proposal_id})")

    st.subheader("Current Proposal Data")
    # Display current data (might have been updated by interview)
    if st.session_state.current_proposal_data:
         st.json(st.session_state.current_proposal_data)
    else:
         st.write("No data extracted or added yet.")

    st.subheader("Select Template")
    available_templates = get_available_templates()
    if not available_templates:
        st.error("Cannot proceed without templates. Please add '.md' files to the 'templates' directory.")
    else:
        # Use index=None for default selection prompt if template_name not set or invalid
        current_template_index = None
        if st.session_state.template_name in available_templates:
             current_template_index = available_templates.index(st.session_state.template_name)

        selected_template = st.selectbox(
            "Select a proposal template:",
            options=available_templates,
            index=current_template_index if current_template_index is not None else 0, # Default to first if none selected
            key="template_selector"
        )

        # Load template content if selection changes or not yet loaded
        if selected_template and selected_template != st.session_state.template_name or not st.session_state.template_content:
             st.session_state.template_name = selected_template
             st.session_state.template_content = load_template(selected_template)
             if st.session_state.template_content:
                 st.session_state.template_placeholders = find_placeholders(st.session_state.template_content)
                 st.text_area("Template Preview:", st.session_state.template_content, height=150, key="template_preview")
                 # Reset downstream state dependent on template
                 st.session_state.missing_keys = set()
                 st.session_state.interview_data = {} # Clear previous interview inputs
                 st.session_state.final_proposal_content = None
                 st.rerun() # Rerun to update missing keys based on new template
             else:
                 st.error(f"Failed to load template '{selected_template}'.")
                 st.session_state.template_content = None
                 st.session_state.template_placeholders = set()


# Step 3: Interview Mode (only if template loaded and proposal exists)
if st.session_state.template_content and st.session_state.proposal_id is not None:
    st.header("3. Fill Missing Information (Interview)")

    # Calculate missing keys based on current DB data and template placeholders
    st.session_state.missing_keys = st.session_state.template_placeholders - set(st.session_state.current_proposal_data.keys())

    if not st.session_state.missing_keys:
        st.success("All template placeholders are currently filled by the proposal data!")
        # Clear any lingering interview data if no longer needed
        st.session_state.interview_data = {}
    else:
        st.warning(f"Missing data required by template: **{', '.join(sorted(list(st.session_state.missing_keys)))}**")
        st.write("Please provide values for the missing items below:")

        # Use a form to collect all inputs before processing
        with st.form("interview_form"):
            interview_responses = {}
            for key in sorted(list(st.session_state.missing_keys)):
                # Use existing interview data as default if available from a previous partial submit
                default_value = st.session_state.interview_data.get(key, "")
                interview_responses[key] = st.text_input(f"Enter value for '{key}':", value=default_value, key=f"interview_{key}")

            submitted = st.form_submit_button("Submit Missing Data")
            if submitted:
                # Basic validation: check for empty responses
                valid_submission = True
                final_interview_data = {}
                for key, value in interview_responses.items():
                    cleaned_value = value.strip()
                    if not cleaned_value:
                        st.error(f"Value for '{key}' cannot be empty.")
                        valid_submission = False
                    final_interview_data[key] = cleaned_value # Store stripped value

                if valid_submission:
                    st.session_state.interview_data = final_interview_data
                    # Save the newly gathered data to the DB
                    db_session = SessionLocal()
                    try:
                        add_proposal_data(db_session, st.session_state.proposal_id, st.session_state.interview_data)
                        st.success("Missing data submitted and saved to database.")

                        # Update current_proposal_data state immediately
                        st.session_state.current_proposal_data.update(st.session_state.interview_data)
                        # Clear interview data state as it's now saved
                        st.session_state.interview_data = {}
                        # Recalculate missing keys (should now be empty)
                        st.session_state.missing_keys = st.session_state.template_placeholders - set(st.session_state.current_proposal_data.keys())
                        # Rerun to refresh the UI (remove form, update messages)
                        st.rerun()

                    except Exception as e:
                        st.error(f"Failed to save interview data to database: {e}")
                    finally:
                        db_session.close()
                else:
                     # Keep submitted (but invalid) data in state for user to correct
                     st.session_state.interview_data = interview_responses


# Step 4: Generate and Download Proposal
# Requires template selected, proposal_id set, and no missing keys
can_generate = (
    st.session_state.template_content and
    st.session_state.proposal_id is not None and
    not st.session_state.missing_keys # Ensure all keys required by template are present in current_proposal_data
)

if can_generate:
    st.header("4. Generate & Download Proposal")
    st.success("All necessary information is available.")

    if st.button("Generate Proposal Document", key="generate_button"):
        # Use the up-to-date data from session state
        full_context = st.session_state.current_proposal_data
        st.session_state.final_proposal_content = fill_template(st.session_state.template_content, full_context)

        # Final check for any remaining placeholders (shouldn't happen if logic is correct)
        remaining = find_placeholders(st.session_state.final_proposal_content)
        if remaining:
              st.warning(f"Warning: Generated proposal still contains placeholders: {', '.join(remaining)}. This might indicate an issue.")
        else:
             st.success("Proposal content generated successfully!")

        st.markdown("### Generated Proposal Preview:")
        st.text_area("", st.session_state.final_proposal_content, height=300, key="final_preview")


    # Download Button (appears after generation)
    if st.session_state.final_proposal_content:
        # Use the proposal name stored in session state
        proposal_filename = f"{st.session_state.proposal_name or 'proposal'}.md"
        st.download_button(
            label="Download Proposal as Markdown",
            data=st.session_state.final_proposal_content,
            file_name=proposal_filename,
            mime="text/markdown",
            key="download_button"
        )

# --- Footer/Debug ---
# with st.expander("Debug Info (Session State)"):
#     st.write(st.session_state) 