import streamlit as st
import fitz
import pandas as pd
import logging
import time
import io
from datetime import datetime
import functools # Keep for potential future use
import json
import re # No longer needed for experience parsing, can remove if not used elsewhere

# --- Project Modules --- (Keep as before)
try:
    import config
    from services import storage_service, ocr_service, assistants
except ImportError as e: st.error(f"🚨 Failed import: {e}."); st.stop()

# --- Configuration, Page Config, Styling, Logging, DB Init --- (Keep as before)
st.set_page_config( layout="wide", page_title="AI Resume Analyzer Pro", page_icon="📄", initial_sidebar_state="expanded",
    menu_items={ 'Get Help': 'https://github.com/YouROS12/ai-resume-ranker', 'Report a bug': "https://github.com/YouROS12/ai-resume-ranker/issues", 'About': "AI Resume Analyzer Pro" })
# Keep the simplified CSS
st.markdown(""" <style> ... </style> """, unsafe_allow_html=True)
logger = logging.getLogger(__name__);
if not logging.getLogger().handlers: logging.basicConfig(level=logging.INFO, format='%(asctime)s-%(levelname)s-[%(module)s]-%(message)s')
try:
    if hasattr(config, 'validate_config'): config.validate_config()
    storage_service.init_db(); logger.info("System initialized.")
except Exception as e: st.error(f"🚨 System init failed: {e}"); st.stop()

# --- State Management --- (Keep initialize_state, reset_app_state as before)
def initialize_state():
    defaults = { 'mode': None, 'current_step': 0, 'pdf_document': None, 'total_pages': 0, 'current_page_index': 0, 'start_page_of_current_group': 1,
        'resume_page_groups': [], 'splitting_started': False, 'splitting_complete': False, 'ocr_response_data': None, 'pdf_bytes_hash': None,
        'pdf_bytes': None, 'ocr_error': None, 'ocr_in_progress': False, 'uploaded_pdf_name': None, 'job_description': "", 'job_name_input': "",
        'process_button_active': False, 'processing_in_progress': False, 'selected_job_id': None, 'current_job_id': None, 'processing_log': [],
        'last_job_description': "", 'theme': 'light' }
    for key, value in defaults.items():
        if key not in st.session_state: st.session_state[key] = value
def reset_app_state():
    preserved_theme = st.session_state.get('theme', 'light'); keys_to_clear = list(st.session_state.keys())
    for key in keys_to_clear: del st.session_state[key]; st.cache_data.clear(); logger.info("Cleared state & cache.")
    initialize_state(); st.session_state.theme = preserved_theme
initialize_state()

# --- Helper Functions --- (Keep render_page*, cached_load*, convert_df_to_csv, render_step_indicator)
@st.cache_data(max_entries=50)
def render_page_cached(_pdf_doc_bytes_hash, _pdf_doc_bytes, page_index):
    if not _pdf_doc_bytes: return None; # ... (keep implementation)
    try:
        with fitz.open(stream=io.BytesIO(_pdf_doc_bytes), filetype="pdf") as pdf_doc:
            if 0 <= page_index < len(pdf_doc): page = pdf_doc.load_page(page_index); pix = page.get_pixmap(matrix=fitz.Matrix(1.7, 1.7)); return pix.tobytes("png")
            else: return None
    except Exception as e: logger.error(f"Error rendering page {page_index} from cache: {e}", exc_info=True); return None
@st.cache_data(ttl=3600)
def cached_load_job_list(): logger.info("CACHE: Loading job list."); return storage_service.load_job_list()
@st.cache_data(ttl=3600)
def cached_load_candidates_for_job(job_id: int):
    if not job_id: return []; logger.info(f"CACHE: Loading candidates job {job_id}.")
    return storage_service.load_candidates_for_job(job_id) # Uses simplified loader
