from pathlib import Path
import sys

# ---------------------------------------------------------
# Add project root to Python path
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


import streamlit as st
from common.streamlit_style import apply_style
import tempfile
import os
import json
import pandas as pd

import rdf_utils
import SotW_generator


# ---------------------------------------------------------
# Page configuration
# ---------------------------------------------------------

st.set_page_config(
    page_title="ODRL State of the World Generator",
    layout="wide"
)
apply_style()

# ---------------------------------------------------------
# Helper functions
# ---------------------------------------------------------

def pretty_print_rules(rule_list):

    out_lines = []

    def format_rule_dict(rd, indent_level=2):

        indent = "    " * indent_level
        sub_indent = "    " * (indent_level + 1)

        if rd.get("conditions") + rd.get("constraints"):

            out_lines.append(
                f"{indent}Rule conditions:"
            )

            for cond in rd["conditions"] + rd.get("constraints"):

                if isinstance(cond, list) and len(cond) == 3:
                    subj, op, obj = cond
                    out_lines.append(
                        f"{sub_indent}{subj} {op} {obj}"
                    )

                else:
                    out_lines.append(
                        f"{sub_indent}{cond}"
                    )


        if rd.get("duties"):

            out_lines.append(
                f"{indent}Duties:"
            )

            for duty in rd["duties"]:
                format_rule_dict(
                    duty,
                    indent_level + 1
                )


        if rd.get("consequences"):

            out_lines.append(
                f"{indent}Consequences:"
            )

            for cons in rd["consequences"]:
                format_rule_dict(
                    cons,
                    indent_level + 1
                )


        if rd.get("remedies"):

            out_lines.append(
                f"{indent}Remedies:"
            )

            for rem in rd["remedies"]:
                format_rule_dict(
                    rem,
                    indent_level + 1
                )


    for policy in rule_list:

        out_lines.append(
            f"Policy IRI: {policy['policy_iri']}\n"
        )


        # permissions

        out_lines.append(
            "    Permissions:"
        )

        if policy["permissions"]:

            for perm in policy["permissions"]:
                format_rule_dict(
                    perm,
                    2
                )

        else:

            out_lines.append(
                "        (none)"
            )


        out_lines.append("")


        # prohibitions

        out_lines.append(
            "    Prohibitions:"
        )

        if policy["prohibitions"]:

            for prohib in policy["prohibitions"]:
                format_rule_dict(
                    prohib,
                    2
                )

        else:

            out_lines.append(
                "        (none)"
            )


        out_lines.append("")


        # obligations

        out_lines.append(
            "    Obligations:"
        )

        if policy["obligations"]:

            for oblig in policy["obligations"]:
                format_rule_dict(
                    oblig,
                    2
                )

        else:

            out_lines.append(
                "        (none)"
            )


        out_lines.append("")


    return "\n".join(out_lines)



# ---------------------------------------------------------
# App
# ---------------------------------------------------------

def main():

    st.title(
        "ODRL State of the World Generator"
    )

    st.write(
        """
        Upload an ODRL policy file and generate a State of the World (SotW)
        CSV dataset from the policy definition. You can specify the number 
        of rows (events) in the SotW, and whether it should be compliant
        or not with the policy.
        """
    )


    # -----------------------------------------------------
    # Upload policy
    # -----------------------------------------------------

    st.header(
        "1. Upload ODRL Policy"
    )

    uploaded_policy = st.file_uploader(
        "Upload ODRL Policy",
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
        ]
    )


    graph = None


    if uploaded_policy:

        try:

            policy_suffix = Path(uploaded_policy.name).suffix.lower()

            with tempfile.NamedTemporaryFile(
                    suffix=policy_suffix,
                    delete=False
            ) as tmp:

                tmp.write(
                    uploaded_policy.getvalue()
                )

                tmp_path = tmp.name


            graph = rdf_utils.load(tmp_path)[0]


            st.success(
                f"Loaded policy: {uploaded_policy.name}"
            )


            os.remove(tmp_path)


        except Exception as e:

            st.error(
                f"Could not load policy: {e}"
            )


    # -----------------------------------------------------
    # Parameters
    # -----------------------------------------------------

    st.header(
        "2. Generation Parameters"
    )


    number_of_records = st.number_input(
        "Number of Rows (events):",
        min_value=1,
        value=100,
        step=1
    )


    valid = st.checkbox(
        "Compliant",
        value=True
    )


    chance_feature_empty = st.number_input(
        "Chance Feature Empty (0-1):",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.05
    )


    csv_filename = st.text_input(
        "CSV Output Filename:",
        value="sotw.csv"
    )


    # -----------------------------------------------------
    # Generation
    # -----------------------------------------------------

    st.header(
        "3. Generate State of the World"
    )


    if "generated_csv" not in st.session_state:
        st.session_state.generated_csv = None

    if "generated_df" not in st.session_state:
        st.session_state.generated_df = None

    if "generated_validity" not in st.session_state:
        st.session_state.generated_validity = None

    if st.button(
        "Generate State of the World",
        type="primary"
    ):


        if graph is None:

            st.warning(
                "Please upload an ODRL policy first."
            )

        else:

            try:

                df, validity_achieved = (
                    SotW_generator
                    .generate_state_of_the_world_from_policies(
                        graph,
                        number_of_records=number_of_records,
                        valid=valid,
                        chance_feature_empty=chance_feature_empty,
                        csv_file=csv_filename
                    )
                )


                st.session_state.generated_df = df
                st.session_state.generated_csv = csv_filename
                st.session_state.generated_validity = validity_achieved


                st.success(
                    "State of the World generated successfully!"
                )

                if not validity_achieved:
                    generated_status = "non-compliant" if valid else "compliant"
                    st.warning(
                        f"Failed to generate the State of the World with the chosen type of compliance."
                        f"The generated one is {generated_status}."
                    )


            except Exception as e:

                st.error(
                    f"Generation failed: {e}"
                )


    # -----------------------------------------------------
    # Results
    # -----------------------------------------------------

    if st.session_state.generated_df is not None:


        st.header(
            "Generated State of the World"
        )


        df = st.session_state.generated_df


        st.write(
            f"Showing the first rows of the generated {len(df)} records"
        )


        st.dataframe(
            df,
            use_container_width=True
        )


        csv_data = df.to_csv(
            index=False
        ).encode(
            "utf-8"
        )


        st.download_button(
            label="⬇️ Download State of the World CSV",
            data=csv_data,
            file_name=st.session_state.generated_csv,
            mime="text/csv"
        )

    # -----------------------------------------------------
    # Show conditions
    # -----------------------------------------------------

    st.header( "4. Policy Conditions")

    if st.button("Show Rule Conditions"):
        if graph is None:
            st.warning("Upload a policy first.")
        else:
            try:
                rules = (rdf_utils.extract_rule_list_from_policy(graph))
                st.subheader("Pretty Printed Rule Conditions")
                st.text(pretty_print_rules(rules))
                st.subheader("Rule Conditions JSON")
                st.json(rules)
            except Exception as e:
                st.error(
                    f"Could not extract rules: {e}"
                )

if __name__ == "__main__":
    main()