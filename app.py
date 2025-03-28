# app.py
# --- Imports ---
import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import logging
import time
import io  # Required for BytesIO with fitz
from datetime import datetime # For default job name
import functools # Potentially useful for more complex cache invalidation if needed later

# --- Project Modules ---
try:
    import config
    from services import storage_service, ocr_service, assistants
except ImportError as e:
    st.error(f"🚨 Failed to import project modules: {e}.")
    st.stop()

# --- Configuration and Initialization ---
st.set_page_config(layout="wide", page_title="AI Resume Analyzer")
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s-%(levelname)s-[%(module)s]-%(message)s')

try:
    if hasattr(config, 'validate_config'): config.validate_config()
    logger.info("Configuration checked.")
except ValueError as e:
    st.error(f"🚨 Config Error: {e}. Check .env/config.py."); st.stop()

try:
    storage_service.init_db()
    logger.info("Database initialized/checked.")
except Exception as e:
    st.error(f"🚨 DB Init Failed: {e}"); st.stop()

# --- State Management ---
def initialize_state():
    """Initializes Streamlit session state variables."""
    defaults = {
        'current_step': 0, 'pdf_document': None, 'total_pages': 0,
        'current_page_index': 0, 'start_page_of_current_group': 1,
        'resume_page_groups': [], 'splitting_started': False, 'splitting_complete': False,
        'ocr_response_data': None, 'pdf_bytes_hash': None, 'pdf_bytes': None,
        'ocr_error': None, 'ocr_in_progress': False, 'uploaded_pdf_name': None,
        'job_description': "", 'job_name_input': "", 'process_button_active': False,
        'processing_in_progress': False, 'selected_job_id': None, 'current_job_id': None,
        'processing_log': [], 'last_job_description': "",
    }
    for key, value in defaults.items():
        if key not in st.session_state: st.session_state[key] = value
    logger.debug("Session state checked/initialized.")

def reset_app_state():
    """Resets the state for a new analysis."""
    logger.info("Resetting application state for new analysis.")
    # Preserve selected job ID maybe? Or clear everything. Let's clear all for full reset.
    keys_to_clear = list(st.session_state.keys())
    for key in keys_to_clear: del st.session_state[key]
    # Clear all Streamlit cache data as well for a full reset
    st.cache_data.clear()
    logger.info("Cleared all session state and Streamlit cache.")
    initialize_state() # Re-initialize with defaults

# Initialize state at the start
initialize_state()

# --- Helper Functions ---

# Non-cached rendering (Fallback)
def render_page(pdf_document, page_index):
    """Renders page directly from fitz.Document. Non-cached."""
    # ... (Implementation unchanged from previous version) ...
    if not pdf_document: return None
    try:
        if 0 <= page_index < len(pdf_document):
            page=pdf_document.load_page(page_index); pix=page.get_pixmap(matrix=fitz.Matrix(1.7,1.7)); return pix.tobytes("png")
        else: logger.warning(f"render_page: Invalid index {page_index}"); return None
    except Exception as e: logger.error(f"Error rendering page {page_index}: {e}", exc_info=True); return None

# Cached rendering (Preferred)
@st.cache_data(max_entries=50) # Cache images based on hash, bytes, index
def render_page_cached(_pdf_doc_bytes_hash, _pdf_doc_bytes, page_index):
    """Renders PDF page from bytes. Cached."""
    # ... (Implementation unchanged from previous version) ...
    logger.debug(f"Rendering page {page_index} (cache check for hash {_pdf_doc_bytes_hash})")
    if not _pdf_doc_bytes: return None
    try:
        with fitz.open(stream=io.BytesIO(_pdf_doc_bytes), filetype="pdf") as pdf_doc:
            if 0 <= page_index < len(pdf_doc):
                page=pdf_doc.load_page(page_index); pix=page.get_pixmap(matrix=fitz.Matrix(1.7,1.7)); return pix.tobytes("png")
            else: return None
    except Exception as e: logger.error(f"Error rendering page {page_index} from cache: {e}", exc_info=True); return None