@st.cache_data
def convert_df_to_csv(df_to_convert): logger.debug("Converting df to CSV."); return df_to_convert.to_csv(index=False).encode('utf-8')
def render_step_indicator(): # ... (keep implementation)
    steps = ["Upload", "JD", "Split", "Confirm", "Process", "Results"]; cur = st.session_state.current_step
    if cur < len(steps):
        cols = st.columns(len(steps));
        for i, s in enumerate(steps):
            with cols[i]:
                if i < cur: st.markdown(f"<div style='text-align: center; opacity: 0.7;'><span style='color: green;'>✅</span><br><span style='font-size: 0.85em; color: grey;'>{s}</span></div>", unsafe_allow_html=True)
                elif i == cur: st.markdown(f"<div style='text-align: center;'><span style='color: #0d6efd;'>🔵</span><br><span style='font-size: 0.85em; font-weight: bold;'>{s}</span></div>", unsafe_allow_html=True)
                else: st.markdown(f"<div style='text-align: center; opacity: 0.7;'><span style='color: lightgrey;'>⚪</span><br><span style='font-size: 0.85em; color: grey;'>{s}</span></div>", unsafe_allow_html=True)

# --- Utility to safely parse JSON lists/dicts --- (Keep this)
def safe_json_loads(json_string, default_value=None):
    """Safely parses a JSON string, returning default_value on error."""
    if not json_string or not isinstance(json_string, str): return default_value
    try: return json.loads(json_string)
    except (json.JSONDecodeError, TypeError): return default_value

# --- Remove render_candidate_details function ---

# --- *** Final Simplified display_job_results Function *** ---
def display_job_results(job_id: int, job_options: dict):
    """Renders a simple, fixed-column results table with specific extracted info."""
    st.subheader(f"Candidates for: \"{job_options.get(job_id, f'Job ID {job_id}')}\"")
    candidates_data = cached_load_candidates_for_job(job_id) # Gets simplified data

    if not candidates_data:
        st.info(f"No candidates found in the database for this job.")
        return

    try:
        df = pd.DataFrame(candidates_data)
        df_display = pd.DataFrame() # Create a new DF for the final table columns

        # --- Extract and Prepare Data for Display ---

        # 1. Core Identifiers & Direct Fields
        df_display['ID'] = df['id']
        df_display['Name'] = df['candidate_name']
        df_display['Email'] = df['email']
        df_display['Phone'] = df['personal_information'].apply(lambda x: safe_json_loads(x, {}).get('phone_number', 'N/A'))
        df_display['Experience'] = df['total_years_experience'].fillna('N/A').astype(str)
        df_display['Internship Duration'] = df['total_internship_duration'].fillna('N/A').astype(str)
        df_display['Reasoning'] = df['score_reasoning'].fillna('')
        df_display['Job Name'] = df['job_name'] # From the JOIN in load_candidates

        # 2. Scores
        df_display['Fit Score (%)'] = pd.to_numeric(df['score_percent'], errors='coerce').fillna(-1).astype(int)
        df_display['Overall Score (%)'] = pd.to_numeric(df['overall_score_percent'], errors='coerce').fillna(-1).astype(int)

        # 3. Parse JSON Lists for display
        df_display['Degrees'] = df['education'].apply(lambda x: [edu.get('degree', 'N/A') for edu in safe_json_loads(x, []) if isinstance(edu, dict)])
        df_display['All Skills'] = df['skills'].apply(lambda x: safe_json_loads(x, []))
        df_display['Certifications'] = df['certifications'].apply(lambda x: [cert.get('certification_name', 'N/A') for cert in safe_json_loads(x, []) if isinstance(cert, dict)])
        df_display['Matched Skills'] = df['matched_skills'].apply(lambda x: safe_json_loads(x, []))
        df_display['Missing Skills'] = df['missing_skills'].apply(lambda x: safe_json_loads(x, []))

        # --- Define Final Columns and Order ---
        # Match the user's requested list
        final_columns_ordered = [
            'Job Name',
            #'ID',
            'Name',
            'Email',
            'Phone',
            'Experience',
            'Degrees',
            'All Skills',
            'Matched Skills',
            'Missing Skills',
            'Fit Score (%)',
            'Reasoning',
            'Certifications',
            'Internship Duration',
            'Overall Score (%)',
        ]

        # Select only the columns that were successfully created
        final_cols_present = [col for col in final_columns_ordered if col in df_display.columns]
        df_final_table = df_display[final_cols_present]

        # --- Display Table (No Filters) ---
        st.markdown("---")
        st.markdown(f"**Displaying {len(df_final_table)} candidates**")

        # --- Configure Columns ---
        column_config = {
            "Name": st.column_config.TextColumn(width="medium"),
            "Email": st.column_config.TextColumn(width="medium"),
            "Phone": st.column_config.TextColumn(width="small"),
            "Degrees": st.column_config.ListColumn(width="medium"),
            "All Skills": st.column_config.ListColumn(width="large"),
            "Certifications": st.column_config.ListColumn(width="medium"),
            "Fit Score (%)": st.column_config.ProgressColumn(format="%d%%", width="small", min_value=0, max_value=100),
            "Reasoning": st.column_config.TextColumn(width="large"),
            "Matched Skills": st.column_config.ListColumn(width="medium"),
            "Missing Skills": st.column_config.ListColumn(width="medium"),
            "Experience": st.column_config.TextColumn("Total Exp.", width="small"), # Shorten Header
            "Internship Duration": st.column_config.TextColumn("Internships", width="small"), # Shorten Header
            "Overall Score (%)": st.column_config.ProgressColumn(format="%d%%", width="small", min_value=0, max_value=100),
            "Job Name": st.column_config.TextColumn(width="medium"),
            #"ID": st.column_config.NumberColumn(width="small"),
        }
        # Filter config only for columns present in the final table
        active_config = {k: v for k, v in column_config.items() if k in df_final_table.columns}

        st.dataframe(
            df_final_table,
            use_container_width=False, # Enable expand button
            hide_index=True,
            column_config=active_config,
            column_order=final_cols_present
        )

        # --- Download Button (Exports this specific view) ---
        if not df_final_table.empty:
            df_export = df_final_table.copy()
            # Convert list columns to strings for CSV export
            list_cols = ['Degrees', 'All Skills', 'Certifications', 'Matched Skills', 'Missing Skills']
            for col in list_cols:
                if col in df_export.columns:
                     df_export[col] = df_export[col].apply(lambda x: '; '.join(map(str, x)) if isinstance(x, list) else x)

            csv_data = convert_df_to_csv(df_export)
            st.download_button(label="📥 Download Results", data=csv_data, file_name=f'job_{job_id}_candidates_{time.strftime("%Y%m%d")}.csv', mime='text/csv')

    except KeyError as e:
         st.error(f"⚠️ Data Display Error: Could not find data field: {e}.")
         logger.error(f"KeyError displaying results for job {job_id}: {e}", exc_info=True)
    except Exception as e:
        st.error(f"⚠️ An unexpected error occurred displaying results: {e}")
        logger.error(f"Display results error for job {job_id}.", exc_info=True)

