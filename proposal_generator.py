import os
import re
from pathlib import Path
from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape # Jinja2 imports
from database import SessionLocal, get_proposal_with_data, add_proposal_data, Proposal # Import necessary DB components


# --- Configuration ---
TEMPLATE_DIR = Path("templates")
OUTPUT_DIR = Path("output_proposals")

# Setup Jinja2 environment
# We assume templates are directly in TEMPLATE_DIR
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape([]) # Disable autoescaping for Markdown
)

# --- Helper Functions ---

def load_jinja_template(template_name: str):
    """Loads a Jinja2 template object."""
    # Jinja expects filename with extension
    template_filename = f"{template_name}.md"
    try:
        return jinja_env.get_template(template_filename)
    except TemplateNotFound:
        print(f"Error: Jinja template '{template_filename}' not found in {TEMPLATE_DIR}")
        return None
    except Exception as e:
        print(f"Error loading Jinja template '{template_filename}': {e}")
        return None


def find_jinja_placeholders(template_filename: str) -> set[str]:
    """Finds all variable names used in a Jinja2 template."""
    try:
        template_source = jinja_env.loader.get_source(jinja_env, template_filename)[0]
        parsed_content = jinja_env.parse(template_source)
        from jinja2.meta import find_undeclared_variables
        return find_undeclared_variables(parsed_content)
    except TemplateNotFound:
        print(f"Error: Cannot find template '{template_filename}' to parse for placeholders.")
        return set()
    except Exception as e:
        print(f"Error parsing Jinja template '{template_filename}' for placeholders: {e}")
        return set()

def get_proposal_data_as_dict(db_proposal: Proposal) -> dict:
    """Converts ProposalData to dict, attempting number conversion for budget keys."""
    if not db_proposal or not db_proposal.data_entries:
        return {}
    
    data = {}
    for entry in db_proposal.data_entries:
        if entry.value is None:
            continue
        # Attempt to convert known numeric fields (add more keys if needed)
        # Modify keys based on the ones used in the template for budget
        if entry.key in ['marketing_facebook_cost', 'marketing_google_cost', 'marketing_mail_cost', 'marketing_drone_cost', 'marketing_sign_cost']:
            try:
                data[entry.key] = float(entry.value.replace('$', '').replace(',', ''))
            except (ValueError, TypeError):
                print(f"Warning: Could not convert value '{entry.value}' for key '{entry.key}' to float. Using as string.")
                data[entry.key] = entry.value # Fallback to string
        else:
            data[entry.key] = entry.value
    return data

def interactive_interview(missing_keys: set[str]) -> dict:
    """Conducts interview, attempting number conversion for budget keys."""
    print("\n--- Interactive Interview ---")
    print("Please provide values for the following missing pieces of information:")
    filled_data = {}
    for key in sorted(list(missing_keys)):
        while True:
            value = input(f"  Enter value for '{key}': ").strip()
            if value:
                # Attempt conversion for specific keys
                if key in ['marketing_facebook_cost', 'marketing_google_cost', 'marketing_mail_cost', 'marketing_drone_cost', 'marketing_sign_cost']:
                    try:
                        filled_data[key] = float(value.replace('$', '').replace(',', ''))
                        break
                    except ValueError:
                        print("  Invalid number format. Please enter a valid number (e.g., 5000 or 120.50).")
                else:
                    filled_data[key] = value
                    break
            else:
                print("  Input cannot be empty. Please provide a value.")
    print("--- Interview Complete ---")
    return filled_data

def fill_template_jinja(template, context_data: dict) -> str:
    """Fills the Jinja2 template with context data."""
    try:
        return template.render(context_data)
    except Exception as e:
        print(f"Error rendering Jinja template: {e}")
        # Optionally return a partial render or an error message string
        return f"Error rendering template: {e}"

