import sys, json, os
import yaml
import traceback
import atexit
from datetime import date
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl
import ssl


### Config location
VC_CONFIG='/var/openfaas/secrets/' + os.getenv('VC_SECRET_NAME', 'vcconfig')


### Debuging
DEBUG = False
class bgc:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

if(os.getenv("write_debug")):
    sys.stderr.write(
        f"""{bgc.WARNING}WARNING!! DEBUG has been enabled for this function.
        Sensitive information could be printed to sysout{bgc.ENDC} \n"""
    )
    DEBUG = True

def debug(s):
    if DEBUG:
        sys.stderr.write(s + " \n")  # Syserr only get logged on the console logs
        sys.stderr.flush()


class Setter:
    """Setter is a client to set custom attributes to newly created VM.
    """

    def __init__(self):
        """Setter is a client to set custom attributes to newly created VM.
        """
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        debug(f'{bgc.HEADER}Reading Configuration files: {bgc.ENDC}')
        debug(f'{bgc.OKBLUE}VC Config File > {bgc.ENDC}{VC_CONFIG}')
        try:
            with open(VC_CONFIG, 'r') as configfile:
                vcconfig = yaml.load(configfile, Loader=yaml.SafeLoader)
                if not vcconfig['vcenter']['ssl_verify']:
                    self.ssl_context.verify_mode = ssl.CERT_NONE
                self.host = vcconfig['vcenter']['server']
                self.user = vcconfig['vcenter']['user']
                self.pwd  = vcconfig['vcenter']['password']
                self.attr_owner = vcconfig['attributes']['owner']
                self.attr_creation_date = vcconfig['attributes']['creation_date']
                self.attr_last_poweredon = vcconfig['attributes']['last_poweredon']
        except OSError as err:
            raise Exception(f'Could not read vcenter configuration: {err}')
        except KeyError as err:
            raise Exception(f'Missing mandatory configuration key: {err}')
        except Exception as err:
            raise Exception(f'Unknown error when reading settings: {err}')

        debug(f'{bgc.OKBLUE}Initialising vCenter connection...{bgc.ENDC}')
        try:
            self.service_instance = SmartConnect(
                host = self.host,
                user = self.user,
                pwd  = self.pwd,
                port = 443,
                sslContext = self.ssl_context
            )
            atexit.register(Disconnect, self.service_instance)
        except IOError as err:
            raise Exception(f'Error connecting to vCenter: {err}')
        except Exception as err:
            raise Exception(f'Unknown error when creating vsphere session: {err}')


def handle(req):
    """Main function for this handler

    Args:
        req (str): json content of the cloud event
    """
    # Load the Events that function gets from vCenter through the Event Router
    debug(f'{bgc.HEADER}Reading Cloud Event: {bgc.ENDC}')
    debug(f'{bgc.OKBLUE}Event > {bgc.ENDC}{req}')
    try:
        cevent = json.loads(req)
    except json.JSONDecodeError as err:
        return f'Invalid JSON > JSONDecodeError: {err}', 500

    debug(f'{bgc.HEADER}Validating Input data: {bgc.ENDC}')
    debug(f'{bgc.OKBLUE}Event > {bgc.ENDC}{json.dumps(cevent, indent=4, sort_keys=True)}')
    try:
        # CloudEvent - simple validation
        ref_vm = cevent['data']['Vm']['Vm']
        ref_user = cevent['data']['UserName']
        subject = cevent['subject']
    except KeyError as err:
        traceback.print_exc(limit=1, file=sys.stderr)  # providing traceback since it helps debug the exact key that failed
        return f'Invalid JSON, required key not found > KeyError: {err}', 500
    except AttributeError as err:
        traceback.print_exc(limit=1, file=sys.stderr)  # providing traceback since it helps debug the exact key that failed
        return f'Invalid JSON, data not iterable > AttributeError: {err}', 500

    # Initialise a connection to vCenter
    debug(f'{bgc.HEADER}Connecting to the vCenter{bgc.ENDC}')
    try:
        res = Setter()
    except Exception as err: # error in the setter init
        return str(err), 500
    vcinfo = res.service_instance.RetrieveServiceContent().about
    debug(f'Connected to {vcinfo.fullName} ({vcinfo.instanceUuid})')

    content = res.service_instance.RetrieveContent()

    # Lookup for custom attributes
    attr_owner, attr_creation_date, attr_last_poweredon = None, None, None
    cfmgr = res.service_instance.content.customFieldsManager
    for field in cfmgr.field:
        if field.name == res.attr_owner:
            attr_owner = field
        if field.name == res.attr_creation_date:
            attr_creation_date = field
        if field.name == res.attr_last_poweredon:
            attr_last_poweredon = field
    if not (attr_owner and attr_creation_date and attr_last_poweredon):
        return f'Missing attribute for owner or creation_date', 500

    # List and iter on VMs objects
    objView = content.viewManager.CreateContainerView(
        content.rootFolder,
        [vim.VirtualMachine],
        True
    )
    vmList = objView.view
    objView.Destroy()
    for vm in vmList:
        if vm._moId == ref_vm['Value']:
            debug(f'{bgc.HEADER}VM found{bgc.ENDC}')
            debug(f'{bgc.OKBLUE}VM Name> {bgc.ENDC}{vm.name}')

            if subject in ["DrsVmPoweredOnEvent", "VmPoweredOnEvent", "VmPoweringOnWithCustomizedDVPortEvent"]:
                debug(f'{bgc.OKBLUE}Apply attribute > {bgc.ENDC}{attr_last_poweredon.name}')
                cfmgr.SetField(entity=vm, key=attr_last_poweredon.key,
                    value=date.today().strftime("%d/%m/%Y")
                )

            if subject in ["VmCreatedEvent", "VmClonedEvent", "VmRegisteredEvent"]:
                debug(f'{bgc.OKBLUE}Apply attribute > {bgc.ENDC}{attr_owner.name}')
                cfmgr.SetField(entity=vm, key=attr_owner.key, value=ref_user)

                debug(f'{bgc.OKBLUE}Apply attribute > {bgc.ENDC}{attr_creation_date.name}')
                cfmgr.SetField(entity=vm, key=attr_creation_date.key,
                    value=date.today().strftime("%d/%m/%Y")
                )

            return 'Custom attributes were successfully applied', 200
    return f'Missing virtual machine to apply custom attributes', 404