# --- ========================= UI Flow ========================= ---

# --- Sidebar --- (Keep as before)
with st.sidebar:
    st.title("📄 AI Ranker")
    theme_toggle = st.toggle("🌙 Dark Mode", value=st.session_state.theme == 'dark', key="theme_toggle")
    if theme_toggle != (st.session_state.theme == 'dark'):
        st.session_state.theme = 'dark' if theme_toggle else 'light'
        st.rerun()
    st.markdown("---")
    if st.session_state.mode:
        switch_to_mode = 'History View' if st.session_state.mode == 'new' else 'New Analysis'
        if st.button(f"🔄 Switch to {switch_to_mode}", key="switch_mode"):
            st.session_state.mode = 'history' if st.session_state.mode == 'new' else 'new'
            if st.session_state.mode == 'new': st.session_state.current_step = 0
            st.rerun()
    st.markdown("---")
    st.caption(f"DB: `{config.DATABASE_NAME}`")
    if st.button("🔄 Clear Cache & Reload", help="Force reload data.", key="clear_cache"):
        cached_load_job_list.clear(); cached_load_candidates_for_job.clear(); render_page_cached.clear(); convert_df_to_csv.clear()
        logger.info("User cleared Streamlit cache."); st.rerun()
    if st.session_state.current_step > 0 or st.session_state.mode == 'history':
        if st.button("🆕 Reset Application", help="Clears state, returns to mode selection.", key="reset_app"):
            reset_app_state(); st.session_state.mode = None; st.rerun()
    st.markdown("---")
    # Sidebar Status Indicators (keep conditional logic)
    if st.session_state.mode == 'new':
        st.header("New Analysis Status"); step_map = {0:"1. PDF", 1:"2. JD", 2:"3. Split", 3:"4. Confirm", 4:"4. AI Processing", 5:"5. Results"}; st.metric("Current Step", step_map.get(st.session_state.current_step,"?"));
        if st.session_state.get('pdf_bytes_hash'): st.success(f"📄 PDF Loaded")
        if st.session_state.get('ocr_error'): st.error("⚠️ OCR Failed")
        elif isinstance(st.session_state.get('ocr_response_data'), list): st.success("✅ OCR Ready")
        if st.session_state.get('splitting_complete'): st.success(f"✅ Split Done ({len(st.session_state.resume_page_groups)} groups)")
        if st.session_state.get('processing_in_progress'): st.warning("⏳ AI Processing...")
    elif st.session_state.mode == 'history':
        st.header("History View Status");
        try:
            job_list_sidebar = cached_load_job_list()
            job_opts = {job['job_id']: job['job_name'] for job in job_list_sidebar}
            sel_id = st.session_state.get('selected_job_id')

            if sel_id and sel_id in job_opts:
                st.info(f"Viewing: \"{job_opts[sel_id]}\"")
            elif job_list_sidebar:
                st.info("Select a job to view.")
            else:
                st.info("No previous jobs found.")

        except Exception as e:
            logger.error(f"Sidebar job list error: {e}", exc_info=True)
            st.error("Error loading jobs.")