# --- Cached Database Load Functions ---
# These wrap the storage_service calls and apply Streamlit caching.
@st.cache_data(ttl=3600) # Cache job list for 1 hour or until cleared
def cached_load_job_list():
    logger.info("CACHE MISS/RELOAD: Loading job list from database.")
    return storage_service.load_job_list()

@st.cache_data(ttl=3600) # Cache candidates per job_id
def cached_load_candidates_for_job(job_id: int):
    if not job_id: return [] # Avoid caching a call with invalid ID
    logger.info(f"CACHE MISS/RELOAD: Loading candidates for job ID {job_id} from database.")
    return storage_service.load_candidates_for_job(job_id)

# --- ==================== UI Rendering Based on Step ==================== ---
st.title("📄✨ AI Resume Analyzer")
st.markdown("""
*Upload PDF -> Define Resume Boundaries -> Enter Job Description -> Process with AI -> View Results*
""")

# --- Sidebar ---
# Moved Sidebar definition higher, but populate its dynamic parts later or check existence
st.sidebar.title("Info & Status")
st.sidebar.markdown("---")
st.sidebar.caption(f"Database: `{config.DATABASE_NAME}`")
# --- Manual Cache Clear Button ---
if st.sidebar.button("🔄 Clear Cache & Reload Data", help="Force reload data from database."):
    st.cache_data.clear(); logger.info("User cleared Streamlit cache."); st.rerun()
st.sidebar.markdown("---")
# --- Reset Button ---
if st.session_state.current_step > 0:
     if st.sidebar.button("🆕 Start New Analysis (Reset All)", help="Clears state and cache."):
          reset_app_state(); st.rerun() # reset_app_state now includes cache clear
st.sidebar.markdown("---")
st.sidebar.header("Current Status")
step_map = {0:"1. PDF",1:"2. JD",2:"3. Split",3:"4. Ready",4:"4. AI Processing",5:"5. Results"}; st.sidebar.metric("Current Step", step_map.get(st.session_state.current_step,"?"))
# --- Moved Job List Loading and Options Definition Here ---
try:
    job_list = cached_load_job_list()
    job_options = {job['job_id']: f"{job['job_name']} ({datetime.strptime(job['created_at'][:19], '%Y-%m-%d %H:%M:%S').strftime('%y-%m-%d %H:%M')})" for job in job_list}
except Exception as e:
    logger.error(f"Failed to load job list for UI: {e}", exc_info=True)
    job_list = []
    job_options = {}
    st.sidebar.error("Error loading job list.")

# --- Update Sidebar Status Indicators (can now safely use job_options) ---
if st.session_state.get('pdf_bytes_hash'): st.sidebar.success(f"PDF: {st.session_state.uploaded_pdf_name} ({st.session_state.total_pages}p)")
if st.session_state.get('ocr_error'): st.sidebar.error("OCR Failed")
elif isinstance(st.session_state.get('ocr_response_data'), list): st.sidebar.success("OCR Ready")
if st.session_state.get('splitting_complete'): st.sidebar.success(f"Split Done ({len(st.session_state.resume_page_groups)} groups)")
# Now job_options is guaranteed to exist (even if empty)
if st.session_state.get('selected_job_id') and job_options:
     st.sidebar.info(f"Viewing Job: {job_options.get(st.session_state.selected_job_id, 'N/A')}") # Use .get for safety
if st.session_state.get('processing_in_progress'): st.sidebar.warning("⏳ AI Processing...")

# --- Main Panel - Step-Based UI ---

