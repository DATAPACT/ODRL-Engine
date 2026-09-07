from io import StringIO
from rdflib import Graph, URIRef

import rdf_utils
from rdf_utils import extract_rule_list_from_policy, extract_features_list_from_policy, decompose_in_set
import pandas as pd
import os
import shutil
import json
import math
import operator
import re
from datetime import datetime

# if dateutil is not install then install it using (!pip install python-dateutil)
from dateutil import parser
import uuid

#Non set operators
OPS_MAP = {
    "http://www.w3.org/ns/odrl/2/eq": operator.eq,
    "http://www.w3.org/ns/odrl/2/neq": operator.ne,
    "http://www.w3.org/ns/odrl/2/lt": operator.lt,
    "http://www.w3.org/ns/odrl/2/lteq": operator.le,
    "http://www.w3.org/ns/odrl/2/gt": operator.gt,
    "http://www.w3.org/ns/odrl/2/gteq": operator.ge,
}

#Set operators
ODRL_IS_PART_OF = "http://www.w3.org/ns/odrl/2/isPartOf"
ODRL_HAS_PART = "http://www.w3.org/ns/odrl/2/hasPart"
ODRL_IS_ALL_OF = "http://www.w3.org/ns/odrl/2/isAllOf"
ODRL_IS_ANY_OF = "http://www.w3.org/ns/odrl/2/isAnyOf"
ODRL_IS_NONE_OF = "http://www.w3.org/ns/odrl/2/isNoneOf"

DT_COL = "http://www.w3.org/ns/odrl/2/dateTime"

ODRL_INCLUDED_IN = URIRef(
    "http://www.w3.org/ns/odrl/2/includedIn"
)

ODRL_PART_OF = URIRef(
    "http://www.w3.org/ns/odrl/2/partOf"
)


def _extract_uris(value):
    """
    Extract URI strings from the different representations that may
    occur in the policy dictionary.
    Supported examples:
        "http://example.org/action"
        ["http://example.org/action1", "http://example.org/action2"]
        {"iri": "http://example.org/action"}
        {"id": "http://example.org/action"}
        {"@id": "http://example.org/action"}

    """
    if value is None:
        return []

    if isinstance(value, str):
        return [value]

    if isinstance(value, URIRef):
        return [str(value)]

    if isinstance(value, (list, tuple, set)):
        uris = []
        for item in value:
            uris.extend(_extract_uris(item))
        return uris

    if isinstance(value, dict):
        for key in ("iri", "id", "@id", "uri"):
            if key in value:
                return _extract_uris(value[key])

    return []

def _get_nested_rules(rule):
    if not isinstance(rule, dict):
        return

    yield rule

    for duty in rule.get("duties", []) or []:
        yield from _get_nested_rules(duty)

    for consequence in rule.get("consequences", []) or []:
        yield from _get_nested_rules(consequence)

    for remedy in rule.get("remedies", []) or []:
        yield from _get_nested_rules(remedy)


def _get_all_rules(policy):
    """
    Return every rule in a policy, including nested rules.
    """
    if isinstance(policy, list):
        policy = policy[0] if policy else {}

    if not isinstance(policy, dict):
        return

    for permission in policy.get("permissions", []) or []:
        yield from _get_nested_rules(permission)

    for prohibition in policy.get("prohibitions", []) or []:
        yield from _get_nested_rules(prohibition)

    for obligation in policy.get("obligations", []) or []:
        yield from _get_nested_rules(obligation)


ODRL_ACTION = "http://www.w3.org/ns/odrl/2/Action"
ODRL_PARTY = "http://www.w3.org/ns/odrl/2/Party"
ODRL_ASSET = "http://www.w3.org/ns/odrl/2/Asset"


def get_actions(policy):
    """
    Get all action URIs occurring in the policy.

    Supports both:
        rule["action"]

    and the condition representation:
        [
            ODRL Action,
            operator,
            action_uri
        ]
    """
    actions = set()

    for rule in _get_all_rules(policy):

        # Explicit action field, if present
        actions.update(
            _extract_uris(rule.get("action"))
        )

        # Action represented as a condition
        for condition in rule.get("conditions", []) or []:
            if (
                isinstance(condition, list)
                and len(condition) == 3
                and condition[0] == ODRL_ACTION
            ):
                actions.update(
                    _extract_uris(condition[2])
                )

    return actions


def get_parties(policy):
    """
    Get all party URIs occurring in the policy.

    Supports both:
        rule["assignee"]

    and:
        [
            ODRL_PARTY,
            operator,
            party_uri
        ]
    """
    parties = set()

    for rule in _get_all_rules(policy):

        # Explicit assignee field, if present
        parties.update(
            _extract_uris(rule.get("assignee"))
        )

        # Party represented as a condition
        for condition in rule.get("conditions", []) or []:
            if (
                isinstance(condition, list)
                and len(condition) == 3
                and condition[0] == ODRL_PARTY
            ):
                parties.update(
                    _extract_uris(condition[2])
                )

    return parties


def get_assets(policy):
    """
    Get all asset URIs occurring in the policy.

    Supports both:
        rule["target"]

    and:
        [
            ODRL_ASSET,
            operator,
            asset_uri
        ]
    """
    assets = set()

    for rule in _get_all_rules(policy):

        # Explicit target field, if present
        assets.update(
            _extract_uris(rule.get("target"))
        )

        # Asset represented as a condition
        for condition in rule.get("conditions", []) or []:
            if (
                isinstance(condition, list)
                and len(condition) == 3
                and condition[0] == ODRL_ASSET
            ):
                assets.update(
                    _extract_uris(condition[2])
                )

    return assets


def _get_transitive_subjects(graph, predicate, target):
    target = URIRef(str(target))

    discovered = set()
    queue = [target]

    while queue:
        current = queue.pop(0)

        for subject in graph.subjects(predicate, current):
            subject = URIRef(str(subject))

            if subject == target:
                continue

            if subject not in discovered:
                discovered.add(subject)
                queue.append(subject)

    return sorted(str(uri) for uri in discovered)


