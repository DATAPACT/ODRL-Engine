import streamlit as st
import re
import time
import html
from copy import deepcopy

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from profile_editor_concepts import concepts

from rdflib import Graph, URIRef, Literal
from rdflib.namespace import RDF

import logging

logging.basicConfig(level=logging.INFO)



# =========================================================
# DEFAULT / BUILT-IN PREFIXES
# =========================================================
#
# These prefixes are always available to the ontology
# generator, but are deliberately not shown in the
# user-editable prefix section.
#
# =========================================================

DEFAULT_PREFIXES = {
    "cc": "http://creativecommons.org/ns#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "dcterms": "http://purl.org/dc/terms/",
    "dpv": "https://w3id.org/dpv#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "odrl": "http://www.w3.org/ns/odrl/2/",
    "owl": "http://www.w3.org/2002/07/owl#",
    "prov": "http://www.w3.org/ns/prov#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "role": "http://www.w3.org/ns/dx/prof/role/",
    "schema": "https://schema.org/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "sw": "http://www.w3.org/2003/06/sw-vocab-status/ns#",
    "vann": "http://purl.org/vocab/vann/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}

# =========================================================
# IMPORT ODRL ONTOLOGIES
# =========================================================


ODRL_FOLDER = Path(__file__).resolve().parent.parent / "ODRL"
def load_odrl_ontologies():
    """
    Load all Turtle and RDF/XML ontology files from the
    ODRL folder into one global RDF graph.

    Supported:
        *.ttl
        *.rdf
    """

    graph = Graph()
    if not ODRL_FOLDER.exists():
        return graph
    ontology_files = sorted(
        list(ODRL_FOLDER.glob("*.ttl"))
        + list(ODRL_FOLDER.glob("*.rdf"))
    )

    for ontology_file in ontology_files:

        suffix = ontology_file.suffix.lower()

        if suffix == ".ttl":
            rdf_format = "turtle"

        elif suffix == ".rdf":
            rdf_format = "xml"

        else:
            continue

        try:

            graph.parse(
                ontology_file,
                format=rdf_format,
            )

        except Exception as exc:

            st.warning(
                f"Could not load ontology "
                f"'{ontology_file.name}': {exc}"
            )

    return graph


# Global ontology graph.
ontology = load_odrl_ontologies()

# =========================================================
# STREAMLIT CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="ODRL Profile and Ontology Builder",
    layout="wide",
)


# =========================================================
# CSS
# =========================================================

