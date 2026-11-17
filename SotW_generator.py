import os

from rdflib.namespace import RDF
import rdflib
from rdflib.collection import Collection
import rdf_utils
import ODRL_Evaluator
import csv
import random
from datetime import datetime, timedelta, timezone
import pandas as pd
import sys

import policy_normalisation_comparison



ODRL = rdflib.Namespace("http://www.w3.org/ns/odrl/2/")
SOTW = rdflib.Namespace("https://w3id.org/force/sotw#")



sample_actions = [
    "https://example.com#MarketSegmentation",
    "https://example.com#APIconnection",
    "https://example.com#PermissionSetting",
    "https://example.com#LocalDataBackup",
    "https://example.com#UserAuthentication",
    "https://example.com#DataEncryption",
    "https://example.com#ReportGeneration",
    "https://example.com#DataAnalytics",
    "https://example.com#ErrorLogging",
    "https://example.com#UserInterfaceDesign",
    "https://example.com#VersionControl",
    "https://example.com#EventLogging",
    "https://example.com#PaymentProcessing",
    "https://example.com#DataVisualization",
    "https://example.com#FeedbackCollection",
    "https://example.com#APIIntegration",
    "https://example.com#DataMigration",
    "https://example.com#MonitoringDashboard",
    "https://example.com#UserRoleManagement",
    "https://example.com#DataQualityAssessment",
    "https://example.com#AccessControlList",
    "https://example.com#SystemIntegration",
    "https://example.com#SecurityAudit",
    "https://example.com#ResourceAllocation",
    "https://example.com#PrototypeTesting",
    "https://example.com#CustomerDataManagement"
]
sample_parties = [
    "https://example.com#Sarah_Wilson",
    "https://example.com#Michael_Johnson",
    "https://example.com#David_Brown",
    "https://example.com#Emily_Davis",
    "https://example.com#John_Smith",
    "https://example.com#Linda_Garcia",
    "https://example.com#Robert_Lee",
    "https://example.com#Jessica_Martinez",
    "https://example.com#William_Hall",
    "https://example.com#Christina_Thompson",
    "https://example.com#James_Scott",
    "https://example.com#Susan_Bailey",
    "https://example.com#Daniel_Adams",
    "https://example.com#Maria_Walker",
    "https://example.com#David_Allen",
    "https://example.com#Karen_Nelson",
    "https://example.com#Paul_Moore",
    "https://example.com#Patricia_Taylor",
    "https://example.com#Linda_Hernandez",
    "https://example.com#George_Young",
    "https://example.com#Nancy_King",
    "https://example.com#Charles_Wright",
    "https://example.com#Rebecca_Hill",
    "https://example.com#Edward_Green",
    "https://example.com#Angela_Sanchez"
]
sample_assets = [
    "https://example.com#AirQualityDatasetCompressed",
    "https://example.com#CardioMonitoringLogs",
    "https://example.com#SteelProductionIndex2025",
    "https://example.com#StudentPerformanceMetrics",
    "https://example.com#SalesForecastData",
    "https://example.com#InventoryRecords2023",
    "https://example.com#CustomerFeedbackSurveys",
    "https://example.com#ProductReviewsStatistics",
    "https://example.com#WebsiteTrafficLogs",
    "https://example.com#EmployeeEngagementScores",
    "https://example.com#MarketResearchFindings",
    "https://example.com#FinancialPerformanceMetrics",
    "https://example.com#UserActivityLogs",
    "https://example.com#SocialMediaEngagementData",
    "https://example.com#SupplyChainDataAnalytics",
    "https://example.com#WeatherDataDaily",
    "https://example.com#DigitalMarketingMetrics",
    "https://example.com#RetailSalesStatistics",
    "https://example.com#CustomerDemographics",
    "https://example.com#HealthcareOutcomesData",
    "https://example.com#TransportEfficiencyData",
    "https://example.com#UserSatisfactionReports",
    "https://example.com#ECommerceAnalytics2024",
    "https://example.com#AdvertisingPerformanceData",
    "https://example.com#CybersecurityIncidentReports"
]