def _expand_uris(graph, uris, predicate):

    expanded = {}

    for uri in sorted(uris):
        expanded[uri] = _get_transitive_subjects(
            graph,
            predicate,
            uri
        )

    return expanded


def parse_ontology(policy, ontology_files=None, ontology_graphs=None):

    if isinstance(ontology_files, (str, os.PathLike)):
        ontology_files = [ontology_files]

    if ontology_files is None:
        ontology_files = []

    if ontology_graphs is None:
        ontology_graphs = []
    elif isinstance(ontology_graphs, Graph):
        ontology_graphs = [ontology_graphs]

    # ---------------------------------------------------------
    # 1) Load and merge all ontology files + supplied graphs
    # ---------------------------------------------------------

    ontology_graph = Graph()

    # Load ontology files
    for ontology_file in ontology_files:

        loaded = rdf_utils.load(ontology_file)

        if not loaded:
            continue

        graph = loaded[0]

        # Merge the loaded graph into the common ontology graph.
        ontology_graph += graph

    # Add supplied rdflib graphs
    for graph in ontology_graphs:

        if graph is None:
            continue

        ontology_graph += graph

    # ---------------------------------------------------------
    # 2) Extract policy entities
    # ---------------------------------------------------------

    actions = get_actions(policy)
    parties = get_parties(policy)
    assets = get_assets(policy)

    # ---------------------------------------------------------
    # 3) Expand according to ontology relationships
    # ---------------------------------------------------------

    expanded_actions = _expand_uris(
        ontology_graph,
        actions,
        ODRL_INCLUDED_IN
    )

    expanded_party = _expand_uris(
        ontology_graph,
        parties,
        ODRL_PART_OF
    )

    expanded_assets = _expand_uris(
        ontology_graph,
        assets,
        ODRL_PART_OF
    )

    # ---------------------------------------------------------
    # 4) Return all expansions
    # ---------------------------------------------------------

    return {
        "expanded_actions": expanded_actions,
        "expanded_party": expanded_party,
        "expanded_assets": expanded_assets
    }


def evaluate_ODRL_from_files_merge_policies(policy_files, SotW_file):
    graph_rules = []
    features = []
    for file in policy_files:
        graph = rdf_utils.load(file)[0]
        graph_rules.append(extract_rule_list_from_policy(graph))
        features.append(extract_features_list_from_policy(graph))

    # temporary merge code, TODO should be updated when a more stable merge function is created
    merged_permissions = []
    merged_prohibitions = []
    merged_obligations = []
    for policy_list in graph_rules:  # each element is a list of policies
        for policy in policy_list:
            merged_permissions.extend(policy.get("permissions", []))
            merged_prohibitions.extend(policy.get("prohibitions", []))
            merged_obligations.extend(policy.get("obligations", []))

    merged_policy_iri = graph_rules[0][0]["policy_iri"]
    merged_graph_rules = [{
        "policy_iri": merged_policy_iri,
        "permissions": merged_permissions,
        "prohibitions": merged_prohibitions,
        "obligations": merged_obligations
    }]
    merged_feature_map = {}

    for feature_list in features:
        for f in feature_list:
            iri = f["iri"]
            if iri not in merged_feature_map:
                merged_feature_map[iri] = f["type"]

    df = pd.read_csv(SotW_file)

    return evaluate_ODRL_on_dataframe(merged_graph_rules[0], df, merged_feature_map)

def eval_count(value, constraint, OPS_MAP):
    left, op_symbol, right = constraint

    if left != "http://www.w3.org/ns/odrl/2/count":
        return False

    if op_symbol not in OPS_MAP:
        return False

    try:
        return OPS_MAP[op_symbol](float(value), float(right))
    except Exception:
        return False

def is_parseable_date(value):
    if not isinstance(value, str):
        return False

    value = value.strip()

    # Explicitly reject strings consisting only of digits
    if value.isdigit():
        return False

    # First try the supported date formats
    formats = [
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ]

    for fmt in formats:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue

    # Try ISO 8601 date-times with timezone information
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False

def _reasoning_match(left_operand, value, right_operand, reasoning_expansion):
    """
    Check whether value matches right_operand directly or through
    the relevant reasoning expansion.

    Returns True if:
        value == right_operand

    or, for Action/Party/Asset operands, value is one of the
    entities expanded from right_operand.
    """

    if value == right_operand:
        return True

    if reasoning_expansion is None:
        return False

    expansion_key = {
        ODRL_ACTION: "expanded_actions",
        ODRL_PARTY: "expanded_party",
        ODRL_ASSET: "expanded_assets",
    }.get(left_operand)

    if expansion_key is None:
        return False

    expanded = reasoning_expansion.get(expansion_key, {})

    return value in expanded.get(str(right_operand), [])

