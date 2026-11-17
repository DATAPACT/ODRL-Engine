import streamlit as st

import tempfile
import os
import multiprocessing
import pandas as pd
from io import StringIO

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.streamlit_style import apply_style
import ODRL_Evaluator as Evaluator
import rdf_utils
from rdf_utils import extract_features_list_from_policy

# ------------------------------
# Config
# ------------------------------

EVAL_TIMEOUT_SECONDS = int(os.environ.get("ODRL_STREAMLIT_EVAL_TIMEOUT_SECONDS", "30"))
COLUMNS_TIMEOUT_SECONDS = int(os.environ.get("ODRL_STREAMLIT_COLUMNS_TIMEOUT_SECONDS", "15"))

# ------------------------------
# Worker functions (must be top-level/picklable for multiprocessing)
# ------------------------------

def _run_evaluation(policy_paths, sotw_path, result_queue):
    try:
        result = Evaluator.evaluate_ODRL_from_files_merge_policies(policy_paths, sotw_path)
        result_queue.put(("ok", result))
    except Exception as e:
        result_queue.put(("error", str(e)))


def _run_extract_columns(policy_path, result_queue):
    try:
        graph = rdf_utils.load(policy_path)[0]
        features = extract_features_list_from_policy(graph)
        column_names = [feature["iri"] for feature in features]
        result_queue.put(("ok", column_names))
    except Exception as e:
        result_queue.put(("error", str(e)))


def _run_with_timeout(target, args, timeout_seconds):
    """
    Runs `target` in a separate process, hard-killing it if it exceeds
    timeout_seconds. Returns ("ok", value), ("error", message), or ("timeout", None).
    """
    result_queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=target, args=(*args, result_queue))
    proc.start()
    proc.join(timeout=timeout_seconds)

    if proc.is_alive():
        proc.terminate()
        proc.join()
        return ("timeout", None)

    if result_queue.empty():
        # Process died without putting a result (e.g. killed by OOM)
        return ("error", "Evaluation process terminated unexpectedly.")

    return result_queue.get()


# ------------------------------
# Page setup
# ------------------------------

st.set_page_config(
    page_title="ODRL Policy Evaluator",
    layout="wide"
)
apply_style()
st.markdown("## Policy Evaluator")

st.markdown(
    "This is the [OVAL Policy Evaluator for ODRL](https://github.com/DIPS-Tools/ODRL-Engine) from the University of Southampton."
)

st.markdown(
    "Paste or upload an **ODRL Policy** and a **State of the World**, then evaluate. You can see sample files [here](https://github.com/DIPS-Tools/ODRL-Engine/tree/main/test_cases/evaluation/monitoring_compliant)"
)

st.markdown(
    "After uploading an **ODRL Policy** you can press the **Show expected column names** button below to see a list of the column names that should appear in the State of the World. Each column name is listed in a row, note that some of them include a space in the name, which must be preserved. The order of the columns does not matter. If a column does not appear in the State of the World Object, the evaluator will assume all values are null for that feature."
)

st.markdown(
    "The evaluator currently supports comparison of dates, numbers and string and URI identifiers in the State of the World object. Values are considered strings/URIs by default if using the equality operator, or numbers if using a numerical comparison operator like < or >=, unless a common date format (like %d-%m-%Y, %Y-%m-%d, %Y-%m-%dT%H:%M:%S, %Y-%m-%dT%H:%M) is detected. This means that for numbers to be considered equal, they need to be written in the same syntactic form (e.g. '4' would not be considered equal to '4.0')"
)

# ------------------------------
# Session state initialization
# ------------------------------

if "policy_text" not in st.session_state:
    st.session_state.policy_text = ""

if "sotw_text" not in st.session_state:
    st.session_state.sotw_text = ""

if "raw_toggle" not in st.session_state:
    st.session_state.raw_toggle = True  # start TRUE

if "policy_upload_id" not in st.session_state:
    st.session_state.policy_upload_id = None

