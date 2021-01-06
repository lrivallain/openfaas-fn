import sys, json, os
import yaml
import traceback
import atexit
import requests
from datetime import date
import logging
import base64

from function.logger import init_logger

logger = logging.getLogger(__name__)


### Config location based on ARGO_SECRET_NAME
ARGO_CONFIG="/var/openfaas/secrets/" + os.getenv('ARGO_SECRET_NAME', 'argoconfig')

class ArgoWorflow:
    """The ArgoWorflow provide a way to start an argo WF based on an existing template.
    """

    def __init__(self):
        """Initialize the ArgoWorflow
        """
        logger.info("Reading configuration files")
        logger.info(f"Argo config file > {ARGO_CONFIG}")
        try:
            with open(ARGO_CONFIG, 'r') as configfile:
                argoconfig = yaml.load(configfile, Loader=yaml.SafeLoader)
                # read mandatory parameters
                self.server   = argoconfig['argoserver']['server']
                self.ns       = argoconfig['argoserver']['namespace']
                self.sa       = argoconfig['argoserver']['serviceaccount']
                self.template = argoconfig['argoserver']['template']
        except OSError as err:
            raise Exception(f'Could not read argo configuration: {err}')
        except KeyError as err:
            raise Exception(f'Missing mandatory configuration key: {err}')
        except Exception as err:
            raise Exception(f'Unknown error when reading settings: {err}')
        # read non-mandatory parameters
        self.proto         = argoconfig['argoserver'].get('protocol', 'http')
        self.param_name    = argoconfig['argoserver'].get('event_param_name', 'event')
        self.base64_encode = argoconfig['argoserver'].get('base64_encode', False)
        self.raw_labels    = argoconfig['argoserver'].get('labels', [])
        # set a from:veba label
        self.labels = ["from=veba"]
        # add configured labels
        for label in self.raw_labels:
            self.labels.append(f"{label}={self.raw_labels[label]}")


    def submit(self, event: dict):
        """Submit the workflow

        Args:
            event (dict): event data
        """
        logger.debug("Preparing request data")
        uri = f"{self.proto}://{self.server}/api/v1/workflows/{self.ns}/submit"
        self.labels.append(f"event_id={event.get('id')}")
        self.labels.append(f"event_subject={event.get('subject')}")
        # base64 convertion
        if self.base64_encode:
            event_data = base64.b64encode(
                json.dumps(event).encode('utf-8')
            ).decode()
        else:
            event_data = json.dumps(event)
        # prepare the workflow data
        data = {
            "resourceKind": "WorkflowTemplate",
            "resourceName": self.template,
            "submitOptions": {
                "serviceaccount": self.sa,
                "parameters": [
                    f"{self.param_name}={event_data}"
                ],
                "labels": ','.join(self.labels)
            }
        }
        logger.debug(json.dumps(data, indent=4, sort_keys=True))
        headers = { "Content-Type": "application/json" }
        logger.info("Submiting workflow")
        try:
            r = requests.post(uri, json=data, headers=headers)
            logger.debug(r.text)
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            return f"Invalid status code returned: {r.status_code}"
        except Exception as err:
            return f"Unable to make request to argo server {self.server}: {err}", 500
        return "Argo workflow was successfully submited", 200


def handle(req: str):
    """Main function for this handler

    Args:
        req (str): json content of the cloud event
    """
    init_logger()
    if not os.getenv("write_debug"):
        # decrease log level
        logger.setLevel(logging.INFO)

    # Load the Events that function gets from vCenter through the Event Router
    logger.info("Reading Cloud Event")
    logger.debug(f'Event > {req}')
    try:
        cevent = json.loads(req)
    except json.JSONDecodeError as err:
        return f'Invalid JSON > JSONDecodeError: {err}', 500

    logger.info("Validating Input data")
    logger.debug(f'Event (json) > {json.dumps(cevent, indent=4, sort_keys=True)}')

    try:
        # CloudEvent - simple validation of incoming data
        id = cevent['id']
        source = cevent['source']
        subject  = cevent['subject']
        data = cevent['data']
    except KeyError as err:
        traceback.print_exc(limit=1, file=sys.stderr)  # providing traceback since it helps debug the exact key that failed
        return f'Invalid JSON, required key not found > KeyError: {err}', 500
    except AttributeError as err:
        traceback.print_exc(limit=1, file=sys.stderr)  # providing traceback since it helps debug the exact key that failed
        return f'Invalid JSON, data not iterable > AttributeError: {err}', 500

    try:
        argo = ArgoWorflow()
    except Exception as err: # error in the ArgoWorflow init
        return str(err), 500

    return argo.submit(cevent)