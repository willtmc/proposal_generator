import sys
from pathlib import Path
import PyPDF2

def extract_text_from_pdf(pdf_path: Path) -> str | None:
    """Extracts text content from all pages of a PDF file."""
    if not pdf_path.is_file():
        print(f"Error: PDF file not found at '{pdf_path}'")
        return None
    
    text_content = ""
    try:
        with open(pdf_path, 'rb') as pdf_file:
            reader = PyPDF2.PdfReader(pdf_file)
            num_pages = len(reader.pages)
            print(f"Reading {num_pages} pages from '{pdf_path.name}'...")
            for page_num in range(num_pages):
                page = reader.pages[page_num]
                text_content += page.extract_text()
                # Add a separator to roughly indicate page breaks
                text_content += "\n\n--- Page Break ---\n\n"
            print("Text extraction complete.")
            return text_content
    except FileNotFoundError:
        print(f"Error: Could not open PDF file '{pdf_path}'")
        return None
    except Exception as e:
        print(f"An error occurred during PDF processing: {e}")
        return None

def save_as_markdown(text_content: str, output_path: Path):
    """Saves the extracted text content to a Markdown file."""
    try:
        # Ensure the output directory exists (saving to templates/ initially)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text_content, encoding='utf-8')
        print(f"Successfully saved raw Markdown content to: {output_path}")
    except Exception as e:
        print(f"Error saving Markdown file '{output_path}': {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_to_md.py <path_to_pdf_file>")
        sys.exit(1)

    input_pdf_path = Path(sys.argv[1])
    
    # Define output path (save in templates dir with .md extension)
    output_md_path = Path("templates") / f"{input_pdf_path.stem}.md" 

    extracted_text = extract_text_from_pdf(input_pdf_path)

    if extracted_text:
        save_as_markdown(extracted_text, output_md_path)
    else:
        print("Failed to extract text from PDF. No Markdown file created.")
        sys.exit(1) 