# --- Main Panel Logic ---
st.title("📄 AI Resume Analyzer Pro")
# Feature Box Markdown 
st.markdown("""<div style='background-color: #e7f3fe; padding: 1rem; border-radius: 10px; margin-bottom: 1.5rem; border: 1px solid #cce5ff;'> <h4 style='margin: 0 0 0.5rem 0; color: #0a58ca; font-weight: bold;'>🚀 Streamline Your Hiring</h4> <ul style='margin-bottom: 0; padding-left: 20px; color: #0a58ca; list-style-type: disc;'> <li><b>Upload PDF:</b> Process multiple resumes at once.</li> <li><b>Define Boundaries:</b> Easily separate individual resumes.</li> <li><b>AI Analysis:</b> Extract key info and score against your JD.</li> <li><b>Interactive Dashboard:</b> Filter, sort, and export results.</li> </ul> </div> """, unsafe_allow_html=True)

# --- Mode Selection --- 
if not st.session_state.mode:
    st.markdown("### Welcome! Choose an action:"); cols = st.columns(2)
    with cols[0]:
        if st.button("🚀 Process New Resumes", use_container_width=True, type="primary", key="start_new"):
            reset_app_state(); st.session_state.mode = 'new'; st.session_state.current_step = 0; st.rerun()
    with cols[1]:
        if st.button("📊 View Previous Results", use_container_width=True, key="view_history"):
            st.session_state.mode = 'history';
            try: jobs = cached_load_job_list(); st.session_state.selected_job_id = jobs[0]['job_id'] if jobs else None
            except Exception: st.session_state.selected_job_id = None; st.rerun() # Add rerun on exception too