def eval_constraint(row, rule, constraint, OPS_MAP, FEATURE_TYPE_MAP, match_nulls=False, null_conditions=None, reasoning_expansion=None):
    # ----------------------------------------
    # 0) LOGIC CONSTRAINT HANDLING
    # ----------------------------------------
    if (
            isinstance(constraint, list)
            and len(constraint) == 2
            and isinstance(constraint[0], str)
            and isinstance(constraint[1], list)
    ):
        logic_op = constraint[0]
        subconstraints = constraint[1]

        results = []


        for sub in subconstraints:
            result = eval_constraint(row, rule, sub, OPS_MAP, FEATURE_TYPE_MAP, match_nulls=False, null_conditions=None,reasoning_expansion=reasoning_expansion)
            results.append(result)

            # ---- SHORT-CIRCUIT ----
            if logic_op.endswith("or") and result:
                return True
            if logic_op.endswith("and") and not result:
                return False
            if logic_op.endswith("andSequence") and not result:
                return False

        # ---- FINAL EVALUATION ----
        if logic_op.endswith("and") or logic_op.endswith("andSequence"):
            return all(results)

        if logic_op.endswith("or"):
            return any(results)

        if logic_op.endswith("xone"):
            return sum(results) == 1

        # ---- RE-EVALUATE IF WE CAN MATCH NULLS ----
        if match_nulls:
            for sub in subconstraints:

                sub_null_conditions = []
                result = eval_constraint(row, rule, sub, OPS_MAP, FEATURE_TYPE_MAP, match_nulls=match_nulls,
                                         null_conditions=None,reasoning_expansion=reasoning_expansion)
                results.append(result)

                # ---- SHORT-CIRCUIT ----
                if not sub_null_conditions:
                    if logic_op.endswith("or") and result:
                        if null_conditions is not None:
                            null_conditions.append(constraint)
                        return True
                    if logic_op.endswith("and") and not result:
                        return False
                    if logic_op.endswith("andSequence") and not result:
                        return False

            # ---- FINAL EVALUATION WITH NULL MATCHES ----
            if logic_op.endswith("and") or logic_op.endswith("andSequence"):
                if all(results):
                    if null_conditions is not None:
                        null_conditions.append(constraint)
                    return True

            if logic_op.endswith("or"):
                if any(results):
                    if null_conditions is not None:
                        null_conditions.append(constraint)
                    return True

            if logic_op.endswith("xone"):
                if sum(results) == 1:
                    if null_conditions is not None:
                        null_conditions.append(constraint)
                    return True

        return False

    left, op_symbol, right = constraint

    if left == "http://www.w3.org/ns/odrl/2/count":

        if op_symbol not in OPS_MAP:
            return False
        try:
            current_count = rule.get("matches_count", 0)
            return OPS_MAP[op_symbol](float(current_count), float(right))
        except Exception:
            return False

    resolved_left = None

    # First try an exact match.
    if left in row:
        resolved_left = left

    # If there is no exact match, try matching the substring
    # after the last space in `left` against the row columns.
    elif isinstance(left, str):
        left_suffix = left.rsplit(" ", 1)[-1]

        for column in row.index:
            if isinstance(column, str):
                column_suffix = column.rsplit(" ", 1)[-1]

                if left_suffix == column_suffix:
                    resolved_left = column
                    break

        # No matching column was found.
        if resolved_left is None:
            if match_nulls:
                # Missing access-request field is treated as null.
                if null_conditions is not None:
                    null_conditions.append(constraint)
                return True
            else:
                return False

    left = resolved_left

    value = row[left]

    if pd.isna(value) or value == "":
        if match_nulls:
            if null_conditions is not None:
                null_conditions.append(constraint)
            return True
        else:
            return False

    # ----------------------------------------
    # ODRL SET OPERATORS
    # ----------------------------------------
    if op_symbol in {
        ODRL_IS_PART_OF,
        ODRL_HAS_PART,
        ODRL_IS_ALL_OF,
        ODRL_IS_ANY_OF,
        ODRL_IS_NONE_OF,
    }:
        value_set = set(decompose_in_set(value))
        right_set = set(decompose_in_set(right))

        if op_symbol == ODRL_IS_PART_OF:
            return value_set.issubset(right_set)

        if op_symbol == ODRL_HAS_PART:
            return right_set.issubset(value_set)

        if op_symbol == ODRL_IS_ALL_OF:
            return value_set == right_set

        if op_symbol == ODRL_IS_ANY_OF:
            return str(value) in right_set

        if op_symbol == ODRL_IS_NONE_OF:
            return str(value) not in right_set


    if op_symbol not in OPS_MAP:
        return False

    if (
            reasoning_expansion is not None
            and left in {
        ODRL_ACTION,
        ODRL_PARTY,
        ODRL_ASSET,
    }
            and op_symbol == "http://www.w3.org/ns/odrl/2/eq"
    ):
        return _reasoning_match(
            left,
            str(value),
            str(right),
            reasoning_expansion
        )

    column_type = FEATURE_TYPE_MAP.get(left)

    # TODO: fix issues with timezones.
    # --- DateTime handling ---
    if column_type == "http://www.w3.org/2001/XMLSchema#dateTime" or left == "http://www.w3.org/ns/odrl/2/dateTime" or is_parseable_date(right):
        try:
            left_date = parser.parse(str(value)).timestamp()
            right_date = parser.parse(str(right)).timestamp()
            ans = OPS_MAP[op_symbol](left_date, right_date)
            return ans

        except Exception:
            return False

    # --- Equality / inequality → string compare ---
    if op_symbol in ("http://www.w3.org/ns/odrl/2/eq", "http://www.w3.org/ns/odrl/2/neq"):
        try:
            return OPS_MAP[op_symbol](float(value), float(right))
        except Exception:
            return OPS_MAP[op_symbol](str(value), str(right))

    # --- Numeric comparison ---
    try:
        #print("Value ")
        return OPS_MAP[op_symbol](float(value), float(right))
    except Exception:
        return False

def eval_rule(row, rule, OPS_MAP, FEATURE_TYPE_MAP, match_nulls=False, null_conditions=None,reasoning_expansion=None):

    if not isinstance(rule, dict):
        return False

    conditions = rule.get("conditions", [])
 
    if not isinstance(conditions, list):
        return False

    return all(
        eval_constraint(row, rule, c, OPS_MAP, FEATURE_TYPE_MAP, match_nulls=match_nulls,null_conditions=null_conditions, reasoning_expansion=reasoning_expansion)
        for c in conditions
    )

def initialise_evaluation_state(policy):

    if isinstance(policy, list):
        policy = policy[0]

    def init_rule(rule):
        return {
            "rule_id": rule.get("id", str(uuid.uuid4())),
            "matches_count": 0,
            "earliestMatch": None,
            "latestMatch": None,
            "conditions": rule.get("conditions", []),
            "required": 0
        }

    def init_duty(duty):
        return {
            **init_rule(duty),
            "consequences": [init_rule(c) for c in duty.get("consequences", [])]
        }

    def init_prohibition(rule):
        return {
            **init_rule(rule),
            "remedies": [init_rule(r) for r in rule.get("remedies", [])]
        }

    state = {
        "policy_iri": policy.get("policy_iri"),
        "permissions": [],
        "prohibitions": [],
        "obligations": [],
        "rows_violating_permissions": [],
        "rows_violating_prohibitions": []
    }

    for p in policy.get("permissions", []):
        state["permissions"].append({
            **init_rule(p),
            "duties": [init_duty(d) for d in p.get("duties", [])]
        })

    for pr in policy.get("prohibitions", []):
        state["prohibitions"].append(init_prohibition(pr))

    for ob in policy.get("obligations", []):
        state["obligations"].append(init_rule(ob))

    return state