st.markdown(
    """
    <style>

    .block-container {
        padding-top: 1rem;
        padding-bottom: 0.5rem;
    }

    div[data-testid="stVerticalBlock"] {
        gap: 0.25rem;
    }

    .concept-container {
        border-radius: 8px;
        padding: 8px 12px;
        margin: 2px 0;
        border-left: 6px solid rgba(0,0,0,0.2);
    }

    .concept-title {
        font-size: 15px;
        font-weight: 600;
        margin: 0;
        line-height: 1.2;
    }

    .duplicate-warning {
        color: #c62828;
        font-size: 12px;
        margin-top: 2px;
        margin-bottom: 2px;
    }

    .field-description {
        color: #666666;
        font-size: 12px;
        margin: 0;
    }

    div.stButton > button {
        padding-top: 0.25rem;
        padding-bottom: 0.25rem;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# SESSION STATE INITIALISATION
# =========================================================

def initialise_session_state():
    """Initialise all application state."""

    if "prefixes" not in st.session_state:
        st.session_state.prefixes = [
            {
                "id": "prefix_0",
                "prefix": "ex",
                "expansion": "https://example.com/",
            }
        ]

    if "concept_instances" not in st.session_state:
        st.session_state.concept_instances = []

    if "next_concept_id" not in st.session_state:
        st.session_state.next_concept_id = 0


initialise_session_state()


# =========================================================
# BLUEPRINT HELPERS
# =========================================================

def get_concept_blueprint(concept_name):
    """Return the blueprint for a concept by name."""

    for concept in concepts:
        if concept.get("name") == concept_name:
            return concept

    return None


def create_concept_instance(concept_blueprint):
    """
    Create the internal representation of one concept instance.

    The instance stores the blueprint-derived data and the
    user-editable values separately.
    """

    timestamp_ms = int(time.time() * 1000)

    instance_id = st.session_state.next_concept_id
    st.session_state.next_concept_id += 1

    fields = []

    for field_index, field in enumerate(
        concept_blueprint.get("fields", [])
    ):

        field_type = field.get("type")

        field_data = {
            "blueprint": deepcopy(field),
            "value": "",
            "field_index": field_index,
        }

        # Classes are defined directly by the blueprint.
        if field_type == "classes":
            field_data["value"] = deepcopy(
                field.get("class_list", [])
            )

        # ID fields get a prefix and a generated local identifier.
        elif field_type == "ID":
            field_data["prefix"] = get_default_prefix()
            field_data["value"] = (
                f"concept_{timestamp_ms}"
            )

        fields.append(field_data)

    return {
        "instance_id": instance_id,
        "concept_name": concept_blueprint.get("name", ""),
        "fields": fields,
    }


def get_default_prefix():
    """Return the first available prefix."""

    if st.session_state.prefixes:
        return st.session_state.prefixes[0]["prefix"]

    return ""


# =========================================================
# PREFIX VALIDATION
# =========================================================

# A deliberately conservative Turtle prefix syntax.
#
# Examples accepted:
#   ex
#   ex1
#   my_prefix
#   my-prefix
#
# Examples rejected:
#   my prefix
#   my:prefix
#   ex!
#
PREFIX_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]*$"
)


# Characters permitted in the local portion of an IRI.
#
# This is deliberately restricted to URL/IRI-safe characters
# suitable for the generated local part.
#
IRI_LOCAL_PATTERN = re.compile(
    r"^[A-Za-z0-9\-._~!$&'()*+,;=:@%/]*$"
)


def is_valid_prefix(prefix):
    """Return True if a prefix is syntactically acceptable."""

    return bool(
        PREFIX_PATTERN.fullmatch(prefix)
    )


def is_valid_expansion(expansion):
    """
    Basic validation for a prefix expansion.

    rdflib will perform the final RDF/URI handling, but requiring
    an absolute HTTP/HTTPS URI gives the user a useful form-level
    validation.
    """

    return bool(
        re.fullmatch(
            r"https?://[^\s<>\"{}|\\^`]+",
            expansion,
        )
    )


def validate_prefixes():
    """
    Validate all prefixes.

    Returns:
        list[str]: validation errors
    """

    errors = []

    seen = set()

    for index, prefix_data in enumerate(
        st.session_state.prefixes
    ):

        prefix = prefix_data["prefix"].strip()
        expansion = prefix_data["expansion"].strip()

        if not prefix:
            errors.append(
                f"Prefix #{index + 1}: prefix cannot be empty."
            )

        elif not is_valid_prefix(prefix):
            errors.append(
                f"Prefix #{index + 1}: "
                f"'{prefix}' is not a valid Turtle prefix."
            )

        if prefix in seen:
            errors.append(
                f"Prefix #{index + 1}: "
                f"duplicate prefix '{prefix}'."
            )

        seen.add(prefix)

        if not expansion:
            errors.append(
                f"Prefix '{prefix or index + 1}': "
                f"expansion cannot be empty."
            )

        elif not is_valid_expansion(expansion):
            errors.append(
                f"Prefix '{prefix or index + 1}': "
                f"expansion must be an absolute HTTP/HTTPS URI."
            )

    return errors


# =========================================================
# CONCEPT FORM HELPERS
# =========================================================

def get_all_id_values(exclude_instance_id=None):
    """
    Return all currently entered full IRIs.

    Used for duplicate-ID detection.
    """

    ids = []

    for instance in st.session_state.concept_instances:

        if (
            exclude_instance_id is not None
            and instance["instance_id"]
            == exclude_instance_id
        ):
            continue

        for field in instance["fields"]:

            if field["blueprint"].get("type") != "ID":
                continue

            prefix = field.get("prefix", "")
            value = field.get("value", "").strip()

            if prefix and value:
                ids.append(
                    f"{prefix}:{value}"
                )

    return ids


def get_full_id(field_data):
    """Build the compact prefixed IRI for an ID field."""

    prefix = field_data.get("prefix", "")
    value = field_data.get("value", "").strip()

    if not prefix or not value:
        return ""

    return f"{prefix}:{value}"

def get_instance_id(instance):
    """
    Return the compact ID (e.g. ex:Action1)
    for a concept instance.
    """
    for field_data in instance["fields"]:
        if field_data["blueprint"].get("type") == "ID":
            return get_full_id(field_data)
    return ""

def validate_id_local_part(value):
    """
    Validate the editable part of an ID.

    Empty is handled separately because an empty mandatory ID
    is not valid.
    """

    return bool(
        IRI_LOCAL_PATTERN.fullmatch(value)
    )


# =========================================================
# FIELD RENDERERS
# =========================================================
#
# Each field type gets its own renderer.
#
# This is the main extension point for future field types.
#
# =========================================================

def render_id_field(
    instance,
    field_data,
    field_index,
):
    """Render an ID field."""

    prefixes = [
        item["prefix"]
        for item in st.session_state.prefixes
        if item["prefix"]
    ]

    instance_id = instance["instance_id"]

    if not prefixes:
        st.warning(
            "Add at least one prefix before defining an ID."
        )
        return

    current_prefix = field_data.get(
        "prefix",
        prefixes[0],
    )

    if current_prefix not in prefixes:
        current_prefix = prefixes[0]
        field_data["prefix"] = current_prefix

    col1, col2 = st.columns(
        [1, 4]
    )

    with col1:

        selected_prefix = st.selectbox(
            "Prefix",
            options=prefixes,
            index=prefixes.index(
                current_prefix
            ),
            key=(
                f"id_prefix_"
                f"{instance_id}_"
                f"{field_index}"
            ),
        )

        field_data["prefix"] = selected_prefix

    with col2:

        value = st.text_input(
            "ID",
            value=field_data.get(
                "value",
                "",
            ),
            key=(
                f"id_value_"
                f"{instance_id}_"
                f"{field_index}"
            ),
            help=(
                "Only URL/IRI-safe characters are permitted."
            ),
        )

        field_data["value"] = value

    # Form-level validation
    if value and not validate_id_local_part(value):

        st.error(
            "The ID contains characters that are not valid "
            "in the local part of an IRI."
        )

    # Duplicate detection
    full_id = get_full_id(field_data)

    if full_id:

        duplicate_ids = get_all_id_values(
            exclude_instance_id=instance_id
        )

        if full_id in duplicate_ids:

            st.markdown(
                f"""
                <div class="duplicate-warning">
                    ⚠ Duplicate ID: <code>
                    {html.escape(full_id)}
                    </code>
                    <br>
                    Another concept already uses this ID.
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_classes_field(
    field_data,
):
    """
    Render a classes field.

    class_list is supplied by the blueprint, so the values are
    displayed rather than manually entered.
    """

    class_list = field_data["blueprint"].get(
        "class_list",
        [],
    )

    if not class_list:
        return

    st.markdown(
        "**Classes**"
    )

    badges = "".join(
        [
            f'<span style="background:#eeeeee;border-radius:12px;padding:2px 8px;font-size:12px;margin-right:4px;">'
            f'{html.escape(class_iri)}</span>'
            for class_iri in class_list
        ]
    )

    st.markdown(
        badges,
        unsafe_allow_html=True,
    )

    # Keep the actual list in the form's internal data.
    field_data["value"] = deepcopy(
        class_list
    )


def render_text_field(
    instance,
    field_data,
    field_index,
):
    """Render a standard single-line text field."""

    blueprint = field_data["blueprint"]

    label = blueprint.get(
        "text_label",
        "Text",
    )

    info = blueprint.get(
        "text_info",
        "",
    )

    value = st.text_input(
        label,
        value=field_data.get(
            "value",
            "",
        ),
        key=(
            f"text_"
            f"{instance['instance_id']}_"
            f"{field_index}"
        ),
        help=info if info else None,
    )

    field_data["value"] = value


def render_text_area_field(
    instance,
    field_data,
    field_index,
):
    """Render a multi-line text area."""

    blueprint = field_data["blueprint"]

    label = blueprint.get(
        "text_label",
        "Text",
    )

    info = blueprint.get(
        "text_info",
        "",
    )

    value = st.text_area(
        label,
        value=field_data.get(
            "value",
            "",
        ),
        height=60,
        key=(
            f"text_area_"
            f"{instance['instance_id']}_"
            f"{field_index}"
        ),
        help=info if info else None,
    )

    field_data["value"] = value

def render_iri_selection_field(
    instance,
    field_data,
    field_index,
):
    """
    Render a searchable IRI selection field.

    The user sees:

        Label — IRI

    but the stored value is the full IRI.
    """

    blueprint = field_data["blueprint"]

    label = blueprint.get(
        "text_label",
        "Select IRI",
    )

    info = blueprint.get(
        "text_info",
        "",
    )

    candidates = get_iri_selection_candidates(
        blueprint
    )

    if not candidates:

        st.info(
            f"No IRIs are currently available "
            f"for '{label}'."
        )

        field_data["value"] = ""

        return

    # -----------------------------------------------------
    # Sort by label
    # -----------------------------------------------------

    candidates.sort(
        key=lambda item: (
            item["label"].lower(),
            item["iri"].lower(),
        )
    )

    # -----------------------------------------------------
    # Create lookup
    # -----------------------------------------------------

    candidate_by_iri = {
        item["iri"]: item
        for item in candidates
    }

    iri_options = [
        item["iri"]
        for item in candidates
    ]

    # -----------------------------------------------------
    # Current selection
    # -----------------------------------------------------

    current_value = field_data.get(
        "value",
        "",
    )

    if current_value not in iri_options:

        current_value = ""

    # -----------------------------------------------------
    # Searchable selectbox
    # -----------------------------------------------------

    selected_iri = st.selectbox(
        label,
        options=[
            ""
        ] + iri_options,
        index=(
            0
            if not current_value
            else iri_options.index(
                current_value
            ) + 1
        ),
        key=(
            f"iri_selection_"
            f"{instance['instance_id']}_"
            f"{field_index}"
        ),
        format_func=lambda iri: (
            "Select an IRI..."
            if not iri
            else (
                f"{candidate_by_iri[iri]['label']}"
                f" — {iri}"
            )
        ),
        help=info if info else None,
    )

    field_data["value"] = (
        selected_iri
        if selected_iri
        else ""
    )

FIELD_RENDERERS = {
    "ID": render_id_field,
    "classes": render_classes_field,
    "text": render_text_field,
    "text_area": render_text_area_field,
    "IRI_selection": render_iri_selection_field,
}


def render_field(
    instance,
    field_data,
    field_index,
):
    """
    Dispatch a field to the appropriate renderer.

    Unknown field types are deliberately ignored.
    """

    field_type = field_data["blueprint"].get(
        "type"
    )

    renderer = FIELD_RENDERERS.get(
        field_type
    )

    if renderer is None:
        return

    if field_type == "classes":

        renderer(
            field_data,
        )

    else:

        renderer(
            instance,
            field_data,
            field_index,
        )



# =========================================================
# CONCEPT VALIDATION
# =========================================================

def validate_concept_instances():
    """
    Validate all concept instances.

    Returns:
        list[str]: validation errors
    """

    errors = []

    all_ids = []

    for instance_number, instance in enumerate(
        st.session_state.concept_instances,
        start=1,
    ):

        concept_name = instance["concept_name"]

        # -------------------------------------------------
        # First gather ID
        # -------------------------------------------------

        concept_id = ""

        for field_data in instance["fields"]:

            if (
                field_data["blueprint"].get("type")
                == "ID"
            ):

                concept_id = get_full_id(
                    field_data
                )

                local_value = field_data.get(
                    "value",
                    "",
                ).strip()

                if not local_value:

                    if field_data["blueprint"].get(
                        "mandatory",
                        0,
                    ) == 1:

                        errors.append(
                            f"{concept_name} #{instance_number}: "
                            f"ID is mandatory."
                        )

                elif not validate_id_local_part(
                    local_value
                ):

                    errors.append(
                        f"{concept_name} #{instance_number}: "
                        f"ID '{local_value}' contains "
                        f"invalid characters."
                    )

        if concept_id:
            all_ids.append(
                (
                    concept_id,
                    concept_name,
                    instance_number,
                )
            )

        # -------------------------------------------------
        # Validate mandatory text fields
        # -------------------------------------------------

        for field_data in instance["fields"]:

            blueprint = field_data["blueprint"]

            if blueprint.get(
                "mandatory",
                0,
            ) != 1:
                continue

            field_type = blueprint.get(
                "type"
            )

            if field_type in (
                "ID",
                "classes",
            ):
                continue

            value = field_data.get(
                "value",
                "",
            )

            if not isinstance(value, str):
                continue

            if not value.strip():

                label = blueprint.get(
                    "text_label",
                    field_type,
                )

                errors.append(
                    f"{concept_name} #{instance_number}: "
                    f"'{label}' is mandatory."
                )

    # -----------------------------------------------------
    # Duplicate IDs
    # -----------------------------------------------------

    id_map = {}

    for (
        concept_id,
        concept_name,
        instance_number,
    ) in all_ids:

        id_map.setdefault(
            concept_id,
            [],
        ).append(
            (
                concept_name,
                instance_number,
            )
        )

    for concept_id, locations in id_map.items():

        if len(locations) > 1:

            location_text = ", ".join(
                f"{name} #{number}"
                for name, number in locations
            )

            errors.append(
                f"Duplicate ID '{concept_id}' "
                f"is used by: {location_text}."
            )

    return errors


# =========================================================
# PREFIX / CURIE RESOLUTION
# =========================================================

def get_all_prefixes():
    """
    Return both built-in and user-defined prefixes.

    User-defined prefixes take precedence if the same prefix
    is explicitly defined by the user.
    """

    prefixes = dict(DEFAULT_PREFIXES)

    for prefix_data in st.session_state.prefixes:

        prefix = prefix_data["prefix"].strip()
        expansion = prefix_data["expansion"].strip()

        if prefix and expansion:
            prefixes[prefix] = expansion

    return prefixes


def expand_curie(curie):
    """
    Expand a compact CURIE such as:

        odrl:Action

    into:

        http://www.w3.org/ns/odrl/2/Action
    """

    if not isinstance(curie, str):
        raise ValueError(
            f"Expected string IRI, got {type(curie)}"
        )

    if ":" not in curie:
        raise ValueError(
            f"'{curie}' is not a prefixed IRI."
        )

    prefix, local = curie.split(
        ":",
        1,
    )

    prefixes = get_all_prefixes()

    if prefix not in prefixes:
        raise ValueError(
            f"Unknown prefix '{prefix}'."
        )

    return prefixes[prefix] + local

# =========================================================
# IRI / LABEL HELPERS
# =========================================================

def uri_to_display_string(uri):
    """
    Convert an RDF URI into a readable string.

    Prefer the final fragment/path component.
    """

    uri = str(uri)

    # Remove fragment
    if "#" in uri:
        value = uri.rsplit("#", 1)[-1]

    # Otherwise use final path component
    else:
        value = uri.rstrip("/").rsplit("/", 1)[-1]

    # URL decoding can be added later if desired.
    return value or uri


def get_ontology_label(uri):
    """
    Get an rdfs:label for a URI from the imported ontology.

    If no label exists, use the last part of the URI.
    """

    uri_ref = URIRef(str(uri))

    # Use the full URI rather than relying on a particular
    # prefix declaration in the ontology.
    rdfs_label = URIRef(
        "http://www.w3.org/2000/01/rdf-schema#label"
    )

    labels = list(
        ontology.objects(
            uri_ref,
            rdfs_label,
        )
    )

    for label in labels:

        if isinstance(label, Literal):

            value = str(label).strip()

            if value:
                return value

    return uri_to_display_string(uri)


def get_label_from_concept_instance(instance):
    """
    Look for a user-entered rdfs:label on a concept instance.

    The blueprint must contain a text field whose
    text_relations includes rdfs:label.
    """

    RDFS_LABEL = (
        "rdfs:label"
    )

    for field_data in instance["fields"]:

        blueprint = field_data["blueprint"]

        if blueprint.get("type") != "text":
            continue

        relations = blueprint.get(
            "text_relations",
            [],
        )

        if RDFS_LABEL not in relations:
            continue

        value = field_data.get(
            "value",
            "",
        )

        if isinstance(value, str) and value.strip():
            return value.strip()

    return None

def get_form_concept_candidates(
    concept_references
):
    """
    Return IRIs and labels for concepts already defined
    in the form whose concept name occurs in
    concept_references.

    Returns:

        [
            {
                "iri": "...",
                "label": "..."
            },
            ...
        ]
    """

    candidates = []

    if not concept_references:
        return candidates

    referenced_names = set(
        concept_references
    )

    for instance in st.session_state.concept_instances:

        concept_name = instance.get(
            "concept_name"
        )

        if concept_name not in referenced_names:
            continue

        concept_id = ""

        # Find the ID
        for field_data in instance["fields"]:

            if (
                field_data["blueprint"].get(
                    "type"
                )
                == "ID"
            ):

                concept_id = get_full_id(
                    field_data
                )

                break

        if not concept_id:
            # The concept has not got an ID yet.
            continue

        try:

            full_iri = expand_curie(
                concept_id
            )

        except ValueError:

            continue

        label = get_label_from_concept_instance(
            instance
        )

        if not label:
            label = uri_to_display_string(
                full_iri
            )

        candidates.append(
            {
                "iri": full_iri,
                "label": label,
            }
        )

    return candidates

def get_query_candidates(
    concept_query
):
    """
    Execute a SPARQL SELECT query against the global
    ontology graph.

    The query is expected to return:

        ?x
        ?l

    where:

        ?x = IRI
        ?l = optional label

    If ?l is absent, the last part of ?x is used.
    """

    candidates = []

    if not concept_query:
        return candidates

    try:

        results = ontology.query(
            concept_query
        )

        for row in results:

            # The query is expected to return ?x.
            iri = getattr(
                row,
                "x",
                None,
            )

            if iri is None:
                continue

            iri = str(iri).strip()

            if not iri:
                continue

            # Optional ?l
            label = getattr(
                row,
                "l",
                None,
            )

            if label is not None:
                label = str(label).strip()

            if not label:
                label = get_ontology_label(
                    iri
                )

            candidates.append(
                {
                    "iri": iri,
                    "label": label,
                }
            )

    except Exception as exc:

        st.error(
            f"Could not execute concept query: {exc}"
        )

    return candidates

def get_iri_selection_candidates(
    field_blueprint
):
    """
    Return the union of:

    1. Matching concepts already defined in the form.
    2. Results from concept_query against ontology.

    Duplicate IRIs are removed.
    """

    candidates = []

    # -----------------------------------------------------
    # Concepts already defined in the form
    # -----------------------------------------------------

    concept_references = (
        field_blueprint.get(
            "concept_references",
            []
        )
    )

    candidates.extend(
        get_form_concept_candidates(
            concept_references
        )
    )

    # -----------------------------------------------------
    # Imported ontology query
    # -----------------------------------------------------

    concept_query = (
        field_blueprint.get(
            "concept_query"
        )
    )

    if concept_query:

        candidates.extend(
            get_query_candidates(
                concept_query
            )
        )

    # -----------------------------------------------------
    # Deduplicate by IRI
    # -----------------------------------------------------

    unique = {}

    for candidate in candidates:

        iri = candidate["iri"]

        if iri not in unique:

            unique[iri] = candidate

        else:

            # Prefer an actual label over a generated
            # last-part label.
            existing = unique[iri]

            generated_existing = (
                existing["label"]
                == uri_to_display_string(iri)
            )

            if generated_existing:

                unique[iri] = candidate

    return list(
        unique.values()
    )

# =========================================================
# ONTOLOGY GENERATION
# =========================================================

def build_ontology():
    """
    Generate an RDF graph from the current form data.

    Returns:
        rdflib.Graph
    """

    graph = Graph()

    # -----------------------------------------------------
    # Prefix declarations
    # -----------------------------------------------------

    all_prefixes = get_all_prefixes()

    for prefix, expansion in all_prefixes.items():
        graph.bind(
            prefix,
            expansion,
        )

    # -----------------------------------------------------
    # Concept instances
    # -----------------------------------------------------

    for instance in st.session_state.concept_instances:

        concept_id = None

        # Find ID
        for field_data in instance["fields"]:

            if (
                field_data["blueprint"].get("type")
                == "ID"
            ):

                compact_id = get_full_id(
                    field_data
                )

                if compact_id:

                    concept_id = URIRef(
                        expand_curie(
                            compact_id
                        )
                    )

                break

        if concept_id is None:
            # This should normally be caught by validation.
            continue

        # -------------------------------------------------
        # Process each field
        # -------------------------------------------------

        for field_data in instance["fields"]:

            blueprint = field_data["blueprint"]

            field_type = blueprint.get(
                "type"
            )

            # ---------------------------------------------
            # Classes
            # ---------------------------------------------

            if field_type == "classes":

                class_list = blueprint.get(
                    "class_list",
                    [],
                )

                for class_iri in class_list:

                    class_uri = URIRef(
                        expand_curie(
                            class_iri
                        )
                    )

                    graph.add(
                        (
                            concept_id,
                            RDF.type,
                            class_uri,
                        )
                    )

            # ---------------------------------------------
            # Text / Text area
            # ---------------------------------------------

            elif field_type in (
                "text",
                "text_area",
            ):

                value = field_data.get(
                    "value",
                    "",
                )

                if not value:
                    continue

                relations = blueprint.get(
                    "text_relations",
                    [],
                )

                for relation in relations:

                    relation_uri = URIRef(
                        expand_curie(
                            relation
                        )
                    )

                    graph.add(
                        (
                            concept_id,
                            relation_uri,
                            Literal(value),
                        )
                    )
            elif field_type == "IRI_selection":

                selected_iri = field_data.get(
                    "value",
                    "",
                )

                if not selected_iri:
                    continue

                relations = blueprint.get(
                    "text_relations",
                    [],
                )

                selected_uri = URIRef(
                    selected_iri
                )

                for relation in relations:
                    relation_uri = URIRef(
                        expand_curie(
                            relation
                        )
                    )

                    graph.add(
                        (
                            concept_id,
                            relation_uri,
                            selected_uri,
                        )
                    )

            # ---------------------------------------------
            # ID itself is not emitted as a triple.
            # The ID determines the subject.
            # ---------------------------------------------

            elif field_type == "ID":
                continue

            # ---------------------------------------------
            # Unknown field types are ignored.
            # ---------------------------------------------

            else:
                continue

    return graph


def generate_ttl():
    """
    Validate and generate Turtle.

    Returns:
        tuple[str | None, list[str]]
    """

    errors = []

    errors.extend(
        validate_prefixes()
    )

    errors.extend(
        validate_concept_instances()
    )

    if errors:
        return None, errors

    try:

        graph = build_ontology()

        ttl = graph.serialize(
            format="turtle"
        )

        return ttl, []

    except Exception as exc:

        return None, [
            f"Could not generate ontology: {exc}"
        ]


# =========================================================
# PAGE HEADER
# =========================================================

st.title("ODRL Profile and Ontology Builder")

st.markdown(
    """
    This tool allows you to easily define ODRL specific concepts to be used when defining ODRL policies.
    In this version 0.1 of the tool, you can define core features of Actions, Parties, Assets and Left Operands.
    """
)

left_panel, right_panel = st.columns(
    [1, 3],
    gap="medium"
)

# =========================================================
# DOWNLOAD ONTOLOGY
# =========================================================

st.subheader("Ontology")

download_clicked = st.button(
    "Download Ontology",
    use_container_width=True,
)


if download_clicked:

    ttl_content, generation_errors = (
        generate_ttl()
    )

    if generation_errors:

        st.error(
            "The ontology could not be generated. "
            "Please fix the following issues:"
        )

        for error in generation_errors:
            st.error(error)

    else:

        st.success(
            "Ontology generated successfully."
        )

        st.download_button(
            label="Download ontology.ttl",
            data=ttl_content,
            file_name="ontology.ttl",
            mime="text/turtle",
            use_container_width=True,
        )

with left_panel:
    # =========================================================
    # PREFIXES
    # =========================================================

    st.divider()

    st.subheader("Prefixes")

    st.markdown(
        """
        Define the prefixes that can be used by ID and class fields.
        """
    )


    for index, prefix_data in enumerate(
        st.session_state.prefixes
    ):

        with st.container():

            col1, col2, col3 = st.columns(
                [1, 4, 0.7]
            )

            with col1:

                prefix = st.text_input(
                    "Prefix",
                    value=prefix_data["prefix"],
                    key=(
                        f"prefix_name_"
                        f"{prefix_data['id']}"
                    ),
                    help=(
                        "Letters, numbers, underscores and "
                        "hyphens only. Must start with a letter."
                    ),
                )

                prefix_data["prefix"] = prefix.strip()

            with col2:

                expansion = st.text_input(
                    "Expansion",
                    value=prefix_data["expansion"],
                    key=(
                        f"prefix_expansion_"
                        f"{prefix_data['id']}"
                    ),
                    help=(
                        "For example: "
                        "https://example.com/"
                    ),
                )

                prefix_data["expansion"] = (
                    expansion.strip()
                )

            with col3:

                # Don't allow the initial ex prefix to be removed.
                # All other prefixes can be removed.
                if index > 0:

                    if st.button(
                        "Remove",
                        key=(
                            f"remove_prefix_"
                            f"{prefix_data['id']}"
                        ),
                    ):

                        st.session_state.prefixes.pop(
                            index
                        )

                        st.rerun()


    if st.button(
        "Add Prefix",
        use_container_width=False,
    ):

        next_prefix_number = len(
            st.session_state.prefixes
        )

        st.session_state.prefixes.append(
            {
                "id": f"prefix_{next_prefix_number}_{int(time.time() * 1000)}",
                "prefix": "",
                "expansion": "",
            }
        )

        st.rerun()


    # =========================================================
    # ADD CONCEPT
    # =========================================================

    st.divider()

    st.subheader("Add Concept")

    concept_names = [
        concept.get("name", "")
        for concept in concepts
        if concept.get("name")
    ]

    if not concept_names:

        st.warning(
            "No concepts have been defined."
        )

    else:

        concept_col, button_col = st.columns(
            [4, 1]
        )

        with concept_col:

            selected_concept_name = st.selectbox(
                "Concept type",
                options=concept_names,
                key="selected_concept_type",
            )

        with button_col:

            st.write("")

            add_concept_clicked = st.button(
                "Add Concept",
                use_container_width=True,
            )

        if add_concept_clicked:

            blueprint = get_concept_blueprint(
                selected_concept_name
            )

            if blueprint:

                new_instance = (
                    create_concept_instance(
                        blueprint
                    )
                )

                st.session_state.concept_instances.append(
                    new_instance
                )

                st.rerun()


with right_panel:
    # =========================================================
    # CONCEPT EDITING AREA
    # =========================================================

    st.divider()

    st.subheader("Concepts")


    if not st.session_state.concept_instances:

        st.info(
            "No concepts have been added yet. "
            "Select a concept above and click "
            "'Add Concept'."
        )


    for instance_number, instance in enumerate(
        st.session_state.concept_instances,
        start=1,
    ):
        instance_id = instance["instance_id"]

        blueprint = get_concept_blueprint(
            instance["concept_name"]
        )

        background = "#f8f8f8"

        if blueprint:
            background = blueprint.get(
                "background",
                background
            )

        concept_id = get_instance_id(instance)

        title = (
            f"{instance['concept_name']} #{instance_number}"
            if not concept_id
            else f"{instance['concept_name']} #{instance_number} • {concept_id}"
        )

        st.markdown(
            f"""
            <div style="
                border-left: 8px solid {background};
                height: 32px;
                margin-bottom: -32px;
                pointer-events: none;
            ">
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander(
                title,
                expanded=False,
        ):

            remove_clicked = st.button(
                "🗑 Remove",
                key=f"remove_concept_{instance_id}",
            )

            if remove_clicked:
                st.session_state.concept_instances = [
                    item
                    for item in st.session_state.concept_instances
                    if item["instance_id"] != instance_id
                ]
                st.rerun()

            for field_index, field_data in enumerate(
                instance["fields"]
            ):
                blueprint = field_data["blueprint"]

                field_type = blueprint.get("type")

                if field_type not in FIELD_RENDERERS:
                    continue

                render_field(
                    instance,
                    field_data,
                    field_index,
                )

                if blueprint.get(
                    "mandatory",
                    0,
                ) == 1:
                    st.caption("Required")


# =========================================================
# CURRENT DATA SUMMARY
# =========================================================

if st.session_state.concept_instances:

    st.divider()

    with st.expander(
        "Ontology data preview",
        expanded=False,
    ):

        for instance_number, instance in enumerate(
            st.session_state.concept_instances,
            start=1,
        ):

            st.markdown(
                f"**{instance['concept_name']} "
                f"#{instance_number}**"
            )

            preview = {
                "concept_type": instance[
                    "concept_name"
                ],
                "fields": [],
            }

            for field_data in instance["fields"]:

                blueprint = field_data[
                    "blueprint"
                ]

                field_type = blueprint.get(
                    "type"
                )

                if field_type == "ID":

                    preview["fields"].append(
                        {
                            "type": "ID",
                            "value": get_full_id(
                                field_data
                            ),
                        }
                    )

                else:

                    preview["fields"].append(
                        {
                            "type": field_type,
                            "value": field_data.get(
                                "value"
                            ),
                        }
                    )

            st.json(preview)