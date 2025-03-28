# services/assistants.py
import logging
import time
import json
from openai import OpenAI
from datetime import datetime # Import datetime

# --- Project Modules ---
try:
    import config # Import configuration
except ImportError:
    logging.error("Failed to import 'config' module. Ensure config.py exists.")
    # Define fallback defaults or raise error if config is critical
    class MockConfig: MISTRAL_API_KEY=None; OPENAI_API_KEY=None; ASSISTANT_ID_EXTRACT=None; ASSISTANT_ID_SCORE=None; ASSISTANT_TIMEOUT_SECONDS=180
    config = MockConfig()

# --- OpenAI Client Initialization ---
openai_client = None
if config.OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        logging.info("OpenAI client initialized successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize OpenAI client: {e}", exc_info=True)
else:
    logging.warning("OpenAI API Key not found in config. Assistant service will be unavailable.")


# --- Helper Function for Text Aggregation ---
def get_text_for_pages(ocr_markdowns: list[str], page_numbers: list[int]) -> str:
    """
    Combines markdown text from specific page numbers out of a list of all page markdowns.

    Args:
        ocr_markdowns: A list where each element is the cleaned markdown string for a page.
        page_numbers: A list of 1-based page numbers to combine.

    Returns:
        A single string containing the combined markdown for the requested pages.
    """
    combined_text = []
    total_pages_available = len(ocr_markdowns)

    if total_pages_available == 0:
         logging.warning("Received empty list of OCR markdowns for text aggregation.")
         return "--- Error: OCR data is empty ---"

    logging.debug(f"Aggregating text for page numbers {page_numbers} from {total_pages_available} available pages.")
    for page_num in page_numbers:
        page_index = page_num - 1
        if 0 <= page_index < total_pages_available:
            page_content = ocr_markdowns[page_index]
            if page_content is not None and page_content.strip():
                combined_text.append(f"--- Start Page {page_num} ---\n{page_content}\n--- End Page {page_num} ---")
                logging.debug(f"Added content from page {page_num} (index {page_index}).")
            else:
                logging.warning(f"Markdown content for page {page_num} (index {page_index}) is empty/None.")
                combined_text.append(f"--- Warning: Page {page_num} content is empty ---")
        else:
            logging.warning(f"Requested page number {page_num} out of bounds ({total_pages_available} pages).")
            combined_text.append(f"--- Error: Page {page_num} not found ---")

    final_text = "\n\n".join(combined_text)
    logging.debug(f"Aggregated text length: {len(final_text)}")
    return final_text


# --- Generic OpenAI Assistant Call Function ---
def call_openai_assistant(assistant_id: str, prompt: str, thread_id: str = None) -> tuple[str | None, str | None]:
    """
    Runs a specific OpenAI assistant with a given prompt and optional thread ID.
    Returns the assistant's text response and the thread ID used.
    """
    if not openai_client: logging.error("OpenAI client unavailable."); return None, thread_id
    if not assistant_id: logging.error("Assistant ID required."); return None, thread_id
    if not prompt: logging.warning("Empty prompt provided."); return None, thread_id

    logging.info(f"Calling Assistant ID: {assistant_id}")
    try:
        # Thread Management
        if not thread_id:
            thread = openai_client.beta.threads.create(messages=[{"role": "user", "content": prompt}])
            thread_id = thread.id; logging.info(f"Created new OpenAI thread {thread_id}.")
        else:
            openai_client.beta.threads.messages.create(thread_id=thread_id, role="user", content=prompt)
            logging.info(f"Added message to existing OpenAI thread {thread_id}.")

        # Run Creation and Polling
        run = openai_client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)
        logging.info(f"Started run {run.id} on thread {thread_id}.")
        start_time = time.time()
        while run.status in ['queued', 'in_progress', 'cancelling']:
            if time.time() - start_time > config.ASSISTANT_TIMEOUT_SECONDS:
                logging.error(f"Run {run.id} timed out after {config.ASSISTANT_TIMEOUT_SECONDS}s.")
                try: openai_client.beta.threads.runs.cancel(thread_id=thread_id, run_id=run.id)
                except Exception as ce: logging.error(f"Failed to cancel run {run.id}: {ce}")
                return None, thread_id
            time.sleep(2); run = openai_client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            logging.debug(f"Run {run.id} status: {run.status}")

        # Process Final Run Status
        if run.status == 'completed':
            messages = openai_client.beta.threads.messages.list(thread_id=thread_id, order='desc', limit=10)
            for msg in messages.data:
                if msg.role == 'assistant' and msg.content and msg.content[0].type == 'text':
                    resp = msg.content[0].text.value; logging.info(f"Run {run.id} completed.")
                    return resp, thread_id
            logging.warning(f"Run {run.id} completed but no assistant text message found."); return None, thread_id
        elif run.status == 'requires_action':
             logging.error(f"Run {run.id} requires action (not handled)."); return None, thread_id
        else: # failed, cancelled, expired
            err = run.last_error or "No specific error."; logging.error(f"Run {run.id} ended: {run.status}. Details: {err}"); return None, thread_id
    except Exception as e:
        logging.error(f"Exception during OpenAI call (ID: {assistant_id}): {e}", exc_info=True)
        return None, thread_id


