import argparse
import logging
import json
import base64
from format_converters.epub_handler import epub_to_book
from format_converters.book_handler import book_to_epub
from pydantic import ValidationError

def setup_logging():
    """Sets up basic logging for the script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def main():
    """
    Main function to run the EPUB to Book JSON conversion process.
    """
    setup_logging()
    
    parser = argparse.ArgumentParser(
        description="Convert an EPUB file to a standardized Book JSON format and optionally rebuild it back to an EPUB."
    )
    parser.add_argument(
        "epub_path",
        type=str,
        help="The full path to the input EPUB file."
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="output.json",
        help="The path for the intermediate output JSON file. Defaults to 'output.json'."
    )
    parser.add_argument(
        "--output-epub",
        type=str,
        default=None,
        help="The path for the rebuilt output EPUB file. If not provided, this step is skipped."
    )
    
    args = parser.parse_args()
    
    logging.info(f"Input EPUB file: {args.epub_path}")
    logging.info(f"Output JSON file: {args.output_json}")
    if args.output_epub:
        logging.info(f"Rebuilt EPUB output file: {args.output_epub}")
    
    try:
        # Step 1: Convert EPUB to internal Book model
        logging.info("--- Step 1: Converting EPUB to internal Book model ---")
        book_model = epub_to_book(args.epub_path, logger=logging.getLogger())
        
        # Step 2: Save the intermediate JSON representation
        logging.info(f"--- Step 2: Saving internal Book model to {args.output_json} ---")
        
        # Pydantic's default JSON serializer tries to decode bytes as UTF-8, which fails for image data.
        # We need to dump to a Python dict first (mode='python'), then use a custom
        # JSON encoder to handle bytes by converting them to Base64 strings.
        book_dict = book_model.model_dump(mode='python')

        def bytes_as_b64_str(o):
            if isinstance(o, bytes):
                return base64.b64encode(o).decode('ascii')
            raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

        json_output = json.dumps(book_dict, indent=2, default=bytes_as_b64_str)

        # Write the JSON string to the output file
        with open(args.output_json, 'w', encoding='utf-8') as f:
            f.write(json_output)
            
        logging.info(f"Successfully converted EPUB and saved JSON to {args.output_json}")

        # Step 3: Rebuild the EPUB from the Book model, if requested
        if args.output_epub:
            logging.info(f"--- Step 3: Rebuilding EPUB file at {args.output_epub} ---")
            book_to_epub(book_model, args.output_epub, logger=logging.getLogger())
            logging.info(f"Successfully created rebuilt EPUB file at {args.output_epub}")
            logging.info("--- Workflow Complete: EPUB -> JSON -> EPUB ---")
        
    except FileNotFoundError:
        logging.error(f"Error: The file '{args.epub_path}' was not found.")
    except ValidationError as e:
        logging.error("Error: The EPUB data could not be validated against the Book schema.")
        logging.error(f"Pydantic validation details:\n{e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        logging.exception("Traceback:")

if __name__ == "__main__":
    main() 