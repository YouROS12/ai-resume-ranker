# services/storage_service.py
import sqlite3
import json
import logging
from datetime import datetime

# --- Project Modules ---
try:
    import config
except ImportError:
    logging.error("Failed to import 'config' module. Ensure config.py exists.")
    class MockConfig: DATABASE_NAME="fallback_resumes.db" # Provide fallback DB name
    config = MockConfig()


DATABASE_FILE = config.DATABASE_NAME

def init_db():
    """Initializes DB with jobs and candidates tables (NO extraction_date column)."""
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            # Create jobs table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT UNIQUE NOT NULL, pdf_filename TEXT,
                job_description_snippet TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Check existing columns before potentially altering
            cursor.execute("PRAGMA table_info(candidates)")
            existing_columns = [info[1] for info in cursor.fetchall()]

            # Define required columns (ensure foreign key and cascade delete)
            required_columns = {
                "job_id": "INTEGER REFERENCES jobs(job_id) ON DELETE CASCADE",
                "total_years_experience": "REAL",
                "total_internship_duration": "TEXT",
                "overall_score_percent": "REAL"
            }

            # Add missing columns if possible
            for col_name, col_type in required_columns.items():
                if col_name not in existing_columns:
                    try:
                        # Split type from constraint for ALTER ADD COLUMN syntax if needed
                        base_col_type = col_type.split(" ")[0]
                        cursor.execute(f"ALTER TABLE candidates ADD COLUMN {col_name} {base_col_type}")
                        logging.info(f"Added '{col_name}' column to 'candidates' table.")
                        # Note: Foreign key constraints might need separate handling or table recreation
                    except sqlite3.OperationalError as alter_err:
                        logging.warning(f"Could not add '{col_name}' column via ALTER TABLE: {alter_err}")


            # Ensure candidates table exists with the final schema
            # ** REMOVED extraction_date column **
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resume_page_range TEXT, processing_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                job_description_used TEXT, personal_information TEXT, professional_summary TEXT,
                work_experience TEXT, education TEXT, skills TEXT, certifications TEXT,
                score_percent REAL, score_reasoning TEXT, matched_skills TEXT, missing_skills TEXT,
                raw_assistant1_json TEXT, raw_assistant2_json TEXT,
                job_id INTEGER, -- Defined here
                total_years_experience REAL, total_internship_duration TEXT, overall_score_percent REAL,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
            );
            """)
            conn.commit()
            logging.info(f"DB '{DATABASE_FILE}' schema checked/updated.")
    except sqlite3.Error as e:
        logging.error(f"DB init error: {e}", exc_info=True); raise

# --- Job Management Functions ---
def create_job(job_name: str, pdf_filename: str, job_desc_snippet: str) -> int | None:
    """Creates a new job record or retrieves existing ID if name exists."""
    sql = "INSERT INTO jobs (job_name, pdf_filename, job_description_snippet) VALUES (?, ?, ?)"
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor(); cursor.execute(sql, (job_name, pdf_filename, job_desc_snippet)); conn.commit()
            job_id = cursor.lastrowid; logging.info(f"Created job '{job_name}' (ID: {job_id})"); return job_id
    except sqlite3.IntegrityError: # Likely UNIQUE constraint violation
         logging.warning(f"Job '{job_name}' exists. Getting ID."); return get_job_id_by_name(job_name)
    except sqlite3.Error as e: logging.error(f"DB error creating job '{job_name}': {e}",exc_info=True); return None

def get_job_id_by_name(job_name: str) -> int | None:
    """Retrieves the ID of a job given its unique name."""
    sql = "SELECT job_id FROM jobs WHERE job_name = ?"
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor(); result=cursor.execute(sql,(job_name,)).fetchone()
            if result: return result[0]
            else: logging.warning(f"No job found with name '{job_name}'."); return None
    except sqlite3.Error as e: logging.error(f"DB error retrieving job ID for '{job_name}': {e}",exc_info=True); return None

def load_job_list() -> list[dict]:
    """Loads a list of all jobs, most recent first."""
    jobs = [];
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            conn.row_factory=sqlite3.Row
            query="SELECT job_id, job_name, pdf_filename, created_at FROM jobs ORDER BY created_at DESC"
            cursor=conn.cursor(); results=cursor.execute(query).fetchall()
            jobs=[dict(row) for row in results]; logging.info(f"Loaded {len(jobs)} job records.")
    except sqlite3.Error as e: logging.error(f"DB error loading job list: {e}", exc_info=True)
    return jobs

def delete_job_and_candidates(job_id: int) -> bool:
    """Deletes a job and all associated candidates using CASCADE DELETE."""
    if not job_id: logging.warning("Delete attempt with invalid job ID."); return False
    sql = "DELETE FROM jobs WHERE job_id = ?"
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            conn.execute("PRAGMA foreign_keys = ON;") # IMPORTANT: Enable FKs for CASCADE
            cursor = conn.cursor(); cursor.execute(sql, (job_id,)); conn.commit()
            if cursor.rowcount > 0: logging.info(f"Deleted job ID {job_id} and candidates."); return True
            else: logging.warning(f"No job found with ID {job_id} to delete."); return False
    except sqlite3.Error as e: logging.error(f"DB error deleting job ID {job_id}: {e}", exc_info=True); return False

# --- Candidate Data Functions ---
def store_candidate_data(job_id: int, page_range: str, job_desc: str, assistant1_data: dict, assistant2_data: dict, raw1_json: str | None, raw2_json: str | None) -> int | None:
    """Stores processed candidate data linked to a specific job."""
    if not job_id: logging.error("Store failed: invalid job_id."); return None
    if not assistant1_data: assistant1_data = {}
    if not assistant2_data: assistant2_data = {}

    try:
        # Extract scalar/simple fields
        professional_summary=assistant1_data.get('professional_summary')
        work_exp_obj=assistant1_data.get('work_experience',{})
        total_years_experience=work_exp_obj.get('total_years_experience')
        total_internship_duration=work_exp_obj.get('total_internship_duration')
        score_reasoning=assistant2_data.get('reasoning')

        # Parse numeric fields defensively
        def _parse_num(val):
             if val is None: return None
             try: return float(val)
             except: logging.warning(f"Failed parsing '{val}' as number."); return None
        score_percent=_parse_num(assistant2_data.get('score_percent'))
        overall_score_percent=_parse_num(assistant2_data.get('overall_score_percent'))

        # Prepare JSON fields
        personal_info_json=json.dumps(assistant1_data.get('personal_information',{}))
        work_exp_json=json.dumps(work_exp_obj) # Store full work_exp object
        education_json=json.dumps(assistant1_data.get('education',[]))
        skills_json=json.dumps(assistant1_data.get('skills',[]))
        certs_json=json.dumps(assistant1_data.get('certifications',[]))
        matched_skills_json=json.dumps(assistant2_data.get('matched_skills',[]))
        missing_skills_json=json.dumps(assistant2_data.get('missing_skills',[]))

        # ** SQL and Params WITHOUT extraction_date **
        sql = """
        INSERT INTO candidates (
            job_id, resume_page_range, job_description_used,
            personal_information, professional_summary, work_experience, education, skills, certifications,
            score_percent, score_reasoning, matched_skills, missing_skills,
            raw_assistant1_json, raw_assistant2_json, processing_timestamp,
            total_years_experience, total_internship_duration, overall_score_percent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """ # 19 parameters total
        params = (
            job_id, page_range, job_desc,
            personal_info_json, professional_summary, work_exp_json, education_json, skills_json, certs_json,
            score_percent, score_reasoning, matched_skills_json, missing_skills_json,
            str(raw1_json) if raw1_json else None, str(raw2_json) if raw2_json else None, datetime.now(),
            total_years_experience, total_internship_duration, overall_score_percent # Use parsed scores
        )

        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor(); conn.execute("PRAGMA foreign_keys = ON;")
            cursor.execute(sql, params); conn.commit()
            last_id = cursor.lastrowid; logging.info(f"Stored candidate ID: {last_id}"); return last_id
    except sqlite3.Error as e: logging.error(f"DB error storing candidate: {e}", exc_info=True); return None
    except Exception as e: logging.error(f"Unexpected error storing candidate: {e}", exc_info=True); return None

def load_candidates_for_job(job_id: int) -> list[dict]:
    """Loads candidate data for a specific job ID (NO extraction_date)."""
    if not job_id: return []
    data = []
    # ** Select columns WITHOUT extraction_date **
    select_cols = [
        'id', 'resume_page_range', 'score_percent', 'score_reasoning',
        'personal_information', 'skills', 'matched_skills', 'missing_skills',
        'processing_timestamp', 'total_years_experience', 'total_internship_duration',
        'overall_score_percent'
    ]
    select_cols_str = ", ".join(select_cols)
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            conn.row_factory = sqlite3.Row
            query = f"SELECT {select_cols_str} FROM candidates WHERE job_id = ? ORDER BY score_percent DESC, overall_score_percent DESC"
            cursor = conn.cursor(); results = cursor.execute(query, (job_id,)).fetchall()
        # ... (Data processing to extract name/email - unchanged) ...
        data = [dict(row) for row in results]
        for row in data:
             try: pi=json.loads(row['personal_information']) if row.get('personal_information') else {}; row['candidate_name']=pi.get('full_name','N/A'); row['email']=pi.get('email','N/A')
             except: row['candidate_name']='Error'; row['email']=''
        logging.info(f"Loaded {len(data)} candidates for job ID: {job_id}."); return data
    except sqlite3.Error as e: logging.error(f"DB load error job {job_id}: {e}", exc_info=True); return []
    except Exception as e: logging.error(f"Unexpected error loading job {job_id}: {e}", exc_info=True); return []