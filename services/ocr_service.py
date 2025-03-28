import logging
import time
import re
from mistralai import Mistral
from mistralai.models import OCRResponse

import config  # Import configuration

# --- Client Initialization ---
mistral_client = None
if config.MISTRAL_API_KEY:
    try:
        mistral_client = Mistral(api_key=config.MISTRAL_API_KEY)
        logging.info("Mistral client initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize Mistral client: {e}", exc_info=True)
else:
    logging.warning("Mistral API Key not found in config. OCR service will be unavailable.")

# --- Helper Function to Clean Markdown ---
def _remove_image_placeholders(markdown_str: str) -> str:
    """Removes markdown image tags ![alt](url) from the given string."""
    if not isinstance(markdown_str, str):
        return ""  # Return empty string if input is not a string
    # Regex to find markdown images: ![anything](anything)
    cleaned_str = re.sub(r'!\[.*?\]\(.*?\)', '', markdown_str)
    return cleaned_str.strip()

# --- Core OCR Function ---
def perform_ocr(pdf_name: str, pdf_bytes: bytes) -> list[str] | None:
    """
    Uploads a PDF, performs OCR using Mistral AI (text only), cleans image
    placeholders, and returns a list of markdown strings per page.

    Args:
        pdf_name: The original filename of the PDF.
        pdf_bytes: The content of the PDF file as bytes.

    Returns:
        A list of strings, where each string is the cleaned markdown content of a page,
        or None if a critical error occurs. Returns an empty list if OCR succeeds
        but yields no pages or no text.
    """
    if not mistral_client:
        logging.error("Mistral client is not available. Cannot perform OCR.")
        return None
    if not pdf_name or not pdf_bytes:
        logging.error("PDF name or bytes are missing.")
        return None

    logging.info(f"Starting OCR process for PDF: {pdf_name}")
    try:
        # 1. Upload PDF File
        logging.info("Step 1/3: Uploading PDF to Mistral storage...")
        start_upload = time.time()
        uploaded_file = mistral_client.files.upload(
            file={"file_name": pdf_name, "content": pdf_bytes},
            purpose="ocr",
        )
        upload_duration = time.time() - start_upload
        if not uploaded_file or not uploaded_file.id:
            raise ValueError("File upload failed or did not return a valid file ID.")
        logging.info(f"PDF uploaded successfully in {upload_duration:.2f}s. File ID: {uploaded_file.id}")
        
        # Optional short delay to ensure file availability
        time.sleep(1)

        # 2. Get Temporary Signed URL (using default expiry)
        logging.info("Step 2/3: Retrieving temporary signed URL...")
        start_url = time.time()
        signed_url = mistral_client.files.get_signed_url(file_id=uploaded_file.id)
        url_duration = time.time() - start_url
        if not signed_url or not signed_url.url:
            raise ValueError("Failed to retrieve a valid signed URL.")
        logging.info(f"Signed URL obtained in {url_duration:.2f}s.")

        # 3. Process OCR via API (Synchronous, Text Only)
        logging.info(f"Step 3/3: Calling Mistral OCR API (model: {config.OCR_MODEL}, text only)...")
        start_ocr = time.time()
        ocr_response: OCRResponse = mistral_client.ocr.process(
            model=config.OCR_MODEL,  # e.g. "mistral-ocr-latest"
            document={
                "type": "document_url",
                "document_url": signed_url.url,
            },
            include_image_base64=False  # Only text output is desired
        )
        ocr_duration = time.time() - start_ocr
        logging.info(f"Mistral OCR API call completed in {ocr_duration:.2f}s.")

        # 4. Extract and Clean Markdown Text from Each Page
        extracted_markdowns: list[str] = []
        if ocr_response and hasattr(ocr_response, 'pages') and ocr_response.pages:
            logging.info(f"Extracting and cleaning markdown from {len(ocr_response.pages)} pages...")
            for page_index, page in enumerate(ocr_response.pages):
                raw_markdown = getattr(page, 'markdown', '')
                cleaned_markdown = _remove_image_placeholders(raw_markdown)
                extracted_markdowns.append(cleaned_markdown)
                logging.debug(f"Page {page_index + 1}: Cleaned markdown length: {len(cleaned_markdown)}")
            logging.info("Finished extracting and cleaning markdown.")
        elif ocr_response and hasattr(ocr_response, 'pages') and not ocr_response.pages:
            logging.info("OCR process successful, but the response contained 0 pages.")
        else:
            logging.error("Received invalid OCR response structure (missing 'pages' or response is None).")
            return None  # Indicate failure

        return extracted_markdowns  # Return the list of cleaned markdown strings

    except Exception as e:
        logging.error(f"An error occurred during the Mistral OCR process: {e}", exc_info=True)
        return None