def check_match(row, rule_state, OPS_MAP, FEATURE_TYPE_MAP, match_nulls=False, null_conditions=None,reasoning_expansion=None):

    if eval_rule(row, rule_state, OPS_MAP, FEATURE_TYPE_MAP, match_nulls=match_nulls, null_conditions=null_conditions,reasoning_expansion=reasoning_expansion):

        rule_state["matches_count"] += 1

        time_val = row.get("http://www.w3.org/ns/odrl/2/dateTime")

        if time_val is not None:
            try:
                time_val = parser.parse(str(time_val))
            except:
                time_val = None

        if rule_state["earliestMatch"] is None:
            rule_state["earliestMatch"] = time_val

        rule_state["latestMatch"] = time_val

        if rule_state.get("required", 0) == 1:
            rule_state["required"] = 0

        return True

    return False

def evaluate_ODRL_on_df(ODRL_graph, df, evaluation_state=None):
    features = (
        extract_features_list_from_policy(
            ODRL_graph
        )
    )

    policies = (
        extract_rule_list_from_policy(
            ODRL_graph
        )
    )

    feature_type_map = {
        f["iri"]: f["type"]
        for f in features
    }

    return evaluate_ODRL_on_dataframe(
        policies[0],
        df,
        feature_type_map
    )


def evaluate_ODRL_on_dataframe(policy, df, FEATURE_TYPE_MAP, evaluation_state=None,reasoning=True, ontology_files=[], ontology_graphs=[]):

    reasoning_expansion = None
    if reasoning:
        if len(ontology_files) == 0:
            ontology_files.append(os.path.join("ODRL", "ODRL22.ttl"))
        reasoning_expansion = parse_ontology(policy, ontology_files,ontology_graphs)

    if isinstance(policy, list):
        policy = policy[0]

    # Ensure time ordering
    DT_COL = "http://www.w3.org/ns/odrl/2/dateTime"

    if DT_COL in df.columns:
        df[DT_COL] = pd.to_datetime(df[DT_COL], errors="coerce", utc=True)
        df = df.sort_values(by=DT_COL, ascending=True)

    if evaluation_state is None:
        evaluation_state = initialise_evaluation_state(policy)

    validity = 1

    for idx, row in df.iterrows():

        matched_permissions = []
        matched_prohibitions = []

        # ----------------------------------------
        # 1) MATCH ALL RULES (INCLUDING DUTIES ETC.)
        # ----------------------------------------

        # Permissions
        for p in evaluation_state["permissions"]:
            if check_match(row, p, OPS_MAP, FEATURE_TYPE_MAP,reasoning_expansion=reasoning_expansion):
                matched_permissions.append(p)

            # Duties ALWAYS evaluated
            for d in p.get("duties", []):
                check_match(row, d, OPS_MAP, FEATURE_TYPE_MAP,reasoning_expansion=reasoning_expansion)

                for c in d.get("consequences", []):
                    check_match(row, c, OPS_MAP, FEATURE_TYPE_MAP,reasoning_expansion=reasoning_expansion)

        # Prohibitions + remedies
        for f in evaluation_state["prohibitions"]:
            if check_match(row, f, OPS_MAP, FEATURE_TYPE_MAP,reasoning_expansion=reasoning_expansion):
                matched_prohibitions.append(f)

            for r in f.get("remedies", []):
                check_match(row, r, OPS_MAP, FEATURE_TYPE_MAP,reasoning_expansion=reasoning_expansion)

        # Obligations
        for o in evaluation_state["obligations"]:
            check_match(row, o, OPS_MAP, FEATURE_TYPE_MAP,reasoning_expansion=reasoning_expansion)

        # ----------------------------------------
        # 2) PERMISSION VIOLATION
        # ----------------------------------------
        if not matched_permissions:
            evaluation_state["rows_violating_permissions"].append(idx)
            validity = 0

        # ----------------------------------------
        # 3) DUTIES / CONSEQUENCES
        # ----------------------------------------
        for p in matched_permissions:
            for d in p.get("duties", []):

                if d["matches_count"] == 0 and d.get("required", 0) == 0:

                    if not d.get("consequences"):
                        evaluation_state["rows_violating_permissions"].append(idx)
                        validity = 0
                    else:
                        d["required"] = 1
                        for c in d["consequences"]:
                            c["required"] = 1

        # ----------------------------------------
        # 4) PROHIBITIONS + REMEDIES
        # ----------------------------------------
        for f in matched_prohibitions:

            remedies = f.get("remedies", [])

            if not remedies:
                evaluation_state["rows_violating_prohibitions"].append(idx)
                validity = 0
            else:
                for r in remedies:
                    r["required"] = 1

    # ----------------------------------------
    # 5) POST PROCESSING
    # ----------------------------------------


    temporary_validity = validity
    if (
            len(evaluation_state["rows_violating_permissions"]) > 0
            or len(evaluation_state["rows_violating_prohibitions"]) > 0
    ):
        temporary_validity = 0

    obligations_not_satisfied = []
    unfulfilled_duties = []
    unfulfilled_consequences = []
    unfulfilled_remedies = []

    # ---- OBLIGATIONS ----
    for o in evaluation_state["obligations"]:
        if o["matches_count"] < 1:
            obligations_not_satisfied.append(o)
            temporary_validity = 0

    # ---- DUTIES + CONSEQUENCES ----
    for p in evaluation_state["permissions"]:
        for d in p.get("duties", []):

            if d.get("required") == 1:
                unfulfilled_duties.append(d)
                temporary_validity = 0

            for c in d.get("consequences", []):
                if c.get("required") == 1:
                    unfulfilled_consequences.append(c)
                    temporary_validity = 0

    # ---- REMEDIES ----
    for f in evaluation_state["prohibitions"]:
        for r in f.get("remedies", []):
            if r.get("required") == 1:
                unfulfilled_remedies.append(r)
                temporary_validity = 0

    return (
        evaluation_state,
        temporary_validity,
        evaluation_state["rows_violating_permissions"],
        evaluation_state["rows_violating_prohibitions"],
        obligations_not_satisfied,
        unfulfilled_duties,
        unfulfilled_consequences,
        unfulfilled_remedies
    )