if "policy_suffix" not in st.session_state:
    st.session_state.policy_suffix = ".ttl"

if "sotw_upload_id" not in st.session_state:
    st.session_state.sotw_upload_id = None

# ------------------------------
# Layout
# ------------------------------

col1, col2 = st.columns(2)

# ==============================
# POLICY COLUMN
# ==============================

with col1:

    st.subheader("ODRL Policy")

    uploaded_policy = st.file_uploader(
        "Upload Policy File",
        type=[
            "ttl",
            "json",
            "jsonld",
            "rdf",
            "xml",
            "nt",
            "nq",
            "trig",
            "trix",
        ],
        label_visibility="collapsed",
        key="policy_upload"
    )

    # Only load from the uploader when it's a genuinely NEW file —
    # not on every rerun triggered by unrelated widgets. This also
    # means manual edits to the text area below are never clobbered.
    if uploaded_policy is not None:

        if uploaded_policy.file_id != st.session_state.policy_upload_id:
            st.session_state.policy_upload_id = uploaded_policy.file_id
            st.session_state.policy_text = uploaded_policy.getvalue().decode("utf-8")
            # Preserve the original file extension
            st.session_state.policy_suffix = Path(uploaded_policy.name).suffix.lower()

            st.rerun()

    # Policy text box
    policy_text = st.text_area(
        label="Policy Text",
        height=450,
        key="policy_text"
    )

    # ------------------------------
    # Show expected column names
    # ------------------------------

    if st.button(
        "Show expected column names",
        use_container_width=True
    ):

        if not st.session_state.policy_text.strip():

            st.warning("⚠️ Please paste or upload an ODRL policy first.")

        else:

            policy_path = None

            try:
                # Save policy temporarily so rdf_utils can load it
                policy_suffix = st.session_state.policy_suffix

                with tempfile.NamedTemporaryFile(
                    suffix=policy_suffix,
                    delete=False,
                    mode="w",
                    encoding="utf-8"
                ) as policy_file:

                    policy_file.write(
                        st.session_state.policy_text
                    )
                    policy_path = policy_file.name

                with st.spinner("Extracting expected columns..."):
                    status, payload = _run_with_timeout(
                        _run_extract_columns,
                        (policy_path,),
                        COLUMNS_TIMEOUT_SECONDS,
                    )

                if status == "timeout":
                    st.error(
                        f"⚠️ Timed out after {COLUMNS_TIMEOUT_SECONDS} seconds "
                        "while reading the policy."
                    )
                elif status == "error":
                    st.error(
                        "Error, the policy input field does not contain a valid ODRL policy"
                    )
                else:
                    column_names = payload

                    st.subheader("Expected column names")

                    bullet_list = "\n".join(
                        [f"- `{name}`" for name in column_names]
                    )

                    st.markdown(bullet_list)

            except Exception:

                st.error(
                    "Error, the policy input field does not contain a valid ODRL policy"
                )

            finally:

                if policy_path and os.path.exists(policy_path):
                    os.remove(policy_path)

# ==============================
# SOTW COLUMN
# ==============================

with col2:

    st.subheader("State of the World")

    uploaded_sotw = st.file_uploader(
        "Upload SotW CSV",
        type=["csv"],
        label_visibility="collapsed",
        key="sotw_upload"
    )

    if uploaded_sotw is not None:
        if uploaded_sotw.file_id != st.session_state.sotw_upload_id:
            st.session_state.sotw_upload_id = uploaded_sotw.file_id
            st.session_state.sotw_text = uploaded_sotw.getvalue().decode("utf-8")
            st.session_state.raw_toggle = False
            st.rerun()

    raw_toggle = st.toggle("Raw Text", key="raw_toggle")

    if raw_toggle:

        st.session_state.sotw_text = st.text_area(
            "CSV Text",
            value=st.session_state.sotw_text,
            height=450,
        )

    else:

        try:

            if st.session_state.sotw_text.strip():

                df = pd.read_csv(StringIO(st.session_state.sotw_text))
                st.dataframe(df, use_container_width=True, height=450)

            else:

                st.session_state.sotw_text = st.text_area(
                    "CSV Text",
                    value=st.session_state.sotw_text,
                    height=450,
                )

        except Exception:

            st.warning("⚠️ CSV could not be parsed — enable Raw Text mode to edit.")

            st.session_state.sotw_text = st.text_area(
                "CSV Text",
                value=st.session_state.sotw_text,
                height=450,
            )