# --- History View ---
elif st.session_state.mode == 'history':
    st.header("📊 Previous Analysis Results"); st.markdown("Select a job to view results.")
    try: jobs = cached_load_job_list(); opts = {j['job_id']: f"{j['job_name']} ({datetime.strptime(j['created_at'][:19], '%Y-%m-%d %H:%M:%S').strftime('%y-%m-%d %H:%M')})" for j in jobs}
    except Exception as e: st.error(f"Err loading jobs: {e}"); logger.error(f"Hist job list err: {e}", exc_info=True); jobs = []; opts = {}
    if not jobs: st.info("No previous jobs found.")
    else:
        sel = st.session_state.get('selected_job_id'); ids = list(opts.keys());
        if sel not in ids: sel = ids[0] if ids else None
        cols = st.columns([4, 4, 1])
        with cols[0]: # Selectbox
             sel_ui = st.selectbox("Select Job:", options=ids, format_func=lambda jid: opts.get(jid, f"ID {jid}"), index=ids.index(sel) if sel in ids else 0, key="job_sel_hist", label_visibility="collapsed")
             if sel_ui != st.session_state.selected_job_id: st.session_state.selected_job_id = sel_ui; logger.info(f"Hist view selected Job ID {sel_ui}."); st.rerun()
        sel_details = next((j for j in jobs if j['job_id'] == st.session_state.selected_job_id), None)
        with cols[1]: # Details
             if sel_details: st.caption(f"**PDF:** `{sel_details.get('pdf_filename','N/A')}` | **Created:** {datetime.strptime(sel_details['created_at'][:19],'%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M')}")
             elif st.session_state.selected_job_id: st.caption("Loading...")
             else: st.caption("Select job.")
        with cols[2]: # Delete Popover
            if st.session_state.selected_job_id:
                name = opts.get(st.session_state.selected_job_id, f"ID {st.session_state.selected_job_id}")
                with st.popover("🗑️", use_container_width=True, help=f"Delete job '{name}'"):
                    st.warning(f"Delete job **'{name}'** and all data?");
                    if st.button("Confirm Delete", key=f"confirm_del_{st.session_state.selected_job_id}", type="primary"):
                        jid_del = st.session_state.selected_job_id; logger.warning(f"Confirm delete job ID {jid_del} ('{name}')")
                        deleted = storage_service.delete_job_and_candidates(jid_del)
                        if deleted: st.toast(f"Job '{name}' deleted.", icon="✅"); cached_load_candidates_for_job.clear(); cached_load_job_list.clear(); st.session_state.selected_job_id = None; st.rerun()
                        else: st.error("Failed to delete."); logger.error(f"Delete failed job ID {jid_del}.")
        # Display Results using updated function
        if st.session_state.selected_job_id: display_job_results(st.session_state.selected_job_id, opts)
        elif jobs: st.info("Select a job to view results.")


