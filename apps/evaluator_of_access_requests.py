import streamlit as st

import tempfile
import os
import multiprocessing
import json
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
from rdf_utils import extract_features_list_from_policy

# ============================================================
# CONFIG
# ============================================================

EVAL_TIMEOUT_SECONDS = int(
    os.environ.get(
        "ODRL_ACCESS_REQUEST_EVAL_TIMEOUT_SECONDS",
        "30"
    )
)

COLUMNS_TIMEOUT_SECONDS = int(
    os.environ.get(
        "ODRL_ACCESS_REQUEST_COLUMNS_TIMEOUT_SECONDS",
        "15"
    )
)

# ============================================================
# HUMAN-READABLE ACCESS REQUEST RESULT HELPERS
# ============================================================

ODRL_NS = "http://www.w3.org/ns/odrl/2/"

OPERATOR_LABELS = {
    f"{ODRL_NS}eq": "equal to",
    f"{ODRL_NS}neq": "not equal to",
    f"{ODRL_NS}lt": "less than",
    f"{ODRL_NS}lteq": "less than or equal to",
    f"{ODRL_NS}gt": "greater than",
    f"{ODRL_NS}gteq": "greater than or equal to",
    f"{ODRL_NS}isAnyOf": "one of",
    f"{ODRL_NS}isNoneOf": "none of",
    f"{ODRL_NS}hasPart": "has part",
    f"{ODRL_NS}isPartOf": "is part of",
    f"{ODRL_NS}isAllOf": "contains all of",
}


# ============================================================
# CSS FOR RULE RESULT CONTAINERS
# ============================================================

st.markdown(
    """
    <style>

    .odrl-rule {
        border-radius: 0.5rem;
        padding: 1rem 1.25rem 1.25rem 1.25rem;
        margin-bottom: 1rem;
        border: 1px solid rgba(0, 0, 0, 0.08);
    }

    .odrl-rule-green {
        background-color: rgba(40, 167, 69, 0.12);
        border-left: 5px solid #28a745;
    }

    .odrl-rule-yellow {
        background-color: rgba(255, 193, 7, 0.16);
        border-left: 5px solid #ffc107;
    }

    .odrl-rule-red {
        background-color: rgba(220, 53, 69, 0.12);
        border-left: 5px solid #dc3545;
    }

    .odrl-rule-message {
        font-weight: 500;
        margin-bottom: 0.75rem;
    }

    .odrl-rule-heading {
        font-weight: 600;
        margin-top: 0.75rem;
        margin-bottom: 0.25rem;
    }

    .odrl-rule-list {
        margin-top: 0.25rem;
        margin-bottom: 0.75rem;
        padding-left: 1.5rem;
    }

    .odrl-rule-list li {
        margin-bottom: 0.2rem;
    }

    .odrl-original-rule {
        margin-top: 1rem;
        padding-top: 0.75rem;
        border-top: 1px solid rgba(0, 0, 0, 0.12);
    }

    .odrl-original-rule-label {
        font-size: 0.8rem;
        font-weight: 600;
        opacity: 0.7;
        margin-bottom: 0.25rem;
    }

    .odrl-original-rule-text {
        font-size: 0.85rem;
        font-style: italic;
        opacity: 0.75;
        white-space: pre-line;
    }
    
    .odrl-outcome {
        border-radius: 0.5rem;
        padding: 1rem 1.25rem;
        margin: 1rem 0 1.5rem 0;
        border: 1px solid rgba(0, 0, 0, 0.08);
        font-size: 1.15rem;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }

    .odrl-outcome-granted {
        background-color: rgba(40, 167, 69, 0.12);
        border-left: 5px solid #28a745;
    }

    .odrl-outcome-denied {
        background-color: rgba(220, 53, 69, 0.12);
        border-left: 5px solid #dc3545;
    }

    .odrl-outcome-unknown {
        background-color: rgba(255, 193, 7, 0.16);
        border-left: 5px solid #ffc107;
    }

    .odrl-outcome-icon {
        font-size: 1.5rem;
        line-height: 1;
    }

    .odrl-outcome-explanation {
        margin-top: 0.5rem;
        margin-bottom: 1.5rem;
    }

    </style>
    """,
    unsafe_allow_html=True
)

def initialise_sotw_raw_editor():
    """
    When switching to raw CSV mode, initialise the editor from the
    canonical State of the World text.
    """
    st.session_state.sotw_raw_editor = st.session_state.sotw_text

def update_sotw_from_raw_editor():
    """
    Copy edits made in the raw CSV editor back into the canonical
    State of the World text stored in session state.
    """
    st.session_state.sotw_text = st.session_state.sotw_raw_editor

def humanise_iri(iri):
    """
    Convert an IRI into a readable label.

    Important:
    Literal values such as ISO date/time strings are preserved.
    """

    if iri is None:
        return ""

    # --------------------------------------------------------
    # RDFLib values
    # --------------------------------------------------------

    try:
        from rdflib import URIRef, Literal

        if isinstance(iri, Literal):
            return str(iri)

        if isinstance(iri, URIRef):
            iri = str(iri)

        else:
            iri = str(iri)

    except ImportError:
        iri = str(iri)

    # --------------------------------------------------------
    # ODRL namespace
    # --------------------------------------------------------

    if iri.startswith(ODRL_NS):
        return iri[len(ODRL_NS):]

    # --------------------------------------------------------
    # Only process something as an IRI if it actually starts
    # with an IRI scheme.
    #
    # This is important because:
    #
    #   2027-01-11T11:13:10.665638
    #
    # contains ":" but is NOT an IRI.
    # --------------------------------------------------------

    if not iri.startswith(
        (
            "http://",
            "https://",
            "urn:"
        )
    ):
        return iri

    # --------------------------------------------------------
    # HTTP/HTTPS/URN IRI
    # --------------------------------------------------------

    if "/" in iri:
        iri = iri.rstrip("/").rsplit("/", 1)[-1]

    # Only split ':' after we know this is an IRI.
    if ":" in iri:
        iri = iri.rsplit(":", 1)[-1]

    return iri