def evaluate_ODRL_from_files(policy_file, SotW_file, state_file=None, normalise=False,reasoning=True,ontology_files=[], ontology_graphs=[]):
    graph = rdf_utils.load(policy_file)[0]
    if normalise:
        graph = rdf_utils.load_normalise(policy_file)[0]
    policies = rdf_utils.extract_rule_list_from_policy(graph)
    features = rdf_utils.extract_features_list_from_policy(graph)

    evaluation_state = None

    if state_file and os.path.exists(state_file):
        with open(state_file, "r") as f:
            evaluation_state = json.load(f)

    FEATURE_TYPE_MAP = {f["iri"]: f["type"] for f in features}
    df = pd.read_csv(SotW_file)

    if reasoning:
        ontology_graphs.append(graph)
    return evaluate_ODRL_on_dataframe(policies[0], df, FEATURE_TYPE_MAP, evaluation_state,reasoning=reasoning,ontology_files=ontology_files,ontology_graphs=ontology_graphs)

def evaluate_ODRL_from_strings(
    policy_text,
    sotw_csv,
    evaluation_state=None,
    reasoning=True,
    ontology_files=[],
    ontology_graphs=[]
):
    graph, _ = rdf_utils.parse_string_to_graph(
        policy_text
    )

    policies = (
        extract_rule_list_from_policy(
            graph
        )
    )

    features = (
        extract_features_list_from_policy(
            graph
        )
    )

    feature_type_map = {
        f["iri"]: f["type"]
        for f in features
    }

    df = pd.read_csv(
        StringIO(sotw_csv)
    )

    if isinstance(evaluation_state, str):
        evaluation_state = json.loads(evaluation_state)

    if reasoning:
        ontology_graphs.append(graph)

    return evaluate_ODRL_on_dataframe(
        policies[0],
        df,
        feature_type_map,
        evaluation_state,
        reasoning=reasoning,
        ontology_files=ontology_files,
        ontology_graphs=ontology_graphs
    )

