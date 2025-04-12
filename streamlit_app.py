import streamlit as st
import requests
import os
import sys
from pathlib import Path
import time
import io # Needed for handling file streams

# Import new libraries for file handling
import PyPDF2
import docx # python-docx
import pytesseract
from PIL import Image # Pillow

# --- Configuration ---
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:8000")
EXTRACT_ENDPOINT = f"{FASTAPI_URL}/extract-context"

# Import database and generator functions
try:
    from database import SessionLocal, create_proposal, add_proposal_data, get_proposal_with_data, Proposal, init_db
    from proposal_generator import load_jinja_template, find_jinja_placeholders, fill_template_jinja, TEMPLATE_DIR # <-- Updated imports
except ImportError as e:
    st.error(f"Fatal Error: Could not import modules: {e}. Check paths and installations.")
    st.stop()
except Exception as e:
    st.error(f"Fatal Error: An unexpected error occurred during module import: {e}")
    st.stop()


# --- Text Extraction Helper Functions ---

def extract_text_from_txt(file_content: bytes) -> str:
    """Extracts text from bytes assuming UTF-8 encoding."""
    try:
        return file_content.decode('utf-8')
    except UnicodeDecodeError:
        st.warning("Could not decode .txt file as UTF-8, trying latin-1.")
        try:
            return file_content.decode('latin-1')
        except Exception as e:
            st.error(f"Error decoding .txt file: {e}")
            return ""

def extract_text_from_pdf(file_stream) -> str:
    """Extracts text from a PDF file stream."""
    try:
        reader = PyPDF2.PdfReader(file_stream)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        st.error(f"Error reading PDF content: {e}")
        return ""

def extract_text_from_docx(file_stream) -> str:
    """Extracts text from a DOCX file stream."""
    try:
        document = docx.Document(file_stream)
        text = "\n".join([para.text for para in document.paragraphs])
        return text
    except Exception as e:
        st.error(f"Error reading DOCX content: {e}")
        return ""

def extract_text_from_image(file_stream) -> str:
    """Extracts text from an image file stream using Tesseract OCR."""
    try:
        # Check if tesseract is installed and accessible
        # You might need to configure the path if tesseract isn't in the system PATH
        # pytesseract.pytesseract.tesseract_cmd = r'/path/to/tesseract' # Example if needed
        img = Image.open(file_stream)
        text = pytesseract.image_to_string(img)
        return text
    except Exception as e:
        # Catch specific Tesseract errors if possible, e.g., TesseractNotFoundError
        st.error(f"Error performing OCR on image: {e}. Ensure Tesseract is installed and in PATH.")
        return ""


# --- Other Helper Functions ---

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
            st.stop()

ensure_db_initialized()


# --- Streamlit App ---
st.set_page_config(layout="wide")
st.title("AI Proposal Generator Assistant")

# --- State Initialization ---
# Keep existing state variables, add one for combined text
if 'proposal_id' not in st.session_state:
    st.session_state.proposal_id = None
if 'proposal_name' not in st.session_state:
    st.session_state.proposal_name = None
if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = None
# if 'uploaded_filename' not in st.session_state: # Replace single filename with list
#     st.session_state.uploaded_filename = None
if 'uploaded_file_names' not in st.session_state:
    st.session_state.uploaded_file_names = []
if 'combined_context_text' not in st.session_state:
    st.session_state.combined_context_text = ""
if 'template_name' not in st.session_state:
    st.session_state.template_name = None
if 'template_object' not in st.session_state: # Store Jinja template object
    st.session_state.template_object = None
if 'template_placeholders' not in st.session_state:
    st.session_state.template_placeholders = set()
if 'current_proposal_data' not in st.session_state:
    st.session_state.current_proposal_data = {}
if 'missing_keys' not in st.session_state:
    st.session_state.missing_keys = set()
if 'interview_data' not in st.session_state:
    st.session_state.interview_data = {}
if 'final_proposal_content' not in st.session_state:
    st.session_state.final_proposal_content = None


