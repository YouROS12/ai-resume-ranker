# services/storage_service.py
import sqlite3
import json
import logging
from datetime import datetime

# --- Project Modules / Config ---
try:
    import config
except ImportError:
    logging.error("Failed to import 'config' module. Ensure config.py exists.")
    # Provide fallback DB name if config import fails during development/testing
    class MockConfig: DATABASE_NAME="fallback_resumes.db"
    config = MockConfig()

DATABASE_FILE = config.DATABASE_NAME

# --- Database Initialization with Migration ---
def init_db():
    """
    Initializes the database. Checks the schema for the candidates table's
    foreign key and performs a migration to add ON DELETE CASCADE if missing.
    """
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            # Ensure Foreign Key support is enabled for this connection
            cursor.execute("PRAGMA foreign_keys = ON;")
            fk_status = cursor.execute("PRAGMA foreign_keys;").fetchone()
            logging.info(f"DB Init: Foreign key support is {'ENABLED' if fk_status and fk_status[0] == 1 else 'DISABLED'}.")

            # 1. Create jobs table (safe to run always)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT UNIQUE NOT NULL,
                pdf_filename TEXT,
                job_description_snippet TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            logging.debug("Checked/created jobs table.")

            # 2. Check candidates table and potentially migrate
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='candidates';")
            candidates_table_exists = cursor.fetchone()

            needs_migration = False
            # Define the target schema SQL string once
            correct_schema_sql = """
                CREATE TABLE candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resume_page_range TEXT,
                    processing_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    job_description_used TEXT,
                    personal_information TEXT, -- JSON
                    professional_summary TEXT,
                    work_experience TEXT,      -- JSON
                    education TEXT,            -- JSON
                    skills TEXT,               -- JSON list
                    certifications TEXT,       -- JSON list
                    score_percent REAL,
                    score_reasoning TEXT,
                    matched_skills TEXT,       -- JSON list
                    missing_skills TEXT,       -- JSON list
                    raw_assistant1_json TEXT,
                    raw_assistant2_json TEXT,
                    job_id INTEGER,
                    total_years_experience TEXT, -- Store as TEXT
                    total_internship_duration TEXT, -- Store as TEXT
                    overall_score_percent REAL,
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE -- Ensures cascade delete
                );
                """

            if candidates_table_exists:
                # Check the foreign key definition for ON DELETE CASCADE
                fk_list = cursor.execute("PRAGMA foreign_key_list(candidates);").fetchall()
                # fk_list columns: id, seq, table, from, to, on_update, on_delete, match
                job_id_fk = next((fk for fk in fk_list if fk[3] == 'job_id'), None) # Find FK constraint for job_id column

                if job_id_fk and job_id_fk[6].upper() != 'CASCADE': # fk[6] is the 'on_delete' action
                    needs_migration = True
                    logging.warning("Detected 'candidates' table is MISSING 'ON DELETE CASCADE' for job_id. Migration needed.")
                elif not job_id_fk:
                     logging.warning("Detected 'candidates' table exists but has NO foreign key constraint for job_id. Migration needed.")
                     needs_migration = True # Also migrate if FK is missing entirely
                else:
                     logging.info("Verified 'candidates' table has 'ON DELETE CASCADE' for job_id.")

            # --- Migration Logic ---
            if needs_migration:
                try:
                    logging.info("Starting schema migration for 'candidates' table...")
                    # Use a transaction for atomicity
                    cursor.execute("BEGIN TRANSACTION;")

                    # Get columns from old table to determine which data to copy
                    cursor.execute("PRAGMA table_info(candidates);")
                    old_columns = [info[1] for info in cursor.fetchall()]
                    logging.debug(f"Old columns: {', '.join(old_columns)}")

                    # a. Rename old table
                    cursor.execute("ALTER TABLE candidates RENAME TO candidates_old_migration;")
                    logging.info("Renamed existing 'candidates' table to 'candidates_old_migration'.")

                    # b. Create new table with correct schema (using the defined SQL)
                    cursor.execute(correct_schema_sql)
                    logging.info("Created new 'candidates' table with correct schema (including ON DELETE CASCADE).")

                    # Get columns from new table to ensure we only copy compatible columns
                    cursor.execute("PRAGMA table_info(candidates);")
                    new_columns = [info[1] for info in cursor.fetchall()]
                    logging.debug(f"New columns: {', '.join(new_columns)}")

                    # Identify columns present in both old and new tables for safe copying
                    common_columns = [col for col in old_columns if col in new_columns]
                    common_columns_str = ", ".join([f'"{col}"' for col in common_columns])
                    logging.debug(f"Common columns for copying: {common_columns_str}")

                    # c. Copy data from old to new table for common columns
                    if common_columns:
                        sql_copy = f"INSERT INTO candidates ({common_columns_str}) SELECT {common_columns_str} FROM candidates_old_migration;"
                        logging.debug(f"Executing copy SQL: {sql_copy}")
                        cursor.execute(sql_copy)
                        logging.info(f"Copied data ({cursor.rowcount} rows) from old table to new table.")
                    else:
                        logging.warning("No common columns found between old and new 'candidates' table definition. Data not copied.")

                    # d. Drop old table
                    cursor.execute("DROP TABLE candidates_old_migration;")
                    logging.info("Dropped the old 'candidates_old_migration' table.")

                    # e. Commit the transaction
                    cursor.execute("COMMIT;")
                    logging.info("Schema migration for 'candidates' table COMPLETED successfully.")

                except sqlite3.Error as migrate_err:
                    logging.error(f"Migration FAILED: {migrate_err}", exc_info=True)
                    try:
                        cursor.execute("ROLLBACK;") # Attempt to rollback changes on error
                        logging.info("Migration changes rolled back.")
                    except Exception as rollback_err:
                        logging.error(f"Error during migration rollback: {rollback_err}")
                    # Optional: Try renaming back if possible, though might fail if new table exists
                    # try:
                    #    cursor.execute("ALTER TABLE candidates_old_migration RENAME TO candidates;")
                    #    logging.info("Attempted to restore original table name 'candidates' after failed migration.")
                    # except Exception: pass
                    raise migrate_err # Re-raise the original migration error

            # 3. Create candidates table if it didn't exist at all
            elif not candidates_table_exists:
                 cursor.execute(correct_schema_sql) # Use the defined correct schema SQL
                 logging.info("Created 'candidates' table as it did not exist (with ON DELETE CASCADE).")

            conn.commit() # Commit any changes like initial table creation
            logging.info(f"DB '{DATABASE_FILE}' schema check/migration process finished.")

    except sqlite3.Error as e:
        logging.error(f"DB init/migration encountered an error: {e}", exc_info=True); raise
    except Exception as e:
         # Catch any other unexpected errors during init
         logging.error(f"Unexpected error during DB init/migration: {e}", exc_info=True); raise