def generate_pd_state_of_the_world_from_policies(
    odrl_graph: rdflib.Graph,
    number_of_records=100,
    valid=True,
    chance_feature_empty=0.5,
    attempts_for_chosen_validity = 10
):
    features = rdf_utils.extract_features_list_from_policy(odrl_graph)
    policy_list = rdf_utils.extract_rule_list_from_policy(odrl_graph)

    feature_iris = [f["iri"] for f in features]

    dataframe = None

    now = datetime.now()

    chosen_validity_achieved = False

    generation_attempts = 0

    while not chosen_validity_achieved and generation_attempts < attempts_for_chosen_validity:

        generation_attempts += 1
        rows = []

        # PRECOMPUTE invalid rows (10% but min 1)
        if not valid:
            n_invalid = max(1, int(0.10 * number_of_records))
            invalid_indices = set(random.sample(range(number_of_records), n_invalid))
        else:
            invalid_indices = set()

        for i in range(number_of_records):
            if not policy_list:
                continue

            row_should_invert = (i in invalid_indices)
            row = {}

            policy = random.choice(policy_list)
            if not policy["permissions"]:
                continue

            permission_rule = random.choice(policy["permissions"])
            permission_triplets_lists = permission_rule["conditions"] + permission_rule["constraints"]

            # Features that appear in permission rules
            features_with_triplets = [
                feature["iri"]
                for feature in features
                if any(t[0] == feature["iri"] for t in permission_triplets_lists)
            ]

            # Choose 1 feature to invert
            inverted_feature_iri = None
            if row_should_invert and features_with_triplets:
                inverted_feature_iri = random.choice(features_with_triplets)

            for feature in features:
                iri = feature["iri"]
                ftype = feature["type"]

                # Special datetime feature
                if iri == "http://www.w3.org/ns/odrl/2/dateTime":
                    row[iri] = (now - timedelta(minutes=i * 10)).isoformat()
                    continue

                matching_triplets = [t for t in permission_triplets_lists if t[0] == iri]
                invert_condition = (iri == inverted_feature_iri)

                if matching_triplets:
                    _, op, val = random.choice(matching_triplets)

                    # INT
                    try:
                        val_int = int(val)
                        if (op == "http://www.w3.org/ns/odrl/2/eq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/neq" and invert_condition):
                            row[iri] = val_int
                        elif (op == "http://www.w3.org/ns/odrl/2/neq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/eq" and invert_condition):
                            row[iri] = val_int + random.randint(1, 100)
                        elif (op == "http://www.w3.org/ns/odrl/2/lt" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/gteq" and invert_condition):
                            row[iri] = val_int - random.randint(1, 100)
                        elif (op == "http://www.w3.org/ns/odrl/2/lteq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/gt" and invert_condition):
                            row[iri] = val_int - random.randint(0, 100)
                        elif (op == "http://www.w3.org/ns/odrl/2/gt" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/lteq" and invert_condition):
                            row[iri] = val_int + random.randint(1, 100)
                        elif (op == "http://www.w3.org/ns/odrl/2/gteq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/lt" and invert_condition):
                            row[iri] = val_int + random.randint(0, 100)
                        else:
                            row[iri] = val_int
                        continue
                    except ValueError:
                        pass

                    # FLOAT
                    try:
                        val_float = float(val)
                        if (op == "http://www.w3.org/ns/odrl/2/eq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/neq" and invert_condition):
                            row[iri] = val_float
                        elif (op == "http://www.w3.org/ns/odrl/2/neq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/eq" and invert_condition):
                            row[iri] = val_float + random.uniform(1, 100)
                        elif (op == "http://www.w3.org/ns/odrl/2/lt" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/gteq" and invert_condition):
                            row[iri] = val_float - random.uniform(1, 100)
                        elif (op == "http://www.w3.org/ns/odrl/2/lteq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/gt" and invert_condition):
                            row[iri] = val_float - random.uniform(0, 100)
                        elif (op == "http://www.w3.org/ns/odrl/2/gt" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/lteq" and invert_condition):
                            row[iri] = val_float + random.uniform(1, 100)
                        elif (op == "http://www.w3.org/ns/odrl/2/gteq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/lt" and invert_condition):
                            row[iri] = val_float + random.uniform(0, 100)
                        else:
                            row[iri] = val_float
                        continue
                    except ValueError:
                        pass

                    # STRING fallback
                    if (op == "http://www.w3.org/ns/odrl/2/eq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/neq" and invert_condition):
                        row[iri] = val
                    elif (op == "http://www.w3.org/ns/odrl/2/neq" and not invert_condition) or (op == "http://www.w3.org/ns/odrl/2/eq" and invert_condition):
                        row[iri] = f"https://example.com/iri/sotw#{random.randint(1, 100000)}"
                    else:
                        row[iri] = ""

                else:
                    # No rule → random or empty
                    if random.random() < chance_feature_empty:
                        row[iri] = ""
                    else:
                        if iri == "http://www.w3.org/ns/odrl/2/Party":
                            row[iri] = random.choice(sample_parties)
                        elif iri == "http://www.w3.org/ns/odrl/2/Action":
                            row[iri] = random.choice(sample_actions)
                        elif iri == "http://www.w3.org/ns/odrl/2/Asset":
                            row[iri] = random.choice(sample_assets)
                        elif ftype == "http://www.w3.org/ns/shacl#IRI":
                            row[iri] = f"https://example.com/iri/sotw#{random.randint(1, 100)}"
                        else:
                            row[iri] = random.randint(0, 100)

            rows.append(row)
        dataframe = pd.DataFrame(rows, columns=feature_iris)

        chosen_validity_achieved = ODRL_Evaluator.evaluate_ODRL_graph_on_dataframe(odrl_graph,dataframe)[1] == valid

    return dataframe, chosen_validity_achieved


def generate_state_of_the_world_from_policies(
    odrl_graph: rdflib.Graph,
    number_of_records=100,
    valid=True,
    chance_feature_empty=0.5,
    csv_file="sotw.csv"
):
    df, validity_achieved = generate_pd_state_of_the_world_from_policies(
        odrl_graph,
        number_of_records=number_of_records,
        valid=valid,
        chance_feature_empty=chance_feature_empty
    )

    df.to_csv(csv_file, index=False, encoding="utf-8")
    return df, validity_achieved


    #print(f"CSV file '{csv_file}' generated with {len(rows)} rows and {len(feature_iris)} columns.")


def generate_state_of_the_world_from_policies_from_file(
        file_path,
        number_of_records=100,
        valid=True,
        chance_feature_empty=0.5,
        csv_file="sotw.csv"
    ):
    g = rdf_utils.load(file_path)[0]
    return generate_state_of_the_world_from_policies(g, number_of_records, valid, chance_feature_empty, csv_file)

def translate_csv_to_solid_syntax(csv_file, destination_file="translated_sotw.ttl"):
    df = pd.read_csv(csv_file)
    rdf_graph = rdflib.Graph()
    sotw_node = rdflib.URIRef("https://example.com/iri/sotw")
    rdf_graph.add((sotw_node, RDF.type, SOTW.SotW))
    for i, row in df.iterrows():
        evaluation_node = rdflib.URIRef(f"https://example.com/iri/sotw#{i}")
        rdf_graph.add((sotw_node, SOTW.context, evaluation_node))
        rdf_graph.add((rdflib.URIRef(evaluation_node), RDF.type, SOTW.EvaluationRequest))
        for col, val in zip(df.columns, row):
            if not pd.isnull(val):
                if col == "http://www.w3.org/ns/odrl/2/dateTime":
                    rdf_graph.add((rdflib.URIRef(evaluation_node), rdflib.URIRef("http://purl.org/dc/terms/issued"), rdflib.Literal(val, datatype=rdflib.XSD.dateTime)))
                elif col == "http://www.w3.org/ns/odrl/2/Party":
                    rdf_graph.add((rdflib.URIRef(evaluation_node), SOTW.evaluatedParty, rdflib.URIRef(val)))
                elif col == "http://www.w3.org/ns/odrl/2/Action": 
                    rdf_graph.add((rdflib.URIRef(evaluation_node), SOTW.evaluatedAction, rdflib.URIRef(val)))
                elif col == "http://www.w3.org/ns/odrl/2/Asset":
                    rdf_graph.add((rdflib.URIRef(evaluation_node), SOTW.evaluatedTarget, rdflib.URIRef(val)))
                else:
                    blank_node = rdflib.BNode()
                    rdf_graph.add((rdflib.URIRef(evaluation_node), SOTW.requestParameter, blank_node))
                    rdf_graph.add((blank_node, RDF.type, SOTW.RequestParameter))
                    if len(col.split()) > 1:
                        prefix, feature_iri = col.split(" ", 1)
                        if prefix in ["http://www.w3.org/ns/odrl/2/Party", "http://www.w3.org/ns/odrl/2/Action", "http://www.w3.org/ns/odrl/2/Asset"]:
                            rdf_graph.add((blank_node, SOTW.describesFeature, rdflib.URIRef(feature_iri)))
                            rdf_graph.add((blank_node, SOTW.value, rdflib.Literal(val)))
                        else:
                            rdf_graph.add((blank_node, SOTW.describesFeature, rdflib.URIRef(feature_iri)))
                            rdf_graph.add((blank_node, SOTW.value, rdflib.Literal(val)))
                    else:
                        rdf_graph.add((blank_node, SOTW.describesFeature, rdflib.URIRef(col)))
                        rdf_graph.add((blank_node, SOTW.value, rdflib.Literal(val)))
    rdf_graph.serialize(destination=destination_file, format="turtle")

# Example usage
#file_path = "example_policies/GATE_Policy_Test.jsonld"
#g = rdf_utils.load(file_path)[0]
#print(g.serialize(format="turtle"))
#print(*extract_features_list_from_policy_from_file(file_path), sep ="\n")
#print("\nPolicies with rules:")
#print(*extract_rule_list_from_policy_from_file(file_path), sep="\n")
#from pprint import pprint
#pprint(
#    extract_rule_list_from_policy_from_file(file_path),
#    sort_dicts=False,
#    width=120
#)

#csv = generate_state_of_the_world_from_policies_from_file(file_path, number_of_records=50, chance_feature_empty=0.3)

#print(csv)
#translate_csv_to_solid_syntax("test_cases/evaluation/monitoring_compliant/test1.csv")