def humanise_value(value):
    """
    Convert an ODRL value into readable text.

    Crucially, date/time literals are returned unchanged.
    """

    if isinstance(value, list):
        return ", ".join(
            humanise_value(item)
            for item in value
        )

    try:
        from rdflib import Literal, URIRef

        # ----------------------------------------------------
        # RDF Literal:
        #
        # Preserve lexical representation.
        #
        # Example:
        # 2027-01-11T11:13:10.665638
        #
        # must remain exactly that.
        # ----------------------------------------------------

        if isinstance(value, Literal):
            return str(value)

        # ----------------------------------------------------
        # RDF URI:
        #
        # Humanise it.
        # ----------------------------------------------------

        if isinstance(value, URIRef):
            return humanise_iri(value)

    except ImportError:
        pass

    # --------------------------------------------------------
    # Plain Python strings.
    #
    # IMPORTANT:
    # Do not treat every string containing ':' as an IRI.
    # --------------------------------------------------------

    if isinstance(value, str):

        if value.startswith(
            (
                "http://",
                "https://",
                "urn:"
            )
        ):
            return humanise_iri(value)

        return value

    return str(value)


def humanise_condition(condition):
    """
    Convert one ODRL condition into a human-readable sentence.
    """

    # --------------------------------------------------------
    # Logical condition
    # --------------------------------------------------------

    if (
        isinstance(condition, list)
        and len(condition) == 2
        and isinstance(condition[0], str)
        and isinstance(condition[1], list)
    ):

        logic_op = humanise_iri(
            condition[0]
        )

        subconditions = condition[1]

        readable = [
            humanise_condition(subcondition)
            for subcondition in subconditions
        ]

        if logic_op.endswith("andSequence"):
            return " and then ".join(readable)

        if logic_op.endswith("and"):
            return " and ".join(readable)

        if logic_op.endswith("or"):
            return " or ".join(readable)

        if logic_op.endswith("xone"):
            return (
                "exactly one of "
                + ", ".join(readable)
            )

        return ", ".join(readable)

    # --------------------------------------------------------
    # Normal condition
    # --------------------------------------------------------

    if (
        not isinstance(condition, list)
        or len(condition) != 3
    ):
        return str(condition)

    left, operator, right = condition

    left_text = humanise_iri(left)

    operator_text = OPERATOR_LABELS.get(
        operator,
        humanise_iri(operator)
    )

    right_text = humanise_value(right)

    if operator_text == "equal to":
        return (
            f"{left_text} is equal to "
            f"{right_text}"
        )

    if operator_text == "not equal to":
        return (
            f"{left_text} is not equal to "
            f"{right_text}"
        )

    if operator_text == "less than":
        return (
            f"{left_text} is less than "
            f"{right_text}"
        )

    if operator_text == "less than or equal to":
        return (
            f"{left_text} is less than or equal to "
            f"{right_text}"
        )

    if operator_text == "greater than":
        return (
            f"{left_text} is greater than "
            f"{right_text}"
        )

    if operator_text == "greater than or equal to":
        return (
            f"{left_text} is greater than or equal to "
            f"{right_text}"
        )

    if operator_text == "one of":
        return (
            f"{left_text} is one of "
            f"{right_text}"
        )

    if operator_text == "none of":
        return (
            f"{left_text} is none of "
            f"{right_text}"
        )

    if operator_text == "has part":
        return (
            f"{left_text} has part "
            f"{right_text}"
        )

    if operator_text == "is part of":
        return (
            f"{left_text} is part of "
            f"{right_text}"
        )

    if operator_text == "contains all of":
        return (
            f"{left_text} contains all of "
            f"{right_text}"
        )

    return (
        f"{left_text} must be {operator_text} "
        f"{right_text}"
    )


def humanise_conditions(conditions):
    """
    Convert conditions into human-readable strings.
    """

    if not conditions:
        return []

    return [
        humanise_condition(condition)
        for condition in conditions
    ]


def humanise_duty(duty):
    """
    Convert a duty into a human-readable description.
    """

    if not isinstance(duty, dict):
        return str(duty)

    description = duty.get("description")

    if description:
        return str(description)

    conditions = duty.get(
        "conditions",
        []
    )

    if conditions:
        return " and ".join(
            humanise_conditions(conditions)
        )

    rule_id = (
        duty.get("id")
        or duty.get("rule_id")
    )

    if rule_id:
        return humanise_iri(rule_id)

    return "unspecified duty"


def humanise_duties(duties):
    """
    Convert duties into human-readable strings.
    """

    if not duties:
        return []

    return [
        humanise_duty(duty)
        for duty in duties
    ]

def humanise_rule(rule, rule_type="rule"):
    """
    Generate a human-readable description of an evaluator rule.

    Party eq <party>  -> assignee
    Action eq <action> -> action
    Asset eq <asset>  -> target

    All other conditions are retained as additional conditions.
    """

    if not isinstance(rule, dict):
        return str(rule)

    description = rule.get("description")

    if description:
        return str(description)

    conditions = rule.get("conditions", [])

    PARTY_IRI = f"{ODRL_NS}Party"
    ACTION_IRI = f"{ODRL_NS}Action"
    ASSET_IRI = f"{ODRL_NS}Asset"
    EQ_IRI = f"{ODRL_NS}eq"

    assignee = None
    action = None
    target = None

    additional_conditions = []

    for condition in conditions:

        if (
            not isinstance(condition, list)
            or len(condition) != 3
        ):
            additional_conditions.append(condition)
            continue

        left, operator, right = condition

        left = str(left)
        operator = str(operator)

        if left == PARTY_IRI and operator == EQ_IRI:
            assignee = right
            continue

        if left == ACTION_IRI and operator == EQ_IRI:
            action = right
            continue

        if left == ASSET_IRI and operator == EQ_IRI:
            target = right
            continue

        additional_conditions.append(condition)

    party_text = (
        humanise_value(assignee)
        if assignee is not None
        else "any party"
    )

    action_text = (
        humanise_value(action)
        if action is not None
        else "unspecified action"
    )

    target_text = (
        humanise_value(target)
        if target is not None
        else "any target"
    )

    rule_description = (
        f"{rule_type} for {party_text} "
        f"to perform action {action_text} "
        f"on {target_text}"
    )

    if additional_conditions:

        readable_conditions = humanise_conditions(
            additional_conditions
        )

        rule_description += (
            "\n\nSubject to the following conditions:"
        )

        for condition in readable_conditions:
            rule_description += f"\n- {condition}"

    return rule_description


# ============================================================
# RULE CONTENT RENDERING
# ============================================================

def render_condition_bullets(conditions):
    """
    Render conditions as Markdown bullets.
    """

    readable_conditions = humanise_conditions(
        conditions
    )

    if not readable_conditions:
        return

    for condition in readable_conditions:
        st.markdown(
            f"- {condition}"
        )