# --- Job Management Functions ---
def create_job(job_name: str, pdf_filename: str, job_desc_snippet: str) -> int | None:
    """Creates a new job record or retrieves existing ID if name exists."""
    sql = "INSERT INTO jobs (job_name, pdf_filename, job_description_snippet) VALUES (?, ?, ?)"
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
             # Ensure FKs are enabled for the connection creating the job
             conn.execute("PRAGMA foreign_keys = ON;")
             cursor = conn.cursor()
             cursor.execute(sql, (job_name, pdf_filename, job_desc_snippet))
             conn.commit()
             job_id = cursor.lastrowid
             logging.info(f"Created job '{job_name}' (ID: {job_id})")
             return job_id
    except sqlite3.IntegrityError: # Likely UNIQUE constraint violation on job_name
         logging.warning(f"Job name '{job_name}' likely already exists. Retrieving existing ID.")
         return get_job_id_by_name(job_name) # Attempt to get existing ID
    except sqlite3.Error as e:
         logging.error(f"Database error creating job '{job_name}': {e}", exc_info=True)
         return None

def get_job_id_by_name(job_name: str) -> int | None:
    """Retrieves the ID of a job given its unique name."""
    sql = "SELECT job_id FROM jobs WHERE job_name = ?"
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            # No need to enable FKs for a simple SELECT
            cursor = conn.cursor()
            result = cursor.execute(sql, (job_name,)).fetchone()
            if result:
                logging.debug(f"Found job ID {result[0]} for name '{job_name}'.")
                return result[0]
            else:
                logging.warning(f"No job found with name '{job_name}'.")
                return None
    except sqlite3.Error as e:
        logging.error(f"Database error retrieving job ID for '{job_name}': {e}", exc_info=True)
        return None