# --- Step 0/1: PDF Upload and OCR ---
if st.session_state.current_step == 0:
    st.header("Step 1: Upload Resume PDF")
    st.info("Select a single PDF file containing one or more resumes.")
    uploaded_pdf = st.file_uploader("Upload PDF", type="pdf", key="pdf_uploader_step0", label_visibility="collapsed")

    if uploaded_pdf is not None:
        pdf_bytes = uploaded_pdf.getvalue()
        current_pdf_hash = hash(pdf_bytes)
        if current_pdf_hash != st.session_state.pdf_bytes_hash:
            logger.info(f"New PDF uploaded: {uploaded_pdf.name}. Resetting state and triggering OCR.")
            # --- Reset state, store bytes and name ---
            st.session_state.pdf_document = None; st.session_state.total_pages = 0; st.session_state.current_page_index = 0
            st.session_state.start_page_of_current_group = 1; st.session_state.resume_page_groups = []; st.session_state.splitting_started = False
            st.session_state.splitting_complete = False; st.session_state.ocr_response_data = None; st.session_state.process_button_active = False
            st.session_state.ocr_error = None; st.session_state.ocr_in_progress = True; st.session_state.processing_in_progress = False
            st.session_state.pdf_bytes_hash = current_pdf_hash; st.session_state.current_job_id = None
            st.session_state.uploaded_pdf_name = uploaded_pdf.name; st.session_state.pdf_bytes = pdf_bytes # Store bytes

            # --- Load PDF ---
            try:
                st.session_state.pdf_document = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
                st.session_state.total_pages = len(st.session_state.pdf_document)
                logger.info(f"PDF loaded: {st.session_state.total_pages} pages.")
            except Exception as pdf_err:
                st.error(f"❌ Failed to load PDF: {pdf_err}"); logger.error(f"PDF load error: {pdf_err}", exc_info=True)
                st.session_state.ocr_in_progress = False; st.session_state.pdf_bytes_hash = None; st.session_state.pdf_bytes = None
                st.rerun()

            # --- Trigger OCR ---
            if st.session_state.pdf_document and st.session_state.total_pages > 0:
                ocr_status_placeholder = st.empty(); ocr_status_placeholder.info("⚙️ Performing OCR...")
                with st.spinner("Processing PDF text..."): ocr_result = ocr_service.perform_ocr(uploaded_pdf.name, pdf_bytes)
                if ocr_result is not None:
                    st.session_state.ocr_response_data = ocr_result
                    msg = f"✅ OCR Done ({len(ocr_result)} pages)." if ocr_result else "⚠️ OCR Done, no text found."
                    if ocr_result: st.session_state.current_step = 1; st.session_state.ocr_error = None; logger.info(msg)
                    else: st.session_state.ocr_error = "No text content extracted."; logger.warning(msg)
                    st.rerun() # Go to Step 1 or show error on rerun
                else:
                    st.session_state.ocr_error = "OCR process failed. Check logs."; logger.error(st.session_state.ocr_error)
                    st.error(f"❌ {st.session_state.ocr_error}")
                st.session_state.ocr_in_progress = False
            else:
                if st.session_state.pdf_document and st.session_state.total_pages == 0: st.warning("⚠️ PDF has 0 pages.")
                st.session_state.ocr_in_progress = False; st.session_state.pdf_bytes_hash = None; st.session_state.pdf_bytes = None

    elif st.session_state.get('ocr_error'): st.error(f"🚨 OCR Error: {st.session_state.ocr_error}")

# --- Step 1: Enter Job Description ---
elif st.session_state.current_step == 1:
    st.header("Step 2: Enter Job Description")
    ocr_page_count = len(st.session_state.ocr_response_data) if isinstance(st.session_state.ocr_response_data, list) else 0
    st.success(f"✅ PDF '{st.session_state.uploaded_pdf_name}' processed ({ocr_page_count} pages ready).")
    st.info("Provide the job description for scoring.")
    jd_input = st.text_area("Job Description", height=250, key="jd_input_step1", placeholder="Paste JD here...", value=st.session_state.job_description)
    if st.button("Next: Define Resume Boundaries ➡️", disabled=(not jd_input.strip())):
        st.session_state.job_description = jd_input.strip()
        st.session_state.current_step = 2; st.session_state.splitting_started = True; st.session_state.splitting_complete = False
        st.session_state.resume_page_groups = []; st.session_state.current_page_index = 0; st.session_state.start_page_of_current_group = 1
        logger.info("JD entered, proceeding to Step 2 (Splitting)."); st.rerun()