def render_duty_bullets(duties):
    """
    Render duties as Markdown bullets.
    """

    readable_duties = humanise_duties(
        duties
    )

    if not readable_duties:
        return

    for duty in readable_duties:
        st.markdown(
            f"- {duty}"
        )


# ============================================================
# EVALUATION NOTIFICATIONS
# ============================================================

def render_evaluation_notifications(payload):
    """
    Render all matched permissions and prohibitions.

    Each complete result is rendered as a single HTML block so
    that the message, conditions and original rule all appear
    inside the same coloured background.
    """

    permissions = payload.get(
        "permissions_matched",
        []
    )

    prohibitions = payload.get(
        "prohibitions_matched",
        []
    )

    displayed = False

    # ========================================================
    # Helper for safely inserting text into HTML
    # ========================================================

    def escape_html(value):
        import html
        return html.escape(str(value))

    # ========================================================
    # PERMISSIONS
    # ========================================================

    for permission_match in permissions:

        rule = permission_match.get(
            "rule",
            {}
        )

        conditions = permission_match.get(
            "conditions",
            []
        )

        duties = permission_match.get(
            "duties",
            []
        )

        # ----------------------------------------------------
        # Determine colour / message
        # ----------------------------------------------------

        if not conditions and not duties:

            css_class = "odrl-rule-green"

            message = (
                "Your access request is explicitly "
                "granted by a rule."
            )

        else:

            css_class = "odrl-rule-yellow"

            message = (
                "Your access request can be granted "
                "by a permission rule if the following "
                "conditions hold:"
            )

        # ----------------------------------------------------
        # Build HTML
        # ----------------------------------------------------

        html_parts = []

        html_parts.append(
            f'<div class="odrl-rule {css_class}">'
        )

        # Main message

        html_parts.append(
            f'<div class="odrl-rule-message">'
            f'{escape_html(message)}'
            f'</div>'
        )

        # ----------------------------------------------------
        # Conditions
        # ----------------------------------------------------

        if conditions:

            html_parts.append(
                '<ul class="odrl-rule-list">'
            )

            for condition in humanise_conditions(
                conditions
            ):

                html_parts.append(
                    f'<li>{escape_html(condition)}</li>'
                )

            html_parts.append(
                '</ul>'
            )

        # ----------------------------------------------------
        # Duties
        # ----------------------------------------------------

        if duties:

            html_parts.append(
                '<div class="odrl-rule-heading">'
                'Subject to fulfillment of duties:'
                '</div>'
            )

            html_parts.append(
                '<ul class="odrl-rule-list">'
            )

            for duty in humanise_duties(duties):

                html_parts.append(
                    f'<li>{escape_html(duty)}</li>'
                )

            html_parts.append(
                '</ul>'
            )

        # ----------------------------------------------------
        # Original rule
        # ----------------------------------------------------

        rule_description = humanise_rule(
            rule,
            rule_type="permission"
        )

        html_parts.append(
            '<div class="odrl-original-rule">'
            '<div class="odrl-original-rule-label">'
            'Original Permission'
            '</div>'
            '<div class="odrl-original-rule-text">'
            + escape_html(rule_description)
            + '</div>'
              '</div>'
        )

        html_parts.append(
            '</div>'
        )

        st.markdown(
            "".join(html_parts),
            unsafe_allow_html=True
        )

        displayed = True

    # ========================================================
    # PROHIBITIONS
    # ========================================================

    for prohibition_match in prohibitions:

        rule = prohibition_match.get(
            "rule",
            {}
        )

        conditions = prohibition_match.get(
            "conditions",
            []
        )

        # ----------------------------------------------------
        # Determine colour / message
        # ----------------------------------------------------

        if conditions:

            css_class = "odrl-rule-yellow"

            message = (
                "Your access request might be prohibited "
                "by a rule if the following conditions hold:"
            )

        else:

            css_class = "odrl-rule-red"

            message = (
                "Your access request is explicitly "
                "prohibited by a rule."
            )

        # ----------------------------------------------------
        # Build HTML
        # ----------------------------------------------------

        html_parts = []

        html_parts.append(
            f'<div class="odrl-rule {css_class}">'
        )

        html_parts.append(
            f'<div class="odrl-rule-message">'
            f'{escape_html(message)}'
            f'</div>'
        )

        # ----------------------------------------------------
        # Conditions
        # ----------------------------------------------------

        if conditions:

            html_parts.append(
                '<ul class="odrl-rule-list">'
            )

            for condition in humanise_conditions(
                conditions
            ):

                html_parts.append(
                    f'<li>{escape_html(condition)}</li>'
                )

            html_parts.append(
                '</ul>'
            )

        # ----------------------------------------------------
        # Original prohibition
        # ----------------------------------------------------

        rule_description = humanise_rule(
            rule,
            rule_type="prohibition"
        )

        html_parts.append(
            '<div class="odrl-original-rule">'
            '<div class="odrl-original-rule-label">'
            'Original Prohibition'
            '</div>'
            '<div class="odrl-original-rule-text">'
            + escape_html(rule_description)
            + '</div>'
              '</div>'
        )

        html_parts.append(
            '</div>'
        )

        st.markdown(
            "".join(html_parts),
            unsafe_allow_html=True
        )

        displayed = True

    return displayed



# ============================================================
# WORKER FUNCTIONS
# ============================================================

def _run_extract_columns(policy_path, result_queue):
    """
    Extract the feature IRIs from an ODRL policy.
    """
    try:
        graph = rdf_utils.load(policy_path)[0]

        features = extract_features_list_from_policy(graph)

        column_names = [
            feature["iri"]
            for feature in features
        ]

        result_queue.put(("ok", column_names))

    except Exception as e:
        result_queue.put(("error", str(e)))