def evaluate_ODRL_access_request_on_dataframe(
    access_request,
    policy,
    FEATURE_TYPE_MAP,
    df=None,
    evaluation_state=None,
    semantics_for_duties=1,
    semantics_by_default=-1,
    reasoning=True,
    ontology_files=[],
    ontology_graphs=[]
):
    """
    Evaluate a prospective access request against an ODRL policy.

    Parameters
    ----------
    access_request : dict
        Dictionary representing the prospective new row. Keys should match
        the State-of-the-World dataframe column names.

    policy : dict or list
        ODRL policy, in the same format expected by
        evaluate_ODRL_on_dataframe() / initialise_evaluation_state().

    df : pandas.DataFrame or None
        Existing State-of-the-World data. If supplied, the policy is first
        evaluated against it to establish the current evaluation state.

    FEATURE_TYPE_MAP : dict
        Mapping from feature IRI / column name to its datatype.

    evaluation_state : dict or None
        Optional existing evaluation state. If supplied, it is used as the
        starting state instead of evaluating df.

    semantics_for_duties : either 1 or -1
        With 1 (default value), the access request is to be accepted even if duties are not satisfied, on the promise that they will be.
        With -1, the access request is to be rejected if duties are not explicitly satisfied in the State of the World.

    semantics_by_default : either 1, 0 or -1
        With 1 permitted-by-default: the access request is to be accepted unless it matches a prohibition.
        With -1 prohibited-by-default (default value): the access request is to be rejected unless it matches a permission.
        With 0 unspecified-by-default: the response to the access request will be unspecified if it does not match a permission or a prohibition.


    Returns
    -------
    dict
        {
            "permissions_matched": [
                {
                    "rule": <permission rule>,
                    "conditions": <conditions satisfied only through null matching>,
                    "duties": <unfulfilled duties>
                }
            ],
            "prohibitions_matched": [
                {
                    "rule": <prohibition rule>,
                    "conditions": <conditions satisfied only through null matching>
                }
            ]
        }
    """

    reasoning_expansion = None
    if reasoning:
        if len(ontology_files) == 0:
            ontology_files.append(os.path.join("ODRL", "ODRL22.ttl"))
        reasoning_expansion = parse_ontology(policy,ontology_files,ontology_graphs)

    policy_for_conflict = (
        policy[0]
        if isinstance(policy, list)
        else policy
    )

    conflict = policy_for_conflict.get(
        "conflict",
        0
    )

    # ---------------------------------------------------------
    # 1) Normalise policy
    # ---------------------------------------------------------
    if isinstance(policy, list):
        policy = policy[0]

    # ---------------------------------------------------------
    # 2) Create / establish evaluation state
    # ---------------------------------------------------------
    if evaluation_state is None:
        if df is not None:
            result = evaluate_ODRL_on_dataframe(
                policy,
                df,
                FEATURE_TYPE_MAP,
                reasoning=reasoning,
                ontology_graphs=ontology_graphs,
                ontology_files=ontology_files
            )
            evaluation_state = result[0]
        else:
            evaluation_state = initialise_evaluation_state(policy)

    # ---------------------------------------------------------
    # 3) Convert access request into a pandas Series
    # ---------------------------------------------------------

    accept_explanation = []

    # add datetime set to now, if none is specified, as an access request is never about the past
    if DT_COL not in access_request or access_request[DT_COL] in (None, ""):
        time_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        access_request[DT_COL] = time_now
        accept_explanation.append("Warning: your request did not specify a time, and thus it defaulted to the current time "+time_now+". Set the odrl:dateTime feature in your access request if you want to specify another time.")

    access_request_row = pd.Series(access_request)

    permissions_matched = []
    prohibitions_matched = []

    # =========================================================
    # 4) Evaluate all permissions
    # =========================================================
    for permission in evaluation_state.get("permissions", []):

        # -----------------------------------------------------
        # First try normal matching.
        # -----------------------------------------------------
        normal_match = eval_rule(
            access_request_row,
            permission,
            OPS_MAP,
            FEATURE_TYPE_MAP,
            match_nulls=False,
            null_conditions=None,
            reasoning_expansion=reasoning_expansion,
        )

        null_conditions = []

        if normal_match:
            # No null-based conditions were needed.
            matched_conditions = []

        else:
            # -------------------------------------------------
            # Try again allowing missing/null values to match.
            # -------------------------------------------------
            null_match = eval_rule(
                access_request_row,
                permission,
                OPS_MAP,
                FEATURE_TYPE_MAP,
                match_nulls=True,
                null_conditions=null_conditions,
                reasoning_expansion=reasoning_expansion
            )

            if not null_match:
                continue

            matched_conditions = null_conditions

        # -----------------------------------------------------
        # Determine unfulfilled duties
        # -----------------------------------------------------
        unfulfilled_duties = []

        for duty in permission.get("duties", []):
            if duty.get("matches_count", 0) == 0:
                unfulfilled_duties.append(duty)

        # -----------------------------------------------------
        # Store matching permission
        # -----------------------------------------------------
        permissions_matched.append({
            "rule": permission,
            "conditions": matched_conditions,
            "duties": unfulfilled_duties
        })

    # =========================================================
    # 5) Evaluate all prohibitions
    # =========================================================
    for prohibition in evaluation_state.get("prohibitions", []):

        # -----------------------------------------------------
        # First try normal matching.
        # -----------------------------------------------------
        normal_match = eval_rule(
            access_request_row,
            prohibition,
            OPS_MAP,
            FEATURE_TYPE_MAP,
            match_nulls=False,
            null_conditions=None,
            reasoning_expansion=reasoning_expansion
        )

        null_conditions = []

        if normal_match:
            # No null-based conditions were needed.
            matched_conditions = []

        else:
            # -------------------------------------------------
            # Try again allowing missing/null values to match.
            # -------------------------------------------------
            null_match = eval_rule(
                access_request_row,
                prohibition,
                OPS_MAP,
                FEATURE_TYPE_MAP,
                match_nulls=True,
                null_conditions=null_conditions,
                reasoning_expansion=reasoning_expansion
            )

            if not null_match:
                continue

            matched_conditions = null_conditions

        # -----------------------------------------------------
        # Store matching prohibition.
        #
        # Unlike permissions, prohibitions do not need duties.
        # -----------------------------------------------------
        prohibitions_matched.append({
            "rule": prohibition,
            "conditions": matched_conditions
        })

    # ---------------------------------------------------------
    # 6) Process conflicts and compute access decision
    # ---------------------------------------------------------

    accept_decision = None
    inconsistent_policy = False

    # ---------------------------------------------------------
    # 6.1) Determine full matches
    #
    # A rule is a "full match" when it matched without needing
    # any null / unspecified access-request features.
    # ---------------------------------------------------------
    full_match_permission = any(
        len(permission.get("conditions", [])) == 0
        for permission in permissions_matched
    )

    full_match_prohibition = any(
        len(prohibition.get("conditions", [])) == 0
        for prohibition in prohibitions_matched
    )

    # ---------------------------------------------------------
    # 6.2) Process policy conflict strategy
    # ---------------------------------------------------------

    # conflict =  1  -> permissions override prohibitions
    # conflict = -1  -> prohibitions override permissions
    # conflict =  0  -> conflicts invalidate the policy

    if conflict == 1 and full_match_permission:

        if full_match_prohibition:
            accept_explanation.append(
                "Your request would have matched a prohibition, but since it also "
                "matched a permission, and the conflict strategy of your policy is "
                "that permissions override prohibitions, that prohibition was ignored."
            )

        # Permissions override prohibitions.
        prohibitions_matched.clear()

    elif conflict == -1 and full_match_prohibition:

        if full_match_permission:
            accept_explanation.append(
                "Your request would have matched a permission, but since it also "
                "matched a prohibition, and the conflict strategy of your policy is "
                "that prohibitions override permissions, that permission was ignored."
            )

        # Prohibitions override permissions.
        permissions_matched.clear()

    elif (
            conflict == 0
            and full_match_permission
            and full_match_prohibition
    ):

        inconsistent_policy = True

        accept_explanation.append(
            "A rule conflict was detected as your request matched both a permission "
            "and a prohibition. Since the conflict strategy of your policy is to "
            "invalidate policies with conflicts, your request cannot be processed "
            "as the policy is invalid. Either set a different conflict strategy "
            "to the policy, or resolve the conflict between rules before "
            "re-evaluating."
        )

    conditional_match_permission = any(
        len(permission.get("conditions", [])) > 0
        for permission in permissions_matched
    )

    conditional_match_prohibition = any(
        len(prohibition.get("conditions", [])) > 0
        for prohibition in prohibitions_matched
    )

    # ---------------------------------------------------------
    # 6.3) Warn about conditional / null-based matches
    #
    # This warning is only relevant when the policy is not inconsistent
    # ---------------------------------------------------------
    if (
            not inconsistent_policy
            and (
            conditional_match_permission
            or conditional_match_prohibition
    )
    ):
        accept_explanation.append(
            "Warning, some rules of the policy could match your request if some "
            "of the unspecified details (null features) of your request were "
            "given certain values. Please see the evaluation details for more "
            "information on rules that matched subject to conditions. You might "
            "want to specify those features better to gain a more precise decision."
        )

    # ---------------------------------------------------------
    # 6.4) If the policy is inconsistent, do not make a decision
    # ---------------------------------------------------------
    if inconsistent_policy:
        return {
            "permissions_matched": permissions_matched,
            "prohibitions_matched": prohibitions_matched,
            "accept_decision": accept_decision,
            "accept_explanation": accept_explanation
        }

    # ---------------------------------------------------------
    # 6.5) Recompute whether effective full matches remain
    #
    # Conflict resolution above may have cleared one of the
    # matched-rule sets.
    # ---------------------------------------------------------
    if full_match_permission and full_match_prohibition:
        if conflict == 1:
            # Permission won.
            effective_full_match_permission = True
            effective_full_match_prohibition = False

        elif conflict == -1:
            # Prohibition won.
            effective_full_match_permission = False
            effective_full_match_prohibition = True

        else:
            effective_full_match_permission = full_match_permission
            effective_full_match_prohibition = full_match_prohibition
    else:
        effective_full_match_permission = full_match_permission
        effective_full_match_prohibition = full_match_prohibition

    # ---------------------------------------------------------
    # 6.6) No full permission and no full prohibition
    # ---------------------------------------------------------
    if (
            not effective_full_match_permission
            and not effective_full_match_prohibition
    ):

        # -----------------------------------------------------
        # A) Permission-by-default
        # -----------------------------------------------------
        if semantics_by_default == 1:

            accept_decision = True

            accept_explanation.append(
                "Your request did not match any permissions or prohibitions "
                "of the policy. Since this evaluation was set to use "
                "permission-by-default semantics, your request is automatically "
                "accepted as it is not explicitly prohibited."
            )

        # -----------------------------------------------------
        # B) Prohibition-by-default
        # -----------------------------------------------------
        elif semantics_by_default == -1:

            accept_decision = False

            accept_explanation.append(
                "Your request did not match any permissions or prohibitions "
                "of the policy. Since this evaluation was set to use "
                "prohibition-by-default semantics, your request is automatically "
                "rejected as it is not explicitly permitted."
            )

        # -----------------------------------------------------
        # C) Unspecified-by-default
        # -----------------------------------------------------
        elif semantics_by_default == 0:

            accept_decision = None

            accept_explanation.append(
                "Your request did not match any permissions or prohibitions "
                "of the policy. Since this evaluation was set to use "
                "unspecified-by-default semantics, a reject or accept decision "
                "cannot be reached, as your request lies outside of what the "
                "given policy regulates."
            )

    # ---------------------------------------------------------
    # 6.7) Exactly one side has a full match
    # ---------------------------------------------------------
    elif (
            effective_full_match_permission
            and not effective_full_match_prohibition
    ):

        # -----------------------------------------------------
        # D) Permission matched
        # -----------------------------------------------------

        # Start by assuming duties are required.
        required_duties_exist = True

        # If ANY fully matched permission has no duties, then
        # there is at least one permission that can be granted
        # without requiring duties to be satisfied.
        for permission in permissions_matched:

            conditions = permission.get("conditions", [])
            duties = permission.get("duties", [])

            if (
                    len(conditions) == 0
                    and len(duties) == 0
            ):
                required_duties_exist = False
                break

        # -----------------------------------------------------
        # Duties must already be satisfied
        # -----------------------------------------------------
        if (
                semantics_for_duties == -1
                and required_duties_exist
        ):

            accept_decision = False

            accept_explanation.append(
                "Your request only matched a permission subject to duties. "
                "Since there is no evidence that such duties have been "
                "satisfied in the event log in the State of the World, and "
                "the evaluator semantics has been set to only accept "
                "permissions with duties already satisfied, your request "
                "has been rejected."
            )

        # -----------------------------------------------------
        # Duties may be fulfilled on the promise they will be
        # -----------------------------------------------------
        elif required_duties_exist:

            accept_decision = True

            accept_explanation.append(
                "Your request only matched a permission subject to duties. "
                "Since there is no evidence that such duties have been "
                "satisfied in the event log in the State of the World, "
                "the access request is granted on the promise that the "
                "required duties will be fulfilled before the requested "
                "action is performed"
            )

        # -----------------------------------------------------
        # No duties required
        # -----------------------------------------------------
        else:

            accept_decision = True

            accept_explanation.append(
                "Your request matched a permission so it can be accepted. No duties are required to be fulfilled."
            )

    # ---------------------------------------------------------
    # 6.8) Prohibition only
    # ---------------------------------------------------------
    elif (
            not effective_full_match_permission
            and effective_full_match_prohibition
    ):

        # -----------------------------------------------------
        # E) Prohibition matched
        # -----------------------------------------------------
        accept_decision = False

        accept_explanation.append(
            "Your request matched a prohibition of the policy and it is thus rejected."
        )

    # ---------------------------------------------------------
    # 6.9) Return final evaluation
    # ---------------------------------------------------------
    return {
        "permissions_matched": permissions_matched,
        "prohibitions_matched": prohibitions_matched,
        "accept_decision": accept_decision,
        "accept_explanation": accept_explanation
    }