# --- Step 2: Splitting ---
elif st.session_state.current_step == 2:
    st.header("Step 3: Define Resume Boundaries")
    st.info("Review pages. Click 'End Resume Here' on the **last** page of each resume.")
    current_page_num = st.session_state.current_page_index + 1
    st.write(f"**Reviewing Page: {current_page_num} / {st.session_state.total_pages}** (Group starts page {st.session_state.start_page_of_current_group})")

    # --- Display page image (using cache and stored bytes) ---
    page_image_bytes = None; pdf_bytes_for_render = st.session_state.get('pdf_bytes')
    if pdf_bytes_for_render and st.session_state.pdf_bytes_hash:
        page_image_bytes = render_page_cached(st.session_state.pdf_bytes_hash, pdf_bytes_for_render, st.session_state.current_page_index)
    if not page_image_bytes and st.session_state.pdf_document: # Fallback
        page_image_bytes = render_page(st.session_state.pdf_document, st.session_state.current_page_index)
    if page_image_bytes: st.image(page_image_bytes, use_container_width=False, width=400)
    else: st.warning("Could not render page preview.")

    # --- Action Buttons ---
    st.markdown("---"); nav_cols = st.columns([1, 1, 2, 1])
    with nav_cols[0]: # Prev
        if st.button("⬅️ Prev", disabled=st.session_state.current_page_index<=0, use_container_width=True): st.session_state.current_page_index-=1; st.rerun()
    with nav_cols[1]: # Next
        if st.button("Next ➡️", disabled=current_page_num>=st.session_state.total_pages, use_container_width=True): st.session_state.current_page_index+=1; st.rerun()
    with nav_cols[2]: # Finalize
        if st.button(f"✅ End Resume Here (Pgs {st.session_state.start_page_of_current_group}-{current_page_num})", type="primary", use_container_width=True):
            grp=list(range(st.session_state.start_page_of_current_group, current_page_num+1)); st.session_state.resume_page_groups.append(grp); logger.info(f"Finalized group: {grp}.")
            st.session_state.current_page_index+=1; st.session_state.start_page_of_current_group=st.session_state.current_page_index+1
            if st.session_state.current_page_index>=st.session_state.total_pages: st.session_state.splitting_complete=True; st.session_state.current_step=3; logger.info("Split complete.")
            st.rerun()
    with nav_cols[3]: # Skip
         if st.button("⏭️ Skip", help="Exclude page", use_container_width=True):
            logger.info(f"Skipped page {current_page_num}."); st.session_state.current_page_index+=1; st.session_state.start_page_of_current_group=st.session_state.current_page_index+1
            if st.session_state.current_page_index>=st.session_state.total_pages: st.session_state.splitting_complete=True; st.session_state.current_step=3; logger.info("Split complete after skip.")
            st.rerun()
    if st.session_state.resume_page_groups: st.write("Defined Groups:", st.session_state.resume_page_groups)

# --- Step 3: Ready to Process ---
elif st.session_state.current_step == 3:
    st.header("Step 4: Process Resumes with AI")
    st.success(f"✅ Ready! ({len(st.session_state.resume_page_groups)} resume groups defined).")
    if not st.session_state.resume_page_groups: st.warning("No groups defined.")
    else:
        default_job_name = f"{st.session_state.uploaded_pdf_name.rsplit('.',1)[0] if st.session_state.uploaded_pdf_name else 'Job'}_{datetime.now().strftime('%Y%m%d_%H%M')}"
        st.session_state.job_name_input = st.text_input("Assign Unique Job Name:", value=st.session_state.get('job_name_input', default_job_name), key="job_name_step3")
        process_disabled = not st.session_state.job_name_input.strip()
        if st.button("🚀 Process Job", key="process_submit_step3", type="primary", disabled=process_disabled):
            job_name = st.session_state.job_name_input.strip()
            if not job_name: st.error("❌ Job name required.")
            else:
                logger.info(f"Attempting job create/retrieve for '{job_name}'...")
                job_desc_snippet=(st.session_state.job_description[:100]+'...'); pdf_file=st.session_state.uploaded_pdf_name or "N/A"
                current_job_id = storage_service.create_job(job_name, pdf_file, job_desc_snippet)
                if current_job_id is None: st.error(f"❌ Failed start job '{job_name}'. Name taken or DB error?"); logger.error(f"Failed get job_id for '{job_name}'.")
                else:
                    st.session_state.current_job_id=current_job_id; st.session_state.processing_log=[]; st.session_state.current_step=4
                    logger.info(f"Starting AI loop for Job ID {current_job_id} ('{job_name}')."); st.rerun()