# --- Workflow Steps ---

# Step 1: File Upload and Context Extraction
st.header("1. Upload Context & Extract Data")
st.write("Upload one or more context documents (.txt, .pdf, .docx, .png, .jpg, .jpeg). Their text content will be combined and sent to the AI for key information extraction.")

uploaded_files = st.file_uploader(
    "Upload context documents:",
    type=['txt', 'pdf', 'docx', 'png', 'jpg', 'jpeg'],
    accept_multiple_files=True, # Allow multiple files
    key="file_uploader"
)

# Check if the list of uploaded files has changed
current_file_names = sorted([f.name for f in uploaded_files])
if uploaded_files and current_file_names != st.session_state.get('uploaded_file_names', []):
    st.info(f"Processing {len(uploaded_files)} file(s): {', '.join(current_file_names)}")
    # Reset downstream state when new files are uploaded
    st.session_state.proposal_id = None
    st.session_state.proposal_name = None
    st.session_state.extracted_data = None
    st.session_state.current_proposal_data = {}
    st.session_state.interview_data = {}
    st.session_state.missing_keys = set()
    st.session_state.final_proposal_content = None
    st.session_state.combined_context_text = ""
    st.session_state.uploaded_file_names = current_file_names # Mark as processed

    all_text = []
    has_errors = False
    with st.spinner("Extracting text from uploaded files..."):
        for uploaded_file in uploaded_files:
            st.write(f" - Processing {uploaded_file.name}...")
            file_stream = io.BytesIO(uploaded_file.getvalue())
            text = ""
            file_type = Path(uploaded_file.name).suffix.lower()

            if file_type == '.txt':
                text = extract_text_from_txt(uploaded_file.getvalue()) # txt needs bytes directly
            elif file_type == '.pdf':
                text = extract_text_from_pdf(file_stream)
            elif file_type == '.docx':
                text = extract_text_from_docx(file_stream)
            elif file_type in ['.png', '.jpg', '.jpeg']:
                text = extract_text_from_image(file_stream)
            else:
                st.warning(f"Unsupported file type: {uploaded_file.name}")
                continue # Skip unsupported types

            if text:
                all_text.append(text)
            else:
                # Error messages are shown within the extractor functions
                st.warning(f"Could not extract text from {uploaded_file.name}.")
                # Decide if partial failure should stop the whole process
                # has_errors = True

    # Combine text from all successfully processed files
    st.session_state.combined_context_text = "\n\n--- File Separator ---\n\n".join(all_text)

    if not st.session_state.combined_context_text.strip():
        st.error("Failed to extract any text from the uploaded files.")
        st.session_state.uploaded_file_names = [] # Allow re-upload if all failed
    else:
        st.success("Text extraction complete.")
        st.text_area("Combined Text Preview (first 1000 chars):", st.session_state.combined_context_text[:1000] + "...", height=200, key="combined_preview")

        # --- Call AI for Extraction --- (Moved here to run after all files processed)
        with st.spinner("Sending combined text to AI for context extraction..."):
            try:
                response = requests.post(EXTRACT_ENDPOINT, json={"text": st.session_state.combined_context_text}, timeout=120) # Increased timeout
                response.raise_for_status()
                extracted = response.json().get("data", {})
                st.session_state.extracted_data = extracted if isinstance(extracted, dict) else {}
                st.success("AI extraction successful!")

                # --- Create Proposal in DB --- (Moved here)
                db_session = SessionLocal()
                try:
                    proposal_name_base = "proposal_from_upload"
                    if current_file_names:
                         proposal_name_base = Path(current_file_names[0]).stem # Use first filename as base
                    timestamp = int(time.time())
                    st.session_state.proposal_name = f"{proposal_name_base}_{timestamp}"
                    new_proposal = create_proposal(db_session, st.session_state.proposal_name)
                    st.session_state.proposal_id = new_proposal.id

                    if st.session_state.extracted_data:
                        add_proposal_data(db_session, new_proposal.id, st.session_state.extracted_data)
                        st.session_state.current_proposal_data = st.session_state.extracted_data
                        st.success(f"Extracted data saved to new proposal '{st.session_state.proposal_name}' (ID: {st.session_state.proposal_id}).")
                    else:
                        st.warning("AI did not return any structured data.")
                        st.session_state.current_proposal_data = {}
                    st.rerun() # Rerun to update UI state

                except Exception as db_error:
                    st.error(f"Database error after extraction: {db_error}")
                    st.session_state.proposal_id = None
                    st.session_state.proposal_name = None
                    st.session_state.current_proposal_data = {}
                finally:
                    db_session.close()

            except requests.exceptions.Timeout:
                 st.error("Error calling extraction API: Request timed out.")
            except requests.exceptions.ConnectionError:
                 st.error(f"Error calling extraction API: Could not connect to the backend at {FASTAPI_URL}.")
            except requests.exceptions.RequestException as e:
                 st.error(f"Error calling extraction API: {e}")
            except Exception as e:
                 st.error(f"An unexpected error occurred during AI processing: {e}")

            # If extraction or DB saving failed, clear related state
            if st.session_state.proposal_id is None:
                st.session_state.extracted_data = None
                st.session_state.current_proposal_data = {}