def evaluate_ODRL_access_request_from_string(
    access_request_string,
    policy_string,
    state_of_the_world_string=None,
    evaluation_state_string=None,
    semantics_for_duties=1,
    semantics_by_default=-1,
    reasoning=True,
    ontology_files=[],
    ontology_graphs=[]

):

    # ---------------------------------------------------------
    # 1) Parse access request
    # ---------------------------------------------------------
    access_request = json.loads(access_request_string)

    if not isinstance(access_request, dict):
        raise ValueError(
            "access_request_string must contain a JSON object."
        )

    # ---------------------------------------------------------
    # 2) Parse policy
    # ---------------------------------------------------------
    graph, _ = rdf_utils.parse_string_to_graph(
        policy_string
    )

    if reasoning:
        ontology_graphs.append(graph)

    policies = extract_rule_list_from_policy(graph)
    features = extract_features_list_from_policy(graph)

    if not policies:
        raise ValueError("No policy could be extracted from policy_string.")

    feature_type_map = {
        f["iri"]: f["type"]
        for f in features
    }

    # ---------------------------------------------------------
    # 3) Parse State of the World, if supplied
    # ---------------------------------------------------------
    df = None

    if state_of_the_world_string is not None:
        df = pd.read_csv(
            StringIO(state_of_the_world_string)
        )

    # ---------------------------------------------------------
    # 4) Parse evaluation state, if supplied
    # ---------------------------------------------------------
    evaluation_state = None

    if evaluation_state_string is not None:
        evaluation_state = json.loads(evaluation_state_string)

        if not isinstance(evaluation_state, dict):
            raise ValueError(
                "evaluation_state_string must contain a JSON object."
            )

    # ---------------------------------------------------------
    # 5) Evaluate access request
    # ---------------------------------------------------------
    return evaluate_ODRL_access_request_on_dataframe(
        access_request,
        policies[0],
        feature_type_map,
        df=df,
        evaluation_state=evaluation_state,
        semantics_for_duties=semantics_for_duties,
        semantics_by_default=semantics_by_default,
        reasoning=reasoning,
        ontology_files=ontology_files,
        ontology_graphs=ontology_graphs
    )


