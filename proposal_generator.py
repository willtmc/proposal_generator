import os
import re
from pathlib import Path
from sqlalchemy.orm import Session
from database import SessionLocal, get_proposal_with_data, add_proposal_data, Proposal # Import necessary DB components


# --- Configuration ---
TEMPLATE_DIR = Path("templates")
OUTPUT_DIR = Path("output_proposals")


# --- Helper Functions ---

def load_template(template_name: str) -> str | None:
    """Loads a Markdown template from the templates directory."""
    template_path = TEMPLATE_DIR / f"{template_name}.md"
    if not template_path.is_file():
        print(f"Error: Template '{template_name}.md' not found in {TEMPLATE_DIR}")
        return None
    try:
        return template_path.read_text()
    except Exception as e:
        print(f"Error reading template '{template_name}.md': {e}")
        return None

def find_placeholders(template_content: str) -> set[str]:
    """Finds all placeholders in the format {placeholder_name} in the template."""
    # Regex to find {word}
    placeholders = re.findall(r"\{([a-zA-Z0-9_]+)\}", template_content)
    return set(placeholders)

def get_proposal_data_as_dict(db_proposal: Proposal) -> dict[str, str]:
    """Converts the ProposalData entries into a simple key-value dictionary."""
    if not db_proposal or not db_proposal.data_entries:
        return {}
    return {entry.key: entry.value for entry in db_proposal.data_entries if entry.value is not None}

def interactive_interview(missing_keys: set[str]) -> dict[str, str]:
    """Conducts an interactive interview in the terminal to fill missing data."""
    print("\n--- Interactive Interview ---")
    print("Please provide values for the following missing pieces of information:")
    filled_data = {}
    for key in sorted(list(missing_keys)): # Ask in alphabetical order
        while True:
            value = input(f"  Enter value for '{key}': ").strip()
            if value: # Require some input
                filled_data[key] = value
                break
            else:
                print("  Input cannot be empty. Please provide a value.")
    print("--- Interview Complete ---")
    return filled_data

def fill_template(template_content: str, context_data: dict) -> str:
    """Fills the placeholders in the template with context data."""
    filled_content = template_content
    for key, value in context_data.items():
        placeholder = f"{{{key}}}"
        filled_content = filled_content.replace(placeholder, str(value)) # Ensure value is string
    return filled_content

def save_proposal(proposal_name: str, content: str):
    """Saves the filled proposal to the output directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True) # Ensure output dir exists
    output_path = OUTPUT_DIR / f"{proposal_name.replace(' ', '_').lower()}_proposal.md"
    try:
        output_path.write_text(content)
        print(f"Proposal saved successfully to: {output_path}")
    except Exception as e:
        print(f"Error saving proposal '{output_path}': {e}")

# --- Main Generator Logic ---

def generate_proposal(db: Session, proposal_id: int, template_name: str):
    """Generates a proposal by fetching data, interviewing for missing info, and filling a template."""
    print(f"\nGenerating proposal for ID: {proposal_id} using template: '{template_name}'")

    # 1. Load Template
    template_content = load_template(template_name)
    if not template_content:
        return

    # 2. Find Placeholders
    placeholders = find_placeholders(template_content)
    if not placeholders:
        print(f"Warning: No placeholders found in template '{template_name}'. Output will be the same as template.")

    # 3. Fetch Existing Proposal Data
    db_proposal = get_proposal_with_data(db, proposal_id)
    if not db_proposal:
        print(f"Error: Proposal with ID {proposal_id} not found in the database.")
        return

    existing_data = get_proposal_data_as_dict(db_proposal)
    print(f"Found {len(existing_data)} existing data points for proposal '{db_proposal.name}'.")

    # 4. Identify Missing Data
    missing_keys = placeholders - set(existing_data.keys())

    # 5. Interactive Interview for Missing Data
    newly_filled_data = {}
    if missing_keys:
        print(f"Missing data for placeholders: {sorted(list(missing_keys))}")
        newly_filled_data = interactive_interview(missing_keys)
        # Optionally: Save newly gathered data back to the database
        try:
            add_proposal_data(db, proposal_id, newly_filled_data)
            print(f"Successfully saved {len(newly_filled_data)} new data points to the database.")
        except Exception as e:
            print(f"Warning: Failed to save newly gathered data to DB for proposal {proposal_id}: {e}")
            # Decide if generation should continue even if saving failed
            # For now, we continue
    else:
        print("All required placeholders are filled from existing data.")

    # 6. Combine Data and Fill Template
    full_context = {**existing_data, **newly_filled_data}
    final_proposal_content = fill_template(template_content, full_context)

    # 7. Check if any placeholders remain (e.g., if interview failed or data was None)
    remaining_placeholders = find_placeholders(final_proposal_content)
    if remaining_placeholders:
        print(f"Warning: The following placeholders remain unfilled: {remaining_placeholders}")

    # 8. Save Filled Proposal
    save_proposal(db_proposal.name, final_proposal_content)

# --- Entry Point ---

if __name__ == "__main__":
    # Example Usage:
    # Replace with actual Proposal ID and desired template name
    target_proposal_id = 1
    target_template_name = "basic_template"

    # Basic argument parsing or prompt user
    try:
        proposal_id_input = input(f"Enter the Proposal ID to generate (default: {target_proposal_id}): ").strip()
        if proposal_id_input:
            target_proposal_id = int(proposal_id_input)

        template_name_input = input(f"Enter the template name (without .md) (default: {target_template_name}): ").strip()
        if template_name_input:
            target_template_name = template_name_input

    except ValueError:
        print("Invalid input. Please enter a number for the Proposal ID.")
        exit(1)
    except EOFError: # Handle Ctrl+D or empty input if run non-interactively
        print("Input cancelled. Exiting.")
        exit(0)


    # Get DB session
    db_session = SessionLocal()
    try:
        generate_proposal(db_session, target_proposal_id, target_template_name)
    except Exception as e:
        print(f"\nAn unexpected error occurred during proposal generation: {e}")
    finally:
        db_session.close()
        print("\nProposal generation process finished.") 