def load_job_list() -> list[dict]:
    """Loads a list of all jobs, most recent first."""
    jobs = []
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            conn.row_factory = sqlite3.Row # Fetch rows as dict-like objects
            query = "SELECT job_id, job_name, pdf_filename, created_at FROM jobs ORDER BY created_at DESC"
            cursor = conn.cursor()
            results = cursor.execute(query).fetchall()
            jobs = [dict(row) for row in results]
            logging.info(f"Loaded {len(jobs)} job records from database.")
    except sqlite3.Error as e:
        logging.error(f"Database error loading job list: {e}", exc_info=True)
    return jobs

def delete_job_and_candidates(job_id: int) -> bool:
    """Deletes a job and all associated candidates using CASCADE DELETE."""
    if not job_id:
        logging.warning("Delete attempt with invalid job ID (None or 0).")
        return False
    sql = "DELETE FROM jobs WHERE job_id = ?"
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            # --- CRUCIAL: Enable FK Constraint enforcement for THIS specific connection ---
            conn.execute("PRAGMA foreign_keys = ON;")
            # Verify FK status for this connection (for debugging)
            fk_status_cursor = conn.execute("PRAGMA foreign_keys;")
            fk_status = fk_status_cursor.fetchone()
            if fk_status and fk_status[0] == 1:
                logging.info(f"Foreign key enforcement is ENABLED for connection during delete operation for job ID {job_id}.")
            else:
                # This case should be rare if init_db works, but is important to log
                logging.warning(f"Foreign key enforcement is DISABLED for connection during delete operation for job ID {job_id}. Cascade will likely fail!")

            cursor = conn.cursor()
            cursor.execute(sql, (job_id,))
            conn.commit()

            # Check if a row was actually deleted
            if cursor.rowcount > 0:
                logging.info(f"Successfully executed DELETE for job ID {job_id} (rowcount: {cursor.rowcount}). Associated candidates should be deleted via CASCADE.")
                return True
            else:
                # This means the job_id didn't exist in the 'jobs' table
                logging.warning(f"No job found with ID {job_id} to delete (rowcount was 0).")
                return False # Indicate job wasn't found / deleted
    except sqlite3.IntegrityError as e:
         # This specific error should now be much less likely if ON DELETE CASCADE works
         if "FOREIGN KEY constraint failed" in str(e):
              logging.error(f"DB Integrity Error deleting job ID {job_id}: FOREIGN KEY VIOLATION. This is unexpected if ON DELETE CASCADE is set correctly in the DB schema. Error: {e}", exc_info=True)
         else:
              logging.error(f"DB Integrity Error deleting job ID {job_id}: {e}", exc_info=True)
         return False
    except sqlite3.Error as e:
        # Catch other potential SQLite errors during delete
        logging.error(f"Database error deleting job ID {job_id}: {e.__class__.__name__} - {e}", exc_info=True)
        return False
    except Exception as e:
        # Catch any unexpected Python errors
        logging.error(f"Unexpected Python error during delete operation for job ID {job_id}: {e}", exc_info=True)
        return False


