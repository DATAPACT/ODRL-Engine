# =========================================================
# CONCEPT BLUEPRINT
# =========================================================
#
#   "concepts" must be a list, even if there is only one
#   concept.
#
# =========================================================

concepts = [
    {
        "name": "Action",
        "background": "#FFF9C4",
        "fields": [
            {
                "type": "classes",
                "class_list": [
                    "odrl:Action"
                ],
            },
            {
                "type": "ID",
                "mandatory": 1,
            },
            {
                "type": "IRI_selection",
                "text_label": "More general type of action",
                "text_relations": [
                    "odrl:includedIn"
                ],
                "concept_references": [
                    "Action"
                ],
                "concept_query": """
                    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

                    SELECT DISTINCT ?x ?l
                    WHERE {
                        {
                            ?x odrl:includedIn ?y .
                        }
                        UNION
                        {
                            ?y odrl:includedIn ?x .
                        }
                        OPTIONAL {
                            ?x rdfs:label ?l .
                        }
                    }
                """,
                "mandatory": 1,
            },
            {
                "type": "text",
                "text_label": "Label",
                "text_info": (
                    "Add a short human readable name "
                    "for this concept"
                ),
                "text_relations": [
                    "rdfs:label"
                ],
                "mandatory": 0,
            },
            {
                "type": "text_area",
                "text_label": "Description",
                "text_info": (
                    "Add a longer description "
                    "for this concept"
                ),
                "text_relations": [
                    "rdfs:comment"
                ],
                "mandatory": 0,
            },
        ],
    },
    {
        "name": "Party",
        "background": "#FFDAB9",
        "fields": [
            {
                "type": "classes",
                "class_list": [
                    "odrl:Party"
                ],
            },
            {
                "type": "ID",
                "mandatory": 1,
            },
            {
                "type": "IRI_selection",
                "text_label": "More general type of Party",
                "text_relations": [
                    "odrl:partOf"
                ],
                "concept_references": [
                    "Party"
                ],
                "concept_query": """
                    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

                    SELECT DISTINCT ?x ?l
                    WHERE {
                        {
                            ?x odrl:partOf ?y .
                        }
                        UNION
                        {
                            ?y odrl:partOf ?x .
                        }
                        OPTIONAL {
                            ?x rdfs:label ?l .
                        }
                    }
                """,
                "mandatory": 0,
            },
            {
                "type": "text",
                "text_label": "Label",
                "text_info": (
                    "Add a short human readable name "
                    "for this concept"
                ),
                "text_relations": [
                    "rdfs:label"
                ],
                "mandatory": 0,
            },
            {
                "type": "text_area",
                "text_label": "Description",
                "text_info": (
                    "Add a longer description "
                    "for this concept"
                ),
                "text_relations": [
                    "rdfs:comment"
                ],
                "mandatory": 0,
            },
        ],
    },
    {
        "name": "Asset",
        "background": "#ADD8E6",
        "fields": [
            {
                "type": "classes",
                "class_list": [
                    "odrl:Asset"
                ],
            },
            {
                "type": "ID",
                "mandatory": 1,
            },
            {
                "type": "IRI_selection",
                "text_label": "More general type of Asset",
                "text_relations": [
                    "odrl:partOf"
                ],
                "concept_references": [
                    "Asset"
                ],
                "concept_query": """
                    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

                    SELECT DISTINCT ?x ?l
                    WHERE {
                        {
                            ?x odrl:partOf ?y .
                        }
                        UNION
                        {
                            ?y odrl:partOf ?x .
                        }
                        OPTIONAL {
                            ?x rdfs:label ?l .
                        }
                    }
                """,
                "mandatory": 0,
            },
            {
                "type": "text",
                "text_label": "Label",
                "text_info": (
                    "Add a short human readable name "
                    "for this concept"
                ),
                "text_relations": [
                    "rdfs:label"
                ],
                "mandatory": 0,
            },
            {
                "type": "text_area",
                "text_label": "Description",
                "text_info": (
                    "Add a longer description "
                    "for this concept"
                ),
                "text_relations": [
                    "rdfs:comment"
                ],
                "mandatory": 0,
            },
        ],
    },
    {
        "name": "Left Operand",
        "background": "#90EE90",
        "fields": [
            {
                "type": "classes",
                "class_list": [
                    "odrl:LeftOperand"
                ],
            },
            {
                "type": "ID",
                "mandatory": 1,
            },
            {
                "type": "IRI_selection",
                "text_label": "The Asset, Party or Action this Left Operand refines.",
                "text_relations": [
                    "rdfs:domain"
                ],
                "concept_references": [
                    "Asset", "Party", "Action"
                ],
                "concept_query": """
                    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
                    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

                    SELECT DISTINCT ?x ?l
                    WHERE {
                        {
                            ?x odrl:partOf ?y .
                        }
                        UNION
                        {
                            ?y odrl:partOf ?x .
                        }
                        OPTIONAL {
                            ?x rdfs:label ?l .
                        }
                    }
                """,
                "mandatory": 0,
            },
            {
                "type": "text",
                "text_label": "Label",
                "text_info": (
                    "Add a short human readable name "
                    "for this concept"
                ),
                "text_relations": [
                    "rdfs:label"
                ],
                "mandatory": 0,
            },
            {
                "type": "text_area",
                "text_label": "Description",
                "text_info": (
                    "Add a longer description "
                    "for this concept"
                ),
                "text_relations": [
                    "rdfs:comment"
                ],
                "mandatory": 0,
            },
        ],
    }
]