def _run_extract_policy_info(policy_path, result_queue):
    """
    Extract both features and actions from an ODRL policy.

    The feature extraction is the same mechanism used by the existing
    evaluator. Actions are extracted directly from the policy graph.
    """
    try:
        graph = rdf_utils.load(policy_path)[0]

        features = extract_features_list_from_policy(graph)

        column_names = [
            feature["iri"]
            for feature in features
        ]

        # ----------------------------------------------------
        # Extract actions from the policy.
        #
        # We use the RDF graph directly rather than depending
        # on the internal representation returned by
        # extract_rule_list_from_policy().
        # ----------------------------------------------------

        ODrl_ACTION = rdf_utils.ODRL_NS["action"] \
            if hasattr(rdf_utils, "ODRL_NS") else None

        # More robustly use the explicit IRI.
        ACTION_PREDICATE = (
            "http://www.w3.org/ns/odrl/2/action"
        )

        RDF_VALUE = (
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#value"
        )

        actions = set()

        for subject, predicate, obj in graph:

            if str(predicate) != ACTION_PREDICATE:
                continue

            # ODRL actions are normally represented as a blank node
            # containing rdf:value.
            action_node = obj

            for _, value_predicate, value in graph:
                if (
                    _ == action_node
                    and str(value_predicate) == RDF_VALUE
                ):
                    actions.add(str(value))

        # ----------------------------------------------------
        # Fallback:
        #
        # If actions were represented directly as IRIs rather
        # than rdf:value blank nodes, retain them as well.
        # ----------------------------------------------------

        for subject, predicate, obj in graph:
            if str(predicate) == ACTION_PREDICATE:
                if str(obj).startswith(
                    "http://www.w3.org/ns/odrl/2/"
                ):
                    actions.add(str(obj))

        result_queue.put(
            (
                "ok",
                {
                    "columns": column_names,
                    "actions": sorted(actions)
                }
            )
        )

    except Exception as e:
        result_queue.put(("error", str(e)))


def _run_access_request_evaluation(
    access_request_string,
    policy_string,
    state_of_the_world_string,
    unspecified_action_semantics,
    duty_semantics,
    result_queue
):
    """
    Evaluate the prospective access request using the selected
    policy semantics.
    """
    try:

        result = Evaluator.evaluate_ODRL_access_request_from_string(
            access_request_string,
            policy_string,
            state_of_the_world_string=state_of_the_world_string,
            semantics_by_default=unspecified_action_semantics,
            semantics_for_duties=duty_semantics
        )

        result_queue.put(("ok", result))

    except Exception as e:
        result_queue.put(("error", str(e)))


def _run_with_timeout(target, args, timeout_seconds):
    """
    Runs target in a separate process and hard-kills it if it
    exceeds timeout_seconds.

    Returns:
        ("ok", value)
        ("error", message)
        ("timeout", None)
    """

    result_queue = multiprocessing.Queue()

    proc = multiprocessing.Process(
        target=target,
        args=(*args, result_queue)
    )

    proc.start()

    proc.join(timeout=timeout_seconds)

    if proc.is_alive():
        proc.terminate()
        proc.join()

        return ("timeout", None)

    if result_queue.empty():
        return (
            "error",
            "Evaluation process terminated unexpectedly."
        )

    return result_queue.get()


# ============================================================
# HELPER FUNCTIONS
# ============================================================

ACTION_IRI = "http://www.w3.org/ns/odrl/2/Action"


def make_access_request_json(form_values):
    """
    Convert the generated form into the JSON representation
    expected by evaluate_ODRL_access_request_from_string().
    """

    request = {}

    for key, value in form_values.items():

        if value is None:
            continue

        value = str(value).strip()

        if not value:
            continue

        request[key] = value

    return json.dumps(
        request,
        indent=2
    )

# ============================================================
# BUILT-IN EVALUATION TEST CASES
# ============================================================

TEST_CASES_DIR = (
    PROJECT_ROOT
    / "test_cases"
    / "evaluation"
    / "access_control"
)


def load_test_cases():
    """
    Discover built-in access-control evaluation test cases.

    A test case X consists of:
        X.ttl  - ODRL policy
        X.json - access request
        X.txt  - expected result / metadata
        X.csv  - optional State of the World

    Only tests having at least the required .ttl, .json and .txt
    files are returned.
    """

    test_cases = {}

    if not TEST_CASES_DIR.exists():
        return test_cases

    for ttl_path in sorted(TEST_CASES_DIR.glob("*.ttl")):
        test_name = ttl_path.stem

        json_path = TEST_CASES_DIR / f"{test_name}.json"
        txt_path = TEST_CASES_DIR / f"{test_name}.txt"
        csv_path = TEST_CASES_DIR / f"{test_name}.csv"

        # A valid test requires these three files.
        if not json_path.exists() or not txt_path.exists():
            continue

        metadata = {}

        try:
            with txt_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()

                    if not line or "=" not in line:
                        continue

                    key, value = line.split("=", 1)
                    metadata[key.strip()] = value.strip()

        except Exception:
            # Ignore malformed test metadata rather than breaking
            # the whole application.
            continue

        test_cases[test_name] = {
            "policy_path": ttl_path,
            "access_request_path": json_path,
            "sotw_path": csv_path if csv_path.exists() else None,
            "metadata": metadata,
        }

    return test_cases


def load_test_case(test_name):
    """
    Load all files belonging to one built-in test case and return
    their contents plus metadata.
    """

    test_cases = load_test_cases()

    if test_name not in test_cases:
        raise ValueError(
            f"Test case '{test_name}' could not be found."
        )

    test_case = test_cases[test_name]

    with test_case["policy_path"].open(
        "r", encoding="utf-8"
    ) as f:
        policy_text = f.read()

    with test_case["access_request_path"].open(
        "r", encoding="utf-8"
    ) as f:
        access_request_text = f.read()

    sotw_text = ""

    if test_case["sotw_path"] is not None:
        with test_case["sotw_path"].open(
            "r", encoding="utf-8"
        ) as f:
            sotw_text = f.read()

    metadata = test_case["metadata"]

    return {
        "policy_text": policy_text,
        "access_request_text": access_request_text,
        "sotw_text": sotw_text,
        "expected_accept_decision": metadata.get(
            "expected_accept_decision"
        ),
        "semantics_for_duties": int(
            metadata.get("semantics_for_duties", -1).rstrip(",")
        ),
        "semantics_by_default": int(
            metadata.get("semantics_by_default", -1).rstrip(",")
        ),
        "test_description": metadata.get(
            "test_description", ""
        ),
        "test_tag": metadata.get(
            "test_tag", ""
        ),
    }