# Step 2: Review Data and Select Template
if st.session_state.proposal_id is not None:
    st.header("2. Review Data & Select Template")
    st.info(f"Working with Proposal: **{st.session_state.proposal_name}** (ID: {st.session_state.proposal_id})")

    st.subheader("Current Proposal Data")
    if st.session_state.current_proposal_data:
         st.json(st.session_state.current_proposal_data)
    else:
         st.write("No data extracted or added yet.")

    st.subheader("Select Template")
    available_templates = get_available_templates()
    if not available_templates:
        st.error("Cannot proceed without templates. Please add '.md' files to the 'templates' directory.")
    else:
        current_template_index = None
        if st.session_state.template_name in available_templates:
             current_template_index = available_templates.index(st.session_state.template_name)

        selected_template = st.selectbox(
            "Select a proposal template:",
            options=available_templates,
            index=current_template_index if current_template_index is not None else 0,
            key="template_selector"
        )

        # Load Jinja template object if selection changes or not yet loaded
        if selected_template and (selected_template != st.session_state.template_name or not st.session_state.template_object):
            st.session_state.template_name = selected_template
            # Load Jinja Template Object
            st.session_state.template_object = load_jinja_template(selected_template)
            if st.session_state.template_object:
                # Get placeholders using Jinja parser
                st.session_state.template_placeholders = find_jinja_placeholders(f"{selected_template}.md")
                # Get template content for preview (can read source from loaded template)
                try:
                    template_content_preview = st.session_state.template_object.environment.loader.get_source(st.session_state.template_object.environment, st.session_state.template_object.name)[0]
                    st.text_area("Template Preview:", template_content_preview, height=150, key="template_preview")
                except Exception:
                    st.warning("Could not display template preview.") # Non-critical
                
                st.session_state.missing_keys = set()
                st.session_state.interview_data = {}
                st.session_state.final_proposal_content = None
                st.rerun()
            else:
                st.error(f"Failed to load template '{selected_template}'.")
                st.session_state.template_object = None
                st.session_state.template_placeholders = set()