def evaluate_ODRL_access_request_from_files(
    access_request_file,
    policy_file,
    state_of_the_world_file=None,
    evaluation_state_file=None,
    semantics_for_duties=1,
    semantics_by_default=-1,
    reasoning=True,
    ontology_files=[],
    ontology_graphs=[]
):

    # ---------------------------------------------------------
    # 1) Load access request
    # ---------------------------------------------------------
    with open(access_request_file, "r") as f:
        access_request = json.load(f)

    if not isinstance(access_request, dict):
        raise ValueError(
            "access_request_file must contain a JSON object."
        )

    # ---------------------------------------------------------
    # 2) Load policy
    # ---------------------------------------------------------
    graph = rdf_utils.load(policy_file)[0]

    if reasoning:
        ontology_graphs.append(graph)

    policies = extract_rule_list_from_policy(graph)
    features = extract_features_list_from_policy(graph)

    if not policies:
        raise ValueError(
            "No policy could be extracted from policy_file."
        )

    feature_type_map = {
        f["iri"]: f["type"]
        for f in features
    }

    # ---------------------------------------------------------
    # 3) Load State of the World, if supplied
    # ---------------------------------------------------------
    df = None

    if state_of_the_world_file is not None:
        df = pd.read_csv(state_of_the_world_file)

    # ---------------------------------------------------------
    # 4) Load evaluation state, if supplied
    # ---------------------------------------------------------
    evaluation_state = None

    if evaluation_state_file is not None:
        with open(evaluation_state_file, "r") as f:
            evaluation_state = json.load(f)

        if not isinstance(evaluation_state, dict):
            raise ValueError(
                "evaluation_state_file must contain a JSON object."
            )

    # ---------------------------------------------------------
    # 5) Evaluate access request
    # ---------------------------------------------------------
    return evaluate_ODRL_access_request_on_dataframe(
        access_request,
        policies[0],
        feature_type_map,
        df=df,
        evaluation_state=evaluation_state,
        semantics_for_duties=semantics_for_duties,
        semantics_by_default=semantics_by_default,
        reasoning=reasoning,
        ontology_files=ontology_files,
        ontology_graphs=ontology_graphs
    )


def evaluate_ODRL_from_files_streaming(policy_file, SotW_file, max_rows_per_SotW=1, normalise=False, reasoning=True,
    ontology_files=[], ontology_graphs=[]):

    STREAM_DIR = "stream_simulation"

    # ----------------------------------------
    # 1) PREPARE STREAM DIRECTORY
    # ----------------------------------------
    if os.path.exists(STREAM_DIR):
        shutil.rmtree(STREAM_DIR)
    os.makedirs(STREAM_DIR)

    # ----------------------------------------
    # 2) LOAD POLICY + FEATURES
    # ----------------------------------------
    graph = rdf_utils.load(policy_file)[0]
    if normalise:
        graph = rdf_utils.load_normalise(policy_file)[0]

    policies = extract_rule_list_from_policy(graph)
    features = extract_features_list_from_policy(graph)

    FEATURE_TYPE_MAP = {f["iri"]: f["type"] for f in features}

    # ----------------------------------------
    # 3) LOAD + SORT SOTW
    # ----------------------------------------
    df = pd.read_csv(SotW_file)



    if DT_COL in df.columns:
        df[DT_COL] = pd.to_datetime(df[DT_COL], errors="coerce", utc=True)
        df = df.sort_values(by=DT_COL, ascending=True)

    # ----------------------------------------
    # 4) SPLIT INTO STREAM FILES
    # ----------------------------------------
    total_rows = len(df)
    num_chunks = math.ceil(total_rows / max_rows_per_SotW)

    stream_files = []

    for i in range(num_chunks):
        start = i * max_rows_per_SotW
        end = start + max_rows_per_SotW

        chunk_df = df.iloc[start:end]

        file_path = os.path.join(STREAM_DIR, f"stream{i}.csv")
        chunk_df.to_csv(file_path, index=False)

        stream_files.append(file_path)

    # ----------------------------------------
    # 5) PROCESS STREAM FILES SEQUENTIALLY
    # ----------------------------------------
    evaluation_state = None
    result = None

    state_file = os.path.join(STREAM_DIR, "evaluation_state.json")

    for i, stream_file in enumerate(stream_files):

        result = evaluate_ODRL_from_files(
            policy_file,
            stream_file,
            state_file=state_file,
            normalise=normalise,
            reasoning=reasoning,
            ontology_files=ontology_files,
            ontology_graphs=ontology_graphs
        )

        # Save updated state
        evaluation_state = result[0]

        with open(state_file, "w") as f:
            json.dump(evaluation_state, f, default=str, indent=2)

    # ----------------------------------------
    # 6) RETURN FINAL RESULT
    # ----------------------------------------
    return result


#result = evaluate_ODRL_from_files("example_policies/GATE_Test/GATE_Policy_Test_Edited.jsonld",
#                                  "example_policies/GATE_Test/GATE_SotW_valid.csv")
#print(result)
#result = evaluate_ODRL_from_files("example_policies/isPartOf1.ttl",
#                                 "example_policies/isPartOf1.csv")
#print(result)

#access_request_result = evaluate_ODRL_access_request_from_string(
#    """
#{
#  "http://www.w3.org/ns/odrl/2/Action": "http://www.w3.org/ns/odrl/2/play"
#}
#""",
#    """
#
#  """
#)
#print(access_request_result)