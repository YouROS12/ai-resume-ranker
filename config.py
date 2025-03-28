import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file located in the project root
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

# Logging Configuration (optional basic setup)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(module)s] - %(message)s')

# API Keys and IDs
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID_EXTRACT = os.getenv("ASSISTANT_ID_EXTRACT")
ASSISTANT_ID_SCORE = os.getenv("ASSISTANT_ID_SCORE")

# Database Configuration
DATABASE_NAME = "resumes.db" # Use relative path, stored in project root

# OCR Configuration
OCR_MODEL = "mistral-ocr-latest"
OCR_SIGNED_URL_EXPIRY_SECONDS = 600 # 10 minutes

# Assistant Configuration
ASSISTANT_TIMEOUT_SECONDS = 180 # 3 minutes

# Validation (optional but recommended)
def validate_config():
    """Checks if essential configuration values are present."""
    essential_vars = {
        "MISTRAL_API_KEY": MISTRAL_API_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "ASSISTANT_ID_EXTRACT": ASSISTANT_ID_EXTRACT,
        "ASSISTANT_ID_SCORE": ASSISTANT_ID_SCORE
    }
    missing = [name for name, value in essential_vars.items() if not value]
    if missing:
        error_msg = f"Missing essential configuration variable(s) in .env file: {', '.join(missing)}"
        logging.error(error_msg)
        raise ValueError(error_msg)
    logging.info("Configuration validated successfully.")