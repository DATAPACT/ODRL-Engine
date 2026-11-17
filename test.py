import rdflib
import pyshacl
import test_utils
import ODRL_Evaluator
import validate
import os
import uuid
import time
import json
from rdf_utils import extract_features_list_from_policy, extract_rule_list_from_policy

total_eval_time = 0.0
total_eval_calls = 0

tests_passed = 0
tests_failed = 0
test_log = []

def detect_odrl_file_format(filepath):
    """
    Detect whether a file has a supported ODRL RDF serialization.
    """
    extension = os.path.splitext(filepath)[1].lower()
    formats = {
        ".jsonld": "json-ld",
        ".ttl": "turtle",
        ".rdf": "rdf/xml",
    }

    return formats.get(extension)

def timed_evaluation(func, *args, **kwargs):
    global total_eval_time, total_eval_calls

    start = time.perf_counter()
    result = func(*args, **kwargs)
    end = time.perf_counter()

    total_eval_time += (end - start)
    total_eval_calls += 1

    return result

def unordered_equal(a, b):
    """
    Compare two values, ignoring the order of elements in lists.
    Nested lists are also compared without considering order.
    Dictionaries are compared by keys and values.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        return (
            a.keys() == b.keys()
            and all(unordered_equal(a[k], b[k]) for k in a)
        )

    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False

        # Match each element with one unmatched element in b.
        unmatched = list(b)

        for item_a in a:
            for i, item_b in enumerate(unmatched):
                if unordered_equal(item_a, item_b):
                    unmatched.pop(i)
                    break
            else:
                return False

        return True

    return a == b


def check_expected_conditional_rules(expected_conditions, matched_rules):
    actual_conditions = [
        rule.get("conditions", [])
        for rule in matched_rules
        if rule.get("conditions", []) != []
    ]

    missing = [
        expected for expected in expected_conditions
        if not any(unordered_equal(expected, actual) for actual in actual_conditions)
    ]

    extra = [
        actual for actual in actual_conditions
        if not any(unordered_equal(actual, expected) for expected in expected_conditions)
    ]

    return missing, extra

def run_access_request_evaluation_tests():
    global tests_passed
    global tests_failed
    global test_log

    folder = "test_cases/evaluation/access_control"

    if not os.path.exists(folder):
        print(f"Skipping access request evaluation tests: folder does not exist: {folder}")
        return

    category_stats = {}

    files = os.listdir(folder)

    # Every .ttl file represents one test case.
    base_names = sorted(
        os.path.splitext(f)[0]
        for f in files
        if f.endswith(".ttl")
    )

    for base in base_names:

        policy_file = os.path.join(folder, base + ".ttl")
        request_file = os.path.join(folder, base + ".json")
        sotw_file = os.path.join(folder, base + ".csv")
        params_file = os.path.join(folder, base + ".txt")

        # Required files
        if not os.path.exists(request_file):
            print(f"Skipping access request test {base}: missing JSON request file")
            continue

        if not os.path.exists(params_file):
            print(f"Skipping access request test {base}: missing TXT parameters file")
            continue

        # Read test parameters
        params = {}

        try:
            with open(params_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()

                    if not line or "=" not in line:
                        continue

                    key, value = line.split("=", 1)
                    params[key.strip()] = value.strip()

            # Convert expected_accept_decision to bool / None
            expected_raw = params.get("expected_accept_decision")

            if expected_raw == "True":
                expected_accept_decision = True
            elif expected_raw == "False":
                expected_accept_decision = False
            elif expected_raw == "None":
                expected_accept_decision = None
            else:
                print(
                    f"Skipping access request test {base}: "
                    f"invalid or missing expected_accept_decision"
                )
                continue

            expected_conditional_prohibitions = json.loads(params.get("expected_conditional_prohibitions", "[]"))
            expected_conditional_permissions = json.loads(params.get("expected_conditional_permissions", "[]"))

            test_tag = params.get("test_tag", "others").strip()

            if not test_tag:
                test_tag = "others"

            # Optional evaluation semantics
            semantics_for_duties = int(
                params.get("semantics_for_duties", 1).rstrip(",")
            )

            semantics_by_default = int(
                params.get("semantics_by_default", -1).rstrip(",")
            )

        except Exception as e:
            tests_failed += 1
            test_log.append(
                f"Exception reading access request test parameters {base}: {e}"
            )
            print(
                f"Access request test {base} failed while reading parameters: {e}"
            )
            continue

        if test_tag not in category_stats:
            category_stats[test_tag] = {"passed": 0, "total": 0}

        category_stats[test_tag]["total"] += 1

        try:
            result = timed_evaluation(
                ODRL_Evaluator.evaluate_ODRL_access_request_from_files,
                access_request_file=request_file,
                policy_file=policy_file,
                state_of_the_world_file=(
                    sotw_file if os.path.exists(sotw_file) else None
                ),
                semantics_for_duties=semantics_for_duties,
                semantics_by_default=semantics_by_default,
            )

            accept_decision = result["accept_decision"]

        except Exception as e:
            tests_failed += 1
            test_log.append(
                f"Exception evaluating access request test {base}: {e}"
            )
            print(
                f"Access request test {base} failed due to exception: {e}"
            )
            continue

        missing_permissions = []
        extra_permissions = []
        missing_prohibitions = []
        extra_prohibitions = []

        if not expected_conditional_prohibitions and not expected_conditional_permissions:
            conditions_ok = True
        else:
            missing_permissions, extra_permissions = check_expected_conditional_rules(
                expected_conditional_permissions, result.get("permissions_matched", [])
            )
            missing_prohibitions, extra_prohibitions = check_expected_conditional_rules(
                expected_conditional_prohibitions, result.get("prohibitions_matched", [])
            )
            conditions_ok = not (
                    missing_permissions or extra_permissions
                    or missing_prohibitions or extra_prohibitions
            )

        if accept_decision == expected_accept_decision and conditions_ok:
            tests_passed += 1
            category_stats[test_tag]["passed"] += 1

        else:
            tests_failed += 1

            print(
                f"Failed to validate acccess request test {base}, "
                f"expected accept decision {expected_accept_decision} "
                f"but the evaluator returned {accept_decision}."
            )

            test_log.append(
                f"Failed access request test {base} "
                f"(expected accept decision {expected_accept_decision}, "
                f"got {accept_decision})"
            )

            if missing_permissions:
                test_log.append(f"{base}: missing conditional permissions: {missing_permissions}")
            if extra_permissions:
                test_log.append(f"{base}: extra conditional permissions: {extra_permissions}")
            if missing_prohibitions:
                test_log.append(f"{base}: missing conditional prohibitions: {missing_prohibitions}")
            if extra_prohibitions:
                test_log.append(f"{base}: extra conditional prohibitions: {extra_prohibitions}")

    print("\nEvaluation Access Request tests category summary:")
    for category in sorted(category_stats.keys()):
        passed = category_stats[category]["passed"]
        total = category_stats[category]["total"]

        print(f" - Tests: {category} {passed}/{total}")

def run_folder_validation_tests():
    global tests_passed
    global tests_failed
    global test_log

    tests_of_validity = 0
    tests_of_validity_passed = 0
    tests_of_invalidity = 0
    tests_of_invalidity_passed = 0

    base_dirs = {
        "valid_ODRL": (
            "test_cases/validation/valid_ODRL",
            True,
        ),
        "invalid_ODRL": (
            "test_cases/validation/invalid_ODRL",
            False,
        ),
        "monitoring_compliant": (
            "test_cases/evaluation/monitoring_compliant",
            True,
        ),
        "monitoring_non_compliant": (
            "test_cases/evaluation/monitoring_non_compliant",
            True,
        ),
        "access_control": (
            "test_cases/evaluation/access_control",
            True,
        ),
    }

    for test_type, (folder, expected_valid_odrl) in base_dirs.items():

        if not os.path.exists(folder):
            print(f"Skipping validation tests: folder does not exist: {folder}")
            continue

        for filename in sorted(os.listdir(folder)):

            filepath = os.path.join(folder, filename)

            # Only validate supported ODRL RDF serializations
            file_format = detect_odrl_file_format(filepath)

            if file_format is None:
                continue

            try:
                validation_result = validate.validate_ODRL_from_file(filepath)

                is_valid_rdf = validation_result.get(
                    "is_valid_RDF",
                    False
                )

                is_valid_odrl = validation_result.get(
                    "is_valid_ODRL",
                    False
                )

                # All files must be valid RDF.
                # ODRL validity depends on which folder the file is in.
                test_ok = (
                    is_valid_rdf is True
                    and is_valid_odrl is expected_valid_odrl
                )

                if test_ok:
                    tests_passed += 1
                    if expected_valid_odrl:
                        tests_of_validity_passed += 1
                        tests_of_validity += 1
                    else:
                        tests_of_invalidity_passed += 1
                        tests_of_invalidity += 1
                else:
                    tests_failed += 1
                    if expected_valid_odrl:
                        tests_of_validity += 1
                    else:
                        tests_of_invalidity += 1

                    test_log.append(
                        f"Failed ODRL validation test for {filepath}: "
                        f"expected is_valid_RDF=True, "
                        f"is_valid_ODRL={expected_valid_odrl}; "
                        f"got is_valid_RDF={is_valid_rdf}, "
                        f"is_valid_ODRL={is_valid_odrl}"
                    )

                    print(
                        f"ODRL validation failed for {filepath}: "
                        f"expected is_valid_RDF=True, "
                        f"is_valid_ODRL={expected_valid_odrl}; "
                        f"got is_valid_RDF={is_valid_rdf}, "
                        f"is_valid_ODRL={is_valid_odrl}"
                    )

            except Exception as e:
                tests_failed += 1

                test_log.append(
                    f"Exception validating ODRL file {filepath}: {e}"
                )

                print(
                    f"\nODRL validation test of {filepath} "
                    f"failed due to exception:"
                )
                print(str(e))

    print("\n\nValidation tests category summary:")
    print(f" - Valid ODRL policies correctly validated: {tests_of_validity_passed}/{tests_of_validity}")
    print(f" - Invalid ODRL policies correctly found to be invalid: {tests_of_invalidity_passed}/{tests_of_invalidity}")


def run_SotW_tests(test_repetitions, test_cases, test_name ):
    global tests_passed
    global tests_failed
    global test_log

    os.makedirs("error_log_files", exist_ok=True)

    def log_failure(pair, expected):
        uid = uuid.uuid4().hex[:8]

        policy_path = f"error_log_files/{uid}_policy.ttl"
        sotw_path = f"error_log_files/{uid}_sotw.csv"
        log_path = f"error_log_files/{uid}_log.txt"

        # Save ODRL graph
        pair[0].serialize(destination=policy_path, format="turtle")

        # Save SotW dataframe
        pair[1].to_csv(sotw_path, index=False)

        # Re-run evaluation once and capture diagnostics
        FEATURE_TYPE_MAP = {f["iri"]: f["type"] for f in extract_features_list_from_policy(pair[0])}
        result = ODRL_Evaluator.evaluate_ODRL_on_dataframe(
            extract_rule_list_from_policy(pair[0]),
            pair[1],
            FEATURE_TYPE_MAP
        )

        with open(log_path, "w", encoding="utf-8") as f:
            f.write("=== ODRL State of the World Evaluation Messages ===\n\n")
            if expected:
                f.write("=== Expected Valid, found Invalid ===\n\n")
            else:
                f.write("=== Expected Invalid, found Valid ===\n\n")
            f.write("Result[1]:\n")
            f.write(str(result[1]))
            f.write("\n\nResult[2]:\n")
            f.write(str(result[2]))
            f.write("\n")

        return uid

    for pair in test_cases["valid_pairs"]:
        FEATURE_TYPE_MAP = {f["iri"]: f["type"] for f in extract_features_list_from_policy(pair[0])}
        if ODRL_Evaluator.evaluate_ODRL_on_dataframe(extract_rule_list_from_policy(pair[0]), pair[1], FEATURE_TYPE_MAP)[1]:
            tests_passed += 1
        else:
            tests_failed += 1
            uid = log_failure(pair, True)
            test_log.append(
                f"Failed {test_name} (should be valid, got invalid) | logged as {uid}"
            )

    for pair in test_cases["invalid_pairs"]:
        FEATURE_TYPE_MAP = {f["iri"]: f["type"] for f in extract_features_list_from_policy(pair[0])}
        if not ODRL_Evaluator.evaluate_ODRL_on_dataframe(extract_rule_list_from_policy(pair[0]), pair[1],FEATURE_TYPE_MAP)[1]:
            tests_passed += 1
        else:
            tests_failed += 1
            uid = log_failure(pair, False)
            test_log.append(
                f"Failed {test_name} (should be invalid, got valid) | logged as {uid}"
            )



def run_folder_evaluation_tests():
    global tests_passed
    global tests_failed
    global test_log

    base_dirs = {
        "valid": "test_cases/evaluation/monitoring_compliant",
        "invalid": "test_cases/evaluation/monitoring_non_compliant"
    }

    # Category statistics
    category_stats = {}
    # Format:
    # {
    #   "category_name": {"passed": int, "total": int}
    # }

    def get_category(txt_path):
        """Return category from second line of txt file."""
        if not os.path.exists(txt_path):
            return "other"

        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if len(lines) >= 2:
                category = lines[1].strip()
                if category:
                    return category

        except Exception:
            pass

        return "other"

    def get_first_line(txt_path):
        """Return first line if exists."""
        if not os.path.exists(txt_path):
            return None

        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                line = f.readline().strip()

            if line:
                return line

        except Exception:
            pass

        return None

    for expected_type, folder in base_dirs.items():

        if not os.path.exists(folder):
            continue

        files = os.listdir(folder)

        base_names = set(
            os.path.splitext(f)[0]
            for f in files
            if f.endswith(".ttl")
        )

        for base in base_names:

            ttl_path = os.path.join(folder, base + ".ttl")
            csv_path = os.path.join(folder, base + ".csv")
            txt_path = os.path.join(folder, base + ".txt")

            display_name = os.path.join(folder, base)

            if not os.path.exists(csv_path):
                print(f"Skipping {display_name}: missing CSV file")
                continue

            # Determine category
            category = get_category(txt_path)

            if category not in category_stats:
                category_stats[category] = {"passed": 0, "total": 0}

            category_stats[category]["total"] += 1

            try:
                #result_list = ODRL_Evaluator.evaluate_ODRL_from_files_streaming(ttl_path, csv_path)
                result_list = timed_evaluation(
                    ODRL_Evaluator.evaluate_ODRL_from_files_streaming,
                    ttl_path,
                    csv_path
                )
                result = result_list[1] #all(r.get("decision") == "ALLOW" for r in result_list)

            except Exception as e:

                tests_failed += 1

                print(f"\nEvaluation test of {display_name} failed due to exception:")
                print(str(e))

                continue

            expected_valid = (expected_type == "valid")

            test_ok = (
                (result and expected_valid)
                or
                ((not result) and (not expected_valid))
            )

            if test_ok:

                tests_passed += 1
                category_stats[category]["passed"] += 1

            else:

                tests_failed += 1

                expectation_str = (
                    "valid"
                    if expected_valid
                    else "invalid"
                )

                print(
                    f"Evaluation test of {base} failed "
                    f"(was expected to be {expectation_str})"
                )

                # Print first line if exists
                first_line = get_first_line(txt_path)

                if first_line:
                    print(first_line)

                test_log.append(
                    f"Failed evaluation test {base} "
                    f"(expected {expectation_str})"
                )

    # ---- CATEGORY SUMMARY ----

    print("\nFolder tests category summary:")

    for category in sorted(category_stats.keys()):

        passed = category_stats[category]["passed"]
        total = category_stats[category]["total"]

        print(f"- Tests: {category} {passed}/{total}")


def runTests(test_repetitions = 0):
    global total_eval_time
    global total_eval_calls

    total_eval_time = 0.0
    total_eval_calls = 0

    global tests_passed
    global tests_failed
    global test_log

    tests_passed = 0
    tests_failed = 0
    test_log = []

    # VALIDATION TESTS

    # validate.generate_ODRL_diagnostic_report("example_policies/example_valid.json")
    # validate.generate_ODRL_diagnostic_report("example_policies/example_invalid.json")
    if validate.diagnose_ODRL("example_policies/example_valid.json")[3]:
        tests_passed += 1
    else:
        tests_failed += 1
        test_log.append("Failed to validate example_policies/example_valid.json as valid")

    if not validate.diagnose_ODRL("example_policies/example_invalid.json")[3]:
        tests_passed += 1
    else:
        tests_failed += 1
        test_log.append("Failed to validate example_policies/example_invalid.json as invalid")

    # Folder-based ODRL validation tests
    run_folder_validation_tests()

    # EVALUATION TESTS

    # evaluation with datetime
    result_list = ODRL_Evaluator.evaluate_ODRL_from_files("example_policies/example_valid3.ttl", "example_policies/sotw_ex3_valid.csv")
    result = result_list[1] #all(r.get("decision") == "ALLOW" for r in result_list)
    if result:
        tests_passed += 1
    else:
        tests_failed += 1
        test_log.append("Failed to evaluate datetime example example_policies/example_valid3.ttl as valid on SotW example_policies/sotw_ex3_valid.csv")

    result_list = ODRL_Evaluator.evaluate_ODRL_from_files("example_policies/example_valid3.ttl", "example_policies/sotw_ex3_invalid.csv")
    result = result_list[1] # all(r.get("decision") == "ALLOW" for r in result_list)
    if not result:
        tests_passed += 1
    else:
        tests_failed += 1
        test_log.append("Failed to evaluate datetime example example_policies/example_valid3.ttl as invalid on SotW example_policies/sotw_ex3_invalid.csv")

    run_SotW_tests(test_repetitions,
                   test_utils.generate_permission_test_cases(test_n = test_repetitions,
                                                             p_rule_n = 4,
                                                             f_rule_n = 0,),
                   "Test of SotW Evaluation for Permissions Only"
                   )

    # Folder-based monitoring evaluation tests
    run_folder_evaluation_tests()

    # Folder-based access control evaluation tests
    run_access_request_evaluation_tests()

    # PRINT SUMMARY

    print(f"\nTOTAL TESTS PASSED {tests_passed}/{tests_passed + tests_failed}")

    for log in test_log:
        print(log)

    if total_eval_calls > 0:
        avg_time = total_eval_time / total_eval_calls
        print(f"\nAverage evaluation time: {avg_time:.6f} seconds over {total_eval_calls} runs")

    if tests_failed > 0:
        exit(1)
    else:
        exit(0)


runTests()