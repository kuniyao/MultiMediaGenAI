import argparse
import logging
import json
from format_converters.epub_handler import epub_to_book
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
        description="Convert an EPUB file to a standardized Book JSON format."
    )
    parser.add_argument(
        "epub_path",
        type=str,
        help="The full path to the input EPUB file."
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output.json",
        help="The path for the output JSON file. Defaults to 'output.json'."
    )
    
    args = parser.parse_args()
    
    logging.info(f"Input EPUB file: {args.epub_path}")
    logging.info(f"Output JSON file: {args.output}")
    
    try:
        # Call the main conversion function
        book_model = epub_to_book(args.epub_path, logger=logging.getLogger())
        
        # Convert the Pydantic model to a JSON string
        # `indent=2` makes the JSON file human-readable
        # In Pydantic V2, ensure_ascii=False is the default behavior.
        json_output = book_model.model_dump_json(indent=2)
        
        # Write the JSON string to the output file
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(json_output)
            
        logging.info(f"Successfully converted EPUB and saved JSON to {args.output}")
        
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