# --- Step 4: Processing ---
elif st.session_state.current_step == 4:
    st.header("Step 4: Processing Resumes with AI...")
    st.info(f"🤖 Processing Job '{st.session_state.job_name_input}' (ID: {st.session_state.current_job_id})...")
    total_resumes=len(st.session_state.resume_page_groups); progress_bar=st.progress(0,text="Initializing..."); status_container=st.container(); processed_count=0; error_count=0
    try:
        for i, page_group in enumerate(st.session_state.resume_page_groups):
            # ... (Progress bar, status updates, Call assistants.process_single_resume_group) ...
            pg_rng=f"{page_group[0]}-{page_group[-1]}" if len(page_group)>1 else str(page_group[0]); prog_txt=f"Resume {i+1}/{total_resumes} (Pgs {pg_rng})..."
            curr_prog=(i+0.1)/total_resumes; progress_bar.progress(min(curr_prog,1.0),text=prog_txt); status_container.info(f"🔄 {prog_txt}")
            extracted, scored, raw1, raw2 = assistants.process_single_resume_group(page_group, st.session_state.ocr_response_data, st.session_state.job_description)
            progress_bar.progress(min(curr_prog+0.8/total_resumes,1.0), text=f"AI done for {pg_rng}...")
            # ... (Store results using storage_service.store_candidate_data) ...
            if extracted:
                status_container.write(f"💾 Storing {pg_rng}..."); row_id=storage_service.store_candidate_data(st.session_state.current_job_id,pg_rng,st.session_state.job_description,extracted,scored,raw1,raw2)
                if row_id: processed_count+=1
                else: error_count+=1; status_container.warning(f"⚠️ DB store failed {pg_rng}.")
            else: error_count+=1; status_container.warning(f"⚠️ Extract failed {pg_rng}, not stored.")
            progress_bar.progress(min((i+1)/total_resumes,1.0), text=f"Done {pg_rng}.")
        # --- Processing Finished ---
        final_msg = f"Job '{st.session_state.job_name_input}' finished.";
        if processed_count>0: st.success(f"✅ {final_msg} {processed_count} resumes stored.")
        if error_count>0: st.warning(f"⚠️ {final_msg} Issues with {error_count} resumes.")
        st.session_state.selected_job_id=st.session_state.current_job_id; st.session_state.current_step=5; st.session_state.processing_in_progress=False
        logger.info(f"Finished AI loop Job ID {st.session_state.current_job_id}. Stored:{processed_count}, Errors:{error_count}.")
        time.sleep(1.5); st.rerun()
    except Exception as e: st.error(f"🚨 Critical error: {e}"); logger.error("Main loop exception.",exc_info=True); st.session_state.processing_in_progress=False; st.session_state.current_step=3; st.rerun()