def save_proposal(proposal_name: str, content: str):
    """Saves the filled proposal to the output directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True) # Ensure output dir exists
    output_path = OUTPUT_DIR / f"{proposal_name.replace(' ', '_').lower()}_proposal.md"
    try:
        output_path.write_text(content, encoding='utf-8') # Ensure utf-8 encoding
        print(f"Proposal saved successfully to: {output_path}")
    except Exception as e:
        print(f"Error saving proposal '{output_path}': {e}")

# --- Main Generator Logic ---

def generate_proposal(db: Session, proposal_id: int, template_name: str):
    """Generates a proposal using Jinja2: fetching data, interviewing, filling template."""
    print(f"\nGenerating proposal for ID: {proposal_id} using template: '{template_name}'")

    # 1. Load Jinja Template
    template = load_jinja_template(template_name)
    if not template:
        return

    # 2. Find Placeholders (using Jinja2's meta analysis)
    template_filename = f"{template_name}.md"
    placeholders = find_jinja_placeholders(template_filename)
    if not placeholders:
        print(f"Warning: No variable placeholders found in Jinja template '{template_filename}'.")
    else:
        print(f"Template requires placeholders: {placeholders}")

    # 3. Fetch Existing Proposal Data (with number conversion attempt)
    db_proposal = get_proposal_with_data(db, proposal_id)
    if not db_proposal:
        print(f"Error: Proposal with ID {proposal_id} not found in the database.")
        return

    existing_data = get_proposal_data_as_dict(db_proposal)
    print(f"Found {len(existing_data)} existing data points for proposal '{db_proposal.name}'.")

    # 4. Identify Missing Data
    # Compare Jinja placeholders with keys in our fetched data dictionary
    missing_keys = placeholders - set(existing_data.keys())
    
    # --- Remove calculated keys from missing set --- 
    # These are calculated in Python, not expected from DB or interview
    calculated_keys = {'marketing_total_budget', 'retainer_amount'}
    missing_keys.difference_update(calculated_keys)

    # 5. Interactive Interview for Missing Data (with number conversion attempt)
    newly_filled_data = {}
    if missing_keys:
        print(f"Missing data for placeholders: {sorted(list(missing_keys))}")
        newly_filled_data = interactive_interview(missing_keys)
        # Save newly gathered data back to the database (convert numbers back to string for DB)
        try:
            save_data = {k: str(v) for k, v in newly_filled_data.items()} # Convert all back to string for DB
            add_proposal_data(db, proposal_id, save_data)
            print(f"Successfully saved {len(newly_filled_data)} new data points to the database.")
        except Exception as e:
            print(f"Warning: Failed to save newly gathered data to DB for proposal {proposal_id}: {e}")
    else:
        print("All required placeholders are filled from existing data.")

    # 6. Combine Data and Fill Template using Jinja2
    full_context = {**existing_data, **newly_filled_data}
    
    # --- Calculate derived values --- 
    # Calculate total marketing budget from individual items if they exist
    marketing_keys = [
        'marketing_facebook_cost', 'marketing_google_cost', 
        'marketing_mail_cost', 'marketing_drone_cost', 'marketing_sign_cost'
    ]
    marketing_total_budget = 0
    try:
        for key in marketing_keys:
            # Use .get to avoid KeyError if a key is missing, default to 0
            marketing_total_budget += float(full_context.get(key, 0) or 0)
        # Add the calculated total to the context for the template
        full_context['marketing_total_budget'] = marketing_total_budget
        print(f"Calculated marketing_total_budget: {marketing_total_budget}")
        
        # --- Calculate retainer amount --- 
        retainer_amount = 10000 - marketing_total_budget
        full_context['retainer_amount'] = retainer_amount
        print(f"Calculated retainer_amount: {retainer_amount}")
        
    except (ValueError, TypeError) as e:
        print(f"Warning: Could not calculate total marketing budget or retainer due to non-numeric value(s): {e}. Values might be incorrect in template.")
        # Decide how to handle: maybe set total/retainer to 0 or pass None?
        full_context['marketing_total_budget'] = 0 # Default to 0 on error
        full_context['retainer_amount'] = 10000 # Default retainer if budget calc fails

    final_proposal_content = fill_template_jinja(template, full_context)

    # 7. Check if rendering failed (basic check)
    if final_proposal_content.startswith("Error rendering template:"):
         print("Proposal generation failed due to template rendering error.")
         return # Stop here if rendering failed

    # 8. Save Filled Proposal
    save_proposal(db_proposal.name, final_proposal_content)

# --- Entry Point ---

if __name__ == "__main__":
    target_proposal_id = 1
    # Make sure to use the correct template name (without .md)
    target_template_name = "Real Estate Auction Proposal" # Default to the one we refined

    try:
        proposal_id_input = input(f"Enter the Proposal ID to generate (default: {target_proposal_id}): ").strip()
        if proposal_id_input:
            target_proposal_id = int(proposal_id_input)

        template_name_input = input(f"Enter the template name (without .md, e.g., Real Estate Auction Proposal) (default: {target_template_name}): ").strip()
        if template_name_input:
            target_template_name = template_name_input

    except ValueError:
        print("Invalid input. Please enter a number for the Proposal ID.")
        exit(1)
    except EOFError:
        print("Input cancelled. Exiting.")
        exit(0)

    db_session = SessionLocal()
    try:
        generate_proposal(db_session, target_proposal_id, target_template_name)
    except Exception as e:
        print(f"\nAn unexpected error occurred during proposal generation: {e}")
    finally:
        db_session.close()
        print("\nProposal generation process finished.") 