# Step 3: Interview Mode
if st.session_state.template_object and st.session_state.proposal_id is not None:
    st.header("3. Fill Missing Information (Interview)")

    # Recalculate missing keys based on Jinja placeholders and current DB data
    # Ensure current_proposal_data has number conversions if needed for comparison, though less critical here
    # For simplicity, we compare against string keys from the Jinja analysis
    st.session_state.missing_keys = st.session_state.template_placeholders - set(st.session_state.current_proposal_data.keys())

    # Remove calculated keys explicitly
    calculated_keys = {'marketing_total_budget', 'retainer_amount'}
    st.session_state.missing_keys.difference_update(calculated_keys)

    if not st.session_state.missing_keys:
        st.success("All template placeholders are currently filled by the proposal data!")
        st.session_state.interview_data = {}
    else:
        st.warning(f"Missing data required by template: **{', '.join(sorted(list(st.session_state.missing_keys)))}**")
        st.write("Please provide values for the missing items below:")

        with st.form("interview_form"):
            interview_responses = {}
            for key in sorted(list(st.session_state.missing_keys)):
                default_value = st.session_state.interview_data.get(key, "")
                # TODO: Use st.number_input for specific keys if desired
                # Example: if key in ['marketing_facebook_cost', ...]:
                #     interview_responses[key] = st.number_input(..., format="%.2f")
                # else: 
                interview_responses[key] = st.text_input(f"Enter value for '{key}':", value=default_value, key=f"interview_{key}")

            submitted = st.form_submit_button("Submit Missing Data")
            if submitted:
                valid_submission = True
                final_interview_data = {}
                for key, value in interview_responses.items():
                    # Convert potentially numeric inputs back to string for DB
                    # More robust handling needed if using st.number_input
                    cleaned_value = str(value).strip()
                    if not cleaned_value:
                        st.error(f"Value for '{key}' cannot be empty.")
                        valid_submission = False
                    final_interview_data[key] = cleaned_value

                if valid_submission:
                    st.session_state.interview_data = final_interview_data
                    db_session = SessionLocal()
                    try:
                        # Save data as strings
                        add_proposal_data(db_session, st.session_state.proposal_id, st.session_state.interview_data)
                        st.success("Missing data submitted and saved to database.")
                        # Update state - note data is stringified here
                        st.session_state.current_proposal_data.update(st.session_state.interview_data)
                        st.session_state.interview_data = {}
                        # Recalculate missing keys
                        st.session_state.missing_keys = st.session_state.template_placeholders - set(st.session_state.current_proposal_data.keys())
                        st.session_state.missing_keys.difference_update(calculated_keys)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save interview data to database: {e}")
                    finally:
                        db_session.close()
                else:
                    st.session_state.interview_data = interview_responses

# Step 4: Generate and Download Proposal
can_generate = (
    st.session_state.template_object and
    st.session_state.proposal_id is not None and
    not st.session_state.missing_keys
)

if can_generate:
    st.header("4. Generate & Download Proposal")
    st.success("All necessary information is available.")

    if st.button("Generate Proposal Document", key="generate_button"):
        db_session = SessionLocal()
        try:
            # Fetch latest data and ensure number conversion for Jinja context
            db_proposal = get_proposal_with_data(db_session, st.session_state.proposal_id)
            full_context = get_proposal_data_as_dict(db_proposal) # Use helper that converts numbers
            
            # Add calculated values
            marketing_keys = ['marketing_facebook_cost', 'marketing_google_cost', 'marketing_mail_cost', 'marketing_drone_cost', 'marketing_sign_cost']
            marketing_total_budget = sum(float(full_context.get(key, 0) or 0) for key in marketing_keys)
            retainer_amount = 10000 - marketing_total_budget
            full_context['marketing_total_budget'] = marketing_total_budget
            full_context['retainer_amount'] = retainer_amount

            # Render using Jinja template object
            st.session_state.final_proposal_content = fill_template_jinja(st.session_state.template_object, full_context)

            if st.session_state.final_proposal_content.startswith("Error rendering template:"):
                st.error("Proposal generation failed due to template rendering error.")
                st.session_state.final_proposal_content = None # Clear on error
            else:
                st.success("Proposal content generated successfully!")
                st.markdown("### Generated Proposal Preview:")
                st.text_area("Generated Proposal Preview Text", st.session_state.final_proposal_content, height=300, key="final_preview", label_visibility="collapsed")
        except Exception as e:
            st.error(f"An error occurred during final proposal generation: {e}")
            st.session_state.final_proposal_content = None
        finally:
            db_session.close()

    # ... (Download Button logic - remains the same) ...
    if st.session_state.final_proposal_content:
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