def select_test_case(test_name):
    """
    Streamlit callback used by the test-case dropdown.
    Loads the selected built-in test case into session state.
    """

    if not test_name:
        return

    test_case = load_test_case(test_name)

    st.session_state.policy_text = test_case["policy_text"]
    st.session_state.access_request_text = (
        test_case["access_request_text"]
    )
    st.session_state.sotw_text = test_case["sotw_text"]
    st.session_state.sotw_raw_editor = test_case["sotw_text"]

    # ------------------------------------------------------------
    # Set the semantic values.
    # Also update the selectbox widget state itself.
    # ------------------------------------------------------------

    st.session_state.unspecified_action_semantics = (
        test_case["semantics_by_default"]
    )

    st.session_state.duty_semantics = (
        test_case["semantics_for_duties"]
    )

    # These are the actual keys used by the selectbox widgets.
    unspecified_action_options = {
        "Permitted-By-Default (accept unless explicitly prohibited)": 1,
        "Prohibited-By-Default (reject unless explicitly permitted)": -1,
        "Unspecified-By-Default (do not compute unless explicitly regulated)": 0,
    }

    duty_options = {
        "Grant Access on Promise of Duty Completion": 1,
        "Reject Requests with Unfulfilled Duties": -1,
    }

    st.session_state.unspecified_action_semantics_select = (
        next(
            label
            for label, value in unspecified_action_options.items()
            if value == test_case["semantics_by_default"]
        )
    )

    st.session_state.duty_semantics_select = (
        next(
            label
            for label, value in duty_options.items()
            if value == test_case["semantics_for_duties"]
        )
    )

    # ------------------------------------------------------------
    # Test-case information
    # ------------------------------------------------------------

    st.session_state.test_case_description = (
        test_case["test_description"]
    )

    st.session_state.test_case_expected_decision = (
        test_case["expected_accept_decision"]
    )

    st.session_state.test_case_tag = (
        test_case["test_tag"]
    )

    # The JSON supplied by the test case is authoritative.
    st.session_state.access_request_uploaded = True
    st.session_state.access_request_form_generated = False

    # Clear any previous generated form data.
    st.session_state.access_request_features = []
    st.session_state.access_request_actions = []
    st.session_state.access_request_form_values = {}

    # Clear the previous evaluation result.
    st.session_state.evaluation_result_text = ""
    st.session_state.evaluation_accept_decision = None
    st.session_state.evaluation_accept_explanation = []

    # Mark that the test should be evaluated on the next run.
    st.session_state.evaluate_test_case = True

def display_action_name(action_iri):
    """
    Display a friendlier action name while retaining the full
    IRI as the actual selectbox value.
    """

    if action_iri.startswith(
        "http://www.w3.org/ns/odrl/2/"
    ):
        return action_iri[
            len("http://www.w3.org/ns/odrl/2/"):
        ]

    return action_iri

def add_access_request_to_sotw():
    """
    Add the current access request as a row in the State of the World.
    Handles an initially empty State of the World.
    """

    sotw_text = st.session_state.sotw_text
    access_request_text = st.session_state.access_request_text

    if not access_request_text.strip():
        st.session_state.sotw_add_error = (
            "⚠️ Please provide an access request."
        )
        return

    try:
        # Validate that the access request is a JSON object.
        parsed_request = json.loads(access_request_text)

        if not isinstance(parsed_request, dict):
            raise ValueError(
                "Access request must contain a JSON object."
            )

        # Merge the access request into the State of the World.
        # None means that the CSV is currently empty.
        merged_df = rdf_utils.merge_json_row_from_strings(
            sotw_text if sotw_text.strip() else None,
            access_request_text
        )

        # Store the updated State of the World.
        st.session_state.sotw_text = merged_df.to_csv(
            index=False
        )

        # Show the table rather than the raw CSV editor.
        st.session_state.show_raw_sotw = False

        st.session_state.sotw_add_success = (
            "Access request added to the State of the World."
        )

    except Exception as e:
        st.session_state.sotw_add_error = (
            f"⚠️ Unable to add access request to the "
            f"State of the World: {e}"
        )

# ============================================================
# PAGE SETUP
# ============================================================

st.set_page_config(
    page_title="ODRL Access Request Evaluator",
    layout="wide"
)

apply_style()

st.markdown("## ODRL Access Request Evaluator")

if "selected_test_case" not in st.session_state:
    st.session_state.selected_test_case = ""

if "test_case_description" not in st.session_state:
    st.session_state.test_case_description = ""

if "test_case_expected_decision" not in st.session_state:
    st.session_state.test_case_expected_decision = None

if "test_case_tag" not in st.session_state:
    st.session_state.test_case_tag = ""

if "evaluate_test_case" not in st.session_state:
    st.session_state.evaluate_test_case = False


# ============================================================
# LOAD TEST EXAMPLE
# ============================================================

test_cases = load_test_cases()

test_case_options = [""] + list(test_cases.keys())

selected_test_case = st.selectbox(
    "Load Test Example",
    options=test_case_options,
    index=(
        test_case_options.index(
            st.session_state.selected_test_case
        )
        if st.session_state.selected_test_case in test_case_options
        else 0
    ),
    format_func=lambda x: (
        "Select a test case..."
        if x == ""
        else x
    ),
    key="selected_test_case",
    on_change=lambda: select_test_case(
        st.session_state.selected_test_case
    ),
)


if st.session_state.test_case_description:
    expected_decision = (
        st.session_state.test_case_expected_decision
    )

    test_tag = st.session_state.test_case_tag

    st.info(
        f"Example summary: "
        f"{st.session_state.test_case_description}\n\n"
        f"Expected decision: "
        f"{'Access Granted' if expected_decision == 'True' else 'Access Denied' if expected_decision == 'False' else 'Unspecified'}\n\n"
        f"Feature tested: {test_tag}"
    )

st.markdown(
    "This app allows you to create an access request from an ODRL policy and evaluate "
    "whether the request matches the policy's permissions and "
    "prohibitions."
)

st.markdown(
    """
    This app allows you to create an access request from an ODRL policy and evaluate 
    whether the request matches the policy's permissions, prohibitions and duties. 
    Either select an example to display with the dropdown above, or follow these instructions:
    1) Upload an ODRL Policy
    2) Optionally, upload a State of the World object if you want to factor in previously executed duties.
    3) Fill in the `Access Request Form`, to specify the action you want permission for.
    4) As an alternative to 3), you can upload an access request as a JSON file.
    5) Press the `Evaluate Access Request` button
    6) The result of the evaluation of the access request will be shown below. Green and Red reports signify permissions
    or prohibitions that directly affect your request. Yellow reports signify permissions and prohibitions that might
    affect your access request, depending on certain conditions. For example, a prohibition might only apply if the value
    of a feature you left blank has a value sufficiently low, or a permission might apply only if you are going to fulfill
    a certain duty.
    7) Optionally you can also click on the `Add to State of the World` button to record that the action you are requesting permission
    for has now been performed. You can do this to record performing a duty action, before checking if this allows you to 
    exercise a permission with duties. 
    """
)

