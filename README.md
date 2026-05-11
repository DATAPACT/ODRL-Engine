# Policy Engine (test)

The Policy Engine provides a suite of functionality to inspect, process and use ODRL policies.

## **Main Goal/Functionalities**

Currently the following main functionalities are supported: 

* Visualising an ODRL policy to inspect it
* Validating the correctness of an ODRL policy file against the specification
* Evaluating one or more ODRL policies against a State of the World (like an event log, or a data access request)
* Generating synthetic ODRL policies, and generating synthetic States of the World about policies to be used for testing purposes.

## **How To Install**

### Requirements

Python, rdflib, pyshacl, pandas, matplotlib

## Usage

### Jupiter Notebook Interface

You can easily test the functions of this Policy Engine using the Jupiter Notebook `colab_notebook.ipynb`. This notebook is compatible with Google Colab, and contains instructions on how to use it. 

### Programmatic use

Currently the Policy Engine can be inported as a Python library to use its main functions.

The main functions can be found in the following files (more details in the code):

`validate.py`
* `validate_SHACL`
* `get_ODRL_macro_statistics`
* `describe_ODRL_statistics`
* `diagnose_ODRL`
* `generate_ODRL_diagnostic_report`

`rdf_utils.py`
* `parse_string_to_graph`
* `load`

`ODRL_Evaluator.py`
* `evaluate_ODRL_on_dataframe` core ODRL evaluation function, which takes as inputs an ODRL policy, a state of the world/event stream batch/access request, and optionally a previous saved state of the evaluation json object (this last parameter is only needed in online/stream evaluation) 
* `evaluate_ODRL_from_files` wrapper of the function above, which loads the inputs from files instead of using in-memory objects
* `evaluate_ODRL_from_files_merge_policies` utility function that allows for the processing of multiple policies at once, by merging their rules into a single policy
* `evaluate_ODRL_from_files_streaming` variant test function, that simulates streaming of events by breaking down a single large state of the world into multiple batches, by default containing 1 event each, and evaluates them sequentially 

`ODRL_generator.py`
* `generate_ODRL`

`SotW_generator.py`
* `extract_features_list_from_policy`
* `extract_rule_list`
* `extract_rule_list_from_policy`
* `extract_rule_list_from_policy_from_file`
* `generate_pd_state_of_the_world_from_policies`
* `generate_state_of_the_world_from_policies`
* `extract_features_list_from_policy_from_file`
* `generate_state_of_the_world_from_policies_from_file`

## Internal JSON data model

For ease of computation, ODRL rules are converted internally to a simplified JSON format.

For example, the following ODRL policy (adapted from an example in the ODRL 2.2 specification):

```
{
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "Agreement",
    "uid": "http://example.com/policy:66",
    "profile": "http://example.com/odrl:profile:09",
    "permission": [{
        "target": "http://example.com/data:77",
        "assigner": "http://example.com/org:99",
        "assignee": "http://example.com/person:88",
        "action": "distribute",
		"constraint": [{
           "leftOperand": "dateTime",
           "operator": "gt",
           "rightOperand":  { "@value": "2018-01-01", "@type": "xsd:date" }
       }],
        "duty": [{
            "action": "attribute",
            "attributedParty": "http://australia.gov.au/",
				"constraint": [{
			   "leftOperand": "dateTime",
			   "operator": "lt",
			   "rightOperand":  { "@value": "2028-01-01", "@type": "xsd:date" }
		   }],
            "consequence": [{
               "action": "acceptTracking",
               "trackingParty": "http://example.com/dept:100",
			   "constraint": [{
				   "leftOperand": "dateTime",
				   "operator": "lt",
				   "rightOperand":  { "@value": "2030-01-01", "@type": "xsd:date" }
			   }]
            },
			{
               "action": "acceptTracking",
               "trackingParty": "http://example.com/dept:120",
			   "constraint": [{
				   "leftOperand": "dateTime",
				   "operator": "lt",
				   "rightOperand":  { "@value": "2030-01-01", "@type": "xsd:date" }
			   }]
            }
			]
        }]
    }]
}
```

Is encoded in the following object:

```
[{'policy_iri': 'http://example.com/policy:66',
  'permissions': [{'conditions': [['http://www.w3.org/ns/odrl/2/Party', '=', 'http://example.com/person:88'],
                                  ['http://www.w3.org/ns/odrl/2/Action', '=', 'http://www.w3.org/ns/odrl/2/distribute'],
                                  ['http://www.w3.org/ns/odrl/2/Asset', '=', 'http://example.com/data:77'],
                                  ['http://www.w3.org/ns/odrl/2/dateTime', '>', '2018-01-01']],
                   'duties': [{'conditions': [['http://www.w3.org/ns/odrl/2/Action',
                                               '=',
                                               'http://www.w3.org/ns/odrl/2/attribute'],
                                              ['http://www.w3.org/ns/odrl/2/dateTime', '<', '2028-01-01']],
                               'consequences': [{'conditions': [['http://www.w3.org/ns/odrl/2/Action',
                                                                 '=',
                                                                 'http://www.w3.org/ns/odrl/2/acceptTracking'],
                                                                ['http://www.w3.org/ns/odrl/2/dateTime',
                                                                 '<',
                                                                 '2030-01-01']]},
                                                {'conditions': [['http://www.w3.org/ns/odrl/2/Action',
                                                                 '=',
                                                                 'http://www.w3.org/ns/odrl/2/acceptTracking'],
                                                                ['http://www.w3.org/ns/odrl/2/dateTime',
                                                                 '<',
                                                                 '2030-01-01']]}]}]}],
  'prohibitions': [],
  'obligations': []}]
```

## How to test for correctness

To test, run the `test.py` script. After the tests are run, the output of the tests will be print to console. 

The main test routine checks each main feature of the evaluator against curated test cases, and outputs the number of 
tests passed, along with the average time for evaluation. It also tests the streaming capabilities of the evaluator
by using simulating streaming using the `evaluate_ODRL_from_files_streaming` function.

### How to add evaluation tests

To add an evaluation test, create the following files, where X is a filename of your choosing 
(make sure this name is unique in the folder you will copy them in):
* `X.ttl` (a Turtle file containing a single ODRL policy)
* `X.csv` (a State of the World)
* `X.txt` (optional file, with information about the test)

If this is a test that should result in a "valid" output (if the ODRL policy in X.ttl is valid in State of the World X.csv) 
place the files under `test_cases\evaluation\valid`, 
otherwise under `test_cases\evaluation\invalid`.

Tests placed here will be run automatically when `test.py` is run.

In the X.txt file you can optionally add additional information about your test:
* First line: you can add here a message describing the test, which will be printed if the test fails
* Second line: you can add here a single keyword, to group similar types of tests together. The test output will show a breakdown for each keyword.

## How to perform scalability tests

Scalability tests can be run using the `scalability_tests.py` function.