# --- New Analysis Flow --- (Steps 0-5 logic remains the same, calls updated display_job_results at step 5)
elif st.session_state.mode == 'new':
    if st.session_state.current_step < 5: render_step_indicator(); st.divider()
    # Step 0: PDF Upload (Keep logic)
    if st.session_state.current_step == 0:
        st.header("Step 1: Upload Resume PDF"); st.info("Select a single PDF file.")
        uploaded_pdf = st.file_uploader("Upload PDF", type="pdf", key="pdf_uploader_step0", label_visibility="collapsed")
        if uploaded_pdf is not None: # ... (Keep all PDF processing and OCR logic) ...
            pdf_bytes = uploaded_pdf.getvalue(); current_pdf_hash = hash(pdf_bytes)
            if current_pdf_hash != st.session_state.pdf_bytes_hash:
                logger.info(f"New PDF: {uploaded_pdf.name}."); # Reset state...
                st.session_state.pdf_document = None; st.session_state.total_pages = 0; st.session_state.current_page_index = 0; st.session_state.start_page_of_current_group = 1; st.session_state.resume_page_groups = []; st.session_state.splitting_started = False; st.session_state.splitting_complete = False; st.session_state.ocr_response_data = None; st.session_state.process_button_active = False; st.session_state.ocr_error = None; st.session_state.ocr_in_progress = True; st.session_state.processing_in_progress = False; st.session_state.pdf_bytes_hash = current_pdf_hash; st.session_state.current_job_id = None; st.session_state.uploaded_pdf_name = uploaded_pdf.name; st.session_state.pdf_bytes = pdf_bytes
                try: # Load PDF...
                    st.session_state.pdf_document = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf"); st.session_state.total_pages = len(st.session_state.pdf_document); logger.info(f"PDF loaded: {st.session_state.total_pages} pages.")
                    if st.session_state.total_pages == 0: st.warning("⚠️ PDF has 0 pages."); st.session_state.ocr_in_progress = False; st.session_state.pdf_bytes_hash = None; st.session_state.pdf_bytes = None; st.stop()
                except Exception as pdf_err: st.error(f"❌ Failed load PDF: {pdf_err}"); logger.error(f"PDF load error: {pdf_err}", exc_info=True); st.session_state.ocr_in_progress = False; st.session_state.pdf_bytes_hash = None; st.session_state.pdf_bytes = None; st.stop()
                if st.session_state.pdf_document and st.session_state.total_pages > 0: # Trigger OCR...
                    ocr_status = st.empty(); ocr_status.info("⚙️ Performing OCR..."); t0 = time.time();
                    with st.spinner("Analyzing text..."): ocr_result = ocr_service.perform_ocr(uploaded_pdf.name, pdf_bytes)
                    t1 = time.time(); logger.info(f"OCR done in {t1-t0:.2f}s.")
                    if ocr_result is not None:
                        st.session_state.ocr_response_data = ocr_result
                        if ocr_result: st.session_state.current_step = 1; st.session_state.ocr_error = None; logger.info(f"OCR OK: {len(ocr_result)} pages."); ocr_status.success(f"✅ OCR Done ({len(ocr_result)} pages)."); time.sleep(1); st.rerun()
                        else: st.session_state.ocr_error = "OCR no text."; logger.warning(st.session_state.ocr_error); ocr_status.warning(f"⚠️ {st.session_state.ocr_error}")
                    else: st.session_state.ocr_error = "OCR failed."; logger.error(st.session_state.ocr_error); ocr_status.error(f"❌ {st.session_state.ocr_error}")
                    st.session_state.ocr_in_progress = False
                if st.session_state.ocr_error or st.session_state.total_pages == 0: st.session_state.pdf_bytes_hash = None; st.session_state.pdf_bytes = None
        elif st.session_state.get('ocr_error'): st.error(f"🚨 OCR Error: {st.session_state.ocr_error}")
        elif not st.session_state.get('pdf_bytes_hash'): st.markdown("👈 Upload PDF.")
    # Step 1: JD Input (Keep logic)
    elif st.session_state.current_step == 1:
        st.header("Step 2: Enter Job Description"); # ... (Keep JD input logic) ...
        ocr_count = len(st.session_state.ocr_response_data) if isinstance(st.session_state.ocr_response_data, list) else 0; st.success(f"✅ PDF '{st.session_state.uploaded_pdf_name}' ({ocr_count} pages)."); st.info("Paste JD below.")
        jd_input = st.text_area("Job Description", height=250, key="jd_input_step1", placeholder="Paste JD here...", value=st.session_state.job_description)
        cols = st.columns([1, 3]);
        with cols[0]: # Back btn
             if st.button("⬅️ Back", key="back_to_upload"): st.session_state.current_step = 0; st.rerun()
        with cols[1]: # Next btn
             if st.button("Next ➡️", key="next_to_split", type="primary", disabled=(not jd_input.strip())): st.session_state.job_description = jd_input.strip(); st.session_state.current_step = 2; st.session_state.splitting_started = True; st.session_state.splitting_complete = False; st.session_state.resume_page_groups = []; st.session_state.current_page_index = 0; st.session_state.start_page_of_current_group = 1; logger.info("JD entered."); st.rerun()
    # Step 2: Splitting (Keep logic)
    elif st.session_state.current_step == 2:
        st.header("Step 3: Define Resume Boundaries"); # ... (Keep splitting logic) ...
        st.info("Navigate pages. Click **'End Here'** on last page of each resume. Use 'Skip'.")
        pg_num = st.session_state.current_page_index + 1; st.write(f"**Page: {pg_num}/{st.session_state.total_pages}** (Group starts page {st.session_state.start_page_of_current_group})")
        img_bytes = None; pdf_bytes = st.session_state.get('pdf_bytes');
        if pdf_bytes and st.session_state.pdf_bytes_hash: img_bytes = render_page_cached(st.session_state.pdf_bytes_hash, pdf_bytes, st.session_state.current_page_index)
        if img_bytes: l,m,r=st.columns([1,2,1]); m.image(img_bytes, use_container_width=True)
        else: st.warning("No preview.")
        st.markdown("---"); cols = st.columns(5)
        with cols[0]: # Back
             if st.button("⬅️ Back", key="back_to_jd", use_container_width=True): st.session_state.current_step = 1; st.rerun()
        with cols[1]: # Prev Page
            if st.button("◀️ Prev", disabled=st.session_state.current_page_index<=0, use_container_width=True): st.session_state.current_page_index-=1; st.rerun()
        with cols[2]: # Next Page
            if st.button("Next ▶️", disabled=pg_num>=st.session_state.total_pages, use_container_width=True): st.session_state.current_page_index+=1; st.rerun()
        with cols[3]: # End Resume
            if st.button("✅ End Here", type="primary", use_container_width=True, help=f"End resume on page {pg_num}"):
                grp = list(range(st.session_state.start_page_of_current_group, pg_num + 1)); st.session_state.resume_page_groups.append(grp); logger.info(f"Group: {grp}."); st.toast(f"Resume (Pgs {grp[0]}-{grp[-1]}) defined.", icon="✅")
                st.session_state.current_page_index += 1; st.session_state.start_page_of_current_group = st.session_state.current_page_index + 1
                if st.session_state.current_page_index >= st.session_state.total_pages: st.session_state.splitting_complete = True; st.session_state.current_step = 3; logger.info("Split complete.")
                st.rerun()
        with cols[4]: # Skip Page
             if st.button("⏭️ Skip", help="Exclude page", use_container_width=True):
                logger.info(f"Skipped page {pg_num}."); st.toast(f"Page {pg_num} skipped.", icon="⏭️")
                st.session_state.current_page_index+=1; st.session_state.start_page_of_current_group=st.session_state.current_page_index+1
                if st.session_state.current_page_index >= st.session_state.total_pages: st.session_state.splitting_complete=True; st.session_state.current_step=3; logger.info("Split complete after skip.")
                st.rerun()
        if st.session_state.resume_page_groups: st.info(f"Defined Groups: `{st.session_state.resume_page_groups}`")
        if pg_num == st.session_state.total_pages and not st.session_state.splitting_complete: st.warning("Last page. 'End Here' or 'Skip Page' to finish.")
    # Step 3: Confirm (Keep logic)
    elif st.session_state.current_step == 3:
        st.header("Step 4: Confirm and Process"); # ... (Keep confirm logic) ...
        if not st.session_state.resume_page_groups: st.warning("⚠️ No groups defined."); # Back button...
        else:
            st.success(f"✅ Ready! {len(st.session_state.resume_page_groups)} groups defined:"); st.json(st.session_state.resume_page_groups)
            default_job = f"{st.session_state.uploaded_pdf_name.rsplit('.',1)[0] if st.session_state.uploaded_pdf_name else 'Job'}_{datetime.now().strftime('%Y%m%d_%H%M')}"
            st.session_state.job_name_input = st.text_input("Assign Unique Job Name:", value=st.session_state.get('job_name_input', default_job), key="job_name_step3")
            disabled = not st.session_state.job_name_input.strip(); cols = st.columns([1, 3])
            with cols[0]: # Back btn
                 if st.button("⬅️ Back", key="back_to_split_confirm2"): st.session_state.current_step = 2; # ... (Logic to resume splitting) ...
                 last_pg = max(p for grp in st.session_state.resume_page_groups for p in grp) if st.session_state.resume_page_groups else 0; st.session_state.current_page_index = min(last_pg, st.session_state.total_pages - 1); st.session_state.start_page_of_current_group = st.session_state.current_page_index + 1; st.session_state.splitting_complete = False; st.rerun()
            with cols[1]: # Process btn
                 if st.button("🚀 Process Job", key="process_submit_step3", type="primary", disabled=disabled):
                     job_name = st.session_state.job_name_input.strip();
                     if not job_name: st.error("❌ Name empty.")
                     else: # Create Job ID...
                         logger.info(f"Create/get job '{job_name}'..."); job_desc = (st.session_state.job_description[:100] + '...'); pdf = st.session_state.uploaded_pdf_name or "N/A"; job_id = storage_service.create_job(job_name, pdf, job_desc)
                         if job_id is None: ex_id = storage_service.get_job_id_by_name(job_name); st.error(f"❌ Job '{job_name}' exists (ID: {ex_id})." if ex_id else f"❌ Failed start job '{job_name}'."); logger.error(f"Fail get/create job '{job_name}'.")
                         else: st.session_state.current_job_id = job_id; st.session_state.processing_log = []; st.session_state.current_step = 4; st.session_state.processing_in_progress = True; logger.info(f"Start AI loop Job ID {job_id} ('{job_name}')."); st.rerun()
    # Step 4: Processing (Keep logic)
    elif st.session_state.current_step == 4:
        st.header("Step 4: AI Processing..."); # ... (Keep processing loop logic) ...
        st.info(f"🤖 Processing Job '{st.session_state.job_name_input}' (ID: {st.session_state.current_job_id}). Wait...")
        total = len(st.session_state.resume_page_groups);
        if total == 0: st.error("No groups."); #... reset logic ...
        else: # Processing loop...
            prog_bar = st.progress(0, text="Init..."); status = st.empty(); ok=0; err=0
            try:
                for i, grp in enumerate(st.session_state.resume_page_groups): # AI Processing Loop...
                    rng=f"{grp[0]}-{grp[-1]}" if len(grp)>1 else str(grp[0]); val=(i+1)/total; txt=f"Proc. {i+1}/{total} (Pgs {rng})"
                    prog_bar.progress(val, text=txt); status.info(f"🔄 {txt}: AI..."); t0=time.time()
                    extracted, scored, raw1, raw2 = assistants.process_single_resume_group(grp, st.session_state.ocr_response_data, st.session_state.job_description)
                    t1=time.time(); logger.info(f"{txt}: AI done {t1-t0:.2f}s."); status.info(f"🔄 {txt}: Store...")
                    if extracted and scored: # Store...
                         t0=time.time(); rowid=storage_service.store_candidate_data(st.session_state.current_job_id, rng, st.session_state.job_description, extracted, scored, raw1, raw2); t1=time.time()
                         if rowid: ok+=1; logger.info(f"{txt}: Stored OK {t1-t0:.2f}s.")
                         else: err+=1; logger.error(f"{txt}: DB store fail."); status.warning(f"⚠️ DB fail Pgs {rng}.")
                    elif extracted: err+=1; logger.error(f"{txt}: Score fail."); status.warning(f"⚠️ Score fail Pgs {rng}.")
                    else: err+=1; logger.error(f"{txt}: Extract fail."); status.warning(f"⚠️ Extract fail Pgs {rng}.")
                # Finish...
                prog_bar.progress(1.0, text="Complete!"); msg = f"Job '{st.session_state.job_name_input}' done."
                if ok > 0: status.success(f"✅ {msg} {ok} stored.")
                if err > 0: status.warning(f"⚠️ {msg} Issues with {err}.")
                if ok==0 and err==0: status.warning("Finished, no resumes processed.")
                st.session_state.selected_job_id = st.session_state.current_job_id; st.session_state.current_step = 5; st.session_state.processing_in_progress = False; logger.info(f"Finished Job ID {st.session_state.current_job_id}. Stored: {ok}, Errors: {err}.")
                time.sleep(2); st.rerun()
            except Exception as e: st.error(f"🚨 Critical error: {e}"); logger.error("AI loop exception.", exc_info=True); st.session_state.processing_in_progress = False; st.session_state.current_step = 3; st.rerun()
    # Step 5: Show Results (Calls updated display_job_results)
    elif st.session_state.current_step == 5:
        st.header("🏁 Step 5: Analysis Results"); # ... (Keep logic calling display_job_results) ...
        job_name = st.session_state.get('job_name_input', f"ID {st.session_state.selected_job_id}"); st.info(f"Results for job: **{job_name}** (ID: {st.session_state.selected_job_id})")
        try: jobs = cached_load_job_list(); opts = {j['job_id']: f"{j['job_name']} (...)" for j in jobs}
        except Exception as e: logger.error(f"Results view job opts error: {e}"); opts = {}
        if st.session_state.selected_job_id: display_job_results(st.session_state.selected_job_id, opts)
        else: st.warning("No job selected."); logger.warning("Results step 5 no selected_job_id.")
        if st.button("✨ Process Another PDF", key="process_another"): reset_app_state(); st.session_state.mode = 'new'; st.session_state.current_step = 0; st.rerun()


# --- Fallback --- (Keep as before)
elif st.session_state.mode == 'new' and st.session_state.current_step not in range(6):
     st.error("Unexpected state. Resetting."); logger.error(f"App invalid state: Step {st.session_state.current_step}. Resetting.")
     reset_app_state(); st.session_state.mode = None; st.rerun()

# --- Footer --- (Keep as before)
st.markdown("---"); st.caption("AI Resume Analyzer Pro | Powered by Streamlit, OpenAI & Mistral")