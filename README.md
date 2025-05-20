# AI Resume Ranker

## Description

This project is a web application built with Streamlit that automates the initial screening and ranking of resumes from a PDF file against a specific job description. It leverages AI services for Optical Character Recognition (OCR) and structured data extraction/scoring.

The application guides the user through a step-by-step process:
1.  Upload a PDF containing one or more resumes.
2.  Enter the target job description.
3.  Interactively define the page boundaries for each individual resume within the PDF.
4.  Initiate AI processing, where each resume is analyzed.
5.  View the ranked results in a filterable and sortable table, including extracted details, fit scores, and AI reasoning.

## Features

*   **PDF Upload:** Supports uploading a single PDF file containing multiple resumes.
*   **Mistral AI OCR:** Uses Mistral AI's OCR service to accurately extract text content from each page of the PDF in markdown format.
*   **Interactive Resume Splitting:** A user-friendly interface to visually define which pages belong to each resume.
*   **OpenAI Assistant Integration:** Utilizes two distinct OpenAI Assistants:
    *   **Extractor:** Parses the resume text into a structured JSON format (personal info, experience, education, skills, etc.).
    *   **Scorer:** Evaluates the extracted data against the provided job description, calculating a fit score, an overall quality score, identifying matched/missing skills, and providing reasoning. Includes current date context for experience calculation.
*   **Job-Based Processing:** Organizes analysis runs into named "Jobs", linked to a specific PDF and job description.
*   **Persistent Storage:** Uses an SQLite database (`resumes.db`) to store job details and processed candidate data, allowing users to revisit past results.
*   **Results Dashboard:** Displays ranked candidate data in an interactive table powered by Streamlit and Pandas.
    *   Filtering by fit score, years of experience, and text search (name/email).
    *   Sorting by various columns.
    *   Progress bars for scores.
    *   Detailed view of matched/missing skills and AI reasoning.
*   **Job Management:** Select, view details of, and delete previous processing jobs and their associated data.
*   **Data Export:** Download filtered results as a CSV file.
*   **Caching:** Employs Streamlit's caching (`st.cache_data`) to improve performance for PDF page rendering and database lookups.

## Technology Stack

*   **Language:** Python 3.x
*   **Web Framework/UI:** Streamlit
*   **PDF Processing:** PyMuPDF (`fitz`)
*   **OCR Service:** Mistral AI API (`mistralai`)
*   **AI Analysis:** OpenAI Assistants API (`openai`)
*   **Database:** SQLite (`sqlite3`)
*   **Data Handling:** Pandas
*   **Configuration:** python-dotenv

## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone (https://github.com/YouROS12/ai-resume-ranker)
    cd <repository-directory>
    ```

2.  **Create a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Create `requirements.txt`:**
    Based on the imports, create a `requirements.txt` file with at least the following content (you might need to add specific versions based on your environment or pin them for stability):
    ```txt
    streamlit
    pymupdf
    pandas
    openai
    mistralai
    python-dotenv
    ```

4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Configure Environment Variables:**
    *   Create a file named `.env` in the project's root directory (where `config.py` is located).
    *   Add your API keys and Assistant IDs to this file. **See the Configuration section below for details.**

6.  **Set up OpenAI Assistants:**
    *   You need to have **two pre-configured Assistants** set up in your OpenAI account (platform.openai.com):
        *   One for **Extraction:** Trained/instructed to receive raw resume text and output structured JSON data (personal info, work history, education, skills, etc.).
        *   One for **Scoring:** Trained/instructed to receive the extracted JSON data, a job description, and the current date, then output a JSON containing scores, reasoning, matched/missing skills.
    *   Copy the unique **Assistant IDs** for both of these into your `.env` file.

## Configuration (`.env` File)

Create a `.env` file in the root directory with the following variables:

```dotenv
# .env

# Mistral AI API Key (for OCR)
MISTRAL_API_KEY="your_mistral_api_key_here"

# OpenAI API Key (for Assistants)
OPENAI_API_KEY="sk-your_openai_api_key_here"

# OpenAI Assistant ID for Resume Data Extraction
ASSISTANT_ID_EXTRACT="asst_your_extraction_assistant_id_here"

# OpenAI Assistant ID for Resume Scoring against Job Description
ASSISTANT_ID_SCORE="asst_your_scoring_assistant_id_here"

# --- Optional: Default values are set in config.py if not present ---
# OCR_MODEL="mistral-ocr-latest"
# ASSISTANT_TIMEOUT_SECONDS=180


Replace the placeholder values with your actual keys and IDs.

Ensure this file is not committed to version control (add .env to your .gitignore file).

Running the Application

Make sure your virtual environment is activated.

Navigate to the project directory in your terminal.

Run the Streamlit app:

streamlit run app.py
IGNORE_WHEN_COPYING_START
content_copy
download
Use code with caution.
Bash
IGNORE_WHEN_COPYING_END

The application should open in your web browser.

Usage Workflow

Step 1: Upload PDF: Use the file uploader to select the PDF containing resumes. The app will automatically perform OCR using Mistral AI.

Step 2: Enter Job Description: Paste the full job description into the text area. Click "Next".

Step 3: Define Resume Boundaries:

Review each page preview.

Click "End Resume Here" on the last page of each individual resume.

Use "Next"/"Prev" to navigate. Use "Skip" to exclude a page entirely.

Defined groups will be listed. Once the last page is processed/skipped, the app moves to the next step.

Step 4: Process Resumes:

Assign a unique name for this analysis job (a default is suggested based on the PDF name and date).

Click "Process Job". The app will iterate through each defined resume group:

Aggregate OCR text for the group's pages.

Call the OpenAI Extraction Assistant.

Call the OpenAI Scoring Assistant with extracted data and the JD.

Store results in the database.

A progress bar indicates the status.

Step 5: View Results:

The results for the just-processed job are displayed by default.

Use the dropdown to select and view results from previous jobs.

Use filter controls (score sliders, text search) to narrow down the list.

Click column headers to sort.

Use the "Download Filtered Results" button to get a CSV.

Use the "Delete" button (with confirmation) next to the job selector to remove a job and its data permanently.

Click "Process Another PDF" (or "Start New Analysis" in the sidebar) to reset the application and start over.

Database

The application uses an SQLite database file named resumes.db (defined in config.py).

This file will be created automatically in the project root directory when the application runs for the first time if it doesn't exist.

The storage_service.py module handles all database interactions (initialization, creating jobs, storing candidates, loading data, deleting jobs).

The candidates table stores the processed information for each resume, linked to a job_id. Deleting a job via the UI will automatically delete associated candidates due to the ON DELETE CASCADE foreign key constraint.

Remember to replace `<your-repository-url>` and `<repository-directory>` placeholders in the setup instructions if applicable. This README should provide a good starting point for anyone wanting to understand, set up, and use your application.
IGNORE_WHEN_COPYING_START
content_copy
download
Use code with caution.
IGNORE_WHEN_COPYING_END