st.markdown(
    """
    Depending on the use case, an access request can be granted depending on different interpretations of the policy. 
    This evaluator does not mandate specific semantics (such as only accept requests if there is an explicit permission, 
    or only accept requests if there is no explicit prohibition, or etc.) but provides the necessary information to make
    a decision based on domain specific requirements.
    """
)


# ============================================================
# SESSION STATE
# ============================================================

if "policy_text" not in st.session_state:
    st.session_state.policy_text = ""

if "sotw_text" not in st.session_state:
    st.session_state.sotw_text = ""

if "access_request_text" not in st.session_state:
    st.session_state.access_request_text = "{}"

if "policy_upload_id" not in st.session_state:
    st.session_state.policy_upload_id = None

if "sotw_upload_id" not in st.session_state:
    st.session_state.sotw_upload_id = None

if "access_request_upload_id" not in st.session_state:
    st.session_state.access_request_upload_id = None

if "policy_suffix" not in st.session_state:
    st.session_state.policy_suffix = ".ttl"

if "access_request_form_generated" not in st.session_state:
    st.session_state.access_request_form_generated = False

if "access_request_features" not in st.session_state:
    st.session_state.access_request_features = []

if "access_request_actions" not in st.session_state:
    st.session_state.access_request_actions = []

if "access_request_form_values" not in st.session_state:
    st.session_state.access_request_form_values = {}

if "evaluation_result_text" not in st.session_state:
    st.session_state.evaluation_result_text = ""

if "evaluation_accept_decision" not in st.session_state:
    st.session_state.evaluation_accept_decision = None

if "evaluation_accept_explanation" not in st.session_state:
    st.session_state.evaluation_accept_explanation = []

if "unspecified_action_semantics" not in st.session_state:
    st.session_state.unspecified_action_semantics = -1

if "duty_semantics" not in st.session_state:
    st.session_state.duty_semantics = 1

if "access_request_uploaded" not in st.session_state:
    st.session_state.access_request_uploaded = False

# ============================================================
# SEMANTICS SETTINGS
# ============================================================

settings_left, settings_right = st.columns(2)

# ------------------------------------------------------------
# Unspecified Actions Semantics
# ------------------------------------------------------------

with settings_left:

    unspecified_action_options = {
        "Permitted-By-Default (accept unless explicitly prohibited)": 1,
        "Prohibited-By-Default (reject unless explicitly permitted)": -1,
        "Unspecified-By-Default (do not compute unless explicitly regulated)": 0,
    }

    selected_unspecified_action_semantics = st.selectbox(
        "**Semantics for Unspecified Actions** — "
        "How to treat requests for actions that are not "
        "regulated by the policy",
        options=list(unspecified_action_options.keys()),
        index=list(
            unspecified_action_options.values()
        ).index(
            st.session_state.unspecified_action_semantics
        ),
        key="unspecified_action_semantics_select"
    )

    st.session_state.unspecified_action_semantics = (
        unspecified_action_options[
            selected_unspecified_action_semantics
        ]
    )


# ------------------------------------------------------------
# Duties Semantics
# ------------------------------------------------------------

with settings_right:

    duty_options = {
        "Grant Access on Promise of Duty Completion": 1,
        "Reject Requests with Unfulfilled Duties": -1,
    }

    selected_duty_semantics = st.selectbox(
        "**Semantics for Duties** — "
        "How to treat unfulfilled duties",
        options=list(duty_options.keys()),
        index=list(
            duty_options.values()
        ).index(
            st.session_state.duty_semantics
        ),
        key="duty_semantics_select"
    )

    st.session_state.duty_semantics = (
        duty_options[selected_duty_semantics]
    )


# ============================================================
# ABCD LAYOUT
# ============================================================

col_left, col_right = st.columns(2)


# ============================================================
# A — POLICY
# ============================================================

with col_left:

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

    if uploaded_policy is not None:

        if (
            uploaded_policy.file_id
            != st.session_state.policy_upload_id
        ):

            st.session_state.policy_upload_id = (
                uploaded_policy.file_id
            )

            st.session_state.policy_text = (
                uploaded_policy
                .getvalue()
                .decode("utf-8")
            )

            st.session_state.policy_suffix = (
                Path(uploaded_policy.name)
                .suffix
                .lower()
            )

            # A new policy means the old generated form is no
            # longer necessarily valid.
            st.session_state.access_request_form_generated = False
            st.session_state.access_request_features = []
            st.session_state.access_request_actions = []
            st.session_state.access_request_form_values = {}

            st.rerun()

    st.text_area(
        "Policy Text",
        height=400,
        key="policy_text"
    )


# ============================================================
# C — STATE OF THE WORLD
# ============================================================

with col_left:

    st.subheader("State of the World")

    uploaded_sotw = st.file_uploader(
        "Upload SotW CSV",
        type=["csv"],
        label_visibility="collapsed",
        key="sotw_upload"
    )

    if uploaded_sotw is not None:

        if (
            uploaded_sotw.file_id
            != st.session_state.sotw_upload_id
        ):

            st.session_state.sotw_upload_id = (
                uploaded_sotw.file_id
            )

            st.session_state.sotw_text = (
                uploaded_sotw
                .getvalue()
                .decode("utf-8")
            )

            st.session_state.sotw_raw_editor = (
                st.session_state.sotw_text
            )

            st.rerun()

    show_raw_sotw = st.toggle(
        "Show raw CSV text",
        value=False,
        key="show_raw_sotw",
        on_change=initialise_sotw_raw_editor
    )

    if show_raw_sotw:
        st.text_area(
            "CSV Text",
            height=400,
            key="sotw_raw_editor",
            on_change=update_sotw_from_raw_editor
        )

    else:
        if st.session_state.sotw_text.strip():
            try:
                sotw_df = pd.read_csv(
                    StringIO(st.session_state.sotw_text)
                )

                st.dataframe(
                    sotw_df,
                    use_container_width=True,
                    height=400
                )

            except Exception as e:
                st.error(
                    f"Unable to display the State of the World CSV: {e}"
                )
        else:
            st.info("The State of the World is empty.")


# ============================================================
# B — ACCESS REQUEST FORM
# ============================================================