# --- Step 5: Show Results ---
elif st.session_state.current_step == 5:
    st.header("Step 5: View Processed Job Results")

    # --- Job Selection & Deletion ---
    job_list = cached_load_job_list() # Use cached function
    job_options = {job['job_id']: f"{job['job_name']} ({datetime.strptime(job['created_at'][:19], '%Y-%m-%d %H:%M:%S').strftime('%y-%m-%d %H:%M')})" for job in job_list}
    default_job_id = st.session_state.get('selected_job_id')
    if default_job_id not in job_options and job_list: default_job_id = job_list[0]['job_id'] # Most recent

    selected_job_details = next((job for job in job_list if job['job_id'] == default_job_id), None)
    col_select, col_detail, col_delete = st.columns([3, 3, 1])

    with col_select: # Selectbox for Job
        selected_job_id_from_ui = st.selectbox(
            "Select Job:", options=list(job_options.keys()), format_func=lambda jid: job_options.get(jid, f"ID {jid}"),
            index=list(job_options.keys()).index(default_job_id) if default_job_id in job_options else 0, key="job_selector_step5", label_visibility="collapsed"
        )
        if selected_job_id_from_ui != st.session_state.selected_job_id:
            st.session_state.selected_job_id = selected_job_id_from_ui; logger.info(f"User selected Job ID {st.session_state.selected_job_id}"); st.rerun()

    with col_detail: # Show details of selected job
        if selected_job_details: st.caption(f"**PDF:** {selected_job_details.get('pdf_filename','N/A')} | **Created:** {datetime.strptime(selected_job_details['created_at'][:19],'%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M')}")
        else: st.caption("Select a job.")

    with col_delete: # Delete button with popover confirmation
        if st.session_state.selected_job_id:
            del_key = f"del_job_{st.session_state.selected_job_id}"
            with st.popover("🗑️ Delete", use_container_width=True):
                st.warning(f"Delete '{job_options.get(st.session_state.selected_job_id)}' and all its data?")
                if st.button("Confirm Delete", key=f"confirm_{del_key}", type="primary"):
                    job_id_to_delete = st.session_state.selected_job_id
                    logger.warning(f"User confirmed deletion for job ID {job_id_to_delete}")
                    deleted = storage_service.delete_job_and_candidates(job_id_to_delete)
                    if deleted:
                        st.toast(f"Job ID {job_id_to_delete} deleted.")
                        # Clear caches
                        cached_load_candidates_for_job.clear(job_id=job_id_to_delete) # Specific job cache
                        cached_load_job_list.clear() # Job list cache
                        st.session_state.selected_job_id = None # Reset selection
                        st.rerun() # Reload job list and results area
                    else:
                        st.error("Failed to delete job. Check logs.")
                        logger.error(f"Deletion failed for job ID {job_id_to_delete}.")

    # --- Load and Display Results for Selected Job ---
    if st.session_state.selected_job_id:
        st.subheader(f"Candidates for: \"{job_options.get(st.session_state.selected_job_id, 'N/A')}\"")
        # Load data specifically for the selected job using cached function
        results_data = cached_load_candidates_for_job(st.session_state.selected_job_id)

        if results_data:
            # --- Display Logic Starts Here ---
            try:
                df = pd.DataFrame(results_data)

                # Define Columns and Prepare DataFrame
                display_columns = {
                    'id': 'ID', 'candidate_name': 'Name','email': 'Email', 'resume_page_range': 'Pages',
                    'score_percent': 'Fit Score (%)', 'overall_score_percent': 'Overall Score (%)',
                    'total_years_experience': 'Exp (Yrs)', 'total_internship_duration': 'Internships',
                    'matched_skills': 'Matched Skills', 'missing_skills': 'Missing Skills',
                    'score_reasoning': 'Reasoning (Fit)', 'processing_timestamp': 'Processed At'
                }
                # Ensure columns exist
                for col in display_columns.keys(): df[col] = df.get(col)
                display_df = df[list(display_columns.keys())].copy()
                display_df.rename(columns=display_columns, inplace=True)

                # Formatting
                if 'Processed At' in display_df.columns:
                    try: display_df['Processed At'] = pd.to_datetime(display_df['Processed At']).dt.strftime('%Y-%m-%d %H:%M')
                    except: display_df['Processed At'] = 'Invalid Date'
                display_df['Fit Score (%)'] = pd.to_numeric(display_df['Fit Score (%)'], errors='coerce').fillna(-1).astype(int)
                display_df['Overall Score (%)'] = pd.to_numeric(display_df['Overall Score (%)'], errors='coerce').fillna(-1).astype(int)
                display_df['Exp (Yrs)'] = pd.to_numeric(display_df['Exp (Yrs)'], errors='coerce').fillna(0).round(1)

                # Filtering UI
                st.markdown("---"); st.markdown("#### Filter Results")
                filter_cols = st.columns([1, 1, 2])
                min_fit_score = filter_cols[0].slider("Min Fit Score:", -1, 100, -1, format="%d%%", key="sf", help="Filter by job fit score (-1 shows all).")
                min_exp_years = filter_cols[1].slider("Min Exp (Yrs):", 0, int(display_df['Exp (Yrs)'].max()) + 1, 0, key="ef", help="Filter by minimum years of experience.")
                search_term = filter_cols[2].text_input("Search Name/Email:", key="searchf", placeholder="Filter by text...")

                # Apply Filters
                filtered_df = display_df[
                    (display_df['Fit Score (%)'] >= min_fit_score) &
                    (display_df['Exp (Yrs)'] >= min_exp_years)
                ]
                if search_term:
                    filtered_df = filtered_df[
                        filtered_df['Name'].astype(str).str.contains(search_term, case=False, na=False) |
                        filtered_df['Email'].astype(str).str.contains(search_term, case=False, na=False)
                    ]

                st.markdown(f"**Displaying {len(filtered_df)} of {len(results_data)} candidates for this job**")

                # Display Table with column configuration
                st.dataframe(
                    filtered_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "ID": st.column_config.NumberColumn(width="small"),
                        "Name": st.column_config.TextColumn(width="medium"),
                        "Email": st.column_config.TextColumn(width="medium"),
                        "Pages": st.column_config.TextColumn(width="small"),
                        "Fit Score (%)": st.column_config.ProgressColumn(
                            format="%d%%", width="medium", min_value=0, max_value=100,
                            help="Candidate fit score based on JD."
                        ),
                        "Overall Score (%)": st.column_config.ProgressColumn(
                            format="%d%%", width="medium", min_value=0, max_value=100,
                            help="General CV quality score."
                        ),
                        "Exp (Yrs)": st.column_config.NumberColumn(format="%.1f Yrs", width="small"),
                        "Internships": st.column_config.TextColumn(width="small"),
                        "Matched Skills": st.column_config.ListColumn(width="medium", help="Skills found matching JD."),
                        "Missing Skills": st.column_config.ListColumn(width="medium", help="Skills from JD potentially missing."),
                        "Reasoning (Fit)": st.column_config.TextColumn(width="large", help="AI reasoning for the fit score."),
                        "Processed At": st.column_config.TextColumn(width="medium")
                    }
                )

                # Download Button
                @st.cache_data
                def convert_df_to_csv(df_to_convert): return df_to_convert.to_csv(index=False).encode('utf-8')
                csv_data = convert_df_to_csv(filtered_df)
                st.download_button(
                    label="📥 Download Filtered Results", data=csv_data,
                    file_name=f'job_{st.session_state.selected_job_id}_results_{time.strftime("%Y%m%d")}.csv',
                    mime='text/csv', help="Download the currently filtered table data."
                )
            # --- End Display Logic ---
            except Exception as display_err:
                st.error(f"⚠️ Error occurred while displaying results: {display_err}")
                logger.error("Results display encountered an error.", exc_info=True)
        else: # If results_data is empty
            st.info(f"No candidates found in the database for the selected job (ID: {st.session_state.selected_job_id}).")
    else: # If no job is selected
        st.info("Select a processing job from the dropdown above to view results.")

    # Button to start over
    if st.button("Process Another PDF"):
        reset_app_state()
        st.rerun()

# --- Fallback (No changes needed here) ---
elif st.session_state.current_step not in range(6):
     st.error("Unexpected state. Resetting."); logger.error(f"App invalid state: {st.session_state.current_step}. Resetting.")
     reset_app_state(); st.rerun()

# --- Sidebar ---
# --- Fallback ---
elif st.session_state.current_step not in range(6):
     st.error("Unexpected state. Resetting."); logger.error(f"App invalid state: {st.session_state.current_step}. Resetting.")
     reset_app_state(); st.rerun()