# --- Candidate Data Functions ---
def store_candidate_data(job_id: int, page_range: str, job_desc: str, assistant1_data: dict, assistant2_data: dict, raw1_json: str | None, raw2_json: str | None) -> int | None:
    """Stores processed candidate data linked to a specific job."""
    if not job_id: logging.error("Store failed: invalid job_id."); return None
    # Ensure input data are dictionaries, default to empty if None
    if assistant1_data is None: assistant1_data = {}
    if assistant2_data is None: assistant2_data = {}

    try:
        # Extract data safely using .get()
        professional_summary = assistant1_data.get('professional_summary')
        work_exp_obj = assistant1_data.get('work_experience', {}) # Default to empty dict
        # Get experience details as strings or None, handle potential non-string types from AI
        total_years_experience = work_exp_obj.get('total_years_experience')
        total_internship_duration = work_exp_obj.get('total_internship_duration')
        score_reasoning = assistant2_data.get('reasoning')

        # Parse numeric scores defensively
        def _parse_num(val):
             if val is None: return None
             try: return float(val)
             except (ValueError, TypeError): logging.warning(f"Failed parsing score '{val}' as number."); return None
        score_percent = _parse_num(assistant2_data.get('score_percent'))
        overall_score_percent = _parse_num(assistant2_data.get('overall_score_percent'))

        # Prepare JSON fields safely, handling potential non-serializable data
        def _dump_json(data, default=None):
            if data is None: return json.dumps(default) if default is not None else None
            try: return json.dumps(data, ensure_ascii=False) # Allow unicode characters
            except TypeError as e:
                 logging.warning(f"Data type error dumping JSON: {e}. Data type: {type(data)}. Storing default: {default}");
                 return json.dumps(default) if default is not None else None

        # Dump complex fields to JSON strings for storage
        personal_info_json = _dump_json(assistant1_data.get('personal_information'), default={})
        work_exp_json = _dump_json(work_exp_obj, default={}) # Store full work_exp object as received
        education_json = _dump_json(assistant1_data.get('education'), default=[])
        skills_json = _dump_json(assistant1_data.get('skills'), default=[])
        certs_json = _dump_json(assistant1_data.get('certifications'), default=[])
        matched_skills_json = _dump_json(assistant2_data.get('matched_skills'), default=[])
        missing_skills_json = _dump_json(assistant2_data.get('missing_skills'), default=[])

        # SQL statement matching the current 'candidates' table schema
        sql = """
        INSERT INTO candidates (
            job_id, resume_page_range, job_description_used, personal_information, professional_summary,
            work_experience, education, skills, certifications, score_percent, score_reasoning, matched_skills,
            missing_skills, raw_assistant1_json, raw_assistant2_json, processing_timestamp, total_years_experience,
            total_internship_duration, overall_score_percent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Prepare parameters, ensuring experience durations are stored as strings or None
        params = (
            job_id, page_range, job_desc, personal_info_json, professional_summary,
            work_exp_json, education_json, skills_json, certs_json, score_percent,
            score_reasoning, matched_skills_json, missing_skills_json,
            str(raw1_json) if raw1_json else None, str(raw2_json) if raw2_json else None,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), # Use standard format
            str(total_years_experience) if total_years_experience is not None else None, # Store as TEXT
            str(total_internship_duration) if total_internship_duration is not None else None, # Store as TEXT
            overall_score_percent
        )

        with sqlite3.connect(DATABASE_FILE) as conn:
            # Enable FKs for storing to ensure job_id exists
            conn.execute("PRAGMA foreign_keys = ON;")
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            last_id = cursor.lastrowid
            logging.info(f"Stored candidate data with ID: {last_id} for job ID: {job_id}")
            return last_id
    except sqlite3.IntegrityError as e:
         # Specifically log FK violations if they happen here
         if "FOREIGN KEY constraint failed" in str(e):
              logging.error(f"DB Integrity Error storing candidate (Job ID {job_id}): FOREIGN KEY VIOLATION. Does Job ID {job_id} exist in jobs table? Error: {e}", exc_info=True)
         else:
              logging.error(f"DB Integrity Error storing candidate (Job ID {job_id}): {e}", exc_info=True)
         return None
    except sqlite3.Error as e:
        # Catch other potential SQLite errors
        logging.error(f"Database error storing candidate data (Job ID {job_id}): {e}", exc_info=True);
        return None
    except Exception as e:
        # Catch any unexpected Python errors during data preparation or storage
        logging.error(f"Unexpected Python error storing candidate data (Job ID {job_id}): {e}", exc_info=True);
        return None

# --- Simplified load_candidates_for_job ---
def load_candidates_for_job(job_id: int) -> list[dict]:
    """
    Loads candidate data for a specific job ID, selecting all actual DB columns,
    and extracting only candidate_name and email from the personal_information JSON.
    """
    if not job_id: return []
    processed_data = []
    # Select all actual columns from the candidates table definition
    select_cols = [
        'c.id', 'c.job_id', 'j.job_name', 'c.resume_page_range',
        'c.processing_timestamp', 'c.job_description_used',
        'c.personal_information', # JSON - will be parsed below for name/email
        'c.professional_summary',
        'c.work_experience',      # JSON
        'c.education',            # JSON
        'c.skills',               # JSON (list)
        'c.certifications',       # JSON (list)
        'c.score_percent',
        'c.score_reasoning',
        'c.matched_skills',       # JSON (list)
        'c.missing_skills',       # JSON (list)
        'c.raw_assistant1_json',
        'c.raw_assistant2_json',
        'c.total_years_experience', # TEXT
        'c.total_internship_duration', # TEXT
        'c.overall_score_percent'
    ]
    select_cols_str = ", ".join(select_cols)

    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            conn.row_factory = sqlite3.Row # Fetch rows as dict-like objects
            query = f"""
                SELECT {select_cols_str}
                FROM candidates c
                JOIN jobs j ON c.job_id = j.job_id
                WHERE c.job_id = ?
                ORDER BY c.score_percent DESC, c.overall_score_percent DESC
            """
            cursor = conn.cursor()
            results = cursor.execute(query, (job_id,)).fetchall()
            # Convert Row objects to standard Python dictionaries immediately
            raw_data = [dict(row) for row in results]
            logging.info(f"Loaded {len(raw_data)} raw candidate records for job ID: {job_id}.")

        # --- Process raw data: Only extract Name and Email ---
        for row_dict in raw_data:
            # Start with a copy of the dictionary containing all DB columns
            processed_row = row_dict.copy()

            # Parse personal_information JSON safely to get name and email
            pi_json = row_dict.get('personal_information')
            candidate_name = 'N/A' # Default values
            email = 'N/A'
            if pi_json and isinstance(pi_json, str): # Check if it's a non-empty string
                try:
                    pi_data = json.loads(pi_json)
                    # Ensure the parsed data is a dictionary before accessing keys
                    if isinstance(pi_data, dict):
                        candidate_name = pi_data.get('full_name', 'N/A')
                        email = pi_data.get('email', 'N/A')
                    else:
                         logging.warning(f"Cand. ID {row_dict.get('id', 'N/A')}: Parsed personal_information was not a dictionary (type: {type(pi_data)}).")
                except (json.JSONDecodeError, TypeError) as e:
                    # Log error if JSON is invalid or not the expected type
                    logging.warning(f"Cand. ID {row_dict.get('id', 'N/A')}: Error parsing personal_information JSON: {e}")
            elif pi_json:
                # Log if the field is not a string (unexpected)
                 logging.warning(f"Cand. ID {row_dict.get('id', 'N/A')}: personal_information field type is {type(pi_json)}, expected string.")


            # Add the extracted fields to the dictionary (overwriting if they somehow existed)
            processed_row['candidate_name'] = candidate_name
            processed_row['email'] = email

            # Add the fully processed row to our results list
            processed_data.append(processed_row)

        logging.info(f"Processed {len(processed_data)} candidate records (added name/email) for job ID: {job_id}.")
        return processed_data

    except sqlite3.Error as e:
        # Handle potential database errors during loading
        logging.error(f"Database error loading candidates for job {job_id}: {e}", exc_info=True)
        return []
    except Exception as e:
        # Handle any other unexpected errors during processing
        logging.error(f"Unexpected error loading/processing candidates for job {job_id}: {e}", exc_info=True)
        return []