with col_right:

    st.subheader("Access Request Form")

    generate_form = st.button(
        "Generate Access Request Form",
        use_container_width=True
    )

    # --------------------------------------------------------
    # Generate the form.
    #
    # This also happens automatically when a policy has just
    # been uploaded.
    # --------------------------------------------------------

    if (
            generate_form
            or (
            st.session_state.policy_upload_id is not None
            and not st.session_state.access_request_form_generated
            and not st.session_state.access_request_uploaded
            and st.session_state.policy_text.strip()
    )
    ):

        policy_path = None

        try:

            policy_suffix = (
                st.session_state.policy_suffix
            )

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

            with st.spinner(
                "Reading policy features and actions..."
            ):

                status, payload = _run_with_timeout(
                    _run_extract_policy_info,
                    (policy_path,),
                    COLUMNS_TIMEOUT_SECONDS
                )

            if status == "timeout":

                st.error(
                    f"⚠️ Timed out after "
                    f"{COLUMNS_TIMEOUT_SECONDS} seconds "
                    "while reading the policy."
                )

            elif status == "error":

                st.error(
                    "Error, the policy input field does not "
                    "contain a valid ODRL policy."
                )

            else:

                features = payload["columns"]
                actions = payload["actions"]

                # ------------------------------------------------
                # Put Action first.
                #
                # Remove it from the normal feature list so that
                # it isn't displayed twice.
                # ------------------------------------------------

                other_features = [
                    feature
                    for feature in features
                    if feature != ACTION_IRI
                ]

                ordered_features = [
                    ACTION_IRI
                ] + other_features

                st.session_state.access_request_features = (
                    ordered_features
                )

                st.session_state.access_request_actions = (
                    actions
                )

                # ------------------------------------------------
                # Initialise form values.
                #
                # Preserve values already entered if possible.
                # ------------------------------------------------

                old_values = (
                    st.session_state
                    .access_request_form_values
                )

                new_values = {}

                for feature in ordered_features:

                    if feature in old_values:
                        new_values[feature] = (
                            old_values[feature]
                        )

                    elif feature == ACTION_IRI:

                        if actions:
                            new_values[feature] = actions[0]
                        else:
                            new_values[feature] = ""

                    else:
                        new_values[feature] = ""

                st.session_state.access_request_form_values = (
                    new_values
                )

                st.session_state.access_request_uploaded = False

                st.session_state.access_request_form_generated = True

                # ------------------------------------------------
                # Immediately generate JSON from the form.
                # ------------------------------------------------

                st.session_state.access_request_text = (
                    make_access_request_json(
                        new_values
                    )
                )

        except Exception as e:

            st.error(
                f"⚠️ Error generating access request form: {e}"
            )

        finally:

            if (
                policy_path
                and os.path.exists(policy_path)
            ):
                os.remove(policy_path)

    # --------------------------------------------------------
    # Render generated form
    # --------------------------------------------------------

    if st.session_state.access_request_form_generated:

        st.markdown("#### Request fields")

        features = (
            st.session_state
            .access_request_features
        )

        actions = (
            st.session_state
            .access_request_actions
        )

        for feature in features:

            # --------------------------------------------
            # Action gets a dropdown.
            # --------------------------------------------

            if feature == ACTION_IRI:

                current_value = (
                    st.session_state
                    .access_request_form_values
                    .get(feature, "")
                )

                if actions:

                    # Add a custom option to the dropdown
                    CUSTOM_ACTION = "__CUSTOM_ACTION__"
                    action_options = actions + [CUSTOM_ACTION]

                    if current_value in actions:
                        selected_option = current_value
                    else:
                        selected_option = CUSTOM_ACTION

                    selected_action = st.selectbox(
                        "Action",
                        options=action_options,
                        index=action_options.index(selected_option),
                        format_func=lambda x: (
                            "Custom..." if x == CUSTOM_ACTION
                            else display_action_name(x)
                        ),
                        key="access_request_action_select",
                        disabled=st.session_state.access_request_uploaded
                    )

                    # If Custom... is selected, show a text box
                    if selected_action == CUSTOM_ACTION:
                        selected_action = st.text_input(
                            "Custom action",
                            value=(
                                current_value
                                if current_value not in actions
                                else ""
                            ),
                            key="access_request_custom_action",
                            disabled=st.session_state.access_request_uploaded
                        )

                    st.session_state \
                        .access_request_form_values[
                        feature
                    ] = selected_action

                else:

                    st.warning(
                        "No actions were found in the policy."
                    )

            # --------------------------------------------
            # All other features are normal text inputs.
            # --------------------------------------------

            else:

                current_value = (
                    st.session_state
                    .access_request_form_values
                    .get(feature, "")
                )

                value = st.text_input(
                    feature,
                    value=current_value,
                    key=f"access_request_feature_{feature}",
                    disabled=st.session_state.access_request_uploaded
                )

                st.session_state \
                    .access_request_form_values[
                        feature
                    ] = value

        # ----------------------------------------------------
        # Every rerun caused by a form-field change reaches
        # here. Rebuild D from the current form values.
        # ----------------------------------------------------

        if not st.session_state.access_request_uploaded:
            st.session_state.access_request_text = (
                make_access_request_json(
                    st.session_state.access_request_form_values
                )
            )


# ============================================================
# D — ACCESS REQUEST JSON
# ============================================================

with col_right:

    st.subheader("Access Request JSON")

    uploaded_access_request = st.file_uploader(
        "Upload Access Request JSON",
        type=["json"],
        label_visibility="collapsed",
        key="access_request_upload"
    )

    if uploaded_access_request is not None:

        if (
            uploaded_access_request.file_id
            != st.session_state.access_request_upload_id
        ):

            st.session_state.access_request_upload_id = (
                uploaded_access_request.file_id
            )

            uploaded_text = (
                uploaded_access_request
                .getvalue()
                .decode("utf-8")
            )

            st.session_state.access_request_text = uploaded_text

            st.session_state.access_request_form_generated = False
            st.session_state.access_request_uploaded = True

            # The uploaded JSON is now the source of truth.
            st.rerun()

    st.text_area(
        "Access Request JSON",
        height=400,
        key="access_request_text"
    )

    add_to_sotw_button = st.button(
        "Add to State of the World",
        use_container_width=True,
        on_click=add_access_request_to_sotw
    )

# ============================================================
# EVALUATION AREA
# ============================================================


st.divider()

evaluate_button = st.button(
    "Evaluate Access Request",
    use_container_width=True
)