# --- Orchestration Function for the Two-Step Process ---
def process_single_resume_group(page_group: list[int], ocr_data: list[str], job_description: str) -> tuple[dict | None, dict | None, str | None, str | None]:
    """
    Processes a single resume group: aggregates text, calls extraction (1)
    and scoring (2) assistants, adding date context to scorer prompt.

    Returns:
        Tuple: (extracted_data, scored_data, raw_json_extract, raw_json_score)
    """
    page_range_str = f"{page_group[0]}-{page_group[-1]}" if len(page_group) > 1 else str(page_group[0])
    logging.info(f"--- Starting processing: Pages {page_range_str} ---")

    extracted_data = None; scored_data = None
    raw_json_extract = None; raw_json_score = None

    # == Step 1: Extraction using Assistant 1 ==
    logging.info(f"Step 1/2: Calling Extractor ({config.ASSISTANT_ID_EXTRACT}) for {page_range_str}...")
    # 1a. Aggregate Text
    try:
        combined_text = get_text_for_pages(ocr_data, page_group)
        if not combined_text or "--- Error:" in combined_text:
            log_msg = f"Failed valid text aggregation for {page_range_str}."; logging.error(log_msg)
            return None, None, f"Error: {log_msg}", None
    except Exception as e:
        logging.error(f"Exception aggregating text for {page_range_str}: {e}", exc_info=True)
        return None, None, "Error: Exception during text aggregation", None

    # 1b. Call Assistant 1
    raw_json_extract, _ = call_openai_assistant(config.ASSISTANT_ID_EXTRACT, combined_text)

    # 1c. Parse Extraction Response
    if raw_json_extract:
        try:
            logging.debug("Parsing extraction response...")
            json_str = raw_json_extract.strip()
            if json_str.startswith("```json"): json_str = json_str[7:]
            if json_str.endswith("```"): json_str = json_str[:-3]
            extracted_data = json.loads(json_str.strip())
            logging.info(f"Parsed extracted data for {page_range_str}.")
        except Exception as e:
            logging.error(f"Failed parsing Extraction AI for {page_range_str}: {e}", exc_info=True)
            extracted_data = None # Ensure failure
    else:
        logging.warning(f"No response from Extraction AI for {page_range_str}.")
        raw_json_extract = "Error: No response from Extraction AI"

    if not extracted_data:
        logging.error(f"Extraction failed/unparsed for {page_range_str}. Skipping scoring.")
        return None, None, raw_json_extract, None

    # == Step 2: Scoring using Assistant 2 ==
    logging.info(f"Step 2/2: Calling Scorer ({config.ASSISTANT_ID_SCORE}) for {page_range_str}...")
    # 2a. Get current date and prepare prompt
    current_date_str = datetime.now().strftime('%d/%m/%Y')
    logging.info(f"Adding current date to scorer prompt: {current_date_str}")
    
    prompt_for_scorer = f"""
    Current Date: {current_date_str}. 

    Candidate Data: ```json\n{json.dumps(extracted_data, indent=2)}\n```
    Job Description: ```\n{job_description}\n```
    """

    # 2b. Call Assistant 2
    raw_json_score, _ = call_openai_assistant(config.ASSISTANT_ID_SCORE, prompt_for_scorer)

    # 2c. Parse Scoring Response
    if raw_json_score:
        try:
            logging.debug("Parsing scoring response...")
            json_str = raw_json_score.strip()
            if json_str.startswith("```json"): json_str = json_str[7:]
            if json_str.endswith("```"): json_str = json_str[:-3]
            scored_data = json.loads(json_str.strip())
            # Optional: Validate presence of required keys
            if not all(k in scored_data for k in ["score_percent", "overall_score_percent"]):
                logging.warning("Scoring response missing required score fields.")
            logging.info(f"Parsed scored data for {page_range_str}.")
        except Exception as e:
            logging.error(f"Failed parsing Scoring AI for {page_range_str}: {e}", exc_info=True)
            scored_data = None
    else:
        logging.warning(f"No response from Scoring AI for {page_range_str}.")
        raw_json_score = "Error: No response from Scoring AI"

    # Use placeholder if scoring failed
    if not scored_data:
        logging.warning(f"Scoring failed/unparsed for {page_range_str}. Using placeholder.")
        scored_data = {"score_percent": None, "reasoning": "Scoring failed", "matched_skills": [], "missing_skills": [], "overall_score_percent": None}
        if raw_json_score is None: raw_json_score = scored_data["reasoning"]

    logging.info(f"--- Finished processing: Pages {page_range_str} ---")
    # Return results (extracted_data does NOT contain the date)
    return extracted_data, scored_data, raw_json_extract, raw_json_score