# ------------------------------
# Evaluate Button
# ------------------------------

st.divider()

evaluate_button = st.button(
    "Evaluate Policy",
    use_container_width=True
)

# ------------------------------
# Evaluation Logic
# ------------------------------

if evaluate_button:

    policy_text = st.session_state.policy_text
    sotw_text = st.session_state.sotw_text

    if not policy_text.strip():
        st.error("⚠️ Please paste or upload an ODRL policy.")
        st.stop()

    if not sotw_text.strip():
        st.error("⚠️ Please paste or upload a SotW CSV.")
        st.stop()

    policy_path = None
    sotw_path = None

    try:

        policy_suffix = st.session_state.policy_suffix

        # Save temp files
        with tempfile.NamedTemporaryFile(
            suffix=policy_suffix,
            delete=False,
            mode="w",
            encoding="utf-8"
        ) as policy_file:

            policy_file.write(policy_text)
            policy_path = policy_file.name

        with tempfile.NamedTemporaryFile(
            suffix=".csv",
            delete=False,
            mode="w",
            encoding="utf-8"
        ) as sotw_file:

            sotw_file.write(sotw_text)
            sotw_path = sotw_file.name

        # Run evaluation with a hard timeout, in a separate process so a
        # hung/pathological evaluation can actually be killed, not just
        # abandoned.
        with st.spinner("Evaluating policy..."):
            status, payload = _run_with_timeout(
                _run_evaluation,
                ([policy_path], sotw_path),
                EVAL_TIMEOUT_SECONDS,
            )

        if status == "timeout":
            st.error(
                f"⚠️ Evaluation timed out after {EVAL_TIMEOUT_SECONDS} seconds. "
                "Try a smaller policy or State of the World."
            )
            st.stop()

        if status == "error":
            st.error(f"⚠️ Evaluation error: {payload}")
            st.stop()

        (
            evaluation_state,
            is_valid,
            rows_violating_permissions,
            rows_violating_prohibitions,
            obligations_not_satisfied,
            unfulfilled_duties,
            unfulfilled_consequences,
            unfulfilled_remedies,
        ) = payload

        st.divider()

        if is_valid:
            st.success("✅ YES — State of the World is VALID (Compliant with the Policy)")
        else:
            st.error("❌ NO — State of the World is NOT VALID (Non-compliant with the Policy)")

        st.subheader("Evaluation Summary")

        if rows_violating_permissions:
            st.subheader("Rows violating permissions")
            st.write(rows_violating_permissions)

        if rows_violating_prohibitions:
            st.subheader("Rows violating prohibitions")
            st.write(rows_violating_prohibitions)

        if obligations_not_satisfied:
            st.subheader("Unsatisfied obligations")
            st.json(obligations_not_satisfied)

        if unfulfilled_duties:
            st.subheader("Unfulfilled duties")
            st.json(unfulfilled_duties)

        if unfulfilled_consequences:
            st.subheader("Unfulfilled consequences")
            st.json(unfulfilled_consequences)

        if unfulfilled_remedies:
            st.subheader("Unfulfilled remedies")
            st.json(unfulfilled_remedies)

    except Exception as e:

        st.error(f"⚠️ Evaluation error: {e}")

    finally:

        if policy_path and os.path.exists(policy_path):
            os.remove(policy_path)

        if sotw_path and os.path.exists(sotw_path):
            os.remove(sotw_path)