if st.session_state.get("sotw_add_success"):
    st.success(st.session_state.sotw_add_success)
    del st.session_state.sotw_add_success

if st.session_state.get("sotw_add_error"):
    st.error(st.session_state.sotw_add_error)
    del st.session_state.sotw_add_error


# ============================================================
# EVALUATE
# ============================================================

if (
    evaluate_button
    or st.session_state.get("evaluate_test_case", False)
):
    # The test-case trigger is consumed now.
    st.session_state.evaluate_test_case = False

    policy_text = (
        st.session_state.policy_text
    )

    sotw_text = (
        st.session_state.sotw_text
    )

    access_request_text = (
        st.session_state.access_request_text
    )

    # --------------------------------------------------------
    # Validate inputs
    # --------------------------------------------------------

    if not policy_text.strip():

        st.error(
            "⚠️ Please paste or upload an ODRL policy."
        )

        st.stop()

    if not access_request_text.strip():

        st.error(
            "⚠️ Please provide an access request."
        )

        st.stop()

    # Validate JSON before starting the worker.
    try:

        parsed_request = json.loads(
            access_request_text
        )

        if not isinstance(parsed_request, dict):
            raise ValueError(
                "Access request must contain a JSON object."
            )

    except Exception as e:

        st.error(
            f"⚠️ Invalid access request JSON: {e}"
        )

        st.stop()

    # --------------------------------------------------------
    # Evaluate
    # --------------------------------------------------------

    with st.spinner(
        "Evaluating access request..."
    ):

        result_queue = multiprocessing.Queue()

        proc = multiprocessing.Process(
            target=_run_access_request_evaluation,
            args=(
                access_request_text,
                policy_text,
                sotw_text if sotw_text.strip() else None,
                st.session_state.unspecified_action_semantics,
                st.session_state.duty_semantics,
                result_queue
            )
        )

        proc.start()

        proc.join(
            timeout=EVAL_TIMEOUT_SECONDS
        )

        if proc.is_alive():

            proc.terminate()
            proc.join()

            status = "timeout"
            payload = None

        elif result_queue.empty():

            status = "error"
            payload = (
                "Evaluation process terminated unexpectedly."
            )

        else:

            status, payload = (
                result_queue.get()
            )

    # --------------------------------------------------------
    # Display result
    # --------------------------------------------------------

    if status == "timeout":

        st.error(
            f"⚠️ Evaluation timed out after "
            f"{EVAL_TIMEOUT_SECONDS} seconds."
        )

    elif status == "error":

        st.error(
            f"⚠️ Evaluation error: {payload}"
        )

    else:

        result_text = json.dumps(
            payload,
            indent=2,
            default=str
        )

        st.session_state.evaluation_result_text = (
            result_text
        )

        # ----------------------------------------------------
        # Store the evaluator's access decision and explanation
        #
        # Expected evaluator return structure:
        #
        # {
        #     "permissions_matched": ...,
        #     "prohibitions_matched": ...,
        #     "accept_decision": True / False / None,
        #     "accept_explanation": [...]
        # }
        # ----------------------------------------------------

        st.session_state.evaluation_accept_decision = (
            payload.get("accept_decision")
        )

        accept_explanation = payload.get(
            "accept_explanation",
            []
        )

        # Normalise the explanation so the UI can safely render
        # it as a bullet-point list.
        if accept_explanation is None:
            accept_explanation = []

        elif isinstance(accept_explanation, str):
            accept_explanation = [accept_explanation]

        else:
            accept_explanation = list(
                accept_explanation
            )

        st.session_state.evaluation_accept_explanation = (
            accept_explanation
        )


# ============================================================
# EVALUATION OUTCOME
# ============================================================

st.subheader("Evaluation Outcome")

if st.session_state.evaluation_result_text:

    accept_decision = (
        st.session_state.evaluation_accept_decision
    )

    accept_explanation = (
        st.session_state.evaluation_accept_explanation
    )

    # --------------------------------------------------------
    # Determine outcome presentation
    # --------------------------------------------------------

    if accept_decision is True:

        outcome_css_class = (
            "odrl-outcome odrl-outcome-granted"
        )

        outcome_icon = "✅"
        outcome_text = "Request Granted"

    elif accept_decision is False:

        outcome_css_class = (
            "odrl-outcome odrl-outcome-denied"
        )

        outcome_icon = "⛔"
        outcome_text = "Request Denied"

    else:

        outcome_css_class = (
            "odrl-outcome odrl-outcome-unknown"
        )

        outcome_icon = "⚠️"
        outcome_text = "Request Could Not be Computed"

    # --------------------------------------------------------
    # Prominent outcome banner
    # --------------------------------------------------------

    st.markdown(
        f"""
        <div class="{outcome_css_class}">
            <span class="odrl-outcome-icon">
                {outcome_icon}
            </span>
            <span>
                {outcome_text}
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    # --------------------------------------------------------
    # Outcome explanation
    # --------------------------------------------------------

    st.markdown(
        "#### Outcome Explanation"
    )

    if accept_explanation:

        st.markdown(
            '<div class="odrl-outcome-explanation">',
            unsafe_allow_html=True
        )

        for explanation in accept_explanation:
            st.markdown(
                f"- {explanation}"
            )

        st.markdown(
            "</div>",
            unsafe_allow_html=True
        )

    else:

        st.info(
            "No outcome explanation was provided."
        )


# ============================================================
# EVALUATION DETAILS
# ============================================================

st.subheader("Evaluation Details")

if st.session_state.evaluation_result_text:

    try:

        result_payload = json.loads(
            st.session_state.evaluation_result_text
        )

        # ----------------------------------------------------
        # Human-readable permission/prohibition details
        # ----------------------------------------------------

        displayed = render_evaluation_notifications(
            result_payload
        )

        if not displayed:
            st.info(
                "No matching permissions or prohibitions "
                "were found for this access request."
            )

        # ----------------------------------------------------
        # Raw result is hidden by default.
        # ----------------------------------------------------

        with st.expander(
            "Show raw evaluation result"
        ):
            st.code(
                st.session_state.evaluation_result_text,
                language="json"
            )

    except Exception as e:

        st.error(
            f"Unable to display evaluation result: {e}"
        )

        with st.expander(
            "Show raw evaluation result"
        ):
            st.code(
                st.session_state.evaluation_result_text,
                language="text"
            )

else:

    st.info(
        "No evaluation has been performed yet."
    )