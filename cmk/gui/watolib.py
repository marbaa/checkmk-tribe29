#!/usr/bin/python
# -*- encoding: utf-8; py-indent-offset: 4 -*-
# +------------------------------------------------------------------+
# |             ____ _               _        __  __ _  __           |
# |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
# |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
# |           | |___| | | |  __/ (__|   <    | |  | | . \            |
# |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
# |                                                                  |
# | Copyright Mathias Kettner 2014             mk@mathias-kettner.de |
# +------------------------------------------------------------------+
#
# This file is part of Check_MK.
# The official homepage is at http://mathias-kettner.de/check_mk.
#
# check_mk is free software;  you can redistribute it and/or modify it
# under the  terms of the  GNU General Public License  as published by
# the Free Software Foundation in version 2.  check_mk is  distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
# out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
# PARTICULAR PURPOSE. See the  GNU General Public License for more de-
# tails. You should have  received  a copy of the  GNU  General Public
# License along with GNU Make; see the file  COPYING.  If  not,  write
# to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
# Boston, MA 02110-1301 USA.

# WATO LIBRARY
#
# This file contains classes, functions and globals that are being
# used by WATO. It does not contain any acutal page handlers or
# WATO modes. Nor complex HTML creation. This is all contained
# in wato.py

#   .--Initialization------------------------------------------------------.
#   |                           ___       _ _                              |
#   |                          |_ _|_ __ (_) |_                            |
#   |                           | || '_ \| | __|                           |
#   |                           | || | | | | |_                            |
#   |                          |___|_| |_|_|\__|                           |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Doing this that must be done when the module WATO is loaded.        |
#   '----------------------------------------------------------------------'

import re
import os
import shutil
import subprocess
import base64
import pickle
import pwd
import pprint
import glob
import traceback
import ast
import multiprocessing
import tarfile
import cStringIO
import requests
import copy
import socket
import time
import threading
from hashlib import sha256
from pathlib2 import Path

try:
    # does not exist in Py3, but is super class of str & unicode in py2
    basestring
except NameError:
    basestring = str  # pylint: disable=redefined-builtin
    unicode = str  # pylint: disable=redefined-builtin

import cmk.daemon as daemon
import cmk.paths
import cmk.defines
import cmk.utils
import cmk.store as store
import cmk.render as render
import cmk.ec.defaults
import cmk.ec.export
import cmk.regex
import cmk.plugin_registry

import cmk.gui.utils as utils
import cmk.gui.config as config
import cmk.gui.hooks as hooks
import cmk.gui.userdb as userdb
import cmk.gui.multitar as multitar
import cmk.gui.sites as sites
import cmk.gui.mkeventd as mkeventd
import cmk.gui.backup as backup
import cmk.gui.log as log
import cmk.gui.background_job as background_job
import cmk.gui.gui_background_job as gui_background_job
import cmk.gui.weblib as weblib
from cmk.gui.i18n import _u, _
from cmk.gui.globals import html
from cmk.gui.htmllib import HTML
from cmk.gui.log import logger
from cmk.gui.exceptions import MKGeneralException, MKAuthException, MKUserError
from cmk.gui.valuespec import (
    Dictionary,
    Integer,
    ListOfStrings,
    IPv4Network,
    Checkbox,
    Transform,
    DropdownChoice,
    ListOf,
    EmailAddressUnicode,
    DualListChoice,
    UserID,
    FixedValue,
    Alternative,
    CascadingDropdown,
    TextAscii,
    TextUnicode,
    TextAreaUnicode,
    ValueSpec,
    ListChoice,
    Float,
    Foldable,
    Tuple,
    Age,
    RegExp,
)

if cmk.is_managed_edition():
    import cmk.gui.cme.managed as managed

#.
#   .--Constants-----------------------------------------------------------.
#   |              ____                _              _                    |
#   |             / ___|___  _ __  ___| |_ __ _ _ __ | |_ ___              |
#   |            | |   / _ \| '_ \/ __| __/ _` | '_ \| __/ __|             |
#   |            | |__| (_) | | | \__ \ || (_| | | | | |_\__ \             |
#   |             \____\___/|_| |_|___/\__\__,_|_| |_|\__|___/             |
#   |                                                                      |
#   '----------------------------------------------------------------------'

# Constants used in configuration files
ALL_HOSTS = ['@all']
ALL_SERVICES = [""]
NEGATE = '@negate'
NO_ITEM = {}  # Just an arbitrary unique thing
ENTRY_NEGATE_CHAR = "!"

# Some paths and directories
wato_root_dir = cmk.paths.check_mk_config_dir + "/wato/"
multisite_dir = cmk.paths.default_config_dir + "/multisite.d/wato/"
sites_mk = cmk.paths.default_config_dir + "/multisite.d/sites.mk"
var_dir = cmk.paths.var_dir + "/wato/"
audit_log_path = var_dir + "log/audit.log"
snapshot_dir = var_dir + "snapshots/"
php_api_dir = var_dir + "php-api/"
# TODO: Move this to CEE specific code again
liveproxyd_config_dir = cmk.paths.default_config_dir + "/liveproxyd.d/wato/"

# Directories and files to synchronize during replication
replication_paths = [
    ("dir", "check_mk", wato_root_dir, ["sitespecific.mk"]),
    ("dir", "multisite", multisite_dir, ["sitespecific.mk"]),
    ("file", "htpasswd", cmk.paths.htpasswd_file),
    ("file", "auth.secret", '%s/auth.secret' % os.path.dirname(cmk.paths.htpasswd_file)),
    ("file", "auth.serials", '%s/auth.serials' % os.path.dirname(cmk.paths.htpasswd_file)),
    # Also replicate the user-settings of Multisite? While the replication
    # as such works pretty well, the count of pending changes will not
    # know.
    ("dir", "usersettings", cmk.paths.var_dir + "/web"),
    ("dir", "mkps", cmk.paths.var_dir + "/packages"),
    ("dir", "local", cmk.paths.omd_root + "/local"),
]

# TODO: Move this to CEE specific code again
if not cmk.is_raw_edition():
    replication_paths += [
        ("dir", "liveproxyd", liveproxyd_config_dir, ["sitespecific.mk"]),
    ]

# Directories and files for backup & restore
backup_paths = replication_paths[:] + [
    ("file", "sites", sites_mk),
]

# Include rule configuration into backup/restore/replication. Current
# status is not backed up.
if config.mkeventd_enabled:
    _rule_pack_dir = str(cmk.ec.export.rule_pack_dir())
    replication_paths.append(("dir", "mkeventd", _rule_pack_dir, ["sitespecific.mk"]))
    backup_paths.append(("dir", "mkeventd", _rule_pack_dir))

    _mkp_rule_pack_dir = str(cmk.ec.export.mkp_rule_pack_dir())
    replication_paths.append(("dir", "mkeventd_mkp", _mkp_rule_pack_dir))
    backup_paths.append(("dir", "mkeventd_mkp", _mkp_rule_pack_dir))

backup_domains = {}
automation_commands = {}
g_rulespecs = None
g_rulegroups = {}

# Global datastructure holding all attributes (in a defined order)
# as pairs of (attr, topic). Topic is the title under which the
# attribute is being displayed. All builtin attributes use the
# topic None. As long as only one topic is used, no topics will
# be displayed. They are useful if you have a great number of
# custom attributes.
# TODO: Cleanup this duplicated data structure into a single one.
g_host_attributes = []

# Dictionary for quick access
g_host_attribute = {}


def load_watolib_plugins():
    utils.load_web_plugins("watolib", globals())


# TODO: Must only be unlocked when it was not locked before. We should find a more
# robust way for doing something like this. If it is locked before, it can now happen
# that this call unlocks the wider locking when calling this funktion in a wrong way.
def init_wato_datastructures(with_wato_lock=False):
    init_watolib_datastructures()
    if os.path.exists(ConfigDomainCACertificates.trusted_cas_file) and\
        not _need_to_create_sample_config():
        return

    if with_wato_lock:
        lock_exclusive()

    if not os.path.exists(ConfigDomainCACertificates.trusted_cas_file):
        ConfigDomainCACertificates().activate()

    _create_sample_config()

    if with_wato_lock:
        unlock_exclusive()


# TODO: Create a hook here and move CEE and other specific things away
def _create_sample_config():
    """Create a very basic sample configuration

    But only if none of the
    files that we will create already exists. That is e.g. the case
    after an update from an older version where no sample config had
    been created.
    """
    if not _need_to_create_sample_config():
        return

    # Just in case. If any of the following functions try to write Git messages
    if config.wato_use_git:
        prepare_git_commit()

    # Global configuration settings
    save_global_settings({
        "use_new_descriptions_for": [
            "df",
            "df_netapp",
            "df_netapp32",
            "esx_vsphere_datastores",
            "hr_fs",
            "vms_diskstat.df",
            "zfsget",
            "ps",
            "ps.perf",
            "wmic_process",
            "services",
            "logwatch",
            "logwatch.groups",
            "cmk-inventory",
            "hyperv_vms",
            "ibm_svc_mdiskgrp",
            "ibm_svc_system",
            "ibm_svc_systemstats.diskio",
            "ibm_svc_systemstats.iops",
            "ibm_svc_systemstats.disk_latency",
            "ibm_svc_systemstats.cache",
            "casa_cpu_temp",
            "cmciii.temp",
            "cmciii.psm_current",
            "cmciii_lcp_airin",
            "cmciii_lcp_airout",
            "cmciii_lcp_water",
            "etherbox.temp",
            "liebert_bat_temp",
            "nvidia.temp",
            "ups_bat_temp",
            "innovaphone_temp",
            "enterasys_temp",
            "raritan_emx",
            "raritan_pdu_inlet",
            "mknotifyd",
            "mknotifyd.connection",
            "postfix_mailq",
            "nullmailer_mailq",
            "barracuda_mailqueues",
            "qmail_stats",
            "http",
            "mssql_backup",
            "mssql_counters.cache_hits",
            "mssql_counters.transactions",
            "mssql_counters.locks",
            "mssql_counters.sqlstats",
            "mssql_counters.pageactivity",
            "mssql_counters.locks_per_batch",
            "mssql_counters.file_sizes",
            "mssql_databases",
            "mssql_datafiles",
            "mssql_tablespaces",
            "mssql_transactionlogs",
            "mssql_versions",
        ],
        "enable_rulebased_notifications": True,
        "ui_theme": "facelift",
    })

    # A contact group for all hosts and services
    groups = {
        "contact": {
            'all': {
                'alias': u'Everything'
            }
        },
    }
    save_group_information(groups)

    # Basic setting of host tags
    wato_host_tags = \
    [('criticality',
      u'Criticality',
      [('prod', u'Productive system', []),
       ('critical', u'Business critical', []),
       ('test', u'Test system', []),
       ('offline', u'Do not monitor this host', [])]),
     ('networking',
      u'Networking Segment',
      [('lan', u'Local network (low latency)', []),
       ('wan', u'WAN (high latency)', []),
       ('dmz', u'DMZ (low latency, secure access)', [])]),
    ]

    wato_aux_tags = []

    save_hosttags(wato_host_tags, wato_aux_tags)

    # Rules that match the upper host tag definition
    ruleset_config = {
        # Make the tag 'offline' remove hosts from the monitoring
        'only_hosts': [(['!offline'], ['@all'], {
            'description': u'Do not monitor hosts with the tag "offline"'
        }),],

        # Rule for WAN hosts with adapted PING levels
        'ping_levels': [({
            'loss': (80.0, 100.0),
            'packets': 6,
            'rta': (1500.0, 3000.0),
            'timeout': 20
        }, ['wan'], ['@all'], {
            'description': u'Allow longer round trip times when pinging WAN hosts'
        }),],

        # All hosts should use SNMP v2c if not specially tagged
        'bulkwalk_hosts': [(['snmp', '!snmp-v1'], ['@all'], {
            'description': u'Hosts with the tag "snmp-v1" must not use bulkwalk'
        }),],

        # Put all hosts and the contact group 'all'
        'host_contactgroups': [('all', [], ALL_HOSTS, {
            'description': u'Put all hosts into the contact group "all"'
        }),],

        # Interval for HW/SW-Inventory check
        'extra_service_conf': {
            'check_interval': [(1440, [], ALL_HOSTS, ["Check_MK HW/SW Inventory$"], {
                'description': u'Restrict HW/SW-Inventory to once a day'
            }),],
        },

        # Disable unreachable notifications by default
        'extra_host_conf': {
            'notification_options': [('d,r,f,s', [], ALL_HOSTS, {}),],
        },

        # Periodic service discovery
        'periodic_discovery': [({
            'severity_unmonitored': 1,
            'severity_vanished': 0,
            'inventory_check_do_scan': True,
            'check_interval': 120.0
        }, [], ALL_HOSTS, {
            'description': u'Perform every two hours a service discovery'
        }),],
    }

    rulesets = FolderRulesets(Folder.root_folder())
    rulesets.from_config(Folder.root_folder(), ruleset_config)
    rulesets.save()

    notification_rules = [
        {
            'allow_disable': True,
            'contact_all': False,
            'contact_all_with_email': False,
            'contact_object': True,
            'description': 'Notify all contacts of a host/service via HTML email',
            'disabled': False,
            'notify_plugin': ('mail', {}),
        },
    ]
    save_notification_rules(notification_rules)

    try:
        import cmk.gui.cee.plugins.wato.sample_config
        cmk.gui.cee.plugins.wato.sample_config.create_cee_sample_config()
    except ImportError:
        pass

    # Make sure the host tag attributes are immediately declared!
    config.wato_host_tags = wato_host_tags
    config.wato_aux_tags = wato_aux_tags

    # Initial baking of agents (when bakery is available)
    if has_agent_bakery():
        import cmk.gui.cee.plugins.wato.agent_bakery
        bake_job = cmk.gui.cee.plugins.wato.agent_bakery.BakeAgentsBackgroundJob()
        bake_job.set_function(cmk.gui.cee.plugins.wato.agent_bakery.bake_agents_background_job)
        try:
            bake_job.start()
        except background_job.BackgroundJobAlreadyRunning:
            pass

    # This is not really the correct place for such kind of action, but the best place we could
    # find to execute it only for new created sites.
    import cmk.gui.werks as werks
    werks.acknowledge_all_werks(check_permission=False)

    cmk.gui.wato.mkeventd.save_mkeventd_sample_config()

    userdb.create_cmk_automation_user()


def _need_to_create_sample_config():
    if os.path.exists(multisite_dir + "hosttags.mk") \
        or os.path.exists(wato_root_dir + "rules.mk") \
        or os.path.exists(wato_root_dir + "groups.mk") \
        or os.path.exists(wato_root_dir + "notifications.mk") \
        or os.path.exists(wato_root_dir + "global.mk"):
        return False
    return True


def init_watolib_datastructures():
    if config.wato_use_git:
        prepare_git_commit()

    update_config_based_host_attributes()


#.
#   .--Changes-------------------------------------------------------------.
#   |                ____ _                                                |
#   |               / ___| |__   __ _ _ __   __ _  ___  ___                |
#   |              | |   | '_ \ / _` | '_ \ / _` |/ _ \/ __|               |
#   |              | |___| | | | (_| | | | | (_| |  __/\__ \               |
#   |               \____|_| |_|\__,_|_| |_|\__, |\___||___/               |
#   |                                       |___/                          |
#   +----------------------------------------------------------------------+
#   | Functions for logging changes and keeping the "Activate Changes"     |
#   | state and finally activating changes.                                |
#   '----------------------------------------------------------------------'


# linkinfo identifies the object operated on. It can be a Host or a Folder
# or a text.
def log_entry(linkinfo, action, message, user_id=None):
    # Using attrencode here is against our regular rule to do the escaping
    # at the last possible time: When rendering. But this here is the last
    # place where we can distinguish between HTML() encapsulated (already)
    # escaped / allowed HTML and strings to be escaped.
    message = cmk.utils.make_utf8(html.attrencode(message)).strip()

    # linkinfo is either a Folder, or a Host or a hostname or None
    if isinstance(linkinfo, Folder):
        link = linkinfo.path() + ":"
    elif isinstance(linkinfo, Host):
        link = linkinfo.folder().path() + ":" + linkinfo.name()
    elif linkinfo == None:
        link = "-"
    else:
        link = linkinfo

    if user_id == None and config.user.id != None:
        user_id = config.user.id
    elif user_id == '':
        user_id = '-'

    if user_id:
        user_id = user_id.encode("utf-8")

    store.mkdir(os.path.dirname(audit_log_path))
    with open(audit_log_path, "ab") as f:
        os.chmod(f.name, 0660)
        f.write("%d %s %s %s %s\n" % (int(time.time()), link, user_id, action,
                                      message.replace("\n", "\\n")))


def log_audit(linkinfo, action, message, user_id=None):
    if config.wato_use_git:
        if isinstance(message, HTML):
            message = html.strip_tags(message.value)
        g_git_messages.append(message)
    log_entry(linkinfo, action, message, user_id)


def confirm_all_local_changes():
    ActivateChanges().confirm_site_changes(config.omd_site())


#
# NEW sync code
#


def add_change(action_name,
               text,
               obj=None,
               add_user=True,
               need_sync=None,
               need_restart=None,
               domains=None,
               sites=None):

    log_audit(obj, action_name, text, config.user.id if add_user else '')
    need_sidebar_reload()

    # On each change to the Check_MK configuration mark the agents to be rebuild
    # TODO: Really? Why?
    #if has_agent_bakery():
    #    import cmk.gui.cee.agent_bakery as agent_bakery
    #    agent_bakery.mark_need_to_bake_agents()

    ActivateChangesWriter().add_change(action_name, text, obj, add_user, need_sync, need_restart,
                                       domains, sites)


def add_service_change(host, action_name, text, need_sync=False):
    add_change(action_name, text, obj=host, sites=[host.site_id()], need_sync=need_sync)


def get_number_of_pending_changes():
    changes = ActivateChanges()
    changes.load()
    return len(changes.grouped_changes())


class ConfigDomain(object):
    needs_sync = True
    needs_activation = True
    always_activate = False
    ident = None
    in_global_settings = True

    @classmethod
    def enabled_domains(cls):
        return [d for d in config_domain_registry.values() if d.enabled()]

    @classmethod
    def get_always_activate_domain_idents(cls):
        return [d.ident for d in config_domain_registry.values() if d.always_activate]

    @classmethod
    def get_class(cls, ident):
        return config_domain_registry[ident]

    @classmethod
    def enabled(cls):
        return True

    @classmethod
    def get_all_default_globals(cls):
        settings = {}
        for domain in ConfigDomain.enabled_domains():
            settings.update(domain().default_globals())
        return settings

    def config_dir(self):
        raise NotImplementedError()

    def config_file(self, site_specific):
        if site_specific:
            return os.path.join(self.config_dir(), "sitespecific.mk")
        return os.path.join(self.config_dir(), "global.mk")

    def activate(self):
        raise MKGeneralException(_("The domain \"%s\" does not support activation.") % self.ident)

    def load(self, site_specific=False):
        filename = self.config_file(site_specific)
        settings = {}

        if not os.path.exists(filename):
            return {}

        try:
            execfile(filename, settings, settings)

            # FIXME: Do not modify the dict while iterating over it.
            for varname in list(settings.keys()):
                if varname not in g_configvars:
                    del settings[varname]

            return settings
        except Exception, e:
            raise MKGeneralException(_("Cannot read configuration file %s: %s") % (filename, e))

    def load_site_globals(self):
        return self.load(site_specific=True)

    def save(self, settings, site_specific=False):
        filename = self.config_file(site_specific)

        output = wato_fileheader()
        for varname, value in settings.items():
            output += "%s = %s\n" % (varname, pprint.pformat(value))

        store.makedirs(os.path.dirname(filename))
        store.save_file(filename, output)

    def save_site_globals(self, settings):
        self.save(settings, site_specific=True)

    def default_globals(self):
        """Returns a dictionary that contains the default settings
        of all configuration variables of this config domain."""
        raise NotImplementedError()

    def _get_global_config_var_names(self):
        """Returns a list of all global config variable names
        associated with this config domain."""
        return [varname for (varname, var) in configvars().items() if var[0] == self.__class__]


class ConfigDomainRegistry(cmk.plugin_registry.ClassRegistry):
    def plugin_base_class(self):
        return ConfigDomain

    def _register(self, plugin_class):
        self._entries[plugin_class.ident] = plugin_class


config_domain_registry = ConfigDomainRegistry()


@config_domain_registry.register
class ConfigDomainCore(ConfigDomain):
    needs_sync = True
    needs_activation = True
    ident = "check_mk"

    def config_dir(self):
        return wato_root_dir

    def activate(self):
        return check_mk_local_automation(config.wato_activation_method)

    def default_globals(self):
        return check_mk_local_automation("get-configuration", [],
                                         self._get_global_config_var_names())


@config_domain_registry.register
class ConfigDomainGUI(ConfigDomain):
    needs_sync = True
    needs_activation = False
    ident = "multisite"

    def config_dir(self):
        return multisite_dir

    def activate(self):
        pass

    def default_globals(self):
        return config.default_config


@config_domain_registry.register
class ConfigDomainEventConsole(ConfigDomain):
    needs_sync = True
    needs_activation = True
    ident = "ec"
    in_global_settings = False

    @classmethod
    def enabled(cls):
        return config.mkeventd_enabled

    def config_dir(self):
        return str(cmk.ec.export.rule_pack_dir())

    def activate(self):
        if getattr(config, "mkeventd_enabled", False):
            mkeventd.execute_command("RELOAD", site=config.omd_site())
            log_audit(None, "mkeventd-activate",
                      _("Activated changes of event console configuration"))
            call_hook_mkeventd_activate_changes()

    def default_globals(self):
        return cmk.ec.defaults.default_config()


@config_domain_registry.register
class ConfigDomainCACertificates(ConfigDomain):
    needs_sync = True
    needs_activation = True
    always_activate = True  # Execute this on all sites on all activations
    ident = "ca-certificates"

    trusted_cas_file = "%s/var/ssl/ca-certificates.crt" % cmk.paths.omd_root

    # This is a list of directories that may contain .pem files of trusted CAs.
    # The contents of all .pem files will be contantenated together and written
    # to "trusted_cas_file". This is done by the function update_trusted_cas().
    # On a system only a single directory, the first existing one is processed.
    system_wide_trusted_ca_search_paths = [
        "/etc/ssl/certs",  # Ubuntu/Debian/SLES
        "/etc/pki/tls/certs",  # CentOS/RedHat
    ]

    _PEM_RE = re.compile(b"-----BEGIN CERTIFICATE-----\r?.+?\r?-----END CERTIFICATE-----\r?\n?"
                         "", re.DOTALL)

    def config_dir(self):
        return multisite_dir

    def config_file(self, site_specific=False):
        return os.path.join(self.config_dir(), "ca-certificates.mk")

    def save(self, settings, site_specific=False):
        super(ConfigDomainCACertificates, self).save(settings, site_specific=site_specific)

        current_config = settings.get("trusted_certificate_authorities", {
            "use_system_wide_cas": True,
            "trusted_cas": [],
        })

        # We need to activate this immediately to make syncs to WATO slave sites
        # possible right after changing the option
        #
        # Since this can be called from any WATO page it is not possible to report
        # errors to the user here. The self._update_trusted_cas() method logs the
        # errors - this must be enough for the moment.
        self._update_trusted_cas(current_config)

    def activate(self):
        try:
            return self._update_trusted_cas(config.trusted_certificate_authorities)
        except Exception:
            logger.exception()
            return [
                "Failed to create trusted CA file '%s': %s" % (self.trusted_cas_file,
                                                               traceback.format_exc())
            ]

    def _update_trusted_cas(self, current_config):
        trusted_cas, errors = [], []

        if current_config["use_system_wide_cas"]:
            trusted, errors = self._get_system_wide_trusted_ca_certificates()
            trusted_cas += trusted

        trusted_cas += current_config["trusted_cas"]

        store.save_file(self.trusted_cas_file, "\n".join(trusted_cas))
        return errors

    def _get_system_wide_trusted_ca_certificates(self):
        trusted_cas, errors = set([]), []
        for p in self.system_wide_trusted_ca_search_paths:
            cert_path = Path(p)

            if not cert_path.is_dir():
                continue

            for entry in cert_path.iterdir():
                cert_file_path = entry.absolute()
                try:
                    if entry.suffix not in [".pem", ".crt"]:
                        continue

                    trusted_cas.update(self._get_certificates_from_file(cert_file_path))
                except IOError:
                    logger.exception()

                    # This error is shown to the user as warning message during "activate changes".
                    # We keep this message for the moment because we think that it is a helpful
                    # trigger for further checking web.log when a really needed certificate can
                    # not be read.
                    #
                    # We know a permission problem with some files that are created by default on
                    # some distros. We simply ignore these files because we assume that they are
                    # not needed.
                    if cert_file_path == Path("/etc/ssl/certs/localhost.crt"):
                        continue

                    errors.append("Failed to add certificate '%s' to trusted CA certificates. "
                                  "See web.log for details." % cert_file_path)

            break

        return list(trusted_cas), errors

    def _get_certificates_from_file(self, path):
        try:
            return [match.group(0) for match in self._PEM_RE.finditer(open("%s" % path).read())]
        except IOError, e:
            if e.errno == 2:  # No such file or directory
                # Silently ignore e.g. dangling symlinks
                return []
            else:
                raise

    def default_globals(self):
        return {
            "trusted_certificate_authorities": {
                "use_system_wide_cas": True,
                "trusted_cas": [],
            }
        }


@config_domain_registry.register
class ConfigDomainOMD(ConfigDomain):
    needs_sync = True
    needs_activation = True
    ident = "omd"
    omd_config_dir = "%s/etc/omd" % (cmk.paths.omd_root)

    def __init__(self):
        super(ConfigDomainOMD, self).__init__()
        self._logger = logger.getChild("config.omd")

    def config_dir(self):
        return self.omd_config_dir

    def default_globals(self):
        return self._from_omd_config(self._load_site_config())

    def activate(self):
        current_settings = self._load_site_config()

        settings = {}
        settings.update(self._to_omd_config(self.load()))
        settings.update(self._to_omd_config(self.load_site_globals()))

        config_change_commands = []
        self._logger.debug("Set omd config: %r" % settings)

        for key, val in settings.items():
            if key not in current_settings:
                continue  # Skip settings unknown to current OMD

            if current_settings[key] == settings[key]:
                continue  # Skip unchanged settings

            config_change_commands.append("%s=%s" % (key, val))

        if not config_change_commands:
            self._logger.debug("Got no config change commands...")
            return

        self._logger.debug("Executing \"omd config change\"")
        self._logger.debug("  Commands: %r" % config_change_commands)
        p = subprocess.Popen(["omd", "config", "change"],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             stdin=subprocess.PIPE,
                             close_fds=True)
        stdout = p.communicate(cmk.utils.make_utf8("\n".join(config_change_commands)))[0]
        self._logger.debug("  Exit code: %d" % p.returncode)
        self._logger.debug("  Output: %r" % stdout)
        if p.returncode != 0:
            raise MKGeneralException(
                _("Failed to activate changed site "
                  "configuration.\nExit code: %d\nConfig: %s\nOutput: %s") %
                (p.returncode, config_change_commands, stdout))

    def _load_site_config(self):
        return self._load_omd_config("%s/site.conf" % self.omd_config_dir)

    def _load_omd_config(self, path):
        settings = {}

        if not os.path.exists(path):
            return {}

        try:
            for line in file(path):
                line = line.strip()

                if line == "" or line.startswith("#"):
                    continue

                var, value = line.split("=", 1)

                if not var.startswith("CONFIG_"):
                    continue

                key = var[7:].strip()
                val = value.strip().strip("'")

                settings[key] = val
        except Exception, e:
            raise MKGeneralException(_("Cannot read configuration file %s: %s") % (path, e))

        return settings

    # Convert the raw OMD configuration settings to the WATO config format.
    # The format that is understood by the valuespecs. Since some valuespecs
    # affect multiple OMD config settings, these need to be converted here.
    #
    # Sadly we can not use the Transform() valuespecs, because each configvar
    # only get's the value associated with it's config key.
    def _from_omd_config(self, config):
        settings = {}

        for key, value in config.items():
            if value == "on":
                settings[key] = True
            elif value == "off":
                settings[key] = False
            else:
                settings[key] = value

        if "LIVESTATUS_TCP" in settings:
            if settings["LIVESTATUS_TCP"]:
                settings["LIVESTATUS_TCP"] = {
                    "port": int(settings["LIVESTATUS_TCP_PORT"]),
                }
                del settings["LIVESTATUS_TCP_PORT"]

                # Be compatible to older sites that don't have the key in their config yet
                settings.setdefault("LIVESTATUS_TCP_ONLY_FROM", "0.0.0.0")

                if settings["LIVESTATUS_TCP_ONLY_FROM"] != "0.0.0.0":
                    settings["LIVESTATUS_TCP"]["only_from"] = \
                        settings["LIVESTATUS_TCP_ONLY_FROM"].split()

                del settings["LIVESTATUS_TCP_ONLY_FROM"]
            else:
                settings["LIVESTATUS_TCP"] = None

        if "NSCA" in settings:
            if settings["NSCA"]:
                settings["NSCA"] = int(settings["NSCA_TCP_PORT"])
            else:
                settings["NSCA"] = None

        if "MKEVENTD" in settings:
            if settings["MKEVENTD"]:
                settings["MKEVENTD"] = []

                for proto in ["SNMPTRAP", "SYSLOG", "SYSLOG_TCP"]:
                    if settings["MKEVENTD_%s" % proto]:
                        settings["MKEVENTD"].append(proto)
            else:
                settings["MKEVENTD"] = None

        # Convert from OMD key (to lower, add "site_" prefix)
        settings = dict([("site_%s" % key.lower(), val) for key, val in settings.items()])

        return settings

    # Bring the WATO internal representation int OMD configuration settings.
    # Counterpart of the _from_omd_config() method.
    def _to_omd_config(self, config):
        settings = {}

        # Convert to OMD key
        config = dict([(key.upper()[5:], val) for key, val in config.items()])

        if "LIVESTATUS_TCP" in config:
            if config["LIVESTATUS_TCP"] is not None:
                config["LIVESTATUS_TCP_PORT"] = "%s" % config["LIVESTATUS_TCP"]["port"]

                if "only_from" in config["LIVESTATUS_TCP"]:
                    config["LIVESTATUS_TCP_ONLY_FROM"] = " ".join(
                        config["LIVESTATUS_TCP"]["only_from"])
                else:
                    config["LIVESTATUS_TCP_ONLY_FROM"] = "0.0.0.0"

                config["LIVESTATUS_TCP"] = "on"
            else:
                config["LIVESTATUS_TCP"] = "off"

        if "NSCA" in config:
            if config["NSCA"] is not None:
                config["NSCA_TCP_PORT"] = "%s" % config["NSCA"]
                config["NSCA"] = "on"
            else:
                config["NSCA"] = "off"

        if "MKEVENTD" in config:
            if config["MKEVENTD"] is not None:
                for proto in ["SNMPTRAP", "SYSLOG", "SYSLOG_TCP"]:
                    config["MKEVENTD_%s" % proto] = proto in config["MKEVENTD"]

                config["MKEVENTD"] = "on"

            else:
                config["MKEVENTD"] = "off"

        for key, value in config.items():
            if isinstance(value, bool):
                settings[key] = "on" if value else "off"
            else:
                settings[key] = "%s" % value

        return settings


#.
#   .--Hosts & Folders-----------------------------------------------------.
#   | _   _           _          ___     _____     _     _                 |
#   || | | | ___  ___| |_ ___   ( _ )   |  ___|__ | | __| | ___ _ __ ___   |
#   || |_| |/ _ \/ __| __/ __|  / _ \/\ | |_ / _ \| |/ _` |/ _ \ '__/ __|  |
#   ||  _  | (_) \__ \ |_\__ \ | (_>  < |  _| (_) | | (_| |  __/ |  \__ \  |
#   ||_| |_|\___/|___/\__|___/  \___/\/ |_|  \___/|_|\__,_|\___|_|  |___/  |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  New Implementation of handling of hosts and folders                 |
#   |  This new implementation is currently additional to the existing one |
#   |  but will replace step by step all direct handling with the folder   |
#   |  and host dictionaries.                                              |
#   '----------------------------------------------------------------------'

# Names:
# folder_path: Path of the folders directory relative to etc/check_mk/conf.d/wato
#              The root folder is "". No trailing / is allowed here.
# wato_info:   The dictionary that is saved in the folder's .wato file

# Terms:
# create, delete   mean actual filesystem operations
# add, remove      mean just modifications in the data structures


class WithPermissions(object):
    def may(self, how):  # how is "read" or "write"
        try:
            self._user_needs_permission(how)
            return True
        except MKAuthException:
            return False

    def reason_why_may_not(self, how):
        try:
            self._user_needs_permission(how)
            return False
        except MKAuthException, e:
            return HTML("%s" % e)

    def need_permission(self, how):
        self._user_needs_permission(how)

    def _user_needs_permission(self, how):
        raise NotImplementedError()


# Base class containing a couple of generic permission checking functions, used
# for Host and Folder
class WithPermissionsAndAttributes(WithPermissions):
    def __init__(self):
        super(WithPermissionsAndAttributes, self).__init__()
        self._attributes = {}
        self._effective_attributes = None

    # .--------------------------------------------------------------------.
    # | ATTRIBUTES                                                         |
    # '--------------------------------------------------------------------'

    def attributes(self):
        return self._attributes

    def attribute(self, attrname, default_value=None):
        return self.attributes().get(attrname, default_value)

    def set_attribute(self, attrname, value):
        self._attributes[attrname] = value

    def has_explicit_attribute(self, attrname):
        return attrname in self.attributes()

    def effective_attributes(self):
        raise NotImplementedError()

    def effective_attribute(self, attrname, default_value=None):
        return self.effective_attributes().get(attrname, default_value)

    def remove_attribute(self, attrname):
        del self.attributes()[attrname]

    def drop_caches(self):
        self._effective_attributes = None

    def _cache_effective_attributes(self, effective):
        self._effective_attributes = effective.copy()

    def _get_cached_effective_attributes(self):
        if self._effective_attributes is None:
            raise KeyError("Not cached")
        else:
            return self._effective_attributes.copy()


#.
#   .--BaseFolder----------------------------------------------------------.
#   |          ____                 _____     _     _                      |
#   |         | __ )  __ _ ___  ___|  ___|__ | | __| | ___ _ __            |
#   |         |  _ \ / _` / __|/ _ \ |_ / _ \| |/ _` |/ _ \ '__|           |
#   |         | |_) | (_| \__ \  __/  _| (_) | | (_| |  __/ |              |
#   |         |____/ \__,_|___/\___|_|  \___/|_|\__,_|\___|_|              |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Base class of SearchFolder and Folder. Implements common methods.   |
#   '----------------------------------------------------------------------'
class BaseFolder(WithPermissionsAndAttributes):
    def hosts(self):
        raise NotImplementedError()

    def host_names(self):
        return self.hosts().keys()

    def host(self, host_name):
        return self.hosts().get(host_name)

    def has_host(self, host_name):
        return host_name in self.hosts()

    def has_hosts(self):
        return len(self.hosts()) != 0

    def host_validation_errors(self):
        return validate_all_hosts(self.host_names())

    def is_disk_folder(self):
        return False

    def is_search_folder(self):
        return False

    def has_parent(self):
        return self.parent() != None

    def parent(self):
        raise NotImplementedError()

    def is_same_as(self, folder):
        return self == folder or self.path() == folder.path()

    def path(self):
        raise NotImplementedError()

    def is_current_folder(self):
        return self.is_same_as(Folder.current())

    def is_parent_of(self, maybe_child):
        return maybe_child.parent() == self

    def is_transitive_parent_of(self, maybe_child):
        if self.is_same_as(maybe_child):
            return True
        elif maybe_child.has_parent():
            return self.is_transitive_parent_of(maybe_child.parent())
        return False

    def is_root(self):
        return not self.has_parent()

    def parent_folder_chain(self):
        folders = []
        folder = self.parent()
        while folder:
            folders.append(folder)
            folder = folder.parent()
        return folders[::-1]

    def show_breadcrump(self, link_to_folder=False, keepvarnames=None):
        if keepvarnames == True:
            uri_func = html.makeuri
            keepvars = []
        else:
            uri_func = html.makeuri_contextless

            if keepvarnames is None:
                keepvarnames = ["mode"]

            keepvars = [(name, html.var(name)) for name in keepvarnames]
            if link_to_folder:
                keepvars.append(("mode", "folder"))

        def render_component(folder):
            return '<a href="%s">%s</a>' % \
                (uri_func([ ("folder", folder.path())] + keepvars),
                 html.attrencode(folder.title()))

        def breadcrump_element_start(end='', z_index=0):
            html.open_li(style="z-index:%d;" % z_index)
            html.div('', class_=["left", end])

        def breadcrump_element_end(end=''):
            html.div('', class_=["right", end])
            html.close_li()

        parts = []
        for folder in self.parent_folder_chain():
            parts.append(render_component(folder))

        # The current folder (with link or without link)
        if link_to_folder:
            parts.append(render_component(self))
        else:
            parts.append(html.attrencode(self.title()))

        # Render the folder path
        html.open_div(class_=["folderpath"])
        html.open_ul()
        num = 0
        for part in parts:
            if num == 0:
                breadcrump_element_start('end', z_index=100 + num)
            else:
                breadcrump_element_start(z_index=100 + num)
            html.open_div(class_=["content"])
            html.write(part)
            html.close_div()

            breadcrump_element_end(num == len(parts) - 1 and
                                   not (self.has_subfolders() and not link_to_folder) and "end" or
                                   "")
            num += 1

        # Render the current folder when having subfolders
        if not link_to_folder and self.has_subfolders() and self.visible_subfolders():
            breadcrump_element_start(z_index=100 + num)
            html.open_div(class_=["content"])
            html.open_form(name="folderpath", method="GET")
            html.dropdown(
                "folder", [("", "")] + self.subfolder_choices(),
                class_="folderpath",
                onchange="folderpath.submit();")
            if keepvarnames == True:
                html.hidden_fields()
            else:
                for var in keepvarnames:
                    html.hidden_field(var, html.var(var))
            html.close_form()
            html.close_div()
            breadcrump_element_end('end')

        html.close_ul()
        html.close_div()

    def name(self):
        raise NotImplementedError()

    def title(self):
        raise NotImplementedError()

    def visible_subfolders(self):
        raise NotImplementedError()

    def subfolder(self, name):
        raise NotImplementedError()

    def has_subfolders(self):
        raise NotImplementedError()

    def subfolder_choices(self):
        raise NotImplementedError()

    def move_subfolder_to(self, subfolder, target_folder):
        raise NotImplementedError()

    def create_subfolder(self, name, title, attributes):
        raise NotImplementedError()

    def edit_url(self, backfolder=None):
        raise NotImplementedError()

    def edit(self, new_title, new_attributes):
        raise NotImplementedError()

    def locked(self):
        raise NotImplementedError()

    def create_hosts(self, entries):
        raise NotImplementedError()

    def site_id(self):
        raise NotImplementedError()


#.
#   .--Folder--------------------------------------------------------------.
#   |                     _____     _     _                                |
#   |                    |  ___|__ | | __| | ___ _ __                      |
#   |                    | |_ / _ \| |/ _` |/ _ \ '__|                     |
#   |                    |  _| (_) | | (_| |  __/ |                        |
#   |                    |_|  \___/|_|\__,_|\___|_|                        |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  This class represents a WATO folder that contains other folders and |
#   |  hosts.                                                              |
#   '----------------------------------------------------------------------'


class CREFolder(BaseFolder):
    # .--------------------------------------------------------------------.
    # | STATIC METHODS                                                     |
    # '--------------------------------------------------------------------'

    @staticmethod
    def all_folders():
        if not html.is_cached("wato_folders"):
            wato_folders = html.set_cache("wato_folders", {})
            Folder("", "").add_to_dictionary(wato_folders)
        return html.get_cached("wato_folders")

    @staticmethod
    def folder_choices():
        return Folder.root_folder().recursive_subfolder_choices()

    @staticmethod
    def folder_choices_fulltitle():
        return Folder.root_folder().recursive_subfolder_choices(current_depth=0, pretty=False)

    @staticmethod
    def folder(folder_path):
        if folder_path in Folder.all_folders():
            return Folder.all_folders()[folder_path]
        else:
            raise MKGeneralException("No WATO folder %s." % folder_path)

    @staticmethod
    def create_missing_folders(folder_path):
        folder = Folder.folder("")
        for subfolder_name in Folder._split_folder_path(folder_path):
            if folder.has_subfolder(subfolder_name):
                folder = folder.subfolder(subfolder_name)
            else:
                folder = folder.create_subfolder(subfolder_name, subfolder_name, {})

    @staticmethod
    def _split_folder_path(folder_path):
        if not folder_path:
            return []
        return folder_path.split("/")

    @staticmethod
    def folder_exists(folder_path):
        return os.path.exists(wato_root_dir + folder_path)

    @staticmethod
    def root_folder():
        return Folder.folder("")

    @staticmethod
    def invalidate_caches():
        html.del_cache("wato_folders")
        Folder.root_folder().drop_caches()

    # Find folder that is specified by the current URL. This is either by a folder
    # path in the variable "folder" or by a host name in the variable "host". In the
    # latter case we need to load all hosts in all folders and actively search the host.
    # Another case is the host search which has the "host_search" variable set. To handle
    # the later case we call .current() of SearchFolder() to let it decide whether or not
    # this is a host search. This method has to return a folder in all cases.
    @staticmethod
    def current():
        if html.is_cached("wato_current_folder"):
            return html.get_cached("wato_current_folder")

        folder = SearchFolder.current_search_folder()
        if folder:
            return folder

        if html.has_var("folder"):
            try:
                folder = Folder.folder(html.var("folder"))
            except MKGeneralException, e:
                raise MKUserError("folder", "%s" % e)
        else:
            host_name = html.var("host")
            folder = Folder.root_folder()
            if host_name:  # find host with full scan. Expensive operation
                host = Host.host(host_name)
                if host:
                    folder = host.folder()

        Folder.set_current(folder)
        return folder

    @staticmethod
    def current_disk_folder():
        folder = Folder.current()
        while not folder.is_disk_folder():
            folder = folder.parent()
        return folder

    @staticmethod
    def set_current(folder):
        html.set_cache("wato_current_folder", folder)

    # .-----------------------------------------------------------------------.
    # | CONSTRUCTION, LOADING & SAVING                                        |
    # '-----------------------------------------------------------------------'

    def __init__(self,
                 name,
                 folder_path=None,
                 parent_folder=None,
                 title=None,
                 attributes=None,
                 root_dir=None):
        super(CREFolder, self).__init__()
        self._name = name
        self._parent = parent_folder
        self._subfolders = {}

        self._choices_for_moving_host = None

        self._root_dir = root_dir
        if self._root_dir:
            self._root_dir = root_dir.rstrip("/") + "/"  # FIXME: ugly
        else:
            self._root_dir = wato_root_dir

        if folder_path != None:
            self._init_by_loading_existing_directory(folder_path)
        else:
            self._init_by_creating_new(title, attributes)

    def _init_by_loading_existing_directory(self, folder_path):
        self._hosts = None
        self._load()
        self.load_subfolders()

    def _init_by_creating_new(self, title, attributes):
        self._hosts = {}
        self._num_hosts = 0
        self._title = title
        self._attributes = attributes
        self._locked = False
        self._locked_hosts = False
        self._locked_subfolders = False

    def __repr__(self):
        return "Folder(%r, %r)" % (self.path(), self._title)

    def get_root_dir(self):
        return self._root_dir

    # Dangerous operation! Only use this if you have a good knowledge of the internas
    def set_root_dir(self, root_dir):
        self._root_dir = root_dir.rstrip("/") + "/"  # O.o

    def parent(self):
        return self._parent

    def is_disk_folder(self):
        return True

    def _load_hosts_on_demand(self):
        if self._hosts == None:
            self._load_hosts()

    def _load_hosts(self):
        self._locked_hosts = False

        self._hosts = {}
        if not os.path.exists(self.hosts_file_path()):
            return

        variables = self._load_hosts_file()
        self._locked_hosts = variables["_lock"]

        # Add entries in clusters{} to all_hosts, prepare cluster to node mapping
        nodes_of = {}
        for cluster_with_tags, nodes in variables["clusters"].items():
            variables["all_hosts"].append(cluster_with_tags)
            nodes_of[cluster_with_tags.split('|')[0]] = nodes

        # Build list of individual hosts
        for host_name_with_tags in variables["all_hosts"]:
            parts = host_name_with_tags.split('|')
            host_name = parts[0]
            host_tags = self._cleanup_host_tags(parts[1:])
            host = self._create_host_from_variables(host_name, host_tags, nodes_of, variables)
            self._hosts[host_name] = host

    def _create_host_from_variables(self, host_name, host_tags, nodes_of, variables):
        cluster_nodes = nodes_of.get(host_name)

        # If we have a valid entry in host_attributes then the hosts.mk file contained
        # valid WATO information from a last save and we use that
        if host_name in variables["host_attributes"]:
            attributes = variables["host_attributes"][host_name]

            attributes = self._transform_old_attributes(attributes)

        else:
            host_tags = self._transform_old_agent_type_in_tag_list(host_tags)

            # Otherwise it is an import from some manual old version of from some
            # CMDB and we reconstruct the attributes. That way the folder inheritance
            # information is not available and all tags are set explicitely
            attributes = {}
            alias = self._get_alias_from_extra_conf(host_name, variables)
            if alias != None:
                attributes["alias"] = alias
            attributes.update(self._get_attributes_from_tags(host_tags))
            for attribute_key, config_dict in [
                ("ipaddress", "ipaddresses"),
                ("ipv6address", "ipv6addresses"),
                ("snmp_community", "explicit_snmp_communities"),
            ]:
                if host_name in variables[config_dict]:
                    attributes[attribute_key] = variables[config_dict][host_name]

        return Host(self, host_name, attributes, cluster_nodes)

    # Old tag group trans:
    #('agent', u'Agent type',
    #    [
    #        ('cmk-agent', u'Check_MK Agent (Server)', ['tcp']),
    #        ('snmp-only', u'SNMP (Networking device, Appliance)', ['snmp']),
    #        ('snmp-v1',   u'Legacy SNMP device (using V1)', ['snmp']),
    #        ('snmp-tcp',  u'Dual: Check_MK Agent + SNMP', ['snmp', 'tcp']),
    #        ('ping',      u'No Agent', []),
    #    ],
    #)
    #
    def _transform_old_agent_type_in_tag_list(self, host_tags):
        if "snmp-only" in host_tags:
            host_tags.remove("snmp-only")
            host_tags.append("snmp-v2")
            # snmp must be already in this list

        if "snmp-tcp" in host_tags:
            host_tags.remove("snmp-tcp")
            host_tags.append("snmp-v2")
            host_tags.append("cmk-agent")
            # snmp and tcp must be already in this list

        return host_tags

    def _transform_old_attributes(self, attributes):
        """Mangle all attribute structures read from the disk to prepare it for the current logic"""
        attributes = self._transform_old_agent_type_in_attributes(attributes)
        attributes = self._transform_none_value_site_attribute(attributes)
        return attributes

    # Old tag group trans:
    #('agent', u'Agent type',
    #    [
    #        ('cmk-agent', u'Check_MK Agent (Server)', ['tcp']),
    #        ('snmp-only', u'SNMP (Networking device, Appliance)', ['snmp']),
    #        ('snmp-v1',   u'Legacy SNMP device (using V1)', ['snmp']),
    #        ('snmp-tcp',  u'Dual: Check_MK Agent + SNMP', ['snmp', 'tcp']),
    #        ('ping',      u'No Agent', []),
    #    ],
    #)
    #
    def _transform_old_agent_type_in_attributes(self, attributes):
        if "tag_agent" not in attributes:
            return attributes  # Nothing set here, no transformation necessary

        if "tag_snmp" in attributes:
            return attributes  # Already in new format, no transformation necessary

        value = attributes["tag_agent"]

        if value == "cmk-agent":
            attributes["tag_snmp"] = "no-snmp"

        elif value == "snmp-only":
            attributes["tag_agent"] = "no-agent"
            attributes["tag_snmp"] = "snmp-v2"

        elif value == "snmp-v1":
            attributes["tag_agent"] = "no-agent"
            attributes["tag_snmp"] = "snmp-v1"

        elif value == "snmp-tcp":
            attributes["tag_agent"] = "cmk-agent"
            attributes["tag_snmp"] = "snmp-v2"

        elif value == "ping":
            attributes["tag_agent"] = "no-agent"
            attributes["tag_snmp"] = "no-snmp"

        return attributes

    def _transform_none_value_site_attribute(self, attributes):
        # Old WATO was saving "site" attribute with value of None. Skip this key.
        if "site" in attributes and attributes["site"] == None:
            del attributes["site"]
        return attributes

    def _load_hosts_file(self):
        variables = {
            "FOLDER_PATH": "",
            "ALL_HOSTS": ALL_HOSTS,
            "ALL_SERVICES": ALL_SERVICES,
            "all_hosts": [],
            "clusters": {},
            "ipaddresses": {},
            "ipv6addresses": {},
            "explicit_snmp_communities": {},
            "management_snmp_credentials": {},
            "management_ipmi_credentials": {},
            "management_protocol": {},
            "extra_host_conf": {
                "alias": []
            },
            "extra_service_conf": {
                "_WATO": []
            },
            "host_attributes": {},
            "host_contactgroups": [],
            "service_contactgroups": [],
            "_lock": False,
        }
        return store.load_mk_file(self.hosts_file_path(), variables)

    def save_hosts(self):
        self.need_unlocked_hosts()
        self.need_permission("write")
        if self._hosts != None:
            self._save_hosts_file()

            # Clean up caches of all hosts in this folder, just to be sure. We could also
            # check out all call sites of save_hosts() and partially drop the caches of
            # individual hosts to optimize this.
            for host in self._hosts.values():
                host.drop_caches()

        call_hook_hosts_changed(self)

    def _save_hosts_file(self):
        self._ensure_folder_directory()
        if not self.has_hosts():
            if os.path.exists(self.hosts_file_path()):
                os.remove(self.hosts_file_path())
            return

        out = cStringIO.StringIO()
        out.write(wato_fileheader())

        all_hosts = []  # list of [Python string for all_hosts]
        clusters = []  # tuple list of (Python string, nodes)
        hostnames = self.hosts().keys()
        hostnames.sort()
        custom_macros = {}  # collect value for attributes that are to be present in Nagios
        cleaned_hosts = {}

        attribute_mappings = [
            # host attr, cmk_base variable name, value, title
            ("ipaddress", "ipaddresses", {}, "Explicit IPv4 addresses"),
            ("ipv6address", "ipv6addresses", {}, "Explicit IPv6 addresses"),
            ("snmp_community", "explicit_snmp_communities", {}, "Explicit SNMP communities"),
            ("management_snmp_community", "management_snmp_credentials", {},
             "Management board SNMP credentials"),
            ("management_ipmi_credentials", "management_ipmi_credentials", {},
             "Management board IPMI credentials"),
            ("management_protocol", "management_protocol", {}, "Management board protocol"),
        ]

        for hostname in hostnames:
            host = self.hosts()[hostname]
            effective = host.effective_attributes()
            cleaned_hosts[hostname] = host.attributes()

            tags = host.tags()
            tagstext = "|".join(list(tags))
            if tagstext:
                tagstext += "|"
            hostentry = '"%s|%swato|/" + FOLDER_PATH + "/"' % (hostname, tagstext)

            if host.is_cluster():
                clusters.append((hostentry, host.cluster_nodes()))
            else:
                all_hosts.append(hostentry)

            # Save the effective attributes of a host to the related attribute maps.
            # These maps are saved directly in the hosts.mk to transport the effective
            # attributes to Check_MK base.
            for attribute_name, _unused_cmk_var_name, dictionary, _unused_title in attribute_mappings:
                value = effective.get(attribute_name)
                if value:
                    dictionary[hostname] = value

            # Create contact group rule entries for hosts with explicitely set values
            # Note: since the type if this entry is a list, not a single contact group, all other list
            # entries coming after this one will be ignored. That way the host-entries have
            # precedence over the folder entries.

            if host.has_explicit_attribute("contactgroups"):
                cgconfig = convert_cgroups_from_tuple(host.attribute("contactgroups"))
                cgs = cgconfig["groups"]
                if cgs and cgconfig["use"]:
                    out.write("\nhost_contactgroups += [\n")
                    for cg in cgs:
                        out.write('    ( %r, [%r] ),\n' % (cg, hostname))
                    out.write(']\n\n')

                    if cgconfig.get("use_for_services"):
                        out.write("\nservice_contactgroups += [\n")
                        for cg in cgs:
                            out.write('    ( %r, [%r], ALL_SERVICES ),\n' % (cg, hostname))
                        out.write(']\n\n')

            for attr, _topic in all_host_attributes():
                attrname = attr.name()
                if attrname in effective:
                    custom_varname = attr.nagios_name()
                    if custom_varname:
                        value = effective.get(attrname)
                        nagstring = attr.to_nagios(value)
                        if nagstring != None:
                            if custom_varname not in custom_macros:
                                custom_macros[custom_varname] = {}
                            custom_macros[custom_varname][hostname] = nagstring

        if len(all_hosts) > 0:
            out.write("all_hosts += [\n")
            for entry in all_hosts:
                out.write('  %s,\n' % entry)
            out.write("]\n")

        if len(clusters) > 0:
            out.write("\nclusters.update({")
            for entry, nodes in clusters:
                out.write('\n  %s : %s,\n' % (entry, repr(nodes)))
            out.write("})\n")

        for attribute_name, cmk_base_varname, dictionary, title in attribute_mappings:
            if dictionary:
                out.write("\n# %s\n" % title)
                out.write("%s.update(" % cmk_base_varname)
                out.write(format_config_value(dictionary))
                out.write(")\n")

        for custom_varname, entries in custom_macros.items():
            macrolist = []
            for hostname, nagstring in entries.items():
                macrolist.append((nagstring, [hostname]))
            if len(macrolist) > 0:
                out.write("\n# Settings for %s\n" % custom_varname)
                out.write("extra_host_conf.setdefault(%r, []).extend(\n" % custom_varname)
                out.write("  %s)\n" % format_config_value(macrolist))

        # If the contact groups of the host are set to be used for the monitoring,
        # we create an according rule for the folder and an according rule for
        # each host that has an explicit setting for that attribute.
        _permitted_groups, contact_groups, use_for_services = self.groups()
        if contact_groups:
            out.write("\nhost_contactgroups.append(\n"
                      "  ( %r, [ '/' + FOLDER_PATH + '/' ], ALL_HOSTS ))\n" % list(contact_groups))
            if use_for_services:
                # Currently service_contactgroups requires single values. Lists are not supported
                for cg in contact_groups:
                    out.write(
                        "\nservice_contactgroups.append(\n"
                        "  ( %r, [ '/' + FOLDER_PATH + '/' ], ALL_HOSTS, ALL_SERVICES ))\n" % cg)

        # Write information about all host attributes into special variable - even
        # values stored for check_mk as well.
        out.write("\n# Host attributes (needed for WATO)\n")
        out.write("host_attributes.update(\n%s)\n" % format_config_value(cleaned_hosts))

        store.save_file(self.hosts_file_path(), out.getvalue())

    # Remove dynamic tags like "wato" and the folder path.
    def _cleanup_host_tags(self, tags):
        return [tag for tag in tags if tag not in ["wato", "//"] and not tag.startswith("/wato/")]

    def _get_attributes_from_tags(self, host_tags):
        # Retrieve setting for each individual host tag. This is needed for
        # reading in hosts.mk files where host_attributes is missing. Can
        # we drop this one day?
        attributes = {}
        for attr, _topic in all_host_attributes():
            if isinstance(attr, HostTagAttribute):
                tagvalue = attr.get_tag_value(host_tags)
                attributes[attr.name()] = tagvalue
        return attributes

    def _get_alias_from_extra_conf(self, host_name, variables):
        aliases = self._host_extra_conf(host_name, variables["extra_host_conf"]["alias"])
        if len(aliases) > 0:
            return aliases[0]
        return

    # This is a dummy implementation which works without tags
    # and implements only a special case of Check_MK's real logic.
    def _host_extra_conf(self, host_name, conflist):
        for value, hostlist in conflist:
            if host_name in hostlist:
                return [value]
        return []

    def _load(self):
        wato_info = self._load_wato_info()
        self._title = wato_info.get("title", self._fallback_title())
        self._attributes = self._transform_old_attributes(wato_info.get("attributes", {}))
        self._locked = wato_info.get("lock", False)
        self._locked_subfolders = wato_info.get("lock_subfolders", False)

        if "num_hosts" in wato_info:
            self._num_hosts = wato_info.get("num_hosts", None)
        else:
            self._num_hosts = len(self.hosts())
            self._save_wato_info()

    def _load_wato_info(self):
        return store.load_data_from_file(self.wato_info_path(), {})

    def save(self):
        self._save_wato_info()
        Folder.invalidate_caches()

    def _save_wato_info(self):
        self._ensure_folder_directory()
        store.save_data_to_file(self.wato_info_path(), self.get_wato_info())

    def get_wato_info(self):
        return {
            "title": self._title,
            "attributes": self._attributes,
            "num_hosts": self._num_hosts,
            "lock": self._locked,
            "lock_subfolders": self._locked_subfolders,
        }

    def _ensure_folder_directory(self):
        store.makedirs(self.filesystem_path())

    def _fallback_title(self):
        if self.is_root():
            return _("Main directory")
        return self.name()

    def load_subfolders(self):
        dir_path = self._root_dir + self.path()
        for entry in os.listdir(dir_path):
            subfolder_dir = dir_path + "/" + entry
            if os.path.isdir(subfolder_dir):
                if self.path():
                    subfolder_path = self.path() + "/" + entry
                else:
                    subfolder_path = entry
                self._subfolders[entry] = Folder(
                    entry, subfolder_path, self, root_dir=self._root_dir)

    def wato_info_path(self):
        return self.filesystem_path() + "/.wato"

    def hosts_file_path(self):
        return self.filesystem_path() + "/hosts.mk"

    def rules_file_path(self):
        return self.filesystem_path() + "/rules.mk"

    def add_to_dictionary(self, dictionary):
        dictionary[self.path()] = self
        for subfolder in self._subfolders.values():
            subfolder.add_to_dictionary(dictionary)

    def drop_caches(self):
        super(CREFolder, self).drop_caches()
        self._choices_for_moving_host = None

        for subfolder in self._subfolders.values():
            subfolder.drop_caches()

        if self._hosts is not None:
            for host in self._hosts.values():
                host.drop_caches()

    # .-----------------------------------------------------------------------.
    # | ELEMENT ACCESS                                                        |
    # '-----------------------------------------------------------------------'

    def name(self):
        return self._name

    def title(self):
        return self._title

    def filesystem_path(self):
        return (self._root_dir + self.path()).rstrip("/")

    def ident(self):
        return self.path()

    def path(self):
        if self.is_root():
            return ""
        elif self.parent().is_root():
            return self.name()
        return self.parent().path() + "/" + self.name()

    def hosts(self):
        self._load_hosts_on_demand()
        return self._hosts

    def num_hosts(self):
        # Do *not* load hosts here! This method must kept cheap
        return self._num_hosts

    def num_hosts_recursively(self):
        num = self.num_hosts()
        for subfolder in self.visible_subfolders().values():
            num += subfolder.num_hosts_recursively()
        return num

    def all_hosts_recursively(self):
        hosts = {}
        hosts.update(self.hosts())
        for subfolder in self.all_subfolders().values():
            hosts.update(subfolder.all_hosts_recursively())
        return hosts

    def visible_subfolders(self):
        visible_folders = {}
        for folder_name, folder in self._subfolders.items():
            if folder.folder_should_be_shown("read"):
                visible_folders[folder_name] = folder

        return visible_folders

    def all_subfolders(self):
        return self._subfolders

    def subfolder(self, name):
        return self._subfolders[name]

    def subfolder_by_title(self, title):
        for subfolder in self.all_subfolders().values():
            if subfolder.title() == title:
                return subfolder

    def has_subfolder(self, name):
        return name in self._subfolders

    def has_subfolders(self):
        return len(self._subfolders) > 0

    def subfolder_choices(self):
        choices = []
        for subfolder in self.visible_subfolders_sorted_by_title():
            choices.append((subfolder.path(), subfolder.title()))
        return choices

    def recursive_subfolder_choices(self, current_depth=0, pretty=True):
        if pretty:
            if current_depth:
                title_prefix = (u"\u00a0" * 6 * current_depth) + u"\u2514\u2500 "
            else:
                title_prefix = ""
            title = HTML(title_prefix + html.attrencode(self.title()))
        else:
            title = HTML(html.attrencode("/".join(self.title_path_without_root())))

        sel = [(self.path(), title)]

        for subfolder in self.visible_subfolders_sorted_by_title():
            sel += subfolder.recursive_subfolder_choices(current_depth + 1, pretty)
        return sel

    def choices_for_moving_folder(self):
        return self._choices_for_moving("folder")

    def choices_for_moving_host(self):
        if self._choices_for_moving_host != None:
            return self._choices_for_moving_host  # Cached

        self._choices_for_moving_host = self._choices_for_moving("host")
        return self._choices_for_moving_host

    def folder_should_be_shown(self, how):
        if not config.wato_hide_folders_without_read_permissions:
            return True

        has_permission = self.may(how)
        for subfolder in self.all_subfolders().values():
            if has_permission:
                break
            has_permission = subfolder.folder_should_be_shown(how)

        return has_permission

    def _choices_for_moving(self, what):
        choices = []

        for folder_path, folder in Folder.all_folders().items():
            if not folder.may("write"):
                continue
            if folder.is_same_as(self):
                continue  # do not move into itself

            if what == "folder":
                if folder.is_same_as(self.parent()):
                    continue  # We are already in that folder
                if folder.name() in folder.all_subfolders():
                    continue  # naming conflict
                if self.is_transitive_parent_of(folder):
                    continue  # we cannot be moved in our child folder

            msg = "/".join(folder.title_path_without_root())
            choices.append((folder_path, msg))

        choices.sort(cmp=lambda a, b: cmp(a[1].lower(), b[1].lower()))
        return choices

    def subfolders_sorted_by_title(self):
        return sorted(self.all_subfolders().values(), cmp=lambda a, b: cmp(a.title(), b.title()))

    def visible_subfolders_sorted_by_title(self):
        return sorted(
            self.visible_subfolders().values(), cmp=lambda a, b: cmp(a.title(), b.title()))

    def site_id(self):
        if "site" in self._attributes:
            return self._attributes["site"]
        elif self.has_parent():
            return self.parent().site_id()
        return default_site()

    def all_site_ids(self):
        site_ids = set()
        self._add_all_sites_to_set(site_ids)
        return list(site_ids)

    def title_path(self, withlinks=False):
        titles = []
        for folder in self.parent_folder_chain() + [self]:
            title = folder.title()
            if withlinks:
                title = "<a href='wato.py?mode=folder&folder=%s'>%s</a>" % (folder.path(), title)
            titles.append(title)
        return titles

    def title_path_without_root(self):
        if self.is_root():
            return [self.title()]
        return self.title_path()[1:]

    def alias_path(self, show_main=True):
        if show_main:
            return " / ".join(self.title_path())
        return " / ".join(self.title_path_without_root())

    def effective_attributes(self):
        try:
            return self._get_cached_effective_attributes()  # cached :-)
        except KeyError:
            pass

        effective = {}
        for folder in self.parent_folder_chain():
            effective.update(folder.attributes())
        effective.update(self.attributes())

        # now add default values of attributes for all missing values
        for host_attribute, _topic in all_host_attributes():
            attrname = host_attribute.name()
            if attrname not in effective:
                effective.setdefault(attrname, host_attribute.default_value())

        self._cache_effective_attributes(effective)
        return effective

    def groups(self, host=None):
        # CLEANUP: this method is also used for determining host permission
        # in behalv of Host::groups(). Not nice but was done for avoiding
        # code duplication
        permitted_groups = set([])
        host_contact_groups = set([])
        if host:
            effective_folder_attributes = host.effective_attributes()
        else:
            effective_folder_attributes = self.effective_attributes()
        cgconf = get_folder_cgconf_from_attributes(effective_folder_attributes)

        # First set explicit groups
        permitted_groups.update(cgconf["groups"])
        if cgconf["use"]:
            host_contact_groups.update(cgconf["groups"])

        if host:
            parent = self
        else:
            parent = self.parent()

        while parent:
            effective_folder_attributes = parent.effective_attributes()
            parconf = get_folder_cgconf_from_attributes(effective_folder_attributes)
            parent_permitted_groups, parent_host_contact_groups, _parent_use_for_services = parent.groups(
            )

            if parconf["recurse_perms"]:  # Parent gives us its permissions
                permitted_groups.update(parent_permitted_groups)

            if parconf["recurse_use"]:  # Parent give us its contact groups
                host_contact_groups.update(parent_host_contact_groups)

            parent = parent.parent()

        return permitted_groups, host_contact_groups, cgconf.get("use_for_services", False)

    def find_host_recursively(self, host_name):
        host = self.host(host_name)
        if host:
            return host

        for subfolder in self.all_subfolders().values():
            host = subfolder.find_host_recursively(host_name)
            if host:
                return host

    def _user_needs_permission(self, how):
        if config.user.may("wato.all_folders"):
            return
        if how == "read" and config.user.may("wato.see_all_folders"):
            return

        permitted_groups, _folder_contactgroups, _use_for_services = self.groups()
        user_contactgroups = userdb.contactgroups_of_user(config.user.id)

        for c in user_contactgroups:
            if c in permitted_groups:
                return

        reason = _("Sorry, you have no permissions to the folder <b>%s</b>.") % self.alias_path()
        if not permitted_groups:
            reason += " " + _("The folder is not permitted for any contact group.")
        else:
            reason += " " + _("The folder's permitted contact groups are <b>%s</b>.") % ", ".join(
                permitted_groups)
            if user_contactgroups:
                reason += " " + _("Your contact groups are <b>%s</b>.") % ", ".join(
                    user_contactgroups)
            else:
                reason += " " + _("But you are not a member of any contact group.")
        reason += " " + _(
            "You may enter the folder as you might have permission on a subfolders, though.")
        raise MKAuthException(reason)

    def need_recursive_permission(self, how):
        self.need_permission(how)
        if how == "write":
            self.need_unlocked()
            self.need_unlocked_subfolders()
            self.need_unlocked_hosts()

        for subfolder in self.all_subfolders().values():
            subfolder.need_recursive_permission(how)

    def need_unlocked(self):
        if self.locked():
            raise MKAuthException(
                _("Sorry, you cannot edit the folder %s. It is locked.") % self.title())

    def need_unlocked_hosts(self):
        if self.locked_hosts():
            raise MKAuthException(_("Sorry, the hosts in the folder %s are locked.") % self.title())

    def need_unlocked_subfolders(self):
        if self.locked_subfolders():
            raise MKAuthException(
                _("Sorry, the sub folders in the folder %s are locked.") % self.title())

    def url(self, add_vars=None):
        if add_vars is None:
            add_vars = []

        url_vars = [("folder", self.path())]
        have_mode = False
        for varname, _value in add_vars:
            if varname == "mode":
                have_mode = True
                break
        if not have_mode:
            url_vars.append(("mode", "folder"))
        if html.var("debug") == "1":
            add_vars.append(("debug", "1"))
        url_vars += add_vars
        return html.makeuri_contextless(url_vars, filename="wato.py")

    def edit_url(self, backfolder=None):
        if backfolder == None:
            if self.has_parent():
                backfolder = self.parent()
            else:
                backfolder = self
        return html.makeuri_contextless([
            ("mode", "editfolder"),
            ("folder", self.path()),
            ("backfolder", backfolder.path()),
        ])

    def locked(self):
        return self._locked

    def locked_subfolders(self):
        return self._locked_subfolders

    def locked_hosts(self):
        self._load_hosts_on_demand()
        return self._locked_hosts

    # Returns:
    #  None:      No network scan is enabled.
    #  timestamp: Next planned run according to config.
    def next_network_scan_at(self):
        if "network_scan" not in self._attributes:
            return

        interval = self._attributes["network_scan"]["scan_interval"]
        last_end = self._attributes.get("network_scan_result", {}).get("end", None)
        if last_end == None:
            next_time = time.time()
        else:
            next_time = last_end + interval

        time_allowed = self._attributes["network_scan"].get("time_allowed")
        if time_allowed == None:
            return next_time  # No time frame limit

        # First transform the time given by the user to UTC time
        brokentime = list(time.localtime(next_time))
        brokentime[3], brokentime[4] = time_allowed[0]
        start_time = time.mktime(brokentime)

        brokentime[3], brokentime[4] = time_allowed[1]
        end_time = time.mktime(brokentime)

        # In case the next time is earlier than the allowed time frame at a day set
        # the time to the time frame start.
        # In case the next time is in the time frame leave it at it's value.
        # In case the next time is later then advance one day to the start of the
        # time frame.
        if next_time < start_time:
            next_time = start_time
        elif next_time > end_time:
            next_time = start_time + 86400

        return next_time

    # .-----------------------------------------------------------------------.
    # | MODIFICATIONS                                                         |
    # |                                                                       |
    # | These methods are for being called by actual WATO modules when they   |
    # | want to modify folders and hosts. They all check permissions and      |
    # | locking. They may raise MKAuthException or MKUserError.               |
    # |                                                                       |
    # | Folder permissions: Creation and deletion of subfolders needs write   |
    # | permissions in the parent folder (like in Linux).                     |
    # |                                                                       |
    # | Locking: these methods also check locking. Locking is for preventing  |
    # | changes in files that are created by third party applications.        |
    # | A folder has three lock attributes:                                   |
    # |                                                                       |
    # | - locked_hosts() -> hosts.mk file in the folder must not be modified  |
    # | - locked()       -> .wato file in the folder must not be modified     |
    # | - locked_subfolders() -> No subfolders may be created/deleted         |
    # |                                                                       |
    # | Sidebar: some sidebar snapins show the WATO folder tree. Everytime    |
    # | the tree changes the sidebar needs to be reloaded. This is done here. |
    # |                                                                       |
    # | Validation: these methods do *not* validate the parameters for syntax.|
    # | This is the task of the actual WATO modes or the API.                 |
    # '-----------------------------------------------------------------------'

    def create_subfolder(self, name, title, attributes):
        # 1. Check preconditions
        config.user.need_permission("wato.manage_folders")
        self.need_permission("write")
        self.need_unlocked_subfolders()
        must_be_in_contactgroups(attributes.get("contactgroups"))

        # 2. Actual modification
        new_subfolder = Folder(name, parent_folder=self, title=title, attributes=attributes)
        self._subfolders[name] = new_subfolder
        new_subfolder.save()
        add_change(
            "new-folder",
            _("Created new folder %s") % new_subfolder.alias_path(),
            obj=new_subfolder,
            sites=[new_subfolder.site_id()])
        call_hook_folder_created(new_subfolder)
        need_sidebar_reload()
        return new_subfolder

    def delete_subfolder(self, name):
        # 1. Check preconditions
        config.user.need_permission("wato.manage_folders")
        self.need_permission("write")
        self.need_unlocked_subfolders()

        # 2. check if hosts have parents
        subfolder = self.subfolder(name)
        hosts_with_children = self._get_parents_of_hosts(subfolder.all_hosts_recursively().keys())
        if hosts_with_children:
            raise MKUserError("delete_host", _("You cannot delete these hosts: %s") % \
                              ", ".join([_("%s is parent of %s.") % (parent, ", ".join(children))
                              for parent, children in sorted(hosts_with_children.items())]))

        # 3. Actual modification
        call_hook_folder_deleted(subfolder)
        add_change(
            "delete-folder",
            _("Deleted folder %s") % subfolder.alias_path(),
            obj=self,
            sites=subfolder.all_site_ids())
        self._remove_subfolder(name)
        shutil.rmtree(subfolder.filesystem_path())
        Folder.invalidate_caches()
        need_sidebar_reload()

    def move_subfolder_to(self, subfolder, target_folder):
        # 1. Check preconditions
        config.user.need_permission("wato.manage_folders")
        self.need_permission("write")
        self.need_unlocked_subfolders()
        target_folder.need_permission("write")
        target_folder.need_unlocked_subfolders()
        subfolder.need_recursive_permission("write")  # Inheritance is changed
        if os.path.exists(target_folder.filesystem_path() + "/" + subfolder.name()):
            raise MKUserError(
                None,
                _("Cannot move folder: A folder with this name already exists in the target folder."
                 ))

        original_alias_path = subfolder.alias_path()

        # 2. Actual modification
        affected_sites = subfolder.all_site_ids()
        old_filesystem_path = subfolder.filesystem_path()
        del self._subfolders[subfolder.name()]
        subfolder._parent = target_folder
        target_folder._subfolders[subfolder.name()] = subfolder
        shutil.move(old_filesystem_path, subfolder.filesystem_path())
        subfolder.rewrite_hosts_files()  # fixes changed inheritance
        Folder.invalidate_caches()
        affected_sites = list(set(affected_sites + subfolder.all_site_ids()))
        add_change(
            "move-folder",
            _("Moved folder %s to %s") % (original_alias_path, target_folder.alias_path()),
            obj=subfolder,
            sites=affected_sites)
        need_sidebar_reload()

    def edit(self, new_title, new_attributes):
        # 1. Check preconditions
        self.need_permission("write")
        self.need_unlocked()

        # For changing contact groups user needs write permission on parent folder
        if get_folder_cgconf_from_attributes(new_attributes) != \
           get_folder_cgconf_from_attributes(self.attributes()):
            must_be_in_contactgroups(self.attributes().get("contactgroups"))
            if self.has_parent():
                if not self.parent().may("write"):
                    raise MKAuthException(
                        _("Sorry. In order to change the permissions of a folder you need write "
                          "access to the parent folder."))

        # 2. Actual modification

        # Due to a change in the attribute "site" a host can move from
        # one site to another. In that case both sites need to be marked
        # dirty. Therefore we first mark dirty according to the current
        # host->site mapping and after the change we mark again according
        # to the new mapping.
        affected_sites = self.all_site_ids()

        self._title = new_title
        self._attributes = new_attributes

        # Due to changes in folder/file attributes, host files
        # might need to be rewritten in order to reflect Changes
        # in Nagios-relevant attributes.
        self.save()
        self.rewrite_hosts_files()

        affected_sites = list(set(affected_sites + self.all_site_ids()))
        add_change(
            "edit-folder",
            _("Edited properties of folder %s") % self.title(),
            obj=self,
            sites=affected_sites)

    def create_hosts(self, entries):
        # 1. Check preconditions
        config.user.need_permission("wato.manage_hosts")
        self.need_unlocked_hosts()
        self.need_permission("write")

        for host_name, attributes, cluster_nodes in entries:
            must_be_in_contactgroups(attributes.get("contactgroups"))
            validate_host_uniqueness("host", host_name)

        # 2. Actual modification
        self._load_hosts_on_demand()
        for host_name, attributes, cluster_nodes in entries:
            host = Host(self, host_name, attributes, cluster_nodes)
            self._hosts[host_name] = host
            self._num_hosts = len(self._hosts)
            add_change(
                "create-host",
                _("Created new host %s.") % host_name,
                obj=host,
                sites=[host.site_id()])
        self._save_wato_info()  # num_hosts has changed
        self.save_hosts()

    def delete_hosts(self, host_names):
        # 1. Check preconditions
        config.user.need_permission("wato.manage_hosts")
        self.need_unlocked_hosts()
        self.need_permission("write")

        # 2. check if hosts have parents
        hosts_with_children = self._get_parents_of_hosts(host_names)
        if hosts_with_children:
            raise MKUserError("delete_host", _("You cannot delete these hosts: %s") % \
                              ", ".join([_("%s is parent of %s.") % (parent, ", ".join(children))
                              for parent, children in sorted(hosts_with_children.items())]))

        # 3. Delete host specific files (caches, tempfiles, ...)
        self._delete_host_files(host_names)

        # 4. Actual modification
        for host_name in host_names:
            host = self.hosts()[host_name]
            del self._hosts[host_name]
            self._num_hosts = len(self._hosts)
            add_change(
                "delete-host", _("Deleted host %s") % host_name, obj=host, sites=[host.site_id()])

        self._save_wato_info()  # num_hosts has changed
        self.save_hosts()

    def _get_parents_of_hosts(self, host_names):
        # Note: Deletion of chosen hosts which are parents
        # is possible if and only if all children are chosen, too.
        hosts_with_children = {}
        for child_key, child in Folder.root_folder().all_hosts_recursively().items():
            for host_name in host_names:
                if host_name in child.parents():
                    hosts_with_children.setdefault(host_name, [])
                    hosts_with_children[host_name].append(child_key)

        result = {}
        for parent, children in hosts_with_children.items():
            if not set(children) < set(host_names):
                result.setdefault(parent, children)
        return result

    # Group the given host names by their site and delete their files
    def _delete_host_files(self, host_names):
        hosts_by_site = {}
        for host_name in host_names:
            host = self.hosts()[host_name]
            hosts_by_site.setdefault(host.site_id(), []).append(host_name)

        for site_id, site_host_names in hosts_by_site.items():
            check_mk_automation(site_id, "delete-hosts", site_host_names)

    def move_hosts(self, host_names, target_folder):
        # 1. Check preconditions
        config.user.need_permission("wato.manage_hosts")
        config.user.need_permission("wato.edit_hosts")
        config.user.need_permission("wato.move_hosts")
        self.need_permission("write")
        self.need_unlocked_hosts()
        target_folder.need_permission("write")
        target_folder.need_unlocked_hosts()

        # 2. Actual modification
        for host_name in host_names:
            host = self.host(host_name)

            affected_sites = [host.site_id()]

            self._remove_host(host)
            target_folder._add_host(host)

            affected_sites = list(set(affected_sites + [host.site_id()]))
            add_change(
                "move-host",
                _("Moved host from %s to %s") % (self.path(), target_folder.path()),
                obj=host,
                sites=affected_sites)

        self._save_wato_info()  # num_hosts has changed
        self.save_hosts()
        target_folder._save_wato_info()
        target_folder.save_hosts()

    def rename_host(self, oldname, newname):
        # 1. Check preconditions
        config.user.need_permission("wato.manage_hosts")
        config.user.need_permission("wato.edit_hosts")
        self.need_unlocked_hosts()
        host = self.hosts()[oldname]
        host.need_permission("write")

        # 2. Actual modification
        host.rename(newname)
        del self._hosts[oldname]
        self._hosts[newname] = host
        add_change(
            "rename-host",
            _("Renamed host from %s to %s") % (oldname, newname),
            obj=host,
            sites=[host.site_id()])
        self.save_hosts()

    def rename_parent(self, oldname, newname):
        # Must not fail because of auth problems. Auth is check at the
        # actually renamed host.
        changed = rename_host_in_list(self._attributes["parents"], oldname, newname)
        if not changed:
            return False

        add_change(
            "rename-parent",
            _("Renamed parent from %s to %s in folder \"%s\"") % (oldname, newname,
                                                                  self.alias_path()),
            obj=self,
            sites=self.all_site_ids())
        self.save_hosts()
        self.save()
        return True

    def rewrite_hosts_files(self):
        self._rewrite_hosts_file()
        for subfolder in self.all_subfolders().values():
            subfolder.rewrite_hosts_files()

    def _add_host(self, host):
        self._load_hosts_on_demand()
        self._hosts[host.name()] = host
        host._folder = self
        self._num_hosts = len(self._hosts)

    def _remove_host(self, host):
        self._load_hosts_on_demand()
        del self._hosts[host.name()]
        host._folder = None
        self._num_hosts = len(self._hosts)

    def _remove_subfolder(self, name):
        del self._subfolders[name]

    def _add_all_sites_to_set(self, site_ids):
        site_ids.add(self.site_id())
        for host in self.hosts().values():
            site_ids.add(host.site_id())
        for subfolder in self.all_subfolders().values():
            subfolder._add_all_sites_to_set(site_ids)

    def _rewrite_hosts_file(self):
        self._load_hosts_on_demand()
        self.save_hosts()

    # .-----------------------------------------------------------------------.
    # | HTML Generation                                                       |
    # '-----------------------------------------------------------------------'

    def show_locking_information(self):
        self._load_hosts_on_demand()
        lock_messages = []

        # Locked hosts
        if self._locked_hosts == True:
            lock_messages.append(
                _("Host attributes are locked "
                  "(You cannot create, edit or delete hosts in this folder)"))
        elif self._locked_hosts:
            lock_messages.append(self._locked_hosts)

        # Locked folder attributes
        if self._locked == True:
            lock_messages.append(
                _("Folder attributes are locked "
                  "(You cannot edit the attributes of this folder)"))
        elif self._locked:
            lock_messages.append(self._locked)

        # Also subfolders are locked
        if self._locked_subfolders:
            lock_messages.append(
                _("Subfolders are locked "
                  "(You cannot create or remove folders in this folder)"))
        elif self._locked_subfolders:
            lock_messages.append(self._locked_subfolders)

        if lock_messages:
            if len(lock_messages) == 1:
                lock_message = lock_messages[0]
            else:
                li_elements = "".join(["<li>%s</li>" % m for m in lock_messages])
                lock_message = "<ul>" + li_elements + "</ul>"
            html.show_info(lock_message)


def validate_host_uniqueness(varname, host_name):
    host = Host.host(host_name)
    if host:
        raise MKUserError(
            varname,
            _('A host with the name <b><tt>%s</tt></b> already '
              'exists in the folder <a href="%s">%s</a>.') % (host_name, host.folder().url(),
                                                              host.folder().alias_path()))


#.
#   .--External API--------------------------------------------------------.
#   |      _____      _                        _      _    ____ ___        |
#   |     | ____|_  _| |_ ___ _ __ _ __   __ _| |    / \  |  _ \_ _|       |
#   |     |  _| \ \/ / __/ _ \ '__| '_ \ / _` | |   / _ \ | |_) | |        |
#   |     | |___ >  <| ||  __/ |  | | | | (_| | |  / ___ \|  __/| |        |
#   |     |_____/_/\_\\__\___|_|  |_| |_|\__,_|_| /_/   \_\_|  |___|       |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Functions called by others that import wato (such as views)         |
#   '----------------------------------------------------------------------'


# Create an URL to a certain WATO folder when we just know its path
def link_to_folder_by_path(path):
    return "wato.py?mode=folder&folder=" + html.urlencode(path)


# Create an URL to the edit-properties of a host when we just know its name
def link_to_host_by_name(host_name):
    return "wato.py?" + html.urlencode_vars([("mode", "edit_host"), ("host", host_name)])


# Return a list with all the titles of the paths'
# components, e.g. "muc/north" -> [ "Main Directory", "Munich", "North" ]
def get_folder_title_path(path, with_links=False):
    # In order to speed this up, we work with a per HTML-request cache
    cache_name = "wato_folder_titles" + (with_links and "_linked" or "")
    cache = html.set_cache_default(cache_name, {})
    if path not in cache:
        cache[path] = Folder.folder(path).title_path(with_links)
    return cache[path]


# Return the title of a folder - which is given as a string path
def get_folder_title(path):
    folder = Folder.folder(path)
    if folder:
        return folder.title()
    return path


#.
#   .--Search Folder-------------------------------------------------------.
#   |    ____                      _       _____     _     _               |
#   |   / ___|  ___  __ _ _ __ ___| |__   |  ___|__ | | __| | ___ _ __     |
#   |   \___ \ / _ \/ _` | '__/ __| '_ \  | |_ / _ \| |/ _` |/ _ \ '__|    |
#   |    ___) |  __/ (_| | | | (__| | | | |  _| (_) | | (_| |  __/ |       |
#   |   |____/ \___|\__,_|_|  \___|_| |_| |_|  \___/|_|\__,_|\___|_|       |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  A virtual folder representing the result of a search.               |
#   '----------------------------------------------------------------------'
class SearchFolder(BaseFolder):
    @staticmethod
    def criteria_from_html_vars():
        crit = {".name": html.var("host_search_host")}
        crit.update(collect_attributes("host_search", do_validate=False, varprefix="host_search_"))
        return crit

    # This method is allowed to return None when no search is currently performed.
    @staticmethod
    def current_search_folder():
        if html.has_var("host_search"):
            base_folder = Folder.folder(html.var("folder", ""))
            search_criteria = SearchFolder.criteria_from_html_vars()
            folder = SearchFolder(base_folder, search_criteria)
            Folder.set_current(folder)
            return folder

    # .--------------------------------------------------------------------.
    # | CONSTRUCTION                                                       |
    # '--------------------------------------------------------------------'

    def __init__(self, base_folder, criteria):
        super(SearchFolder, self).__init__()
        self._criteria = criteria
        self._base_folder = base_folder
        self._found_hosts = None
        self._name = None

    def __repr__(self):
        return "SearchFolder(%r, %s)" % (self._base_folder.path(), self._name)

    # .--------------------------------------------------------------------.
    # | ACCESS                                                             |
    # '--------------------------------------------------------------------'

    def attributes(self):
        return {}

    def parent(self):
        return self._base_folder

    def is_search_folder(self):
        return True

    def _user_needs_permission(self, how):
        pass

    def title(self):
        return _("Search results for folder %s") % self._base_folder.title()

    def hosts(self):
        if self._found_hosts == None:
            self._found_hosts = self._search_hosts_recursively(self._base_folder)
        return self._found_hosts

    def locked_hosts(self):
        return False

    def locked_subfolders(self):
        return False

    def show_locking_information(self):
        pass

    def has_subfolder(self, name):
        return False

    def has_subfolders(self):
        return False

    def choices_for_moving_host(self):
        return Folder.folder_choices()

    def path(self):
        if self._name:
            return self._base_folder.path() + "//search:" + self._name
        return self._base_folder.path() + "//search"

    def url(self, add_vars=None):
        if add_vars is None:
            add_vars = []

        url_vars = [("host_search", "1")] + add_vars

        for varname, value in html.all_vars().items():
            if varname.startswith("host_search_") \
                or varname.startswith("_change"):
                url_vars.append((varname, value))
        return self.parent().url(url_vars)

    # .--------------------------------------------------------------------.
    # | ACTIONS                                                            |
    # '--------------------------------------------------------------------'

    def delete_hosts(self, host_names):
        auth_errors = []
        for folder, these_host_names in self._group_hostnames_by_folder(host_names):
            try:
                folder.delete_hosts(these_host_names)
            except MKAuthException, e:
                auth_errors.append(
                    _("<li>Cannot delete hosts in folder %s: %s</li>") % (folder.alias_path(), e))
        self._invalidate_search()
        if auth_errors:
            raise MKAuthException(
                _("Some hosts could not be deleted:<ul>%s</ul>") % "".join(auth_errors))

    def move_hosts(self, host_names, target_folder):
        auth_errors = []
        for folder, host_names1 in self._group_hostnames_by_folder(host_names):
            try:
                # FIXME: this is not transaction safe, might get partially finished...
                folder.move_hosts(host_names1, target_folder)
            except MKAuthException, e:
                auth_errors.append(
                    _("<li>Cannot move hosts from folder %s: %s</li>") % (folder.alias_path(), e))
        self._invalidate_search()
        if auth_errors:
            raise MKAuthException(
                _("Some hosts could not be moved:<ul>%s</ul>") % "".join(auth_errors))

    # .--------------------------------------------------------------------.
    # | PRIVATE METHODS                                                    |
    # '--------------------------------------------------------------------'

    def _group_hostnames_by_folder(self, host_names):
        by_folder = {}
        for host_name in host_names:
            host = self.host(host_name)
            by_folder.setdefault(host.folder().path(), []).append(host)

        return [
            (hosts[0].folder(), [host.name() for host in hosts]) for hosts in by_folder.values()
        ]

    def _search_hosts_recursively(self, in_folder):
        hosts = self._search_hosts(in_folder)
        for subfolder in in_folder.all_subfolders().values():
            hosts.update(self._search_hosts_recursively(subfolder))
        return hosts

    def _search_hosts(self, in_folder):
        if not in_folder.may("read"):
            return {}

        found = {}
        for host_name, host in in_folder.hosts().items():
            if self._criteria[".name"] and not host_attribute_matches(self._criteria[".name"],
                                                                      host_name):
                continue

            # Compute inheritance
            effective = host.effective_attributes()

            # Check attributes
            dont_match = False
            for attr, _topic in all_host_attributes():
                attrname = attr.name()
                if attrname in self._criteria and  \
                    not attr.filter_matches(self._criteria[attrname], effective.get(attrname), host_name):
                    dont_match = True
                    break

            if not dont_match:
                found[host_name] = host

        return found

    def _invalidate_search(self):
        self._found_hosts = None


#.
#   .--Host----------------------------------------------------------------.
#   |                         _   _           _                            |
#   |                        | | | | ___  ___| |_                          |
#   |                        | |_| |/ _ \/ __| __|                         |
#   |                        |  _  | (_) \__ \ |_                          |
#   |                        |_| |_|\___/|___/\__|                         |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Class representing one host that is managed via WATO. Hosts are     |
#   |  contained in Folders.                                               |
#   '----------------------------------------------------------------------'


class CREHost(WithPermissionsAndAttributes):
    # .--------------------------------------------------------------------.
    # | STATIC METHODS                                                     |
    # '--------------------------------------------------------------------'

    @staticmethod
    def host(host_name):
        return Folder.root_folder().find_host_recursively(host_name)

    @staticmethod
    def all():
        return Folder.root_folder().all_hosts_recursively()

    @staticmethod
    def host_exists(host_name):
        return Host.host(host_name) != None

    # .--------------------------------------------------------------------.
    # | CONSTRUCTION, LOADING & SAVING                                     |
    # '--------------------------------------------------------------------'

    def __init__(self, folder, host_name, attributes, cluster_nodes):
        super(CREHost, self).__init__()
        self._folder = folder
        self._name = host_name
        self._attributes = attributes
        self._cluster_nodes = cluster_nodes
        self._cached_host_tags = None

    def __repr__(self):
        return "Host(%r)" % (self._name)

    def drop_caches(self):
        super(CREHost, self).drop_caches()
        self._cached_host_tags = None

    # .--------------------------------------------------------------------.
    # | ELEMENT ACCESS                                                     |
    # '--------------------------------------------------------------------'

    def ident(self):
        return self.name()

    def name(self):
        return self._name

    def alias(self):
        # Alias cannot be inherited, so no need to use effective_attributes()
        return self.attributes().get("alias")

    def folder(self):
        return self._folder

    def locked(self):
        return self.folder().locked_hosts()

    def need_unlocked(self):
        return self.folder().need_unlocked_hosts()

    def is_cluster(self):
        return self._cluster_nodes != None

    def cluster_nodes(self):
        return self._cluster_nodes

    def is_offline(self):
        return self.tag("criticality") == "offline"

    def site_id(self):
        return self._attributes.get("site") or self.folder().site_id()

    def parents(self):
        return self.effective_attribute("parents", [])

    def tags(self):
        # Compute tags from settings of each individual tag. We've got
        # the current value for each individual tag. Also other attributes
        # can set tags (e.g. the SiteAttribute)
        if self._cached_host_tags is not None:
            return self._cached_host_tags  # Cached :-)

        tags = set([])
        effective = self.effective_attributes()
        for attr, _topic in all_host_attributes():
            value = effective.get(attr.name())
            tags.update(attr.get_tag_list(value))

        # When a host as been configured not to use the agent and not to use
        # SNMP, it needs to get the ping tag assigned.
        # Because we need information from multiple attributes to get this
        # information, we need to add this decision here.
        if "no-snmp" in tags and "no-agent" in tags:
            tags.add("ping")

        # The following code is needed to migrate host/rule matching from <1.5
        # to 1.5 when a user did not modify the "agent type" tag group.  (See
        # migrate_old_sample_config_tag_groups() for more information)
        aux_tag_ids = [t[0] for t in config.aux_tags()]

        # Be compatible to: Agent type -> SNMP v2 or v3
        if "no-agent" in tags and "snmp-v2" in tags and "snmp-only" in aux_tag_ids:
            tags.add("snmp-only")
        # Be compatible to: Agent type -> Dual: SNMP + TCP
        if "cmk-agent" in tags and "snmp-v2" in tags and "snmp-tcp" in aux_tag_ids:
            tags.add("snmp-tcp")

        self._cached_host_tags = tags
        return tags

    def tag(self, taggroup_name):
        effective = self.effective_attributes()
        attribute_name = "tag_" + taggroup_name
        return effective.get(attribute_name)

    def discovery_failed(self):
        return self.attributes().get("inventory_failed", False)

    def validation_errors(self):
        if hooks.registered('validate-host'):
            errors = []
            for hook_function in hooks.get('validate-host'):
                try:
                    hook_function(self)
                except MKUserError, e:
                    errors.append("%s" % e)
            return errors
        return []

    def effective_attributes(self):
        try:
            return self._get_cached_effective_attributes()  # cached :-)
        except KeyError:
            pass

        effective = self.folder().effective_attributes()
        effective.update(self.attributes())
        self._cache_effective_attributes(effective)
        return effective

    def groups(self):
        return self.folder().groups(self)

    def _user_needs_permission(self, how):
        if config.user.may("wato.all_folders"):
            return True

        if how == "write":
            config.user.need_permission("wato.edit_hosts")

        permitted_groups, _host_contact_groups, _use_for_services = self.groups()
        user_contactgroups = userdb.contactgroups_of_user(config.user.id)

        for c in user_contactgroups:
            if c in permitted_groups:
                return

        reason = _("Sorry, you have no permission on the host '<b>%s</b>'. The host's contact "
                   "groups are <b>%s</b>, your contact groups are <b>%s</b>.") % \
                   (self.name(), ", ".join(permitted_groups), ", ".join(user_contactgroups))
        raise MKAuthException(reason)

    def edit_url(self):
        return html.makeuri_contextless([
            ("mode", "edit_host"),
            ("folder", self.folder().path()),
            ("host", self.name()),
        ])

    def params_url(self):
        return html.makeuri_contextless([
            ("mode", "object_parameters"),
            ("folder", self.folder().path()),
            ("host", self.name()),
        ])

    def services_url(self):
        return html.makeuri_contextless([
            ("mode", "inventory"),
            ("folder", self.folder().path()),
            ("host", self.name()),
        ])

    def clone_url(self):
        return html.makeuri_contextless([
            ("mode", "newcluster" if self.is_cluster() else "newhost"),
            ("folder", self.folder().path()),
            ("clone", self.name()),
        ])

    # .--------------------------------------------------------------------.
    # | MODIFICATIONS                                                      |
    # |                                                                    |
    # | These methods are for being called by actual WATO modules when they|
    # | want to modify hosts. See details at the comment header in Folder. |
    # '--------------------------------------------------------------------'

    def edit(self, attributes, cluster_nodes):
        # 1. Check preconditions
        if attributes.get("contactgroups") != self._attributes.get("contactgroups"):
            self._need_folder_write_permissions()
        self.need_permission("write")
        self.need_unlocked()
        must_be_in_contactgroups(attributes.get("contactgroups"))

        # 2. Actual modification
        affected_sites = [self.site_id()]
        self._attributes = attributes
        self._cluster_nodes = cluster_nodes
        affected_sites = list(set(affected_sites + [self.site_id()]))
        self.folder().save_hosts()
        add_change(
            "edit-host", _("Modified host %s.") % self.name(), obj=self, sites=affected_sites)

    def update_attributes(self, changed_attributes):
        new_attributes = self.attributes().copy()
        new_attributes.update(changed_attributes)
        self.edit(new_attributes, self._cluster_nodes)

    def clean_attributes(self, attrnames_to_clean):
        # 1. Check preconditions
        if "contactgroups" in attrnames_to_clean:
            self._need_folder_write_permissions()
        self.need_unlocked()

        # 2. Actual modification
        affected_sites = [self.site_id()]
        for attrname in attrnames_to_clean:
            if attrname in self._attributes:
                del self._attributes[attrname]
        affected_sites = list(set(affected_sites + [self.site_id()]))
        self.folder().save_hosts()
        add_change(
            "edit-host",
            _("Removed explicit attributes of host %s.") % self.name(),
            obj=self,
            sites=affected_sites)

    def _need_folder_write_permissions(self):
        if not self.folder().may("write"):
            raise MKAuthException(
                _("Sorry. In order to change the permissions of a host you need write "
                  "access to the folder it is contained in."))

    def clear_discovery_failed(self):
        # 1. Check preconditions
        # We do not check permissions. They are checked during the discovery.
        self.need_unlocked()

        # 2. Actual modification
        self.set_discovery_failed(False)

    def set_discovery_failed(self, how=True):
        # 1. Check preconditions
        # We do not check permissions. They are checked during the discovery.
        self.need_unlocked()

        # 2. Actual modification
        if how:
            if not self._attributes.get("inventory_failed"):
                self._attributes["inventory_failed"] = True
                self.folder().save_hosts()
        else:
            if self._attributes.get("inventory_failed"):
                del self._attributes["inventory_failed"]
                self.folder().save_hosts()

    def rename_cluster_node(self, oldname, newname):
        # We must not check permissions here. Permissions
        # on the renamed host must be sufficient. If we would
        # fail here we would leave an inconsistent state
        changed = rename_host_in_list(self._cluster_nodes, oldname, newname)
        if not changed:
            return False

        add_change(
            "rename-node",
            _("Renamed cluster node from %s into %s.") % (oldname, newname),
            obj=self,
            sites=[self.site_id()])
        self.folder().save_hosts()
        return True

    def rename_parent(self, oldname, newname):
        # Same is with rename_cluster_node()
        changed = rename_host_in_list(self._attributes["parents"], oldname, newname)
        if not changed:
            return False

        add_change(
            "rename-parent",
            _("Renamed parent from %s into %s.") % (oldname, newname),
            obj=self,
            sites=[self.site_id()])
        self.folder().save_hosts()
        return True

    def rename(self, new_name):
        add_change(
            "rename-host",
            _("Renamed host from %s into %s.") % (self.name(), new_name),
            obj=self,
            sites=[self.site_id()])
        self._name = new_name


#.
#   .--Attributes----------------------------------------------------------.
#   |              _   _   _        _ _           _                        |
#   |             / \ | |_| |_ _ __(_) |__  _   _| |_ ___  ___             |
#   |            / _ \| __| __| '__| | '_ \| | | | __/ _ \/ __|            |
#   |           / ___ \ |_| |_| |  | | |_) | |_| | ||  __/\__ \            |
#   |          /_/   \_\__|\__|_|  |_|_.__/ \__,_|\__\___||___/            |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | A host attribute is something that is inherited from folders to      |
#   | hosts. Examples are the IP address and the host tags.                |
#   '----------------------------------------------------------------------'


# TODO: Refactor declare_host_attribute() setting private attributes here
class Attribute(object):
    # The constructor stores name and title. If those are
    # dynamic then leave them out and override name() and
    # title()
    def __init__(self, name=None, title=None, help_txt=None, default_value=None):
        self._name = name
        self._title = title
        self._help = help_txt
        self._default_value = default_value

        self._show_in_table = True
        self._show_in_folder = True
        self._show_in_host_search = False
        self._show_in_form = True
        self._show_inherited_value = True
        self._depends_on_tags = []
        self._depends_on_roles = []
        self._editable = True
        self._from_config = False

    # Return the name (= identifier) of the attribute
    def name(self):
        return self._name

    # Return the name of the Nagios configuration variable
    # if this is a Nagios-bound attribute (e.g. "alias" or "_SERIAL")
    def nagios_name(self):
        return None

    # Return the title to be displayed to the user
    def title(self):
        return self._title

    # Return an optional help text
    def help(self):
        return self._help

    # Return the default value for new hosts
    def default_value(self):
        return self._default_value

    # Render HTML code displaying a value
    def paint(self, value, hostname):
        return "", value

    # Whether or not the user is able to edit this attribute. If
    # not, the value is shown read-only (when the user is permitted
    # to see the attribute).
    def may_edit(self):
        return True

    # Whether or not to show this attribute in tables.
    # This value is set by declare_host_attribute
    def show_in_table(self):
        return self._show_in_table

    # Whether or not to show this attribute in the edit form.
    # This value is set by declare_host_attribute
    def show_in_form(self):
        return self._show_in_form

    # Whether or not to make this attribute configurable in
    # files and folders (as defaule value for the hosts)
    def show_in_folder(self):
        return self._show_in_folder

    # Whether or not to make this attribute configurable in
    # the host search form
    def show_in_host_search(self):
        return self._show_in_host_search

    # Whether or not this attribute can be edited after creation
    # of the object
    def editable(self):
        return self._editable

    # Whether it is allowed that a host has no explicit
    # value here (inherited or direct value). An mandatory
    # has *no* default value.
    def is_mandatory(self):
        return False

    # Return information about the user roles we depend on.
    # The method is usually not overridden, but the variable
    # _depends_on_roles is set by declare_host_attribute().
    def depends_on_roles(self):
        return self._depends_on_roles

    # Return information about whether or not either the
    # inherited value or the default value should be shown
    # for an attribute.
    # _depends_on_roles is set by declare_host_attribute().
    def show_inherited_value(self):
        return self._show_inherited_value

    # Return information about the host tags we depend on.
    # The method is usually not overridden, but the variable
    # _depends_on_tags is set by declare_host_attribute().
    def depends_on_tags(self):
        return self._depends_on_tags

    # Whether or not this attribute has been created from the
    # config of the site.
    # The method is usually not overridden, but the variable
    # _from_config is set by declare_host_attribute().
    def from_config(self):
        return self._from_config

    # Render HTML input fields displaying the value and
    # make it editable. If filter == True, then the field
    # is to be displayed in filter mode (as part of the
    # search filter)
    def render_input(self, varprefix, value):
        pass

    # Create value from HTML variables.
    def from_html_vars(self, varprefix):
        return None

    # Check whether this attribute needs to be validated at all
    # Attributes might be permanently hidden (show_in_form = False)
    # or dynamically hidden by the depends_on_tags, editable features
    def needs_validation(self, for_what):
        if not self.is_visible(for_what):
            return False
        return html.var('attr_display_%s' % self._name, "1") == "1"

    # Gets the type of current view as argument and returns whether or not
    # this attribute is shown in this type of view
    def is_visible(self, for_what):
        if for_what in ["host", "cluster", "bulk"] and not self.show_in_form():
            return False
        elif for_what == "folder" and not self.show_in_folder():
            return False
        elif for_what == "host_search" and not self.show_in_host_search():
            return False
        return True

    # Check if the value entered by the user is valid.
    # This method may raise MKUserError in case of invalid user input.
    def validate_input(self, value, varprefix):
        pass

    # If this attribute should be present in Nagios as
    # a host custom macro, then the value of that macro
    # should be returned here - otherwise None
    def to_nagios(self, value):
        return None

    # Checks if the give value matches the search attributes
    # that are represented by the current HTML variables.
    def filter_matches(self, crit, value, hostname):
        return crit == value

    # Host tags to set for this host
    def get_tag_list(self, value):
        return []

    def is_checkbox_tag(self):
        return False


# A simple text attribute. It is stored in
# a Python unicode string
class TextAttribute(Attribute):
    def __init__(self,
                 name,
                 title,
                 help_txt=None,
                 default_value="",
                 mandatory=False,
                 allow_empty=True,
                 size=25):
        Attribute.__init__(self, name, title, help_txt, default_value)
        self._mandatory = mandatory
        self._allow_empty = allow_empty
        self._size = size

    def paint(self, value, hostname):
        if not value:
            return "", ""
        return "", value

    def is_mandatory(self):
        return self._mandatory

    def render_input(self, varprefix, value):
        if value == None:
            value = ""
        html.text_input(varprefix + "attr_" + self.name(), value, size=self._size)

    def from_html_vars(self, varprefix):
        value = html.get_unicode_input(varprefix + "attr_" + self.name())
        if value == None:
            value = ""
        return value.strip()

    def validate_input(self, value, varprefix):
        if self._mandatory and not value:
            raise MKUserError(varprefix + "attr_" + self.name(),
                              _("Please specify a value for %s") % self.title())
        if not self._allow_empty and value.strip() == "":
            raise MKUserError(
                varprefix + "attr_" + self.name(),
                _("%s may be missing, if must not be empty if it is set.") % self.title())

    def filter_matches(self, crit, value, hostname):
        if value == None:  # Host does not have this attribute
            value = ""

        return host_attribute_matches(crit, value)


def host_attribute_matches(crit, value):
    if crit and crit[0] == "~":
        # insensitive infix regex match
        return re.search(crit[1:], value, re.IGNORECASE) != None

    # insensitive infix search
    return crit.lower() in value.lower()


# A simple text attribute that is not editable by the user.
# It can be used to store context information from other
# systems (e.g. during an import of a host database from
# another system).
class FixedTextAttribute(TextAttribute):
    def __init__(self, name, title, help_txt=None):
        TextAttribute.__init__(self, name, title, help_txt, None)
        self._mandatory = False

    def render_input(self, varprefix, value):
        if value != None:
            html.hidden_field(varprefix + "attr_" + self.name(), value)
            html.write(value)

    def from_html_vars(self, varprefix):
        return html.var(varprefix + "attr_" + self.name())


# A text attribute that is stored in a Nagios custom macro
class NagiosTextAttribute(TextAttribute):
    def __init__(self,
                 name,
                 nag_name,
                 title,
                 help_txt=None,
                 default_value="",
                 mandatory=False,
                 allow_empty=True,
                 size=25):
        TextAttribute.__init__(self, name, title, help_txt, default_value, mandatory, allow_empty,
                               size)
        self.nag_name = nag_name

    def nagios_name(self):
        return self.nag_name

    def to_nagios(self, value):
        if value:
            return value
        return None


# An attribute for selecting one item out of list using
# a drop down box (<select>). Enumlist is a list of
# pairs of keyword / title. The type of value is string.
# In all cases where no value is defined or the value is
# not in the enumlist, the default value is being used.
class EnumAttribute(Attribute):
    def __init__(self, name, title, help_txt, default_value, enumlist):
        Attribute.__init__(self, name, title, help_txt, default_value)
        self._enumlist = enumlist
        self._enumdict = dict(enumlist)

    def paint(self, value, hostname):
        return "", self._enumdict.get(value, self.default_value())

    def render_input(self, varprefix, value):
        html.dropdown(varprefix + "attr_" + self.name(), self._enumlist, value)

    def from_html_vars(self, varprefix):
        return html.var(varprefix + "attr_" + self.name(), self.default_value())


# A selection dropdown for a host tag
class HostTagAttribute(Attribute):
    def __init__(self, tag_definition):
        # Definition is either triple or 4-tuple (with
        # dependency definition)
        tag_id, title, self._taglist = tag_definition
        name = "tag_" + tag_id
        if len(self._taglist) == 1:
            def_value = None
        else:
            def_value = self._taglist[0][0]
        Attribute.__init__(self, name, title, "", def_value)

    def is_checkbox_tag(self):
        return len(self._taglist) == 1

    def paint(self, value, hostname):
        # Localize the titles. To make the strings available in the scanned localization
        # files the _() function must also be placed in the configuration files
        # But don't localize empty strings - This empty string is connected to the header
        # of the .mo file
        if len(self._taglist) == 1:
            title = self._taglist[0][1]
            if title:
                title = _u(title)
            if value:
                return "", title
            return "", "%s %s" % (_("Not"), title)
        for entry in self._taglist:
            if value == entry[0]:
                return "", entry[1] and _u(entry[1]) or ''
        return "", ""  # Should never happen, at least one entry should match
        # But case could occur if tags definitions have been changed.

    def render_input(self, varprefix, value):
        varname = varprefix + "attr_" + self.name()
        if value == None:
            value = html.var(varname, "")  # "" is important for tag groups with an empty tag entry

        # Tag groups with just one entry are being displayed
        # as checkboxes
        choices = []
        for e in self._taglist:
            tagvalue = e[0]
            if not tagvalue:  # convert "None" to ""
                tagvalue = ""
            if len(e) >= 3:  # have secondary tags
                secondary_tags = e[2]
            else:
                secondary_tags = []
            choices.append(("|".join([tagvalue] + secondary_tags), e[1] and _u(e[1]) or ''))
            if value != "" and value == tagvalue and secondary_tags:
                value = value + "|" + "|".join(secondary_tags)

        if len(choices) == 1:
            html.checkbox(
                varname,
                value != "",
                label=choices[0][1],
                onclick='wato_fix_visibility();',
                tags=choices[0][0])
        else:
            html.dropdown(varname, choices, value, onchange="wato_fix_visibility();")

    def from_html_vars(self, varprefix):
        varname = varprefix + "attr_" + self.name()
        if len(self._taglist) == 1:
            if html.get_checkbox(varname):
                return self._taglist[0][0]
            return None
        else:
            # strip of secondary tags
            value = html.var(varname).split("|")[0]
            if not value:
                value = None
            return value

    # Special function for computing the setting of a specific
    # tag group from the total list of tags of a host
    def get_tag_value(self, tags):
        for entry in self._taglist:
            if entry[0] in tags:
                return entry[0]
        return None

    # Return list of host tags to set (handles
    # secondary tags)
    def get_tag_list(self, value):
        for entry in self._taglist:
            if entry[0] == value:
                if len(entry) >= 3:
                    taglist = [value] + entry[2]
                else:
                    taglist = [value]
                if taglist[0] == None:
                    taglist = taglist[1:]
                return taglist
        return []  # No matching tag


# An attribute using the generic ValueSpec mechanism
class ValueSpecAttribute(Attribute):
    def __init__(self, name, vs):
        Attribute.__init__(self, name)
        self._valuespec = vs

    def title(self):
        return self._valuespec.title()

    def help(self):
        return self._valuespec.help()

    def default_value(self):
        return self._valuespec.default_value()

    def paint(self, value, hostname):
        return "", \
            self._valuespec.value_to_text(value)

    def render_input(self, varprefix, value):
        self._valuespec.render_input(varprefix + self._name, value)

    def from_html_vars(self, varprefix):
        return self._valuespec.from_html_vars(varprefix + self._name)

    def validate_input(self, value, varprefix):
        self._valuespec.validate_value(value, varprefix + self._name)


class NagiosValueSpecAttribute(ValueSpecAttribute):
    def __init__(self, name, nag_name, vs):
        ValueSpecAttribute.__init__(self, name, vs)
        self.nag_name = nag_name

    def nagios_name(self):
        return self.nag_name

    def to_nagios(self, value):
        value = self._valuespec.value_to_text(value)
        if value:
            return value
        return None


# Convert old tuple representation to new dict representation of
# folder's group settings
def convert_cgroups_from_tuple(value):
    if isinstance(value, dict):
        if "use_for_services" in value:
            return value

        new_value = {
            "use_for_services": False,
        }
        new_value.update(value)
        return value

    return {
        "groups": value[1],
        "recurse_perms": False,
        "use": value[0],
        "use_for_services": False,
        "recurse_use": False,
    }


# Attribute needed for folder permissions
class ContactGroupsAttribute(Attribute):
    # The constructor stores name and title. If those are
    # dynamic than leave them out and override name() and
    # title()
    def __init__(self):
        url = "wato.py?mode=rulesets&group=grouping"
        Attribute.__init__(
            self, "contactgroups", _("Permissions"),
            _("Only members of the contact groups listed here have WATO permission "
              "to the host / folder. If you want, you can make those contact groups "
              "automatically also <b>monitoring contacts</b>. This is completely "
              "optional. Assignment of host and services to contact groups "
              "can be done by <a href='%s'>rules</a> as well.") % url)
        self._default_value = (True, [])
        self._contactgroups = None
        self._users = None
        self._loaded_at = None

    def paint(self, value, hostname):
        value = convert_cgroups_from_tuple(value)
        texts = []
        self.load_data()
        items = self._contactgroups.items()
        items.sort(cmp=lambda a, b: cmp(a[1]['alias'], b[1]['alias']))
        for name, cgroup in items:
            if name in value["groups"]:
                display_name = cgroup.get("alias", name)
                texts.append('<a href="wato.py?mode=edit_contact_group&edit=%s">%s</a>' %
                             (name, display_name))
        result = ", ".join(texts)
        if texts and value["use"]:
            result += html.render_span(
                html.render_b("*"),
                title=_("These contact groups are also used in the monitoring configuration."))
        return "", result

    def render_input(self, varprefix, value):
        value = convert_cgroups_from_tuple(value)

        # If we're just editing a host, then some of the checkboxes will be missing.
        # This condition is not very clean, but there is no other way to savely determine
        # the context.
        is_host = bool(html.var("host")) or html.var("mode") == "newhost"
        is_search = varprefix == "host_search"

        # Only show contact groups I'm currently in and contact
        # groups already listed here.
        self.load_data()
        self._vs_contactgroups().render_input(varprefix + self._name, value['groups'])

        html.hr()

        if is_host:
            html.checkbox(
                varprefix + self._name + "_use",
                value["use"],
                label=_("Add these contact groups to the host"))

        elif not is_search:
            html.checkbox(
                varprefix + self._name + "_recurse_perms",
                value["recurse_perms"],
                label=_("Give these groups also <b>permission on all subfolders</b>"))
            html.hr()
            html.checkbox(
                varprefix + self._name + "_use",
                value["use"],
                label=_("Add these groups as <b>contacts</b> to all hosts in this folder"))
            html.br()
            html.checkbox(
                varprefix + self._name + "_recurse_use",
                value["recurse_use"],
                label=_("Add these groups as <b>contacts in all subfolders</b>"))

        html.hr()
        html.help(
            _("With this option contact groups that are added to hosts are always "
              "being added to services, as well. This only makes a difference if you have "
              "assigned other contact groups to services via rules in <i>Host & Service Parameters</i>. "
              "As long as you do not have any such rule a service always inherits all contact groups "
              "from its host."))
        html.checkbox(
            varprefix + self._name + "_use_for_services",
            value.get("use_for_services", False),
            label=_("Always add host contact groups also to its services"))

    def load_data(self):
        # Make cache valid only during this HTTP request
        if self._loaded_at == id(html):
            return
        self._loaded_at = id(html)
        self._contactgroups = userdb.load_group_information().get("contact", {})

    def from_html_vars(self, varprefix):
        self.load_data()

        cgs = self._vs_contactgroups().from_html_vars(varprefix + self._name)

        return {
            "groups": cgs,
            "recurse_perms": html.get_checkbox(varprefix + self._name + "_recurse_perms"),
            "use": html.get_checkbox(varprefix + self._name + "_use"),
            "use_for_services": html.get_checkbox(varprefix + self._name + "_use_for_services"),
            "recurse_use": html.get_checkbox(varprefix + self._name + "_recurse_use"),
        }

    def filter_matches(self, crit, value, hostname):
        value = convert_cgroups_from_tuple(value)
        # Just use the contact groups for searching
        for contact_group in crit["groups"]:
            if contact_group not in value["groups"]:
                return False
        return True

    def _vs_contactgroups(self):
        cg_choices = sorted([(cg_id, cg_attrs.get("alias", cg_id))
                             for cg_id, cg_attrs in self._contactgroups.items()],
                            key=lambda x: x[1])
        return DualListChoice(choices=cg_choices, rows=20, size=100)


# Declare attributes with this method
def declare_host_attribute(a,
                           show_in_table=True,
                           show_in_folder=True,
                           show_in_host_search=True,
                           topic=None,
                           show_in_form=True,
                           depends_on_tags=None,
                           depends_on_roles=None,
                           editable=True,
                           show_inherited_value=True,
                           may_edit=None,
                           from_config=False):
    if depends_on_tags is None:
        depends_on_tags = []

    if depends_on_roles is None:
        depends_on_roles = []

    g_host_attributes.append((a, topic))
    g_host_attribute[a.name()] = a
    a._show_in_table = show_in_table
    a._show_in_folder = show_in_folder
    a._show_in_host_search = show_in_host_search
    a._show_in_form = show_in_form
    a._show_inherited_value = show_inherited_value
    a._depends_on_tags = depends_on_tags
    a._depends_on_roles = depends_on_roles
    a._editable = editable
    a._from_config = from_config

    if may_edit:
        a.may_edit = may_edit


def undeclare_host_attribute(attrname):
    global g_host_attributes

    if attrname in g_host_attribute:
        attr = g_host_attribute[attrname]
        del g_host_attribute[attrname]
        g_host_attributes = [ha for ha in g_host_attributes if ha[0].name() != attr.name()]


def undeclare_host_tag_attribute(tag_id):
    attrname = "tag_" + tag_id
    undeclare_host_attribute(attrname)


def all_host_attributes():
    return g_host_attributes


def all_host_attribute_names():
    return g_host_attribute.keys()


def host_attribute(name):
    return g_host_attribute[name]


def update_config_based_host_attributes():
    _clear_config_based_host_attributes()
    declare_host_tag_attributes()
    declare_custom_host_attrs()

    Folder.invalidate_caches()
    Folder.root_folder().rewrite_hosts_files()


def _clear_config_based_host_attributes():
    for name, attr in g_host_attribute.items():
        if attr.from_config():
            undeclare_host_attribute(name)


def declare_host_tag_attributes():
    for topic, grouped_tags in group_hosttags_by_topic(config.host_tag_groups()):
        for entry in grouped_tags:
            # if the entry has o fourth component, then its
            # the tag dependency defintion.
            depends_on_tags = []
            depends_on_roles = []
            attr_editable = True
            if len(entry) >= 6:
                attr_editable = entry[5]
            if len(entry) >= 5:
                depends_on_roles = entry[4]
            if len(entry) >= 4:
                depends_on_tags = entry[3]

            if not topic:
                topic = _('Host tags')

            declare_host_attribute(
                HostTagAttribute(entry[:3]),
                show_in_table=False,
                show_in_folder=True,
                editable=attr_editable,
                depends_on_tags=depends_on_tags,
                depends_on_roles=depends_on_roles,
                topic=topic,
                from_config=True,
            )


def declare_custom_host_attrs():
    for attr in config.wato_host_attrs:
        vs = globals()[attr['type']](title=attr['title'], help=attr['help'])

        if attr['add_custom_macro']:
            a = NagiosValueSpecAttribute(attr["name"], "_" + attr["name"], vs)
        else:
            a = ValueSpecAttribute(attr["name"], vs)

        declare_host_attribute(
            a,
            show_in_table=attr['show_in_table'],
            topic=attr['topic'],
            from_config=True,
        )


# Read attributes from HTML variables
def collect_attributes(for_what, do_validate=True, varprefix=""):
    host = {}
    for attr, _topic in all_host_attributes():
        attrname = attr.name()
        if not html.var(for_what + "_change_%s" % attrname, False):
            continue

        value = attr.from_html_vars(varprefix)

        if do_validate and attr.needs_validation(for_what):
            attr.validate_input(value, varprefix)

        host[attrname] = value
    return host


#.
#   .--Global configuration------------------------------------------------.
#   |       ____ _       _           _                    __ _             |
#   |      / ___| | ___ | |__   __ _| |   ___ ___  _ __  / _(_) __ _       |
#   |     | |  _| |/ _ \| '_ \ / _` | |  / __/ _ \| '_ \| |_| |/ _` |      |
#   |     | |_| | | (_) | |_) | (_| | | | (_| (_) | | | |  _| | (_| |      |
#   |      \____|_|\___/|_.__/ \__,_|_|  \___\___/|_| |_|_| |_|\__, |      |
#   |                                                          |___/       |
#   +----------------------------------------------------------------------+
#   |  Code for loading and saving global configuration variables. This is |
#   |  not only needed by the WATO for mode for editing these, but e.g.    |
#   |  also in the code for distributed WATO (handling of site specific    |
#   |  globals).
#   '----------------------------------------------------------------------'

g_configvars = {}
g_configvar_groups = {}
g_configvar_order = {}


def configvars():
    return g_configvars


def configvar_groups():
    return g_configvar_groups


def configvar_order():
    return g_configvar_order


def configvar_show_in_global_settings(varname):
    try:
        return configvars()[varname][-1]
    except KeyError:
        return False


# domain is one of the ConfigDomain classes
def register_configvar(group,
                       varname,
                       valuespec,
                       domain=None,
                       need_restart=None,
                       allow_reset=True,
                       in_global_settings=True):

    if domain is None:
        domain = ConfigDomainCore

    # New API is to hand over the class via domain argument. But not all calls have been
    # migrated. Perform the translation here.
    if isinstance(domain, basestring):
        domain = ConfigDomain.get_class(domain)

    g_configvar_groups.setdefault(group, []).append((domain, varname, valuespec))
    g_configvars[varname] = domain, valuespec, need_restart, allow_reset, in_global_settings


def register_configvar_group(title, order=None):
    if order != None:
        configvar_order()[title] = 18


# Persistenz: Speicherung der Werte
# - WATO speichert seine Variablen für main.mk in conf.d/wato/global.mk
# - Daten, die der User in main.mk einträgt, müssen WATO auch bekannt sein.
#   Sie werden als Defaultwerte verwendet.
# - Daten, die der User in final.mk oder local.mk einträgt, werden von WATO
#   völlig ignoriert. Der Admin kann hier Werte überschreiben, die man mit
#   WATO dann nicht ändern kann. Und man sieht auch nicht, dass der Wert
#   nicht änderbar ist.
# - WATO muss irgendwie von Check_MK herausbekommen, welche Defaultwerte
#   Variablen haben bzw. welche Einstellungen diese Variablen nach main.mk
#   haben.
# - WATO kann main.mk nicht selbst einlesen, weil dann der Kontext fehlt
#   (Default-Werte der Variablen aus Check_MK und aus den Checks)
# - --> Wir machen eine automation, die alle Konfigurationsvariablen
#   ausgibt


def load_configuration_settings(site_specific=False):
    settings = {}
    for domain in ConfigDomain.enabled_domains():
        if site_specific:
            settings.update(domain().load_site_globals())
        else:
            settings.update(domain().load())
    return settings


def save_global_settings(vars_, site_specific=False):
    per_domain = {}
    for varname, (domain, _valuespec, _need_restart, _allow_reset,
                  _in_global_settings) in g_configvars.items():
        if varname not in vars_:
            continue
        per_domain.setdefault(domain.ident, {})[varname] = vars_[varname]

    # The global setting wato_enabled is not registered in the configuration domains
    # since the user must not change it directly. It is set by D-WATO on slave sites.
    if "wato_enabled" in vars_:
        per_domain.setdefault(ConfigDomainGUI.ident, {})["wato_enabled"] = vars_["wato_enabled"]
    if "userdb_automatic_sync" in vars_:
        per_domain.setdefault(ConfigDomainGUI.ident,
                              {})["userdb_automatic_sync"] = vars_["userdb_automatic_sync"]

    for domain in ConfigDomain.enabled_domains():
        if site_specific:
            domain().save_site_globals(per_domain.get(domain.ident, {}))
        else:
            domain().save(per_domain.get(domain.ident, {}))


def save_site_global_settings(vars_):
    save_global_settings(vars_, site_specific=True)


#.
#   .--Distributed WATO----------------------------------------------------.
#   |                 ____     __        ___  _____ ___                    |
#   |                |  _ \    \ \      / / \|_   _/ _ \                   |
#   |                | | | |____\ \ /\ / / _ \ | || | | |                  |
#   |                | |_| |_____\ V  V / ___ \| || |_| |                  |
#   |                |____/       \_/\_/_/   \_\_| \___/                   |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Code for distributed WATO. Site configuration. Pushing snapshots.   |
#   '----------------------------------------------------------------------'


class SiteManagement(object):
    @classmethod
    def connection_method_valuespec(cls):
        # ValueSpecs for the more complex input fields
        return CascadingDropdown(
            orientation="horizontal",
            choices=cls._connection_choices(),
        )

    @classmethod
    def _connection_choices(cls):
        conn_choices = [
            (None, _("Connect to the local site")),
            ("tcp", _("Connect via TCP"), cls._tcp_port_valuespec()),
            ("unix", _("Connect via UNIX socket"),
             TextAscii(label=_("Path:"), size=40, allow_empty=False)),
        ]
        return conn_choices

    @classmethod
    def _tcp_port_valuespec(cls):
        return Tuple(
            title=_("TCP Port to connect to"),
            orientation="float",
            elements=[
                TextAscii(
                    label=_("Host:"),
                    allow_empty=False,
                    size=15,
                ),
                Integer(
                    label=_("Port:"),
                    minvalue=1,
                    maxvalue=65535,
                    default_value=6557,
                ),
            ])

    @classmethod
    def user_sync_valuespec(cls):
        return CascadingDropdown(
            orientation="horizontal",
            choices=[
                (None, _("Disable automatic user synchronization (use master site users)")),
                ("all", _("Sync users with all connections")),
                ("list", _("Sync with the following LDAP connections"),
                 ListChoice(
                     choices=userdb.connection_choices,
                     allow_empty=False,
                 )),
            ])

    @classmethod
    def validate_configuration(cls, site_id, site_configuration, all_sites):
        if not re.match("^[-a-z0-9A-Z_]+$", site_id):
            raise MKUserError(
                "id", _("The site id must consist only of letters, digit and the underscore."))

        if not site_configuration.get("alias"):
            raise MKUserError(
                "alias",
                _("Please enter an alias name or description for the site %s.") % site_id)

        if site_configuration.get("url_prefix") and site_configuration.get("url_prefix")[-1] != "/":
            raise MKUserError("url_prefix", _("The URL prefix must end with a slash."))

        # Connection
        if site_configuration.get("socket") == None and site_id != config.omd_site():
            raise MKUserError(
                "method_sel",
                _("You can only configure a local site connection for "
                  "the local site. The site IDs ('%s' and '%s') are "
                  "not equal.") % (site_id, config.omd_site()))

        # Timeout
        if "timeout" in site_configuration:
            timeout = site_configuration["timeout"]
            try:
                int(timeout)
            except ValueError:
                raise MKUserError("timeout",
                                  _("The timeout %s is not a valid integer number.") % timeout)

        # Status host
        status_host = site_configuration.get("status_host")
        if status_host:
            status_host_site, status_host_name = status_host
            if status_host_site not in all_sites:
                raise MKUserError("sh_site", _("The site of the status host does not exist."))
            if status_host_site == site_id:
                raise MKUserError("sh_site",
                                  _("You cannot use the site itself as site of the status host."))
            if not status_host_name:
                raise MKUserError("sh_host", _("Please specify the name of the status host."))

        if site_configuration.get("replication"):
            multisiteurl = site_configuration.get("multisiteurl")
            if not site_configuration.get("multisiteurl"):
                raise MKUserError("multisiteurl",
                                  _("Please enter the Multisite URL of the slave site."))

            if not multisiteurl.endswith("/check_mk/"):
                raise MKUserError("multisiteurl", _("The Multisite URL must end with /check_mk/"))

            if not multisiteurl.startswith("http://") and \
               not multisiteurl.startswith("https://"):
                raise MKUserError(
                    "multisiteurl",
                    _("The Multisites URL must begin with <tt>http://</tt> or <tt>https://</tt>."))

            if "socket" not in site_configuration:
                raise MKUserError("replication",
                                  _("You cannot do replication with the local site."))

        # User synchronization
        user_sync_valuespec = cls.user_sync_valuespec()
        user_sync_valuespec.validate_value(site_configuration.get("user_sync"), "user_sync")

    @classmethod
    def load_sites(cls):
        if not os.path.exists(sites_mk):
            return config.default_single_site_configuration()

        vars_ = {"sites": {}}
        execfile(sites_mk, vars_, vars_)

        # Be compatible to old "disabled" value in socket attribute.
        # Can be removed one day.
        for site in vars_['sites'].itervalues():
            socket = site.get("socket")
            if socket == 'disabled':
                site['disabled'] = True
                del site['socket']

            elif isinstance(socket, tuple) and socket[0] == "proxy":
                site["socket"] = ("proxy", cls.transform_old_connection_params(socket[1]))

        if not vars_["sites"]:
            # There seem to be installations out there which have a sites.mk
            # which has an empty sites dictionary. Apply the default configuration
            # for these sites too.
            return config.default_single_site_configuration()
        return vars_["sites"]

    @classmethod
    def save_sites(cls, sites, activate=True):
        store.mkdir(multisite_dir)
        store.save_to_mk_file(sites_mk, "sites", sites)

        # Do not activate when just the site's global settings have
        # been edited
        if activate:
            config.load_config()  # make new site configuration active
            update_distributed_wato_file(sites)
            Folder.invalidate_caches()
            need_sidebar_reload()

            create_nagvis_backends(sites)

            # Call the sites saved hook
            call_hook_sites_saved(sites)

    @classmethod
    def delete_site(cls, site_id):
        all_sites = cls.load_sites()
        if site_id not in all_sites:
            raise MKUserError(None, _("Unable to delete unknown site id: %s") % site_id)

        # Make sure that site is not being used by hosts and folders
        if site_id in Folder.root_folder().all_site_ids():
            search_url = html.makeactionuri([
                ("host_search_change_site", "on"),
                ("host_search_site", site_id),
                ("host_search", "1"),
                ("folder", ""),
                ("mode", "search"),
                ("filled_in", "edit_host"),
            ])
            raise MKUserError(
                None,
                _("You cannot delete this connection. It has folders/hosts "
                  "assigned to it. You can use the <a href=\"%s\">host "
                  "search</a> to get a list of the hosts.") % search_url)

        domains = cls._affected_config_domains()

        del all_sites[site_id]
        cls.save_sites(all_sites)
        clear_site_replication_status(site_id)
        add_change(
            "edit-sites",
            _("Deleted site %s") % html.render_tt(site_id),
            domains=domains,
            sites=[default_site()])
        return None

    @classmethod
    def _affected_config_domains(cls):
        return [ConfigDomainGUI]

    @classmethod
    def transform_old_connection_params(cls, value):
        return value


class CRESiteManagement(SiteManagement):
    pass


# TODO: This has been moved directly into watolib because it was not easily possible
# to extract SiteManagement() to a separate module (depends on Folder, add_change, ...).
# As soon as we have untied this we should re-establish a watolib plugin hierarchy and
# move this to a CEE/CME specific watolib plugin
@config_domain_registry.register
class ConfigDomainLiveproxy(ConfigDomain):
    needs_sync = False
    needs_activation = False
    ident = "liveproxyd"
    in_global_settings = True

    @classmethod
    def enabled(cls):
        return not cmk.is_raw_edition() and config.liveproxyd_enabled

    def config_dir(self):
        return liveproxyd_config_dir

    def save(self, settings, site_specific=False):
        super(ConfigDomainLiveproxy, self).save(settings, site_specific=site_specific)
        self.activate()

    def activate(self):
        log_audit(None, "liveproxyd-activate",
                  _("Activating changes of Livestatus Proxy configuration"))

        try:
            pidfile = cmk.paths.livestatus_unix_socket + "proxyd.pid"
            try:
                pid = int(file(pidfile).read().strip())
                os.kill(pid, 10)
            except IOError, e:
                if e.errno == 2:  # No such file or directory
                    pass
                else:
                    raise
        except Exception, e:
            logger.exception()
            html.show_warning(
                _("Could not reload Livestatus Proxy: %s. See web.log "
                  "for further information.") % e)

    # TODO: Move default values to common module to share
    # the defaults between the GUI code an liveproxyd.
    def default_globals(self):
        return {
            "liveproxyd_log_levels": {
                "cmk.liveproxyd": cmk.log.INFO,
            },
            "liveproxyd_default_connection_params":
                ConfigDomainLiveproxy.connection_params_defaults(),
        }

    @staticmethod
    def connection_params_defaults():
        return {
            "channels": 5,
            "heartbeat": (5, 2.0),
            "channel_timeout": 3.0,
            "query_timeout": 120.0,
            "connect_retry": 4.0,
            "cache": True,
        }


# TODO: This has been moved directly into watolib because it was not easily possible
# to extract SiteManagement() to a separate module (depends on Folder, add_change, ...).
# As soon as we have untied this we should re-establish a watolib plugin hierarchy and
# move this to a CEE/CME specific watolib plugin
class CEESiteManagement(SiteManagement):
    @classmethod
    def _connection_choices(cls):
        choices = super(CEESiteManagement, cls)._connection_choices()

        choices.append(("proxy", _("Use Livestatus Proxy Daemon"), Transform(
            Dictionary(
                optional_keys = ["tcp"],
                columns = 1,
                elements = [
                    ("socket", Alternative(
                        title = _("Connect to"),
                        style = "dropdown",
                        elements = [
                            FixedValue(None,
                                title = _("Connect to the local site"),
                                totext = "",
                            ),
                            cls._tcp_port_valuespec(),
                        ],
                    )),
                    ("tcp", LivestatusViaTCP(
                        title = _("Allow access via TCP"),
                        help = _("This option can be useful to build a cascading distributed setup. "
                                 "The Livestatus Proxy of this site connects to the site configured "
                                 "here via Livestatus and opens up a TCP port for clients. The "
                                 "requests of the clients are forwarded to the destination site. "
                                 "You need to configure a TCP port here that is not used on the "
                                 "local system yet."),
                        tcp_port = 6560,
                    )),
                    ("params", Alternative(
                        title = _("Parameters"),
                        style = "dropdown",
                        elements = [
                            FixedValue(None,
                                title = _("Use global connection parameters"),
                                totext = _("Use the <a href=\"%s\">global parameters</a> for this connection") % \
                                    "wato.py?mode=edit_configvar&site=&varname=liveproxyd_default_connection_params",
                            ),
                            Dictionary(
                                title = _("Use custom connection parameters"),
                                elements = cls.liveproxyd_connection_params_elements(),
                            ),
                        ],
                    )),
                ],
            ),
            forth = cls.transform_old_connection_params,
        )))

        return choices

    @classmethod
    def liveproxyd_connection_params_elements(cls):
        defaults = ConfigDomainLiveproxy.connection_params_defaults()

        return [
            ("channels",
             Integer(
                 title=_("Number of channels to keep open"),
                 minvalue=2,
                 maxvalue=50,
                 default_value=defaults["channels"],
             )),
            ("heartbeat",
             Tuple(
                 title=_("Regular heartbeat"),
                 orientation="float",
                 elements=[
                     Integer(
                         label=_("One heartbeat every"),
                         unit=_("sec"),
                         minvalue=1,
                         default_value=defaults["heartbeat"][0],
                     ),
                     Float(
                         label=_("with a timeout of"),
                         unit=_("sec"),
                         minvalue=0.1,
                         default_value=defaults["heartbeat"][1],
                         display_format="%.1f"),
                 ])),
            ("channel_timeout",
             Float(
                 title=_("Timeout waiting for a free channel"),
                 minvalue=0.1,
                 default_value=defaults["channel_timeout"],
                 unit=_("sec"),
             )),
            ("query_timeout",
             Float(
                 title=_("Total query timeout"),
                 minvalue=0.1,
                 unit=_("sec"),
                 default_value=defaults["query_timeout"],
             )),
            ("connect_retry",
             Float(
                 title=_("Cooling period after failed connect/heartbeat"),
                 minvalue=0.1,
                 unit=_("sec"),
                 default_value=defaults["connect_retry"],
             )),
            ("cache",
             Checkbox(
                 title=_("Enable Caching"),
                 label=_("Cache several non-status queries"),
                 help=_("This option will enable the caching of several queries that "
                        "need no current data. This reduces the number of Livestatus "
                        "queries to sites and cuts down the response time of remote "
                        "sites with large latencies."),
                 default_value=defaults["cache"],
             )),
        ]

    # Each site had it's individual connection params set all time. Detect whether or
    # not a site is at the default configuration and set the config to
    # "use default connection params". In case the values are not similar to the current
    # defaults just change the data structure to the new one.
    @classmethod
    def transform_old_connection_params(cls, value):
        if "params" in value:
            return value

        new_value = {
            "socket": value.pop("socket"),
            "params": value,
        }

        defaults = ConfigDomainLiveproxy.connection_params_defaults()
        for key, val in value.items():
            if val == defaults[key]:
                del value[key]

        if not value:
            new_value["params"] = None

        return new_value

    @classmethod
    def save_sites(cls, sites, activate=True):
        super(CEESiteManagement, cls).save_sites(sites, activate)

        if activate and config.liveproxyd_enabled:
            cls._save_liveproxyd_config(sites)

    @classmethod
    def _save_liveproxyd_config(cls, sites):
        path = cmk.paths.default_config_dir + "/liveproxyd.mk"

        conf = {}
        for siteid, siteconf in sites.items():
            s = siteconf.get("socket")
            if isinstance(s, tuple) and s[0] == "proxy":
                conf[siteid] = {
                    "socket": s[1]["socket"],
                }

                if "tcp" in s[1]:
                    conf[siteid]["tcp"] = s[1]["tcp"]

                if s[1]["params"]:
                    conf[siteid].update(s[1]["params"])

        store.save_to_mk_file(path, "sites", conf)

        ConfigDomainLiveproxy().activate()

    @classmethod
    def _affected_config_domains(cls):
        domains = super(CEESiteManagement, cls)._affected_config_domains()
        if config.liveproxyd_enabled:
            domains.append(ConfigDomainLiveproxy)
        return domains


class SiteManagementFactory(object):
    @staticmethod
    def factory():
        if cmk.is_raw_edition():
            cls = CRESiteManagement
        else:
            cls = CEESiteManagement

        return cls()


def get_login_secret(create_on_demand=False):
    path = var_dir + "automation_secret.mk"

    secret = store.load_data_from_file(path)
    if secret != None:
        return secret

    if not create_on_demand:
        return None

    secret = utils.get_random_string(32)
    store.save_data_to_file(path, secret)
    return secret


# Returns the ID of our site. This function only works in replication
# mode and looks for an entry connecting to the local socket.
def our_site_id():
    for site_id in config.allsites():
        if config.site_is_local(site_id):
            return site_id
    return None


def create_nagvis_backends(sites):
    cfg = [
        '; MANAGED BY CHECK_MK WATO - Last Update: %s' % time.strftime('%Y-%m-%d %H:%M:%S'),
    ]
    for site_id, site in sites.items():
        if site == config.omd_site():
            continue  # skip local site, backend already added by omd
        if 'socket' not in site:
            continue  # skip sites without configured sockets

        # Handle special data format of livestatus proxy config
        if isinstance(site['socket'], tuple):
            if isinstance(site['socket'][1]['socket'], tuple):
                socket = 'tcp:%s:%d' % site['socket'][1]['socket']
            elif site['socket'][1]['socket'] is None:
                socket = 'unix:%s' % cmk.paths.livestatus_unix_socket
            else:
                raise NotImplementedError()

        else:
            socket = site['socket']

        cfg += [
            '',
            '[backend_%s]' % site_id,
            'backendtype="mklivestatus"',
            'socket="%s"' % socket,
        ]

        if site.get("status_host"):
            cfg.append('statushost="%s"' % ':'.join(site['status_host']))

    store.save_file('%s/etc/nagvis/conf.d/cmk_backends.ini.php' % cmk.paths.omd_root,
                    '\n'.join(cfg))


def create_distributed_wato_file(siteid, is_slave):
    output = wato_fileheader()
    output += ("# This file has been created by the master site\n"
               "# push the configuration to us. It makes sure that\n"
               "# we only monitor hosts that are assigned to our site.\n\n")
    output += "distributed_wato_site = '%s'\n" % siteid
    output += "is_wato_slave_site = %r\n" % is_slave

    store.save_file(cmk.paths.check_mk_config_dir + "/distributed_wato.mk", output)


def delete_distributed_wato_file():
    p = cmk.paths.check_mk_config_dir + "/distributed_wato.mk"
    # We do not delete the file but empty it. That way
    # we do not need write permissions to the conf.d
    # directory!
    if os.path.exists(p):
        store.save_file(p, "")


# Makes sure, that in distributed mode we monitor only
# the hosts that are directly assigned to our (the local)
# site.
def update_distributed_wato_file(sites):
    # Note: we cannot access config.sites here, since we
    # are currently in the process of saving the new
    # site configuration.
    distributed = False
    for siteid, site in sites.items():
        if site.get("replication"):
            distributed = True
        if config.site_is_local(siteid):
            create_distributed_wato_file(siteid, is_slave=False)

    # Remove the distributed wato file
    # a) If there is no distributed WATO setup
    # b) If the local site could not be gathered
    if not distributed:  # or not found_local:
        delete_distributed_wato_file()


def do_site_login(site_id, name, password):
    sites = SiteManagementFactory().factory().load_sites()
    site = sites[site_id]
    if not name:
        raise MKUserError("_name", _("Please specify your administrator login on the remote site."))
    if not password:
        raise MKUserError("_passwd", _("Please specify your password."))

    # Trying basic auth AND form based auth to ensure the site login works.
    # Adding _ajaxid makes the web service fail silently with an HTTP code and
    # not output HTML code for an error screen.
    url = site["multisiteurl"] + 'login.py'
    post_data = {
        '_login': '1',
        '_username': name,
        '_password': password,
        '_origtarget': 'automation_login.py',
        '_plain_error': '1',
    }
    response = get_url(
        url, site.get('insecure', False), auth=(name, password), data=post_data).strip()
    if '<html>' in response.lower():
        message = _("Authentication to web service failed.<br>Message:<br>%s") % \
            html.strip_tags(html.strip_scripts(response))
        if config.debug:
            message += "<br>" + _("Automation URL:") + " <tt>%s</tt><br>" % url
        raise MKAutomationException(message)
    elif not response:
        raise MKAutomationException(_("Empty response from web service"))
    else:
        try:
            return ast.literal_eval(response)
        except:
            raise MKAutomationException(response)


def get_url(url, insecure, auth=None, data=None, files=None):
    response = requests.post(
        url,
        data=data,
        verify=not insecure,
        auth=auth,
        files=files,
    )

    response.encoding = "utf-8"  # Always decode with utf-8

    if response.status_code == 401:
        raise MKUserError("_passwd", _("Authentication failed. Invalid login/password."))

    elif response.status_code == 503 and "Site Not Started" in response.text:
        raise MKUserError(None, _("Site is not running"))

    elif response.status_code != 200:
        raise MKUserError(None, _("HTTP Error - %d: %s") % (response.status_code, response.text))

    return response.text


def check_mk_remote_automation(site_id,
                               command,
                               args,
                               indata,
                               stdin_data=None,
                               timeout=None,
                               sync=True):
    site = config.site(site_id)
    if "secret" not in site:
        raise MKGeneralException(
            _("Cannot connect to site \"%s\": The site is not logged in") % site.get(
                "alias", site_id))

    if not site.get("replication"):
        raise MKGeneralException(
            _("Cannot connect to site \"%s\": The replication is disabled") % site.get(
                "alias", site_id))

    if sync:
        sync_changes_before_remote_automation(site_id)

    # Now do the actual remote command
    response = do_remote_automation(
        config.site(site_id),
        "checkmk-automation",
        [
            ("automation", command),  # The Check_MK automation command
            ("arguments", mk_repr(args)),  # The arguments for the command
            ("indata", mk_repr(indata)),  # The input data
            ("stdin_data", mk_repr(stdin_data)),  # The input data for stdin
            ("timeout", mk_repr(timeout)),  # The timeout
        ])
    return response


# If the site is not up-to-date, synchronize it first.
def sync_changes_before_remote_automation(site_id):
    manager = ActivateChangesManager()
    manager.load()

    if not manager.is_sync_needed(site_id):
        return

    logger.info("Syncing %s" % site_id)

    manager.start([site_id], activate_foreign=True, prevent_activate=True)

    # Wait maximum 30 seconds for sync to finish
    timeout = 30
    while manager.is_running() and timeout > 0.0:
        time.sleep(0.5)
        timeout -= 0.5

    state = manager.get_site_state(site_id)
    if state and state["_state"] != "success":
        logger.error(
            _("Remote automation tried to sync pending changes but failed: %s") %
            state.get("_status_details"))


def do_remote_automation(site, command, vars_):
    base_url = site["multisiteurl"]
    secret = site.get("secret")
    if not secret:
        raise MKAutomationException(_("You are not logged into the remote site."))

    url = base_url + "automation.py?" + \
        html.urlencode_vars([
               ("command", command),
               ("secret",  secret),
               ("debug",   config.debug and '1' or '')
        ])

    response = get_url(url, site.get('insecure', False), data=dict(vars_))

    if not response:
        raise MKAutomationException(_("Empty output from remote site."))

    try:
        response = ast.literal_eval(response)
    except:
        # The remote site will send non-Python data in case of an error.
        raise MKAutomationException("%s: <pre>%s</pre>" % (_("Got invalid data"), response))

    return response


# Returns the ID of the default site. This is the site the main folder has
# configured by default. It inherits to all folders and hosts which don't have
# a site set on their own.
# In standalone and master sites this defaults to the local site. In distributed
# slave sites, we don't know the site ID of the master site. We set this explicit
# to false to configure that this host is monitored by another site (that we don't
# know about).
def default_site():
    if is_wato_slave_site():
        return False
    return config.default_site()


# Returns a list of site ids which gets the Event Console configuration replicated
def get_event_console_sync_sites():
    return [s[0] for s in config.get_event_console_site_choices()]


def get_notification_sync_sites():
    return sorted(site_id for site_id, _site in config.wato_slave_sites()
                  if not config.site_is_local(site_id))


# TODO: cleanup all call sites to this name
is_wato_slave_site = config.is_wato_slave_site
site_choices = config.site_choices


def load_site_replication_status(site_id, lock=False):
    return store.load_data_from_file(site_replication_status_path(site_id), {}, lock)


def save_site_replication_status(site_id, repl_status):
    store.save_data_to_file(site_replication_status_path(site_id), repl_status, pretty=False)
    cleanup_legacy_replication_status()


# This can be removed one day. It is only meant for cleaning up the pre 1.4.0
# global replication status file.
def cleanup_legacy_replication_status():
    try:
        os.unlink(var_dir + "replication_status.mk")
    except OSError, e:
        if e.errno == 2:
            pass  # Not existant -> OK
        else:
            raise


def clear_site_replication_status(site_id):
    try:
        os.unlink(site_replication_status_path(site_id))
    except OSError, e:
        if e.errno == 2:
            pass  # Not existant -> OK
        else:
            raise

    ActivateChanges().confirm_site_changes(site_id)


def site_replication_status_path(site_id):
    return "%sreplication_status_%s.mk" % (var_dir, site_id)


def site_changes_path(site_id):
    return os.path.join(var_dir, "replication_changes_%s.mk" % site_id)


def load_replication_status(lock=False):
    return {site_id: load_site_replication_status(site_id, lock=lock) for site_id in config.sites}


def save_replication_status(status):
    status = {}

    for site_id, repl_status in config.sites.items():
        save_site_replication_status(site_id, repl_status)


# Updates one or more dict elements of a site in an atomic way.
def update_replication_status(site_id, vars_):
    store.mkdir(var_dir)

    repl_status = load_site_replication_status(site_id, lock=True)
    try:
        repl_status.setdefault("times", {})
        repl_status.update(vars_)
    finally:
        save_site_replication_status(site_id, repl_status)


def automation_push_snapshot():
    site_id = html.var("siteid")

    verify_slave_site_config(site_id)

    tarcontent = html.request.uploaded_file("snapshot")
    if not tarcontent:
        raise MKGeneralException(_('Invalid call: The snapshot is missing.'))
    tarcontent = tarcontent[2]

    multitar.extract_from_buffer(tarcontent, replication_paths)

    try:
        save_site_globals_on_slave_site(tarcontent)

        confirm_all_local_changes()  # pending changes are lost

        call_hook_snapshot_pushed()

        # Create rule making this site only monitor our hosts
        create_distributed_wato_file(site_id, is_slave=True)
    except Exception:
        raise MKGeneralException(
            _("Failed to deploy configuration: \"%s\". "
              "Please note that the site configuration has been synchronized "
              "partially.") % traceback.format_exc())

    log_audit(None, "replication", _("Synchronized with master (my site id is %s.)") % site_id)

    return True


def save_site_globals_on_slave_site(tarcontent):
    tmp_dir = cmk.paths.tmp_dir + "/sitespecific-%s" % id(html)
    try:
        if not os.path.exists(tmp_dir):
            store.mkdir(tmp_dir)

        multitar.extract_from_buffer(tarcontent, [("dir", "sitespecific", tmp_dir)])

        site_globals = store.load_data_from_file(tmp_dir + "/sitespecific.mk", {})
        save_site_global_settings(site_globals)
    finally:
        shutil.rmtree(tmp_dir)


automation_commands["push-snapshot"] = automation_push_snapshot


def verify_slave_site_config(site_id):
    if not site_id:
        raise MKGeneralException(_("Missing variable siteid"))

    our_id = config.omd_site()

    if not config.is_single_local_site():
        raise MKGeneralException(
            _("Configuration error. You treat us as "
              "a <b>slave</b>, but we have an own distributed WATO configuration!"))

    if our_id != None and our_id != site_id:
        raise MKGeneralException(
            _("Site ID mismatch. Our ID is '%s', but you are saying we are '%s'.") % (our_id,
                                                                                      site_id))

    # Make sure there are no local changes we would lose!
    changes = ActivateChanges()
    changes.load()
    pending = list(reversed(changes.grouped_changes()))
    if pending:
        message = _("There are %d pending changes that would get lost. The most recent are: "
                   ) % len(pending)
        message += ", ".join(change["text"] for _change_id, change in pending[:10])

        raise MKGeneralException(message)


# TODO: Recode to new sync?
def push_user_profile_to_site(site, user_id, profile):
    url = site["multisiteurl"] + "automation.py?" + html.urlencode_vars([
        ("command", "push-profile"),
        ("secret", site["secret"]),
        ("siteid", site['id']),
        ("debug", config.debug and "1" or ""),
    ])

    response = get_url(
        url, site.get('insecure', False), data={
            'user_id': user_id,
            'profile': mk_repr(profile),
        })

    if not response:
        raise MKAutomationException(_("Empty output from remote site."))

    try:
        response = mk_eval(response)
    except:
        # The remote site will send non-Python data in case of an error.
        raise MKAutomationException("%s: <pre>%s</pre>" % (_("Got invalid data"), response))
    return response


# Add pending entry to make sync possible later for admins
def add_profile_replication_change(site_id, result):
    add_change(
        "edit-users",
        _('Profile changed (sync failed: %s)') % result,
        sites=[site_id],
        need_restart=False)


class ActivateChanges(object):
    def __init__(self):
        self._repstatus = {}

        # Changes grouped by site
        self._changes_by_site = {}

        # A list of changes ordered by time and grouped by the change.
        # Each change contains a list of affected sites.
        self._changes = []

        super(ActivateChanges, self).__init__()

    def load(self):
        self._load_replication_status()
        self._load_changes_by_site()
        self._load_changes_by_id()

    def _load_replication_status(self):
        self._repstatus = load_replication_status()

    def _load_changes_by_site(self):
        self._changes_by_site = {}

        self._migrate_old_changes()

        for site_id in self.activation_site_ids():
            self._changes_by_site[site_id] = self._load_site_changes(site_id)

    # Between 1.4.0i* and 1.4.0b4 the changes were stored in
    # self._repstatus[site_id]["changes"], migrate them.
    # TODO: Drop this one day.
    def _migrate_old_changes(self):
        has_old_changes = False
        for site_id, status in self._repstatus.items():
            if status.get("changes"):
                has_old_changes = True
                break

        if not has_old_changes:
            return

        repstatus = load_replication_status(lock=True)

        for site_id, status in self._repstatus.items():
            for change_spec in status.get("changes", []):
                self._save_change(site_id, change_spec)

            try:
                del status["changes"]
            except KeyError:
                pass

        save_replication_status(repstatus)

    # Parse the site specific changes file. The file format has been choosen
    # to be able to append changes without much cost. This is just a
    # intermmediate format for 1.4.x. In 1.5 we will reimplement WATO changes
    # and this very specific file format will vanish.
    def _load_site_changes(self, site_id, lock=False):
        path = site_changes_path(site_id)

        if lock:
            store.aquire_lock(path)

        changes = []
        try:
            for entry in open(path).read().split("\0"):
                if entry:
                    changes.append(ast.literal_eval(entry))
        except IOError, e:
            if e.errno == 2:  # No such file or directory
                pass
            else:
                raise
        except:
            if lock:
                store.release_lock(path)
            raise

        return changes

    def confirm_site_changes(self, site_id):
        try:
            os.unlink(site_changes_path(site_id))
        except OSError, e:
            if e.errno == 2:
                pass  # Not existant -> OK
            else:
                raise

        need_sidebar_reload()

    def _save_site_changes(self, site_id, changes):
        # First truncate the file
        open(site_changes_path(site_id), "w")

        for change_spec in changes:
            self._save_change(site_id, change_spec)

    def _save_change(self, site_id, change_spec):
        path = site_changes_path(site_id)
        try:
            store.aquire_lock(path)

            with open(path, "a+") as f:
                f.write(repr(change_spec) + "\0")
                f.flush()
                os.fsync(f.fileno())

            os.chmod(path, 0660)

        except Exception, e:
            raise MKGeneralException(_("Cannot write file \"%s\": %s") % (path, e))

        finally:
            store.release_lock(path)

    # Returns a list of changes ordered by time and grouped by the change.
    # Each change contains a list of affected sites.
    def _load_changes_by_id(self):
        changes = {}

        for site_id, site_changes in self._changes_by_site.items():
            if not site_changes:
                continue

            for change in site_changes:
                change_id = change["id"]

                if change_id not in changes:
                    changes[change_id] = change.copy()

                affected_sites = changes[change_id].setdefault("affected_sites", [])
                affected_sites.append(site_id)

        self._changes = sorted(changes.items(), key=lambda k_v: k_v[1]["time"])

    def grouped_changes(self):
        return self._changes

    def _changes_of_site(self, site_id):
        return self._changes_by_site[site_id]

    # Returns the list of sites that are affected by WATO changes.
    # these sites are shown on activation page and get change entries
    # added during WATO changes.
    def _activation_sites(self):
        return [(site_id, site)
                for site_id, site in config.user.authorized_sites()
                if config.site_is_local(site_id) or site.get("replication")]

    def activation_site_ids(self):
        return [s[0] for s in self._activation_sites()]

    # Returns the list of sites that should be used when activating all
    # affected sites.
    def dirty_and_active_activation_sites(self):
        dirty = []
        for site_id, site in self._activation_sites():
            status = self._get_site_status(site_id, site)[1]
            is_online = self._site_is_online(status)
            is_logged_in = self._site_is_logged_in(site_id, site)

            if is_online and is_logged_in and self._changes_of_site(site_id):
                dirty.append(site_id)
        return dirty

    def _site_is_logged_in(self, site_id, site):
        return config.site_is_local(site_id) or "secret" in site

    def _site_is_online(self, status):
        return status in ["online", "disabled"]

    def _get_site_status(self, site_id, site):
        if site.get("disabled"):
            site_status = {}
            status = "disabled"
        else:
            site_status = sites.state(site_id, {})
            status = site_status.get("state", "unknown")

        return site_status, status

    def _site_has_foreign_changes(self, site_id):
        changes = self._changes_of_site(site_id)
        return bool([c for c in changes if self._is_foreign(c)])

    def is_sync_needed(self, site_id):
        if config.site_is_local(site_id):
            return False

        return any([c["need_sync"] for c in self._changes_of_site(site_id)])

    def _is_activate_needed(self, site_id):
        return any([c["need_restart"] for c in self._changes_of_site(site_id)])

    # This function returns the last known persisted activation state
    def _last_activation_state(self, site_id):
        manager = ActivateChangesManager()
        site_state_path = os.path.join(manager.activation_persisted_dir,
                                       manager.site_filename(site_id))
        return store.load_data_from_file(site_state_path, {})

    def _get_last_change_id(self):
        return self._changes[-1][1]["id"]

    def has_changes(self):
        return bool(self._changes)

    def has_foreign_changes(self):
        return any(change for _change_id, change in self._changes if self._is_foreign(change))

    def _has_foreign_changes_on_any_site(self):
        return any(change for _change_id, change in self._changes
                   if self._is_foreign(change) and self._affects_all_sites(change))

    def _is_foreign(self, change):
        return change["user_id"] and change["user_id"] != config.user.id

    def _affects_all_sites(self, change):
        return not set(change["affected_sites"]).symmetric_difference(
            set(self.activation_site_ids()))

    def update_activation_time(self, site_id, ty, duration):
        repl_status = load_site_replication_status(site_id, lock=True)
        try:
            times = repl_status.setdefault("times", {})

            if ty not in times:
                times[ty] = duration
            else:
                times[ty] = 0.8 * times[ty] + 0.2 * duration
        finally:
            save_site_replication_status(site_id, repl_status)

    def get_activation_times(self, site_id):
        repl_status = load_site_replication_status(site_id)
        return repl_status.get("times", {})

    def get_activation_time(self, site_id, ty, deflt=None):
        return self.get_activation_times(site_id).get(ty, deflt)


class ActivateChangesWriter(ActivateChanges):
    def add_change(self, action_name, text, obj, add_user, need_sync, need_restart, domains, sites):
        # Default to a core only change
        if domains == None:
            domains = [ConfigDomainCore]

        # All replication sites in case no specific site is given
        if sites == None:
            sites = self.activation_site_ids()

        change_id = self._new_change_id()

        for site_id in sites:
            self._add_change_to_site(site_id, change_id, action_name, text, obj, add_user,
                                     need_sync, need_restart, domains)

    def _new_change_id(self):
        return utils.gen_id()

    def _add_change_to_site(self, site_id, change_id, action_name, text, obj, add_user, need_sync,
                            need_restart, domains):
        # Individual changes may override the domain restart default value
        if need_restart == None:
            need_restart = any([d.needs_activation for d in domains])

        if need_sync == None:
            need_sync = any([d.needs_sync for d in domains])

        def serialize_object(obj):
            if obj == None:
                return None
            return obj.__class__.__name__, obj.ident()

        # Using attrencode here is against our regular rule to do the escaping
        # at the last possible time: When rendering. But this here is the last
        # place where we can distinguish between HTML() encapsulated (already)
        # escaped / allowed HTML and strings to be escaped.
        text = html.attrencode(text)

        self._save_change(
            site_id, {
                "id": change_id,
                "action_name": action_name,
                "text": "%s" % text,
                "object": serialize_object(obj),
                "user_id": config.user.id if add_user else None,
                "domains": [d.ident for d in domains],
                "time": time.time(),
                "need_sync": need_sync,
                "need_restart": need_restart,
            })


class ActivateChangesManager(ActivateChanges):
    # Temporary data
    activation_tmp_base_dir = cmk.paths.tmp_dir + "/wato/activation"
    # Persisted data
    activation_persisted_dir = cmk.paths.var_dir + "/wato/activation"

    def __init__(self):
        self._sites = []
        self._activate_until = None
        self._comment = None
        self._activate_foreign = False
        self._activation_id = None
        self._snapshot_id = None
        if not os.path.exists(self.activation_persisted_dir):
            os.makedirs(self.activation_persisted_dir)
        super(ActivateChangesManager, self).__init__()

    def load_activation(self, activation_id):
        self._activation_id = activation_id

        if not os.path.exists(self._info_path()):
            raise MKUserError(None, "Unknown activation process")

        self._load_activation()

    # Creates the snapshot and starts the single site sync processes. In case these
    # steps could not be started, exceptions are raised and have to be handled by
    # the caller.
    #
    # On success a separate thread is started that writes it's state to a state file
    # below "var/check_mk/wato/activation/<id>_general.state". The <id> is written to
    # the javascript code and can be used for fetching the activation state while
    # the activation is running.
    #
    # For each site a separate thread is started that controls the activation of the
    # configuration on that site. The state is checked by the general activation
    # thread.
    def start(self,
              sites,
              activate_until=None,
              comment=None,
              activate_foreign=False,
              prevent_activate=False):
        self._sites = self._get_sites(sites)

        if activate_until == None:
            self._activate_until = self._get_last_change_id()
        else:
            self._activate_until = activate_until

        self._comment = comment
        self._activate_foreign = activate_foreign
        self._activation_id = self._new_activation_id()
        self._time_started = time.time()
        self._snapshot_id = None
        self._prevent_activate = prevent_activate

        self._verify_valid_host_config()
        self._save_activation()

        self._pre_activate_changes()
        self._create_snapshots()
        self._save_activation()

        self._start_activation()
        self._do_housekeeping()

        return self._activation_id

    def _verify_valid_host_config(self):
        defective_hosts = validate_all_hosts([], force_all=True)
        if defective_hosts:
            raise MKUserError(
                None,
                _("You cannot activate changes while some hosts have "
                  "an invalid configuration: ") + ", ".join([
                      '<a href="%s">%s</a>' % (folder_preserving_link([("mode", "edit_host"),
                                                                       ("host", hn)]), hn)
                      for hn in defective_hosts
                  ]))

    def activate_until(self):
        return self._activate_until

    def wait_for_completion(self):
        while self.is_running():
            time.sleep(0.5)

    # Check whether or not at least one site thread is still working
    # (flock on the <activation_id>/site_<site_id>.mk file)
    def is_running(self):
        state = self.get_state()

        for site_id in self._sites:
            site_state = state["sites"][site_id]

            # The site_state file may be missing/empty, if the operation has started recently.
            # However, if the file is still missing after a considerable amount
            # of time, we consider this site activation as dead
            seconds_since_start = time.time() - self._time_started
            if site_state == {} and seconds_since_start > html.request.request_timeout - 10:
                continue

            if site_state == {} or site_state["_phase"] == PHASE_INITIALIZED:
                # Just been initialized. Treat as running as it has not been
                # started and could not lock the site stat file yet.
                return True  # -> running

            # Check whether or not the process is still there
            try:
                os.kill(site_state["_pid"], 0)
                return True  # -> running
            except OSError, e:
                # 3: not running
                # 1: operation not permitted (another process reused this)
                if e.errno in [3, 1]:
                    pass  # -> not running
                else:
                    raise

        return False  # No site reported running -> not running

    def _new_activation_id(self):
        return utils.gen_id()

    def _get_sites(self, sites):
        for site_id in sites:
            if site_id not in dict(self._activation_sites()):
                raise MKUserError("sites", _("The site \"%s\" does not exist.") % site_id)

        return sites

    def _info_path(self):
        return "%s/%s/info.mk" % (self.activation_tmp_base_dir, self._activation_id)

    def _site_snapshot_file(self, site_id):
        return "%s/%s/site_%s_sync.tar.gz" % (self.activation_tmp_base_dir, self._activation_id,
                                              site_id)

    def _load_activation(self):
        self.__dict__.update(store.load_data_from_file(self._info_path(), {}))

    def _save_activation(self):
        try:
            os.makedirs(os.path.dirname(self._info_path()))
        except OSError, e:
            if e.errno == 17:  # File exists
                pass
            else:
                raise

        return store.save_data_to_file(
            self._info_path(), {
                "_sites": self._sites,
                "_activate_until": self._activate_until,
                "_comment": self._comment,
                "_activate_foreign": self._activate_foreign,
                "_activation_id": self._activation_id,
                "_snapshot_id": self._snapshot_id,
                "_time_started": self._time_started,
            })

    # Give hooks chance to do some pre-activation things (and maybe stop
    # the activation)
    def _pre_activate_changes(self):
        try:
            call_hook_pre_distribute_changes()
        except Exception, e:
            logger.exception()
            if config.debug:
                raise
            raise MKUserError(None, _("Can not start activation: %s") % e)

    # Lock WATO modifications during snapshot creation
    def _create_snapshots(self):
        lock_exclusive()

        if not self._changes:
            raise MKUserError(None, _("Currently there are no changes to activate."))

        if self._get_last_change_id() != self._activate_until:
            raise MKUserError(
                None,
                _("Another change has been made in the meantime. Please review it "
                  "to ensure you also want to activate it now and start the "
                  "activation again."))

        # Create (legacy) WATO config snapshot
        start = time.time()
        logger.debug("Snapshot creation started")
        # TODO: Remove/Refactor once new changes mechanism has been implemented
        #       This single function is responsible for the slow activate changes (python tar packaging..)
        create_snapshot(self._comment)

        work_dir = os.path.join(self.activation_tmp_base_dir, self._activation_id)
        if cmk.is_managed_edition():
            import cmk.gui.cme.managed_snapshots as managed_snapshots
            managed_snapshots.CMESnapshotManager(
                work_dir, self._get_site_configurations()).generate_snapshots()
        else:
            self._generate_snapshots(work_dir)

        logger.debug("Snapshot creation took %.4f" % (time.time() - start))
        unlock_exclusive()

    def _get_site_configurations(self):
        site_configurations = {}

        for site_id in self._sites:
            site_configuration = {}
            self._check_snapshot_creation_permissions(site_id)

            site_configuration["snapshot_path"] = self._site_snapshot_file(site_id)
            site_configuration["work_dir"] = self._get_site_tmp_dir(site_id)

            # Change all default replication paths to be in the site specific temporary directory
            # These paths are then packed into the sync snapshot
            replication_components = []
            for entry in map(list, self._get_replication_components(site_id)):
                entry[2] = entry[2].replace(cmk.paths.omd_root, site_configuration["work_dir"])
                replication_components.append(tuple(entry))

            # Add site-specific global settings
            replication_components.append(("file", "sitespecific",
                                           os.path.join(site_configuration["work_dir"],
                                                        "site_globals", "sitespecific.mk")))

            # Generate a quick reference_by_name for each component
            site_configuration["snapshot_components"] = replication_components
            site_configuration["component_names"] = set()
            for component in site_configuration["snapshot_components"]:
                site_configuration["component_names"].add(component[1])

            site_configurations[site_id] = site_configuration

        return site_configurations

    def _generate_snapshots(self, work_dir):
        with multitar.SnapshotCreator(work_dir, replication_paths) as snapshot_creator:
            for site_id in self._sites:
                self._create_site_sync_snapshot(site_id, snapshot_creator)

    def _create_site_sync_snapshot(self, site_id, snapshot_creator=None):
        self._check_snapshot_creation_permissions(site_id)

        snapshot_path = self._site_snapshot_file(site_id)

        site_tmp_dir = self._get_site_tmp_dir(site_id)

        paths = self._get_replication_components(site_id)
        self.create_site_globals_file(site_id, site_tmp_dir)

        # Add site-specific global settings
        site_specific_paths = [("file", "sitespecific", os.path.join(site_tmp_dir,
                                                                     "sitespecific.mk"))]
        snapshot_creator.generate_snapshot(
            snapshot_path, paths, site_specific_paths, reuse_identical_snapshots=True)

        shutil.rmtree(site_tmp_dir)

    def _get_site_tmp_dir(self, site_id):
        return os.path.join(self.activation_tmp_base_dir, self._activation_id,
                            "sync-%s-specific-%.4f" % (site_id, time.time()))

    def _check_snapshot_creation_permissions(self, site_id):
        if self._site_has_foreign_changes(site_id) and not self._activate_foreign:
            if not config.user.may("wato.activateforeign"):
                raise MKUserError(
                    None,
                    _("There are some changes made by your colleagues that you can not "
                      "activate because you are not permitted to. You can only activate "
                      "the changes on the sites that are not affected by these changes. "
                      "<br>"
                      "If you need to activate your changes on all sites, please contact "
                      "a permitted user to do it for you."))

            raise MKUserError(
                None,
                _("There are some changes made by your colleagues and you did not "
                  "confirm to activate these changes. In order to proceed, you will "
                  "have to confirm the activation or ask you colleagues to activate "
                  "these changes in their own."))

    def _get_replication_components(self, site_id):
        paths = replication_paths[:]
        # Remove Event Console settings, if this site does not want it (might
        # be removed in some future day)
        if not config.sites[site_id].get("replicate_ec"):
            paths = [e for e in paths if e[1] not in ["mkeventd", "mkeventd_mkp"]]

        # Remove extensions if site does not want them
        if not config.sites[site_id].get("replicate_mkps"):
            paths = [e for e in paths if e[1] not in ["local", "mkps"]]

        return paths

    def create_site_globals_file(self, site_id, tmp_dir, sites=None):
        try:
            os.makedirs(tmp_dir)
        except OSError, e:
            if e.errno == 17:  # File exists
                pass
            else:
                raise

        if not sites:
            sites = SiteManagementFactory().factory().load_sites()
        site = sites[site_id]
        config = site.get("globals", {})

        config.update({
            "wato_enabled": not site.get("disable_wato", True),
            "userdb_automatic_sync": site.get("user_sync",
                                              userdb.user_sync_default_config(site_id)),
        })

        store.save_data_to_file(tmp_dir + "/sitespecific.mk", config)

    def _start_activation(self):
        self._log_activation()
        for site_id in self._sites:
            self._start_site_activation(site_id)

    def _start_site_activation(self, site_id):
        self._log_site_activation(site_id)

        # This is doing the first fork and the ActivateChangesSite() is doing the second
        # (to avoid zombie processes when sync processes exit)
        p = multiprocessing.Process(target=self._do_start_site_activation, args=[site_id])
        p.start()
        p.join()

    def _do_start_site_activation(self, site_id):
        try:
            site_activation = ActivateChangesSite(site_id, self._activation_id,
                                                  self._site_snapshot_file(site_id),
                                                  self._prevent_activate)
            site_activation.load()
            site_activation.start()
            os._exit(0)
        except:
            logger.exception()

    def _log_activation(self):
        log_msg = _("Starting activation (Sites: %s)") % ",".join(self._sites)
        log_audit(None, "activate-changes", log_msg)

        if self._comment:
            log_audit(None, "activate-changes", "%s: %s" % (_("Comment"), self._comment))

    def _log_site_activation(self, site_id):
        log_audit(None, "activate-changes", _("Started activation of site %s") % site_id)

    def get_state(self):
        state = {
            "sites": {},
        }

        for site_id in self._sites:
            state["sites"][site_id] = self._load_site_state(site_id)

        return state

    def get_site_state(self, site_id):
        return self._load_site_state(site_id)

    def _load_site_state(self, site_id):
        return store.load_data_from_file(self.site_state_path(site_id), {})

    def site_state_path(self, site_id):
        return os.path.join(self.activation_tmp_base_dir, self._activation_id,
                            self.site_filename(site_id))

    @classmethod
    def site_filename(cls, site_id):
        return "site_%s.mk" % site_id

    # Cleanup stale activations?
    def _do_housekeeping(self):
        lock_exclusive()
        try:
            for activation_id in self._existing_activation_ids():
                # skip the current activation_id
                if self._activation_id == activation_id:
                    continue

                delete = False
                manager = ActivateChangesManager()
                manager.load()

                try:
                    try:
                        manager.load_activation(activation_id)
                    except MKUserError:
                        # Not existant anymore!
                        delete = True
                        raise

                    delete = not manager.is_running()
                finally:
                    if delete:
                        shutil.rmtree("%s/%s" % (ActivateChangesManager.activation_tmp_base_dir,
                                                 activation_id))
        finally:
            unlock_exclusive()

    def _existing_activation_ids(self):
        ids = []

        for activation_id in os.listdir(ActivateChangesManager.activation_tmp_base_dir):
            if len(activation_id) == 36 and activation_id[8] == "-" and activation_id[13] == "-":
                ids.append(activation_id)

        return ids


PHASE_INITIALIZED = "initialized"  # Thread object has been initialized (not in thread yet)
PHASE_STARTED = "started"  # Thread just started, nothing happened yet
PHASE_SYNC = "sync"  # About to sync
PHASE_ACTIVATE = "activate"  # sync done activating changes
PHASE_FINISHING = "finishing"  # Remote work done, finalizing local state
PHASE_DONE = "done"  # Done (with good or bad result)

# PHASE_DONE can have these different states:

STATE_SUCCESS = "success"  # Everything is ok
STATE_ERROR = "error"  # Something went really wrong
STATE_WARNING = "warning"  # e.g. in case of core config warnings

# Available activation time keys

ACTIVATION_TIME_RESTART = "restart"
ACTIVATION_TIME_SYNC = "sync"
ACTIVATION_TIME_PROFILE_SYNC = "profile-sync"


class ActivateChangesSite(multiprocessing.Process, ActivateChanges):
    def __init__(self, site_id, activation_id, site_snapshot_file, prevent_activate=False):
        super(ActivateChangesSite, self).__init__()

        self._site_id = site_id
        self._site_changes = []
        self._activation_id = activation_id
        self._snapshot_file = site_snapshot_file
        self.daemon = True
        self._prevent_activate = prevent_activate

        self._time_started = None
        self._time_updated = None
        self._time_ended = None
        self._phase = None
        self._state = None
        self._status_text = None
        self._status_details = None
        self._warnings = []
        self._pid = None
        self._expected_duration = 10.0

        self._set_result(PHASE_INITIALIZED, _("Initialized"))

    def load(self):
        super(ActivateChangesSite, self).load()
        self._load_this_sites_changes()
        self._load_expected_duration()

    def _load_this_sites_changes(self):
        all_changes = self._changes_of_site(self._site_id)

        change_id = self._activate_until_change_id()

        # Find the last activated change and return all changes till this entry
        # (including the one we were searching for)
        changes = []
        for change in all_changes:
            changes.append(change)
            if change["id"] == change_id:
                break

        self._site_changes = changes

    def run(self):
        # Ensure this process is not detected as apache process by the apache init script
        daemon.set_procname("cmk-activate-changes")

        # Detach from parent (apache) -> Remain running when apache is restarted
        os.setsid()

        # Cleanup existing livestatus connections (may be opened later when needed)
        sites.disconnect()

        # Cleanup resources of the apache
        for x in range(3, 256):
            try:
                os.close(x)
            except OSError, e:
                if e.errno == 9:  # Bad file descriptor
                    pass
                else:
                    raise

        # Reinitialize logging targets
        log.init_logging()

        try:
            self._do_run()
        except:
            logger.exception()

    def _do_run(self):
        try:
            self._time_started = time.time()
            self._lock_activation()

            if self.is_sync_needed(self._site_id):
                self._synchronize_site()

            self._set_result(PHASE_FINISHING, _("Finalizing"))
            configuration_warnings = {}
            if self._prevent_activate:
                self._confirm_synchronized_changes()
            else:
                if self._is_activate_needed(self._site_id):
                    configuration_warnings = self._do_activate()
                self._confirm_activated_changes()

            self._set_done_result(configuration_warnings)
        except Exception, e:
            logger.exception()
            self._set_result(PHASE_DONE, _("Failed"), _("Failed: %s") % e, state=STATE_ERROR)

        finally:
            self._unlock_activation()

            # Create a copy of last result in the persisted dir
            manager = ActivateChangesManager()
            manager.load()
            manager.load_activation(self._activation_id)
            source_path = manager.site_state_path(self._site_id)
            shutil.copy(source_path, manager.activation_persisted_dir)

    def _activate_until_change_id(self):
        manager = ActivateChangesManager()
        manager.load()
        manager.load_activation(self._activation_id)
        manager.activate_until()

    def _set_done_result(self, configuration_warnings):
        if any(configuration_warnings.itervalues()):
            self._warnings = configuration_warnings
            details = self._render_warnings(configuration_warnings)
            self._set_result(PHASE_DONE, _("Activated"), details, state=STATE_WARNING)
        else:
            self._set_result(PHASE_DONE, _("Success"), state=STATE_SUCCESS)

    def _render_warnings(self, configuration_warnings):
        html_code = "<div class=warning>"
        html_code += "<b>%s</b>" % _("Warnings:")
        html_code += "<ul>"
        for domain, warnings in sorted(configuration_warnings.items()):
            for warning in warnings:
                html_code += "<li>%s: %s</li>" % \
                    (html.attrencode(domain), html.attrencode(warning))
        html_code += "</ul>"
        html_code += "</div>"
        return html_code

    def _lock_activation(self):
        # This locks the site specific replication status file
        repl_status = load_site_replication_status(self._site_id, lock=True)
        try:
            if self._is_currently_activating(repl_status):
                raise MKGeneralException(
                    _("The site is currently locked by another activation process. Please try again later"
                     ))

            # This is needed to detect stale activation progress entries
            # (where activation thread is not running anymore)
            self._mark_running()
        finally:
            # This call unlocks the replication status file after setting "current_activation"
            # which will prevent other users from starting an activation for this site.
            update_replication_status(self._site_id, {"current_activation": self._activation_id})

    def _is_currently_activating(self, rep_status):
        if not rep_status.get("current_activation"):
            return False

        #
        # Is this activation still in progress?
        #

        current_activation_id = rep_status.get(self._site_id, {}).get("current_activation")

        manager = ActivateChangesManager()
        manager.load()

        try:
            manager.load_activation(current_activation_id)
        except MKUserError:
            return False  # Not existant anymore!

        if manager.is_running():
            return True

        return False

    def _mark_running(self):
        self._pid = os.getpid()
        self._set_result(PHASE_STARTED, _("Started"))

    def _unlock_activation(self):
        update_replication_status(self._site_id, {
            "last_activation": self._activation_id,
            "current_activation": None,
        })

    # This is done on the central site to initiate the sync process
    def _synchronize_site(self):
        self._set_result(PHASE_SYNC, _("Sychronizing"))

        start = time.time()

        result = self._push_snapshot_to_site()

        duration = time.time() - start
        self.update_activation_time(self._site_id, ACTIVATION_TIME_SYNC, duration)

        # Pre 1.2.7i3 and sites return True on success and a string on error.
        # 1.2.7i3 and later return a list of warning messages on success.
        # [] means OK and no warnings. The error handling is unchanged.
        # Since 1.4.0i3 the old API (True -> success, <unicode>/<str> -> error)
        if isinstance(result, list):
            result = True

        if result != True:
            raise MKGeneralException(_("Failed to synchronize with site: %s") % result)

    def _push_snapshot_to_site(self):
        site = config.site(self._site_id)

        url = html.makeuri_contextless(
            [
                ("command", "push-snapshot"),
                ("secret", site["secret"]),
                ("siteid", site["id"]),
                ("debug", config.debug and "1" or ""),
            ],
            filename=site["multisiteurl"] + "automation.py",
        )

        response_text = self._upload_file(url, site.get('insecure', False))

        try:
            return ast.literal_eval(response_text)
        except SyntaxError:
            raise MKAutomationException(
                _("Garbled automation response: <pre>%s</pre>") % (html.attrencode(response_text)))

    def _upload_file(self, url, insecure):
        return get_url(url, insecure, files={"snapshot": open(self._snapshot_file, "r")})

    def _cleanup_snapshot(self):
        try:
            os.unlink(self._snapshot_file)
        except OSError, e:
            if e.errno == 2:
                pass  # Not existant -> OK
            else:
                raise

    def _do_activate(self):
        self._set_result(PHASE_ACTIVATE, _("Activating"))

        start = time.time()

        configuration_warnings = self._call_activate_changes_automation()

        duration = time.time() - start
        self.update_activation_time(self._site_id, ACTIVATION_TIME_RESTART, duration)
        return configuration_warnings

    def _call_activate_changes_automation(self):
        domains = self._get_domains_needing_activation()

        if config.site_is_local(self._site_id):
            return execute_activate_changes(domains)

        try:
            response = do_remote_automation(
                config.site(self._site_id), "activate-changes", [
                    ("domains", repr(domains)),
                    ("site_id", self._site_id),
                ])
        except MKAutomationException, e:
            if "Invalid automation command: activate-changes" in "%s" % e:
                return self._call_legacy_activate_changes_automation()
            else:
                raise

        return response

    # This is needed to be able to activate the changes on legacy (pre 1.4.0i3) slave sites.
    # Sadly this is only possible by syncing the snapshot a second time.
    def _call_legacy_activate_changes_automation(self):
        site = config.site(self._site_id)

        url = html.makeuri_contextless(
            [
                ("command", "push-snapshot"),
                ("secret", site["secret"]),
                ("siteid", site["id"]),
                ("mode", "slave"),
                ("restart", "yes"),
                ("debug", config.debug and "1" or ""),
            ],
            filename=site["multisiteurl"] + "automation.py",
        )

        response_text = self._upload_file(url, site.get('insecure', False))

        try:
            cmk_configuration_warnings = ast.literal_eval(response_text)

            # In case of an exception it returns a str/unicode message. Wrap the
            # message in a list to be compatible to regular response
            if isinstance(cmk_configuration_warnings, basestring):
                cmk_configuration_warnings = [cmk_configuration_warnings]

            return {"check_mk": cmk_configuration_warnings}
        except:
            raise MKAutomationException(
                _("Garbled automation response from site %s: '%s'") % (site["id"], response_text))

    def _get_domains_needing_activation(self):
        domains = set([])
        for change in self._site_changes:
            if change["need_restart"]:
                domains.update(change["domains"])
        return sorted(list(domains))

    def _confirm_activated_changes(self):
        changes = self._load_site_changes(self._site_id, lock=True)

        try:
            changes = changes[len(self._site_changes):]
        finally:
            self._save_site_changes(self._site_id, changes)

    def _confirm_synchronized_changes(self):
        changes = self._load_site_changes(self._site_id, lock=True)
        try:
            for change in changes:
                change["need_sync"] = False
        finally:
            self._save_site_changes(self._site_id, changes)

    def _set_result(self, phase, status_text, status_details=None, state=STATE_SUCCESS):
        self._phase = phase
        self._status_text = status_text

        if phase != PHASE_INITIALIZED:
            self._set_status_details(phase, status_details)

        self._time_updated = time.time()
        if phase == PHASE_DONE:
            self._time_ended = self._time_updated
            self._state = state

        self._save_state()

    def _set_status_details(self, phase, status_details):
        self._status_details = _("Started at: %s.") % render.time_of_day(self._time_started)

        if phase != PHASE_DONE:
            estimated_time_left = self._expected_duration - (time.time() - self._time_started)
            if estimated_time_left < 0:
                self._status_details += " " + _("Takes %.1f seconds longer than expected") % \
                                                                        abs(estimated_time_left)
            else:
                self._status_details += " " + _("Approximately finishes in %.1f seconds") % \
                                                                        estimated_time_left
        else:
            self._status_details += _(" Finished at: %s.") % render.time_of_day(self._time_ended)

        if status_details:
            self._status_details += "<br>%s" % status_details

    def _save_state(self):
        state_path = os.path.join(ActivateChangesManager.activation_tmp_base_dir,
                                  self._activation_id,
                                  ActivateChangesManager.site_filename(self._site_id))

        return store.save_data_to_file(
            state_path, {
                "_site_id": self._site_id,
                "_phase": self._phase,
                "_state": self._state,
                "_status_text": self._status_text,
                "_status_details": self._status_details,
                "_warnings": self._warnings,
                "_time_started": self._time_started,
                "_time_updated": self._time_updated,
                "_time_ended": self._time_ended,
                "_expected_duration": self._expected_duration,
                "_pid": self._pid,
            })

    def _load_expected_duration(self):
        times = self.get_activation_times(self._site_id)
        duration = 0.0

        if self.is_sync_needed(self._site_id):
            duration += times.get(ACTIVATION_TIME_SYNC, 0)

        if self._is_activate_needed(self._site_id):
            duration += times.get(ACTIVATION_TIME_RESTART, 0)

        # In case expected is 0, calculate with 10 seconds instead of failing
        if duration == 0.0:
            duration = 10.0

        return duration


def execute_activate_changes(domains):
    domains = set(domains).union(ConfigDomain.get_always_activate_domain_idents())

    results = {}
    for domain in sorted(domains):
        domain_class = ConfigDomain.get_class(domain)
        warnings = domain_class().activate()
        results[domain] = warnings or []

    return results


#.
#   .--Snapshots-----------------------------------------------------------.
#   |           ____                        _           _                  |
#   |          / ___| _ __   __ _ _ __  ___| |__   ___ | |_ ___            |
#   |          \___ \| '_ \ / _` | '_ \/ __| '_ \ / _ \| __/ __|           |
#   |           ___) | | | | (_| | |_) \__ \ | | | (_) | |_\__ \           |
#   |          |____/|_| |_|\__,_| .__/|___/_| |_|\___/ \__|___/           |
#   |                            |_|                                       |
#   +----------------------------------------------------------------------+
#   | WATO config snapshots                                                |
#   '----------------------------------------------------------------------'
# TODO: May be removed in near future.


# TODO: Remove once new changes mechanism has been implemented
def create_snapshot(comment):
    store.mkdir(snapshot_dir)

    snapshot_name = "wato-snapshot-%s.tar" % time.strftime("%Y-%m-%d-%H-%M-%S",
                                                           time.localtime(time.time()))

    data = {}
    data["comment"] = _("Activated changes by %s.") % config.user.id

    if comment:
        data["comment"] += _("Comment: %s") % comment

    data["created_by"] = config.user.id
    data["type"] = "automatic"
    data["snapshot_name"] = snapshot_name

    do_create_snapshot(data)

    log_msg = _("Created snapshot %s") % snapshot_name

    log_audit(None, "snapshot-created", log_msg)
    do_snapshot_maintenance()

    return snapshot_name


# TODO: Remove once new changes mechanism has been implemented
def do_create_snapshot(data):
    snapshot_name = data["snapshot_name"]
    snapshot_dir = cmk.paths.var_dir + "/wato/snapshots"
    work_dir = snapshot_dir + "/workdir/%s" % snapshot_name

    try:
        if not os.path.exists(work_dir):
            os.makedirs(work_dir)

        # Open / initialize files
        filename_target = "%s/%s" % (snapshot_dir, snapshot_name)
        filename_work = "%s/%s.work" % (work_dir, snapshot_name)

        file(filename_target, "w").close()

        def get_basic_tarinfo(name):
            tarinfo = tarfile.TarInfo(name)
            tarinfo.mtime = time.time()
            tarinfo.uid = 0
            tarinfo.gid = 0
            tarinfo.mode = 0644
            tarinfo.type = tarfile.REGTYPE
            return tarinfo

        # Initialize the snapshot tar file and populate with initial information
        tar_in_progress = tarfile.open(filename_work, "w")

        for key in ["comment", "created_by", "type"]:
            tarinfo = get_basic_tarinfo(key)
            encoded_value = data[key].encode("utf-8")
            tarinfo.size = len(encoded_value)
            tar_in_progress.addfile(tarinfo, cStringIO.StringIO(encoded_value))

        tar_in_progress.close()

        # Process domains (sorted)
        subtar_info = {}

        for name, info in sorted(get_default_backup_domains().items()):
            prefix = info.get("prefix", "")
            filename_subtar = "%s.tar.gz" % name
            path_subtar = "%s/%s" % (work_dir, filename_subtar)

            paths = ["." if x[1] == "" else x[1] for x in info.get("paths", [])]
            command = [
                "tar", "czf", path_subtar, "--ignore-failed-read", "--force-local", "-C", prefix
            ] + paths

            proc = subprocess.Popen(
                command,
                stdin=None,
                close_fds=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=prefix)
            _stdout, stderr = proc.communicate()
            exit_code = proc.wait()
            # Allow exit codes 0 and 1 (files changed during backup)
            if exit_code not in [0, 1]:
                raise MKGeneralException(
                    "Error while creating backup of %s (Exit Code %d) - %s.\n%s" %
                    (name, exit_code, stderr, command))

            subtar_hash = sha256(file(path_subtar).read()).hexdigest()
            subtar_signed = sha256(subtar_hash + snapshot_secret()).hexdigest()
            subtar_info[filename_subtar] = (subtar_hash, subtar_signed)

            # Append tar.gz subtar to snapshot
            command = ["tar", "--append", "--file=" + filename_work, filename_subtar]
            proc = subprocess.Popen(command, cwd=work_dir, close_fds=True)
            proc.communicate()
            exit_code = proc.wait()

            if os.path.exists(filename_subtar):
                os.unlink(filename_subtar)

            if exit_code != 0:
                raise MKGeneralException("Error on adding backup domain %s to tarfile" % name)

        # Now add the info file which contains hashes and signed hashes for
        # each of the subtars
        info = ''.join(['%s %s %s\n' % (k, v[0], v[1]) for k, v in subtar_info.items()]) + '\n'

        tar_in_progress = tarfile.open(filename_work, "a")
        tarinfo = get_basic_tarinfo("checksums")
        tarinfo.size = len(info)
        tar_in_progress.addfile(tarinfo, cStringIO.StringIO(info))
        tar_in_progress.close()

        shutil.move(filename_work, filename_target)

    finally:
        shutil.rmtree(work_dir)


# TODO: Remove once new changes mechanism has been implemented
def do_snapshot_maintenance():
    snapshots = []
    for f in os.listdir(snapshot_dir):
        if f.startswith('wato-snapshot-'):
            status = get_snapshot_status(f, check_correct_core=False)
            # only remove automatic and legacy snapshots
            if status.get("type") in ["automatic", "legacy"]:
                snapshots.append(f)

    snapshots.sort(reverse=True)
    while len(snapshots) > config.wato_max_snapshots:
        log_audit(None, "snapshot-removed", _("Removed snapshot %s") % snapshots[-1])
        os.remove(snapshot_dir + snapshots.pop())


# Returns status information for snapshots or snapshots in progress
# TODO: Remove once new changes mechanism has been implemented
def get_snapshot_status(snapshot, validate_checksums=False, check_correct_core=True):
    if isinstance(snapshot, tuple):
        name, file_stream = snapshot
    else:
        name = snapshot
        file_stream = None

    # Defaults of available keys
    status = {
        "name": "",
        "total_size": 0,
        "type": None,
        "files": {},
        "comment": "",
        "created_by": "",
        "broken": False,
        "progress_status": "",
    }

    def access_snapshot(handler):
        if file_stream:
            file_stream.seek(0)
            return handler(file_stream)
        return handler(snapshot_dir + name)

    def check_size():
        if file_stream:
            file_stream.seek(0, os.SEEK_END)
            size = file_stream.tell()
        else:
            statinfo = os.stat(snapshot_dir + name)
            size = statinfo.st_size
        if size < 256:
            raise MKGeneralException(_("Invalid snapshot (too small)"))
        else:
            status["total_size"] = size

    def check_extension():
        # Check snapshot extension: tar or tar.gz
        if name.endswith(".tar.gz"):
            status["type"] = "legacy"
            status["comment"] = _("Snapshot created with old version")
        elif not name.endswith(".tar"):
            raise MKGeneralException(_("Invalid snapshot (incorrect file extension)"))

    def check_content():
        status["files"] = access_snapshot(multitar.list_tar_content)

        if status.get("type") == "legacy":
            allowed_files = ["%s.tar" % x[1] for x in backup_paths]
            for tarname in status["files"]:
                if tarname not in allowed_files:
                    raise MKGeneralException(
                        _("Invalid snapshot (contains invalid tarfile %s)") % tarname)
        else:  # new snapshots
            for entry in ["comment", "created_by", "type"]:
                if entry in status["files"]:

                    def handler(x, entry=entry):
                        return multitar.get_file_content(x, entry)

                    status[entry] = access_snapshot(handler)
                else:
                    raise MKGeneralException(_("Invalid snapshot (missing file: %s)") % entry)

    def check_core():
        if "check_mk.tar.gz" not in status["files"]:
            return

        cmk_tar = cStringIO.StringIO(
            access_snapshot(lambda x: multitar.get_file_content(x, 'check_mk.tar.gz')))
        files = multitar.list_tar_content(cmk_tar)
        using_cmc = os.path.exists(cmk.paths.omd_root + '/etc/check_mk/conf.d/microcore.mk')
        snapshot_cmc = 'conf.d/microcore.mk' in files
        if using_cmc and not snapshot_cmc:
            raise MKGeneralException(
                _('You are currently using the Check_MK Micro Core, but this snapshot does not use the '
                  'Check_MK Micro Core. If you need to migrate your data, you could consider changing '
                  'the core, restoring the snapshot and changing the core back again.'))
        elif not using_cmc and snapshot_cmc:
            raise MKGeneralException(
                _('You are currently not using the Check_MK Micro Core, but this snapshot uses the '
                  'Check_MK Micro Core. If you need to migrate your data, you could consider changing '
                  'the core, restoring the snapshot and changing the core back again.'))

    def check_checksums():
        for f in status["files"].values():
            f['checksum'] = None

        # checksums field might contain three states:
        # a) None  - This is a legacy snapshot, no checksum file available
        # b) False - No or invalid checksums
        # c) True  - Checksums successfully validated
        if status['type'] == 'legacy':
            status['checksums'] = None
            return

        if 'checksums' not in status['files'].keys():
            status['checksums'] = False
            return

        # Extract all available checksums from the snapshot
        checksums_raw = access_snapshot(lambda x: multitar.get_file_content(x, 'checksums'))
        checksums = {}
        for l in checksums_raw.split('\n'):
            line = l.strip()
            if ' ' in line:
                parts = line.split(' ')
                if len(parts) == 3:
                    checksums[parts[0]] = (parts[1], parts[2])

        # now loop all known backup domains and check wheter or not they request
        # checksum validation, there is one available and it is valid
        status['checksums'] = True
        for domain_id, domain in backup_domains.items():
            filename = domain_id + '.tar.gz'
            if not domain.get('checksum', True) or filename not in status['files']:
                continue

            if filename not in checksums:
                continue

            checksum, signed = checksums[filename]

            # Get hashes of file in question
            def handler(x, filename=filename):
                return multitar.get_file_content(x, filename)

            subtar = access_snapshot(handler)
            subtar_hash = sha256(subtar).hexdigest()
            subtar_signed = sha256(subtar_hash + snapshot_secret()).hexdigest()

            status['files'][filename]['checksum'] = (checksum == subtar_hash and
                                                     signed == subtar_signed)
            status['checksums'] &= status['files'][filename]['checksum']

    try:
        if len(name) > 35:
            status["name"] = "%s %s" % (name[14:24], name[25:33].replace("-", ":"))
        else:
            status["name"] = name

        if not file_stream:
            # Check if the snapshot build is still in progress...
            path_status = "%s/workdir/%s/%s.status" % (snapshot_dir, name, name)
            path_pid = "%s/workdir/%s/%s.pid" % (snapshot_dir, name, name)

            # Check if this process is still running
            if os.path.exists(path_pid):
                if os.path.exists(path_pid) \
                   and not os.path.exists("/proc/%s" % open(path_pid).read()):
                    status["progress_status"] = _("ERROR: Snapshot progress no longer running!")
                    raise MKGeneralException(
                        _("Error: The process responsible for creating the snapshot is no longer running!"
                         ))
                else:
                    status["progress_status"] = _("Snapshot build currently in progress")

            # Read snapshot status file (regularly updated by snapshot process)
            if os.path.exists(path_status):
                lines = file(path_status, "r").readlines()
                status["comment"] = lines[0].split(":", 1)[1]
                file_info = {}
                for filename in lines[1:]:
                    name, info = filename.split(":", 1)
                    text, size = info[:-1].split(":", 1)
                    file_info[name] = {"size": int(size), "text": text}
                status["files"] = file_info
                return status

        # Snapshot exists and is finished - do some basic checks
        check_size()
        check_extension()
        check_content()
        if check_correct_core:
            check_core()

        if validate_checksums:
            check_checksums()

    except Exception, e:
        if config.debug:
            status["broken_text"] = traceback.format_exc()
            status["broken"] = True
        else:
            status["broken_text"] = '%s' % e
            status["broken"] = True
    return status


def get_default_backup_domains():
    domains = {}
    for domain, value in backup_domains.items():
        if "default" in value and not value.get("deprecated"):
            domains.update({domain: value})
    return domains


def snapshot_secret():
    path = cmk.paths.default_config_dir + '/snapshot.secret'
    try:
        return file(path).read()
    except IOError:
        # create a secret during first use
        try:
            s = os.urandom(256)
        except NotImplementedError:
            s = sha256(time.time())
        file(path, 'w').write(s)
        return s


#.
#   .--Host tags-----------------------------------------------------------.
#   |              _   _           _     _                                 |
#   |             | | | | ___  ___| |_  | |_ __ _  __ _ ___                |
#   |             | |_| |/ _ \/ __| __| | __/ _` |/ _` / __|               |
#   |             |  _  | (_) \__ \ |_  | || (_| | (_| \__ \               |
#   |             |_| |_|\___/|___/\__|  \__\__,_|\__, |___/               |
#   |                                             |___/                    |
#   +----------------------------------------------------------------------+
#   |  Helper functions for dealing with host tags                         |
#   '----------------------------------------------------------------------'


def parse_hosttag_title(title):
    if '/' in title:
        return title.split('/', 1)
    return None, title


def hosttag_topics(hosttags, auxtags):
    names = set([])
    for entry in hosttags + auxtags:
        topic, _title = parse_hosttag_title(entry[1])
        if topic:
            names.add((topic, topic))
    return list(names)


def group_hosttags_by_topic(hosttags):
    tags = {}
    for entry in hosttags:
        topic, title = parse_hosttag_title(entry[1])
        if not topic:
            topic = _('Host tags')
        tags.setdefault(topic, [])
        tags[topic].append((entry[0], title) + entry[2:])
    return sorted(tags.items(), key=lambda x: x[0])


def is_builtin_host_tag_group(tag_group_id):
    # Special handling for the agent tag group. It was a tag group created with
    # the sample WATO configuration until version 1.5x. This means users could've
    # customized the group. In case we find such a customization we treat it as
    # not builtin tag group.
    if tag_group_id == "agent":
        for tag_group in config.wato_host_tags:
            if tag_group[0] == tag_group_id:
                return False
        return True

    for tag_group in config.BuiltinTags().host_tags():
        if tag_group[0] == tag_group_id:
            return True
    return False


def is_builtin_aux_tag(taggroup_id):
    for builtin_taggroup in config.BuiltinTags().aux_tags():
        if builtin_taggroup[0] == taggroup_id:
            return True
    return False


def save_hosttags(hosttags, auxtags):
    output = wato_fileheader()

    output += "wato_host_tags += \\\n%s\n\n" % format_config_value(hosttags)
    output += "wato_aux_tags += \\\n%s\n" % format_config_value(auxtags)

    store.mkdir(multisite_dir)
    store.save_file(multisite_dir + "hosttags.mk", output)

    export_hosttags_to_php(hosttags, auxtags)


# Creates a includable PHP file which provides some functions which
# can be used by the calling program, for example NagVis. It declares
# the following API:
#
# taggroup_title(group_id)
# Returns the title of a WATO tag group
#
# taggroup_choice(group_id, list_of_object_tags)
# Returns either
#   false: When taggroup does not exist in current config
#   null:  When no choice can be found for the given taggroup
#   array(tag, title): When a tag of the taggroup
#
# all_taggroup_choices(object_tags):
# Returns an array of elements which use the tag group id as key
# and have an assiciative array as value, where 'title' contains
# the tag group title and the value contains the value returned by
# taggroup_choice() for this tag group.
#
def export_hosttags_to_php(hosttags, auxtags):
    path = php_api_dir + '/hosttags.php'
    store.mkdir(php_api_dir)

    # need an extra lock file, since we move the auth.php.tmp file later
    # to auth.php. This move is needed for not having loaded incomplete
    # files into php.
    tempfile = path + '.tmp'
    lockfile = path + '.state'
    file(lockfile, 'a')
    store.aquire_lock(lockfile)

    # Transform WATO internal data structures into easier usable ones
    hosttags_dict = {}
    for entry in hosttags:
        id_, title, choices = entry[:3]
        tags = {}
        for tag_id, tag_title, tag_auxtags in choices:
            tags[tag_id] = tag_title, tag_auxtags
        topic, title = parse_hosttag_title(title)
        hosttags_dict[id_] = topic, title, tags
    auxtags_dict = dict(auxtags)

    # First write a temp file and then do a move to prevent syntax errors
    # when reading half written files during creating that new file
    file(tempfile, 'w').write('''<?php
// Created by WATO
global $mk_hosttags, $mk_auxtags;
$mk_hosttags = %s;
$mk_auxtags = %s;

function taggroup_title($group_id) {
    global $mk_hosttags;
    if (isset($mk_hosttags[$group_id]))
        return $mk_hosttags[$group_id][0];
    else
        return $taggroup;
}

function taggroup_choice($group_id, $object_tags) {
    global $mk_hosttags;
    if (!isset($mk_hosttags[$group_id]))
        return false;
    foreach ($object_tags AS $tag) {
        if (isset($mk_hosttags[$group_id][2][$tag])) {
            // Found a match of the objects tags with the taggroup
            // now return an array of the matched tag and its alias
            return array($tag, $mk_hosttags[$group_id][2][$tag][0]);
        }
    }
    // no match found. Test whether or not a "None" choice is allowed
    if (isset($mk_hosttags[$group_id][2][null]))
        return array(null, $mk_hosttags[$group_id][2][null][0]);
    else
        return null; // no match found
}

function all_taggroup_choices($object_tags) {
    global $mk_hosttags;
    $choices = array();
    foreach ($mk_hosttags AS $group_id => $group) {
        $choices[$group_id] = array(
            'topic' => $group[0],
            'title' => $group[1],
            'value' => taggroup_choice($group_id, $object_tags),
        );
    }
    return $choices;
}

?>
''' % (format_php(hosttags_dict), format_php(auxtags_dict)))
    # Now really replace the destination file
    os.rename(tempfile, path)
    store.release_lock(lockfile)
    os.unlink(lockfile)


def format_php(data, lvl=1):
    s = ''
    if isinstance(data, (list, tuple)):
        s += 'array(\n'
        for item in data:
            s += '    ' * lvl + format_php(item, lvl + 1) + ',\n'
        s += '    ' * (lvl - 1) + ')'
    elif isinstance(data, dict):
        s += 'array(\n'
        for key, val in data.iteritems():
            s += '    ' * lvl + format_php(key, lvl + 1) + ' => ' + format_php(val, lvl + 1) + ',\n'
        s += '    ' * (lvl - 1) + ')'
    elif isinstance(data, str):
        s += '\'%s\'' % data.replace('\'', '\\\'')
    elif isinstance(data, unicode):
        s += '\'%s\'' % data.encode('utf-8').replace('\'', '\\\'')
    elif isinstance(data, bool):
        s += data and 'true' or 'false'
    elif data is None:
        s += 'null'
    else:
        s += str(data)

    return s


def validate_tag_id(tag_id, varname):
    if not re.match("^[-a-z0-9A-Z_]*$", tag_id):
        raise MKUserError(
            varname, _("Invalid tag ID. Only the characters a-z, A-Z, "
                       "0-9, _ and - are allowed."))


class Hosttag(object):
    def __init__(self):
        super(Hosttag, self).__init__()
        self._initialize()

    def _initialize(self):
        self.id = None
        self.title = None

    def validate(self):
        if not self.id:
            raise MKUserError("tag_id", _("Please specify a tag ID"))

        validate_tag_id(self.id, "tag_id")

        if not self.title:
            raise MKUserError("title", _("Please supply a title for you auxiliary tag."))

    def parse_config(self, data):
        self._initialize()
        if isinstance(data, dict):
            self._parse_from_dict(data)
        else:
            self._parse_legacy_format(data)

    def _parse_from_dict(self, tag_info):
        self.id = tag_info["id"]
        self.title = tag_info["title"]

    def _parse_legacy_format(self, tag_info):
        self.id, self.title = tag_info[:2]


class AuxTag(Hosttag):
    def __init__(self, data=None):
        super(AuxTag, self).__init__()
        self.topic = None
        if data:
            self.parse_config(data)

    def _parse_from_dict(self, tag_info):
        super(AuxTag, self)._parse_from_dict(tag_info)
        if "topic" in tag_info:
            self.topic = tag_info["topic"]

    def _parse_legacy_format(self, tag_info):
        super(AuxTag, self)._parse_legacy_format(tag_info)
        self.topic, self.title = HosttagsConfiguration.parse_hosttag_title(self.title)

    def get_legacy_format(self):
        return self.id, HosttagsConfiguration.get_merged_topic_and_title(self)

    def get_dict_format(self):
        response = {"id": self.id, "title": self.title}
        if self.topic:
            response["topic"] = self.topic
        return response


class AuxtagList(object):
    def __init__(self):
        self._tags = []

    def get_tags(self):
        return self._tags

    def get_number(self, number):
        return self._tags[number]

    def append(self, aux_tag):
        if is_builtin_aux_tag(aux_tag.id):
            raise MKUserError("tag_id", _("You can not override a builtin auxiliary tag."))
        self._append(aux_tag)

    def _append(self, aux_tag):
        if self.has_aux_tag(aux_tag):
            raise MKUserError("tag_id",
                              _("This tag id does already exist in the list "
                                "of auxiliary tags."))
        self._tags.append(aux_tag)

    def update(self, position, aux_tag):
        self._tags[position] = aux_tag

    def validate(self):
        seen = set()
        for aux_tag in self._tags:
            aux_tag.validate()
            if aux_tag.id in seen:
                raise MKUserError("tag_id", _("Duplicate tag id in auxilary tags: %s") % aux_tag.id)
            seen.add(aux_tag.id)

    def has_aux_tag(self, aux_tag):
        for tmp_aux_tag in self._tags:
            if aux_tag.id == tmp_aux_tag.id:
                return True
        return False

    def get_tag_ids(self):
        return {tag.id for tag in self._tags}

    def get_legacy_format(self):
        response = []
        for aux_tag in self._tags:
            response.append(aux_tag.get_legacy_format())
        return response

    def get_dict_format(self):
        response = []
        for tag in self._tags:
            response.append(tag.get_dict_format())
        return response


class BuiltinAuxtagList(AuxtagList):
    def append(self, aux_tag):
        self._append(aux_tag)


class GroupedHosttag(Hosttag):
    def __init__(self, data=None):
        super(GroupedHosttag, self).__init__()
        self.aux_tag_ids = []
        self.parse_config(data)

    def _parse_from_dict(self, tag_info):
        super(GroupedHosttag, self)._parse_from_dict(tag_info)
        self.aux_tag_ids = tag_info["aux_tags"]

    def _parse_legacy_format(self, tag_info):
        super(GroupedHosttag, self)._parse_legacy_format(tag_info)

        if len(tag_info) == 3:
            self.aux_tag_ids = tag_info[2]

    def get_legacy_format(self):
        return self.id, self.title, self.aux_tag_ids

    def get_dict_format(self):
        return {"id": self.id, "title": self.title, "aux_tags": self.aux_tag_ids}


class HosttagGroup(object):
    def __init__(self, data=None):
        super(HosttagGroup, self).__init__()
        self._initialize()

        if data:
            if isinstance(data, dict):
                self._parse_from_dict(data)
            else:  # legacy tuple
                self._parse_legacy_format(data)

    def _initialize(self):
        self.id = None
        self.title = None
        self.topic = None
        self.tags = []

    def _parse_from_dict(self, group_info):
        self._initialize()
        self.id = group_info["id"]
        self.title = group_info["title"]
        self.topic = group_info.get("topic")
        self.tags = [GroupedHosttag(tag) for tag in group_info["tags"]]

    def _parse_legacy_format(self, group_info):
        self._initialize()
        group_id, group_title, tag_list = group_info[:3]

        self.id = group_id
        self.topic, self.title = HosttagsConfiguration.parse_hosttag_title(group_title)

        for tag in tag_list:
            self.tags.append(GroupedHosttag(tag))

    def get_tag_ids(self):
        return {tag.id for tag in self.tags}

    def get_dict_format(self):
        response = {"id": self.id, "title": self.title, "tags": []}
        if self.topic:
            response["topic"] = self.topic

        for tag in self.tags:
            response["tags"].append(tag.get_dict_format())

        return response

    def get_legacy_format(self):
        return self.id,\
               HosttagsConfiguration.get_merged_topic_and_title(self),\
               self.get_tags_legacy_format()

    def get_tags_legacy_format(self):
        response = []
        for tag in self.tags:
            response.append(tag.get_legacy_format())
        return response

    def get_tag_choices(self):
        choices = []
        for tag in self.tags:
            choices.append((tag.id, tag.title))
        return choices


class HosttagsConfiguration(object):
    def __init__(self):
        super(HosttagsConfiguration, self).__init__()
        self._initialize()

    def _initialize(self):
        self.tag_groups = []
        self.aux_tag_list = AuxtagList()

    @staticmethod
    def parse_hosttag_title(title):
        if '/' in title:
            return title.split('/', 1)
        return None, title

    @staticmethod
    def get_merged_topic_and_title(entity):
        if entity.topic:
            return "%s/%s" % (entity.topic, entity.title)
        return entity.title

    def get_hosttag_topics(self):
        names = set([])
        for tag_group in self.tag_groups:
            topic = tag_group.topic
            if topic:
                names.add((topic, topic))
        return list(names)

    def get_tag_group(self, tag_group_id):
        for group in self.tag_groups:
            if group.id == tag_group_id:
                return group

    def get_aux_tags(self):
        return self.aux_tag_list.get_tags()

    # Returns the raw ids of the grouped tags and the aux tags
    def get_tag_ids(self):
        response = set()
        for tag_group in self.tag_groups:
            response.update(tag_group.get_tag_ids())

        response.update(self.aux_tag_list.get_tag_ids())
        return response

    def get_tag_ids_with_group_prefix(self):
        response = set()
        for tag_group in self.tag_groups:
            response.update(["%s/%s" % (tag_group.id, tag) for tag in tag_group.get_tag_ids()])

        response.update(self.aux_tag_list.get_tag_ids())
        return response

    def parse_config(self, data):
        self._initialize()
        if isinstance(data, dict):
            self._parse_from_dict(data)
        else:
            self._parse_legacy_format(data[0], data[1])

        self.validate_config()

    def _parse_from_dict(self, tag_info):  # new style
        for tag_group in tag_info["tag_groups"]:
            self.tag_groups.append(HosttagGroup(tag_group))
        for aux_tag in tag_info["aux_tags"]:
            self.aux_tag_list.append(AuxTag(aux_tag))

    def _parse_legacy_format(self, taggroup_info, auxtags_info):  # legacy style
        for tag_group_tuple in taggroup_info:
            self.tag_groups.append(HosttagGroup(tag_group_tuple))

        for aux_tag_tuple in auxtags_info:
            self.aux_tag_list.append(AuxTag(aux_tag_tuple))

    def insert_tag_group(self, tag_group):
        if is_builtin_host_tag_group(tag_group.id):
            raise MKUserError("tag_id", _("You can not override a builtin tag group."))
        self._insert_tag_group(tag_group)

    def _insert_tag_group(self, tag_group):
        self.tag_groups.append(tag_group)
        self._validate_group(tag_group)

    def update_tag_group(self, tag_group):
        for idx, group in enumerate(self.tag_groups):
            if group.id == tag_group.id:
                self.tag_groups[idx] = tag_group
                break
        else:
            raise MKUserError("", _("Unknown tag group"))
        self._validate_group(tag_group)

    def validate_config(self):
        for tag_group in self.tag_groups:
            self._validate_group(tag_group)

        self.aux_tag_list.validate()

    # TODO: cleanup this mess
    # This validation is quite gui specific, I do not want to introduce this into the base classes
    def _validate_group(self, tag_group):
        if len(tag_group.id) == 0:
            raise MKUserError("tag_id", _("Please specify an ID for your tag group."))
        validate_tag_id(tag_group.id, "tag_id")

        for tmp_group in self.tag_groups:
            if tmp_group == tag_group:
                continue
            if tmp_group.id == tag_group.id:
                raise MKUserError("tag_id", _("The tag group ID %s is already used by the tag group '%s'.") %\
                                    (tag_group.id, tmp_group.title))

        if not tag_group.title:
            raise MKUserError("title", _("Please specify a title for your host tag group."))

        have_none_tag = False
        for nr, tag in enumerate(tag_group.tags):
            if tag.id or tag.title:
                if not tag.id:
                    tag.id = None
                    if have_none_tag:
                        raise MKUserError("choices_%d_id" % (nr + 1),
                                          _("Only one tag may be empty."))
                    have_none_tag = True
                # Make sure tag ID is unique within this group
                for (n, x) in enumerate(tag_group.tags):
                    if n != nr and x.id == tag.id:
                        raise MKUserError(
                            "choices_id_%d" % (nr + 1),
                            _("Tags IDs must be unique. You've used <b>%s</b> twice.") % tag.id)

            if tag.id:
                # Make sure this ID is not used elsewhere
                for tmp_group in self.tag_groups:
                    # Do not compare the taggroup with itself
                    if tmp_group != tag_group:
                        for tmp_tag in tmp_group.tags:
                            # Check primary and secondary tags
                            if tag.id == tmp_tag.id:
                                raise MKUserError(
                                    "choices_id_%d" % (nr + 1),
                                    _("The tag ID '%s' is already being used by the choice "
                                      "'%s' in the tag group '%s'.") % (tag.id, tmp_tag.title,
                                                                        tmp_group.title))

                # Also check all defined aux tags even if they are not used anywhere
                for aux_tag in self.get_aux_tags():
                    if tag.id == aux_tag.id:
                        raise MKUserError(
                            "choices_id_%d" % (nr + 1),
                            _("The tag ID '%s' is already being used as auxiliary tag.") % tag.id)

        if len(tag_group.tags) == 0:
            raise MKUserError("id_0", _("Please specify at least one tag."))
        if len(tag_group.tags) == 1 and tag_group.tags[0] == None:
            raise MKUserError("id_0", _("Tags with only one choice must have an ID."))

    def load(self):
        hosttags, auxtags = self._load_hosttags()
        self._parse_legacy_format(hosttags, auxtags)

    # Current specification for hosttag entries: One tag definition is stored
    # as tuple of at least three elements. The elements are used as follows:
    # taggroup_id, group_title, list_of_choices, depends_on_tags, depends_on_roles, editable
    def _load_hosttags(self):
        default_config = {
            "wato_host_tags": [],
            "wato_aux_tags": [],
        }

        tag_config = cmk.store.load_mk_file(multisite_dir + "hosttags.mk", default_config)

        self._convert_manual_host_tags(tag_config["wato_host_tags"])
        config.migrate_old_sample_config_tag_groups(tag_config["wato_host_tags"],
                                                    tag_config["wato_aux_tags"])

        return tag_config["wato_host_tags"], tag_config["wato_aux_tags"]

    # Convert manually crafted host tags tags WATO-style. This
    # makes the migration easier
    def _convert_manual_host_tags(self, host_tags):
        for taggroup in host_tags:
            for nr, entry in enumerate(taggroup[2]):
                if len(entry) <= 2:
                    taggroup[2][nr] = entry + ([],)

    def save(self):
        self.validate_config()
        hosttags, auxtags = self.get_legacy_format()
        save_hosttags(hosttags, auxtags)

    def get_legacy_format(self):  # Convert new style to old style
        tag_groups_response = []
        for tag_group in self.tag_groups:
            tag_groups_response.append(tag_group.get_legacy_format())

        aux_tags_response = self.aux_tag_list.get_legacy_format()
        return tag_groups_response, aux_tags_response

    def get_dict_format(self):
        result = {"tag_groups": [], "aux_tags": []}
        for tag_group in self.tag_groups:
            result["tag_groups"].append(tag_group.get_dict_format())

        result["aux_tags"] = self.aux_tag_list.get_dict_format()

        return result


class BuiltinHosttagsConfiguration(HosttagsConfiguration):
    def _initialize(self):
        self.tag_groups = []
        self.aux_tag_list = BuiltinAuxtagList()

    def insert_tag_group(self, tag_group):
        self._insert_tag_group(tag_group)

    def load(self):
        builtin_tags = config.BuiltinTags()
        self._parse_legacy_format(builtin_tags.host_tags(), builtin_tags.aux_tags())


#.
#   .--Hooks---------------------------------------------------------------.
#   |                     _   _             _                              |
#   |                    | | | | ___   ___ | | _____                       |
#   |                    | |_| |/ _ \ / _ \| |/ / __|                      |
#   |                    |  _  | (_) | (_) |   <\__ \                      |
#   |                    |_| |_|\___/ \___/|_|\_\___/                      |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | Hooks allow to register functions that are being called on certain   |
#   | operations. You can e.g. get called whenever changes are activated.  |
#   '----------------------------------------------------------------------'


def register_hook(name, func):
    hooks.register(name, func)


def call_hook_snapshot_pushed():
    hooks.call("snapshot-pushed")


def call_hook_hosts_changed(folder):
    if hooks.registered("hosts-changed"):
        hosts = collect_hosts(folder)
        hooks.call("hosts-changed", hosts)

    # The same with all hosts!
    if hooks.registered("all-hosts-changed"):
        hosts = collect_hosts(Folder.root_folder())
        hooks.call("all-hosts-changed", hosts)


def call_hook_folder_created(folder):
    # CLEANUP: Gucken, welche Hooks es gibt und anpassen auf das neue Objekt
    hooks.call("folder-created", folder)


def call_hook_folder_deleted(folder):
    # CLEANUP: Gucken, welche Hooks es gibt und anpassen auf das neue Objekt
    hooks.call("folder-deleted", folder)


# This hook is executed when one applies the pending configuration changes
# related to the mkeventd via WATO on the local system. The hook is called
# without parameters.
def call_hook_mkeventd_activate_changes():
    if hooks.registered('mkeventd-activate-changes'):
        hooks.call("mkeventd-activate-changes")


# This hook is executed before distributing changes to the remote
# sites (in distributed WATO) or before activating them (in single-site
# WATO). If the hook raises an exception, then the distribution and
# activation is aborted.
def call_hook_pre_distribute_changes():
    if hooks.registered('pre-distribute-changes'):
        hooks.call("pre-distribute-changes", collect_hosts(Folder.root_folder()))


# This hook is executed when one applies the pending configuration changes
# from wato but BEFORE the nagios restart is executed.
#
# It can be used to create custom input files for nagios/Check_MK.
#
# The registered hooks are called with a dictionary as parameter which
# holds all available with the hostnames as keys and the attributes of
# the hosts as values.
def call_hook_pre_activate_changes():
    if hooks.registered('pre-activate-changes'):
        hooks.call("pre-activate-changes", collect_hosts(Folder.root_folder()))


# This hook is executed when one applies the pending configuration changes
# from wato.
#
# But it is only excecuted when there is at least one function
# registered for this host.
#
# The registered hooks are called with a dictionary as parameter which
# holds all available with the hostnames as keys and the attributes of
# the hosts as values.
def call_hook_activate_changes():
    if hooks.registered('activate-changes'):
        hosts = collect_hosts(Folder.root_folder())
        hooks.call("activate-changes", hosts)


# This hook is executed when the save_roles() function is called
def call_hook_roles_saved(roles):
    hooks.call("roles-saved", roles)


# This hook is executed when the SiteManagement.save_sites() function is called
def call_hook_sites_saved(sites):
    hooks.call("sites-saved", sites)


def call_hook_contactsgroups_saved(all_groups):
    hooks.call('contactgroups-saved', all_groups)


# internal helper functions for API
def collect_hosts(folder):
    hosts_attributes = {}
    for host_name, host in Host.all().items():
        hosts_attributes[host_name] = host.effective_attributes()
        hosts_attributes[host_name]["path"] = host.folder().path()
    return hosts_attributes


#.
#   .--Automation----------------------------------------------------------.
#   |          _         _                        _   _                    |
#   |         / \  _   _| |_ ___  _ __ ___   __ _| |_(_) ___  _ __         |
#   |        / _ \| | | | __/ _ \| '_ ` _ \ / _` | __| |/ _ \| '_ \        |
#   |       / ___ \ |_| | || (_) | | | | | | (_| | |_| | (_) | | | |       |
#   |      /_/   \_\__,_|\__\___/|_| |_| |_|\__,_|\__|_|\___/|_| |_|       |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | This code section deals with the interaction of Check_MK. It is used |
#   | for doing inventory, showing the services of a host, deletion of a   |
#   | host and similar things.                                             |
#   '----------------------------------------------------------------------'


class MKAutomationException(MKGeneralException):
    pass


def check_mk_automation(siteid,
                        command,
                        args=None,
                        indata="",
                        stdin_data=None,
                        timeout=None,
                        sync=True):
    if args is None:
        args = []

    if not siteid or config.site_is_local(siteid):
        return check_mk_local_automation(command, args, indata, stdin_data, timeout)
    return check_mk_remote_automation(siteid, command, args, indata, stdin_data, timeout, sync)


def check_mk_local_automation(command, args=None, indata="", stdin_data=None, timeout=None):
    if args is None:
        args = []

    auto_logger = logger.getChild("config.automations")

    if timeout:
        args = ["--timeout", "%d" % timeout] + args

    cmd = ['check_mk', '--automation', command, '--'] + args
    if command in ['restart', 'reload']:
        call_hook_pre_activate_changes()

    cmd = [cmk.utils.make_utf8(a) for a in cmd]
    try:
        # This debug output makes problems when doing bulk inventory, because
        # it garbles the non-HTML response output
        # if config.debug:
        #     html.write("<div class=message>Running <tt>%s</tt></div>\n" % " ".join(cmd))
        auto_logger.info("RUN: %s" % subprocess.list2cmdline(cmd))
        p = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            close_fds=True)
    except Exception, e:
        raise MKGeneralException("Cannot execute <tt>%s</tt>: %s" % (" ".join(cmd), e))

    if stdin_data != None:
        auto_logger.info("STDIN: %r" % stdin_data)
        p.stdin.write(stdin_data)
    else:
        auto_logger.info("STDIN: %r" % indata)
        p.stdin.write(repr(indata))

    p.stdin.close()
    outdata = p.stdout.read()
    exitcode = p.wait()
    auto_logger.info("FINISHED: %d" % exitcode)
    auto_logger.debug("OUTPUT: %r" % outdata)
    if exitcode != 0:
        auto_logger.error(
            "Error running %r (exit code %d)" % (subprocess.list2cmdline(cmd), exitcode))

        if config.debug:
            raise MKGeneralException("Error running <tt>%s</tt> (exit code %d): <pre>%s</pre>" %
                                     (" ".join(cmd), exitcode, hilite_errors(outdata)))
        else:
            raise MKGeneralException(hilite_errors(outdata))

    # On successful "restart" command execute the activate changes hook
    if command in ['restart', 'reload']:
        call_hook_activate_changes()

    try:
        return ast.literal_eval(outdata)
    except Exception, e:
        raise MKGeneralException(
            "Error running <tt>%s</tt>. Invalid output from webservice (%s): <pre>%s</pre>" %
            (" ".join(cmd), e, outdata))


# TODO: Remove this once non OMD environments are not supported anymore
def apache_user():
    return pwd.getpwuid(os.getuid())[0]


def hilite_errors(outdata):
    return re.sub("\nError: *([^\n]*)", "\n<div class=err><b>Error:</b> \\1</div>", outdata)


#.
#   .--Host Tag Conditions-------------------------------------------------.
#   |                _   _           _     _____                           |
#   |               | | | | ___  ___| |_  |_   _|_ _  __ _                 |
#   |               | |_| |/ _ \/ __| __|   | |/ _` |/ _` |                |
#   |               |  _  | (_) \__ \ |_    | | (_| | (_| |                |
#   |               |_| |_|\___/|___/\__|   |_|\__,_|\__, |                |
#   |                                                |___/                 |
#   |            ____                _ _ _   _                             |
#   |           / ___|___  _ __   __| (_) |_(_) ___  _ __  ___             |
#   |          | |   / _ \| '_ \ / _` | | __| |/ _ \| '_ \/ __|            |
#   |          | |__| (_) | | | | (_| | | |_| | (_) | | | \__ \            |
#   |           \____\___/|_| |_|\__,_|_|\__|_|\___/|_| |_|___/            |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |                                                                      |
#   '----------------------------------------------------------------------'


# ValueSpec for editing a tag-condition
class HostTagCondition(ValueSpec):
    def __init__(self, **kwargs):
        ValueSpec.__init__(self, **kwargs)

    def render_input(self, varprefix, value):
        render_condition_editor(value, varprefix)

    def from_html_vars(self, varprefix):
        return get_tag_conditions(varprefix=varprefix)

    def canonical_value(self):
        return []

    def value_to_text(self, value):
        return "|".join(value)

    def validate_datatype(self, value, varprefix):
        if not isinstance(value, list):
            raise MKUserError(varprefix,
                              _("The list of host tags must be a list, but "
                                "is %r") % type(value))
        for x in value:
            if not isinstance(x, str):
                raise MKUserError(
                    varprefix,
                    _("The list of host tags must only contain strings "
                      "but also contains %r") % x)

    def validate_value(self, value, varprefix):
        pass


# Render HTML input fields for editing a tag based condition
def render_condition_editor(tag_specs, varprefix=""):
    if varprefix:
        varprefix += "_"

    if not config.aux_tags() + config.host_tag_groups():
        html.write(
            _("You have not configured any <a href=\"wato.py?mode=hosttags\">host tags</a>."))
        return

    # Determine current (default) setting of tag by looking
    # into tag_specs (e.g. [ "snmp", "!tcp", "test" ] )
    def current_tag_setting(choices):
        default_tag = None
        ignore = True
        for t in tag_specs:
            if t[0] == '!':
                n = True
                t = t[1:]
            else:
                n = False
            if t in [x[0] for x in choices]:
                default_tag = t
                ignore = False
                negate = n
        if ignore:
            deflt = "ignore"
        elif negate:
            deflt = "isnot"
        else:
            deflt = "is"
        return default_tag, deflt

    # Show dropdown with "is/isnot/ignore" and beginning
    # of div that is switched visible by is/isnot
    def tag_condition_dropdown(tagtype, deflt, id_):
        html.open_td()
        dropdown_id = varprefix + tagtype + "_" + id_
        onchange = "valuespec_toggle_dropdownn(this, '%stag_sel_%s');" % (varprefix, id_)
        choices = [
            ("ignore", _("ignore")),
            ("is", _("is")),
            ("isnot", _("isnot")),
        ]
        html.dropdown(dropdown_id, choices, deflt=deflt, onchange=onchange)
        html.close_td()

        html.open_td(class_="tag_sel")
        if html.form_submitted():
            div_is_open = html.var(dropdown_id, "ignore") != "ignore"
        else:
            div_is_open = deflt != "ignore"
        html.open_div(
            id_="%stag_sel_%s" % (varprefix, id_),
            style="display: none;" if not div_is_open else None)

    auxtags = group_hosttags_by_topic(config.aux_tags())
    hosttags = group_hosttags_by_topic(config.host_tag_groups())
    all_topics = set([])
    for topic, _taggroups in auxtags + hosttags:
        all_topics.add(topic)
    all_topics = list(all_topics)
    all_topics.sort()
    make_foldable = len(all_topics) > 1
    for topic in all_topics:
        if make_foldable:
            html.begin_foldable_container("topic", varprefix + topic, True,
                                          HTML("<b>%s</b>" % (_u(topic))))
        html.open_table(class_=["hosttags"])

        # Show main tags
        for t, grouped_tags in hosttags:
            if t == topic:
                for entry in grouped_tags:
                    id_, title, choices = entry[:3]
                    html.open_tr()
                    html.open_td(class_="title")
                    html.write("%s: &nbsp;" % _u(title))
                    html.close_td()
                    default_tag, deflt = current_tag_setting(choices)
                    tag_condition_dropdown("tag", deflt, id_)
                    if len(choices) == 1:
                        html.write_text(" " + _("set"))
                    else:
                        html.dropdown(
                            varprefix + "tagvalue_" + id_,
                            [(t[0], _u(t[1])) for t in choices if t[0] != None],
                            deflt=default_tag)
                    html.close_div()
                    html.close_td()
                    html.close_tr()

        # And auxiliary tags
        for t, grouped_tags in auxtags:
            if t == topic:
                for id_, title in grouped_tags:
                    html.open_tr()
                    html.open_td(class_="title")
                    html.write("%s: &nbsp;" % _u(title))
                    html.close_td()
                    default_tag, deflt = current_tag_setting([(id_, _u(title))])
                    tag_condition_dropdown("auxtag", deflt, id_)
                    html.write_text(" " + _("set"))
                    html.close_div()
                    html.close_td()
                    html.close_tr()

        html.close_table()
        if make_foldable:
            html.end_foldable_container()


# Retrieve current tag condition settings from HTML variables
def get_tag_conditions(varprefix=""):
    if varprefix:
        varprefix += "_"
    # Main tags
    tag_list = []
    for entry in config.host_tag_groups():
        id_, _title, tags = entry[:3]
        mode = html.var(varprefix + "tag_" + id_)
        if len(tags) == 1:
            tagvalue = tags[0][0]
        else:
            tagvalue = html.var(varprefix + "tagvalue_" + id_)

        if mode == "is":
            tag_list.append(tagvalue)
        elif mode == "isnot":
            tag_list.append("!" + tagvalue)

    # Auxiliary tags
    for id_, _title in config.aux_tags():
        mode = html.var(varprefix + "auxtag_" + id_)
        if mode == "is":
            tag_list.append(id_)
        elif mode == "isnot":
            tag_list.append("!" + id_)

    return tag_list


#.
#   .--Handler scripts-----------------------------------------------------.
#   |                 _   _                 _ _                            |
#   |                | | | | __ _ _ __   __| | | ___ _ __                  |
#   |                | |_| |/ _` | '_ \ / _` | |/ _ \ '__|                 |
#   |                |  _  | (_| | | | | (_| | |  __/ |                    |
#   |                |_| |_|\__,_|_| |_|\__,_|_|\___|_|                    |
#   |                                                                      |
#   |                                  _       _                           |
#   |                    ___  ___ _ __(_)_ __ | |_ ___                     |
#   |                   / __|/ __| '__| | '_ \| __/ __|                    |
#   |                   \__ \ (__| |  | | |_) | |_\__ \                    |
#   |                   |___/\___|_|  |_| .__/ \__|___/                    |
#   |                                   |_|                                |
#   +----------------------------------------------------------------------+
#   | Common code for reading and offering notification scripts and alert  |
#   | handlers.                                                            |
#   '----------------------------------------------------------------------'

# Example header of a notification script:
#!/usr/bin/python
# HTML Emails with included graphs
# Bulk: yes
# Argument 1: Full system path to the pnp4nagios index.php for fetching the graphs. Usually auto configured in OMD.
# Argument 2: HTTP-URL-Prefix to open Multisite. When provided, several links are added to the mail.
#
# This script creates a nifty HTML email in multipart format with
# attached graphs and such neat stuff. Sweet!


def load_user_scripts_from(adir):
    scripts = {}
    if os.path.exists(adir):
        for entry in os.listdir(adir):
            entry = entry.decode("utf-8")
            path = adir + "/" + entry
            if os.path.isfile(path) and os.access(path, os.X_OK):
                info = {"title": entry, "bulk": False}
                try:
                    lines = file(path)
                    lines.next()
                    line = lines.next().strip().decode("utf-8")
                    if line.startswith("#") and "encoding:" in line:
                        line = lines.next().strip()
                    if line.startswith("#"):
                        info["title"] = line.lstrip("#").strip().split("#", 1)[0]
                    while True:
                        line = lines.next().strip()
                        if not line.startswith("#") or ":" not in line:
                            break
                        key, value = line[1:].strip().split(":", 1)
                        value = value.strip()
                        if key.lower() == "bulk":
                            info["bulk"] = (value == "yes")

                except:
                    pass
                scripts[entry] = info
    return scripts


def load_user_scripts(what):
    scripts = {}
    not_dir = cmk.paths.share_dir + "/" + what
    try:
        if what == "notifications":
            # Support for setup.sh
            not_dir = cmk.paths.notifications_dir
    except:
        pass

    scripts = load_user_scripts_from(not_dir)
    try:
        local_dir = cmk.paths.omd_root + "/local/share/check_mk/" + what
        scripts.update(load_user_scripts_from(local_dir))
    except:
        pass

    return scripts


def load_notification_scripts():
    return load_user_scripts("notifications")


def user_script_choices(what):
    scripts = load_user_scripts(what)
    choices = [(name, info["title"]) for (name, info) in scripts.items()]
    choices.sort(cmp=lambda a, b: cmp(a[1], b[1]))
    choices = [(k, _u(v)) for k, v in choices]
    return choices


def user_script_title(what, name):
    return dict(user_script_choices(what)).get(name, name)


#.
#   .--Rulespecs-----------------------------------------------------------.
#   |             ____        _                                            |
#   |            |  _ \ _   _| | ___  ___ _ __   ___  ___ ___              |
#   |            | |_) | | | | |/ _ \/ __| '_ \ / _ \/ __/ __|             |
#   |            |  _  | |_| | |  __/\__ \ |_) |  __/ (__\__ \             |
#   |            |_| \_\\__,_|_|\___||___/ .__/ \___|\___|___/             |
#   |                                    |_|                               |
#   +----------------------------------------------------------------------+
#   | The rulespecs are the ruleset specifications registered to WATO.     |
#   '----------------------------------------------------------------------


# TODO: Better rename this and also get_rulegroup() to rulespec group
class Rulegroup(object):
    def __init__(self, name, title=None, help_text=None):
        self.name = name
        self.title = title or name
        self.help = help_text


def register_rulegroup(group_name, title, help_text):
    g_rulegroups[group_name] = Rulegroup(group_name, title, help_text)


def get_rulegroup(group_name):
    return g_rulegroups.get(group_name, Rulegroup(group_name))


class Rulespecs(object):
    def __init__(self):
        super(Rulespecs, self).__init__()
        self._rulespecs = {}
        self._by_group = {}  # for conveniant lookup
        self._sorted_groups = []  # for keeping original order

    def clear(self):
        self._rulespecs.clear()
        self._by_group.clear()
        del self._sorted_groups[:]

    def register(self, rulespec):
        group = rulespec.group_name
        name = rulespec.name

        if group not in self._by_group:
            self._sorted_groups.append(group)
            self._by_group[group] = [rulespec]

        else:
            for nr, this_rulespec in enumerate(self._by_group[group]):
                if this_rulespec.name == name:
                    del self._by_group[group][nr]
                    break  # There cannot be two duplicates!

            self._by_group[group].append(rulespec)

        self._rulespecs[name] = rulespec

    def get(self, name):
        return self._rulespecs[name]

    def exists(self, name):
        return name in self._rulespecs

    def get_rulespecs(self):
        return self._rulespecs

    def get_by_group(self, group_name):
        return self._by_group[group_name]

    # Returns all available ruleset groups to be used in dropdown choices
    def get_group_choices(self, mode):
        choices = []

        for main_group_name in self.get_main_groups():
            main_group = g_rulegroups.get(main_group_name)
            if main_group:
                main_group_title = main_group.title
            else:
                main_group_title = main_group_name

            if mode == "static_checks" and main_group_name != "static":
                continue
            elif mode != "static_checks" and main_group_name == "static":
                continue

            choices.append((main_group_name, main_group_title))

            for group_name in self._by_group:
                if group_name.startswith(main_group_name + "/"):
                    # TODO: Move this subgroup title calculation to some generic place
                    sub_group_title = group_name.split("/", 1)[1]
                    choices.append((cmk.utils.make_utf8(group_name),
                                    u"&nbsp;&nbsp;⌙ %s" % sub_group_title))

        return choices

    # Now we collect all rulesets that apply to hosts, except those specifying
    # new active or static checks
    def get_all_groups(self):
        seen = set()
        return [gn for gn in self._sorted_groups if not (gn in seen or seen.add(gn))]

    # Group names are separated with "/" into main group and optional subgroup.
    # Do not lose carefully manually crafted order of groups!
    def get_main_groups(self):
        seen = set()
        group_names = []

        for group_name in self._sorted_groups:
            main_group = cmk.utils.make_utf8(group_name.split('/')[0])
            if main_group not in seen:
                group_names.append(main_group)
                seen.add(main_group)

        return group_names

    # Now we collect all rulesets that apply to hosts, except those specifying
    # new active or static checks
    def get_host_groups(self):
        seen = set()
        return [
            gn for gn in self._sorted_groups
            if not gn.startswith("static/") and not gn.startswith("checkparams/") and
            gn != "activechecks" and not (gn in seen or seen.add(gn))
        ]

    # Get the exactly matching main groups and all matching sub group names
    def get_matching_groups(self, group_name):
        seen = set()
        return [
            gn for gn in self._sorted_groups
            if (gn == group_name or (group_name and gn.startswith(group_name + "/"))) and
            not (gn in seen or seen.add(gn))
        ]


class Rulespec(object):
    NO_FACTORY_DEFAULT = []  # needed for unique ID
    FACTORY_DEFAULT_UNUSED = []  # means this ruleset is not used if no rule is entered

    def __init__(self, name, group_name, valuespec, item_spec, item_type, item_name, item_help,
                 item_enum, match_type, title, help_txt, is_optional, factory_default,
                 is_deprecated):
        super(Rulespec, self).__init__()

        self.name = name
        self.group_name = group_name
        self.main_group_name = group_name.split("/")[0]
        self.sub_group_name = group_name.split("/")[1] if "/" in group_name else ""
        self.valuespec = valuespec
        self.item_spec = item_spec  # original item spec, e.g. if validation is needed
        self.item_type = item_type  # None, "service", "checktype" or "checkitem"

        if not item_name and item_type == "service":
            self.item_name = _("Service")
        else:
            self.item_name = item_name  # e.g. "mount point"

        self.item_help = item_help  # a description of the item, only rarely used
        self.item_enum = item_enum  # possible fixed values for items
        self.match_type = match_type  # used by WATO rule analyzer (green and grey balls)
        self.title = title or valuespec.title()
        self.help = help_txt or valuespec.help()
        self.factory_default = factory_default
        self.is_optional = is_optional  # rule may be None (like only_hosts)
        self.is_deprecated = is_deprecated


def register_rule(
        group,
        varname,
        valuespec=None,
        title=None,
        help=None,  # pylint: disable=redefined-builtin
        itemspec=None,
        itemtype=None,
        itemname=None,
        itemhelp=None,
        itemenum=None,
        match="first",
        optional=False,
        deprecated=False,
        **kwargs):
    factory_default = kwargs.get("factory_default", Rulespec.NO_FACTORY_DEFAULT)

    rulespec = Rulespec(
        name=varname,
        group_name=group,
        valuespec=valuespec,
        item_spec=itemspec,
        item_type=itemtype,
        item_name=itemname,
        item_help=itemhelp,
        item_enum=itemenum,
        match_type=match,
        title=title,
        help_txt=help,
        is_optional=optional,
        factory_default=factory_default,
        is_deprecated=deprecated,
    )

    g_rulespecs.register(rulespec)


g_rulespecs = Rulespecs()

#.
#   .--Ruleset-------------------------------------------------------------.
#   |                  ____        _                _                      |
#   |                 |  _ \ _   _| | ___  ___  ___| |_                    |
#   |                 | |_) | | | | |/ _ \/ __|/ _ \ __|                   |
#   |                 |  _ <| |_| | |  __/\__ \  __/ |_                    |
#   |                 |_| \_\\__,_|_|\___||___/\___|\__|                   |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |                                                                      |
#   '----------------------------------------------------------------------'


class RulesetCollection(object):
    """Abstract class for holding a collection of rulesets. The most basic
    specific class is the FolderRulesets class which cares about all rulesets
    configured in a folder."""

    def __init__(self):
        super(RulesetCollection, self).__init__()
        # A dictionary containing all ruleset objects of the collection.
        # The name of the ruleset is used as key in the dict.
        self._rulesets = {}

    # Has to be implemented by the subclasses to load the right rulesets
    def load(self):
        raise NotImplementedError()

    def _load_folder_rulesets(self, folder, only_varname=None):
        path = folder.rules_file_path()

        config = {
            "ALL_HOSTS": ALL_HOSTS,
            "ALL_SERVICES": [""],
            "NEGATE": NEGATE,
            "FOLDER_PATH": folder.path(),
            "FILE_PATH": folder.path() + "/hosts.mk",
        }

        # Prepare empty rulesets so that rules.mk has something to
        # append to. We need to initialize all variables here, even
        # when only loading with only_varname.
        for varname in g_rulespecs.get_rulespecs():
            if ':' in varname:
                dictname, _subkey = varname.split(":")
                config[dictname] = {}
            else:
                config[varname] = []

        self.from_config(folder, store.load_mk_file(path, config), only_varname)

    def from_config(self, folder, rulesets_config, only_varname=None):
        for varname in g_rulespecs.get_rulespecs():
            if only_varname and varname != only_varname:
                continue  # skip unwanted options

            ruleset = self._rulesets.setdefault(varname, Ruleset(varname))

            if ':' in varname:
                dictname, subkey = varname.split(":")
                ruleset_config = rulesets_config.get(dictname, {})
                if subkey in ruleset_config:
                    ruleset.from_config(folder, ruleset_config[subkey])
            else:
                ruleset.from_config(folder, rulesets_config.get(varname, []))

    def save(self):
        raise NotImplementedError()

    def save_folder(self, folder):
        raise NotImplementedError()

    def _save_folder(self, folder):
        store.mkdir(folder.get_root_dir())

        content = ""
        for varname, ruleset in sorted(self._rulesets.items(), key=lambda x: x[0]):
            if not g_rulespecs.exists(varname):
                continue  # don't save unknown rulesets

            if ruleset.is_empty_in_folder(folder):
                continue  # don't save empty rule sets

            content += ruleset.to_config(folder)

        store.save_mk_file(folder.rules_file_path(), content)

    def exists(self, name):
        return name in self._rulesets

    def get(self, name, deflt=None):
        return self._rulesets[name]

    def set(self, name, ruleset):
        self._rulesets[name] = ruleset

    def get_rulesets(self):
        return self._rulesets

    def set_rulesets(self, rulesets):
        self._rulesets = rulesets

    # Groups the rulesets in 3 layers (main group, sub group, rulesets)
    def get_grouped(self):
        grouped_dict = {}
        for ruleset in self._rulesets.itervalues():
            main_group = grouped_dict.setdefault(ruleset.rulespec.main_group_name, {})
            group_rulesets = main_group.setdefault(ruleset.rulespec.sub_group_name, [])
            group_rulesets.append(ruleset)

        grouped = []
        for main_group_name, sub_groups in grouped_dict.items():
            sub_group_list = []

            for sub_group_title, group_rulesets in sorted(sub_groups.items(), key=lambda x: x[0]):
                sub_group_list.append((sub_group_title,
                                       sorted(group_rulesets, key=lambda x: x.title())))

            grouped.append((main_group_name, sub_group_list))

        return grouped


class AllRulesets(RulesetCollection):
    def _load_rulesets_recursively(self, folder, only_varname=None):
        for subfolder in folder.all_subfolders().values():
            self._load_rulesets_recursively(subfolder, only_varname)

        self._load_folder_rulesets(folder, only_varname)

    # Load all rules of all folders
    def load(self):
        self._load_rulesets_recursively(Folder.root_folder())

    def save_folder(self, folder):
        self._save_folder(folder)


class SingleRulesetRecursively(AllRulesets):
    def __init__(self, name):
        super(SingleRulesetRecursively, self).__init__()
        self._name = name

    # Load single ruleset from all folders
    def load(self):
        self._load_rulesets_recursively(Folder.root_folder(), only_varname=self._name)

    def save_folder(self, folder):
        raise NotImplementedError()


class FolderRulesets(RulesetCollection):
    def __init__(self, folder):
        super(FolderRulesets, self).__init__()
        self._folder = folder

    def load(self):
        self._load_folder_rulesets(self._folder)

    def save(self):
        self._save_folder(self._folder)


class FilteredRulesetCollection(AllRulesets):
    def save(self):
        raise NotImplementedError("Filtered ruleset collections can not be saved.")


class StaticChecksRulesets(FilteredRulesetCollection):
    def load(self):
        super(StaticChecksRulesets, self).load()
        self._remove_non_static_checks_rulesets()

    def _remove_non_static_checks_rulesets(self):
        for name, ruleset in self._rulesets.items():
            if ruleset.rulespec.main_group_name != "static":
                del self._rulesets[name]


class NonStaticChecksRulesets(FilteredRulesetCollection):
    def load(self):
        super(NonStaticChecksRulesets, self).load()
        self._remove_static_checks_rulesets()

    def _remove_static_checks_rulesets(self):
        for name, ruleset in self._rulesets.items():
            if ruleset.rulespec.main_group_name == "static":
                del self._rulesets[name]


class SearchedRulesets(FilteredRulesetCollection):
    def __init__(self, origin_rulesets, search_options):
        super(SearchedRulesets, self).__init__()
        self._origin_rulesets = origin_rulesets
        self._search_options = search_options
        self._load_filtered()

    def _load_filtered(self):
        """Iterates the rulesets from the original collection,
        applies the search option and takes over the rulesets
        that have at least one matching rule or match itself,
        e.g. by their name, title or help."""

        for ruleset in self._origin_rulesets.get_rulesets().values():
            if ruleset.matches_search_with_rules(self._search_options):
                self._rulesets[ruleset.name] = ruleset


# TODO: Cleanup the rule indexing by position in the rules list. The "rule_nr" is used
# as index accross several HTTP requests where other users may have done something with
# the ruleset. In worst cases the user modifies a rule which should not be modified.
class Ruleset(object):
    def __init__(self, name):
        super(Ruleset, self).__init__()
        self.name = name
        self.rulespec = g_rulespecs.get(name)
        # Holds list of the rules. Using the folder paths as keys.
        self._rules = {}

        # Temporary needed during search result processing
        self.search_matching_rules = []

    def is_empty(self):
        return not self._rules

    def is_empty_in_folder(self, folder):
        return not bool(self.get_folder_rules(folder))

    def num_rules(self):
        return sum([len(rules) for rules in self._rules.values()])

    def num_rules_in_folder(self, folder):
        return len(self.get_folder_rules(folder))

    def get_rules(self):
        rules = []
        for _folder_path, folder_rules in self._rules.items():
            for rule_index, rule in enumerate(folder_rules):
                rules.append((rule.folder, rule_index, rule))
        return sorted(
            rules, key=lambda x: (x[0].path().split("/"), len(rules) - x[1]), reverse=True)

    def get_folder_rules(self, folder):
        try:
            return self._rules[folder.path()]
        except KeyError:
            return []

    def prepend_rule(self, folder, rule):
        rules = self._rules.setdefault(folder.path(), [])
        rules.insert(0, rule)
        self._on_change()

    def append_rule(self, folder, rule):
        rules = self._rules.setdefault(folder.path(), [])
        rules.append(rule)
        self._on_change()

    def insert_rule_after(self, rule, after):
        index = self._rules[rule.folder.path()].index(after) + 1
        self._rules[rule.folder.path()].insert(index, rule)
        add_change(
            "clone-ruleset",
            _("Cloned rule in ruleset '%s'") % self.title(),
            sites=rule.folder.all_site_ids())
        self._on_change()

    def from_config(self, folder, rules_config):
        if not rules_config:
            return

        # Resets the rules of this ruleset for this folder!
        self._rules[folder.path()] = []

        for rule_config in rules_config:
            rule = Rule(folder, self)
            rule.from_config(rule_config)
            self._rules[folder.path()].append(rule)

    def to_config(self, folder):
        content = ""

        if ":" in self.name:
            dictname, subkey = self.name.split(':')
            varname = "%s[%r]" % (dictname, subkey)

            content += "\n%s.setdefault(%r, [])\n" % (dictname, subkey)
        else:
            varname = self.name

            content += "\nglobals().setdefault(%r, [])\n" % (varname)

            if self.is_optional():
                content += "\nif %s == None:\n    %s = []\n" % (varname, varname)

        content += "\n%s = [\n" % varname
        for rule in self._rules[folder.path()]:
            content += rule.to_config()
        content += "] + %s\n\n" % varname

        return content

    # Whether or not either the ruleset itself matches the search or the rules match
    def matches_search_with_rules(self, search_options):
        if not self.matches_ruleset_search_options(search_options):
            return False

        # The ruleset matched or did not decide to skip the whole ruleset.
        # The ruleset should be matched in case a rule matches.
        if not self.has_rule_search_options(search_options):
            return self.matches_fulltext_search(search_options)

        # Store the matching rules for later result rendering
        self.search_matching_rules = []
        for _folder, _rule_index, rule in self.get_rules():
            if rule.matches_search(search_options):
                self.search_matching_rules.append(rule)

        # Show all rulesets where at least one rule matched
        if self.search_matching_rules:
            return True

        # e.g. in case ineffective rules are searched and no fulltext
        # search is filled in: Then don't show empty rulesets.
        if not search_options.get("fulltext"):
            return False

        return self.matches_fulltext_search(search_options)

    def has_rule_search_options(self, search_options):
        return bool([k for k in search_options.keys() if k == "fulltext" or k.startswith("rule_")])

    def matches_fulltext_search(self, search_options):
        return match_one_of_search_expression(
            search_options, "fulltext",
            [self.name, self.title(), self.help()])

    def matches_ruleset_search_options(self, search_options):
        if "ruleset_deprecated" in search_options and search_options[
                "ruleset_deprecated"] != self.is_deprecated():
            return False

        if "ruleset_used" in search_options and search_options["ruleset_used"] == self.is_empty():
            return False

        if "ruleset_group" in search_options \
           and self.rulespec.group_name not in g_rulespecs.get_matching_groups(search_options["ruleset_group"]):
            return False

        if not match_search_expression(search_options, "ruleset_name", self.name):
            return False

        if not match_search_expression(search_options, "ruleset_title", self.title()):
            return False

        if not match_search_expression(search_options, "ruleset_help", self.help()):
            return False

        return True

    def get_rule(self, folder, rule_index):
        return self._rules[folder.path()][rule_index]

    def edit_rule(self, rule):
        add_change(
            "edit-rule",
            _("Changed properties of rule \"%s\" in folder \"%s\"") % (self.title(),
                                                                       rule.folder.alias_path()),
            sites=rule.folder.all_site_ids())
        self._on_change()

    def delete_rule(self, rule):
        self._rules[rule.folder.path()].remove(rule)
        add_change(
            "edit-ruleset",
            _("Deleted rule in ruleset '%s'") % self.title(),
            sites=rule.folder.all_site_ids())
        self._on_change()

    def move_rule_up(self, rule):
        rules = self._rules[rule.folder.path()]
        index = rules.index(rule)
        del rules[index]
        rules[index - 1:index - 1] = [rule]
        add_change(
            "edit-ruleset",
            _("Moved rule #%d up in ruleset \"%s\"") % (index, self.title()),
            sites=rule.folder.all_site_ids())

    def move_rule_down(self, rule):
        rules = self._rules[rule.folder.path()]
        index = rules.index(rule)
        del rules[index]
        rules[index + 1:index + 1] = [rule]
        add_change(
            "edit-ruleset",
            _("Moved rule #%d down in ruleset \"%s\"") % (index, self.title()),
            sites=rule.folder.all_site_ids())

    def move_rule_to_top(self, rule):
        rules = self._rules[rule.folder.path()]
        index = rules.index(rule)
        rules.remove(rule)
        rules.insert(0, rule)
        add_change(
            "edit-ruleset",
            _("Moved rule #%d to top in ruleset \"%s\"") % (index, self.title()),
            sites=rule.folder.all_site_ids())

    def move_rule_to_bottom(self, rule):
        rules = self._rules[rule.folder.path()]
        index = rules.index(rule)
        rules.remove(rule)
        rules.append(rule)
        add_change(
            "edit-ruleset",
            _("Moved rule #%d to bottom in ruleset \"%s\"") % (index, self.title()),
            sites=rule.folder.all_site_ids())

    def move_rule_to(self, rule, index):
        rules = self._rules[rule.folder.path()]
        old_index = rules.index(rule)
        rules.remove(rule)
        rules.insert(index, rule)
        add_change(
            "edit-ruleset",
            _("Moved rule #%d to #%d in ruleset \"%s\"") % (old_index, index, self.title()),
            sites=rule.folder.all_site_ids())

    # TODO: Remove these getters
    def valuespec(self):
        return self.rulespec.valuespec

    def help(self):
        return self.rulespec.help

    def title(self):
        return self.rulespec.title

    def item_type(self):
        return self.rulespec.item_type

    def item_name(self):
        return self.rulespec.item_name

    def item_help(self):
        return self.rulespec.item_help

    def item_enum(self):
        return self.rulespec.item_enum

    def match_type(self):
        return self.rulespec.match_type

    def is_deprecated(self):
        return self.rulespec.is_deprecated

    def is_optional(self):
        return self.rulespec.is_optional

    def _on_change(self):
        if has_agent_bakery():
            import cmk.gui.cee.agent_bakery as agent_bakery
            agent_bakery.ruleset_changed(self.name)

    # Returns the outcoming value or None and a list of matching rules. These are pairs
    # of rule_folder and rule_number
    def analyse_ruleset(self, hostname, service):
        resultlist = []
        resultdict = {}
        effectiverules = []
        for folder, rule_index, rule in self.get_rules():
            if rule.is_disabled():
                continue

            if not rule.matches_host_and_item(Folder.current(), hostname, service):
                continue

            if self.match_type() == "all":
                resultlist.append(rule.value)
                effectiverules.append((folder, rule_index, rule))

            elif self.match_type() == "list":
                resultlist += rule.value
                effectiverules.append((folder, rule_index, rule))

            elif self.match_type() == "dict":
                new_result = rule.value.copy()  # pylint: disable=no-member
                new_result.update(resultdict)
                resultdict = new_result
                effectiverules.append((folder, rule_index, rule))

            else:
                return rule.value, [(folder, rule_index, rule)]

        if self.match_type() in ("list", "all"):
            return resultlist, effectiverules

        elif self.match_type() == "dict":
            return resultdict, effectiverules

        return None, []  # No match


class Rule(object):
    @classmethod
    def create(cls, folder, ruleset, host_list, item_list):
        rule = Rule(folder, ruleset)

        if rule.ruleset.valuespec():
            rule.value = rule.ruleset.valuespec().default_value()

        rule.host_list = host_list

        if rule.ruleset.item_type():
            rule.item_list = item_list

        return rule

    def __init__(self, folder, ruleset):
        super(Rule, self).__init__()
        self.ruleset = ruleset
        self.folder = folder

        # Content of the rule itself
        self._initialize()

    def clone(self):
        cloned = Rule(self.folder, self.ruleset)
        cloned.from_config(self._format_rule())
        return cloned

    def _initialize(self):
        self.tag_specs = []
        self.host_list = []
        self.item_list = None
        self.rule_options = {}

        if self.ruleset.valuespec():
            self.value = None
        else:
            self.value = True

    def from_config(self, rule_config):
        try:
            self._initialize()
            self._parse_rule(rule_config)
        except Exception:
            raise MKGeneralException(_("Invalid rule <tt>%s</tt>") % (rule_config,))

    def _parse_rule(self, rule_config):
        if isinstance(rule_config, dict):
            self._parse_dict_rule(rule_config)
        else:  # tuple
            self._parse_tuple_rule(rule_config)

    def _parse_dict_rule(self, rule_config):
        self.rule_options = rule_config.get("options", {})

        # Extract value from front, if rule has a value
        if self.ruleset.valuespec():
            self.value = rule_config["value"]
        else:
            if rule_config.get("negate"):
                self.value = False
            else:
                self.value = True

        conditions = rule_config.get("conditions", {})
        self.host_list = conditions.get("host_specs", [])
        self.item_list = conditions.get("service_specs")

        # Remove folder tag from tag list
        tag_specs = conditions.get("host_tags", [])
        self.tag_specs = [t for t in tag_specs if not t.startswith("/")]

    def _parse_tuple_rule(self, rule_config):
        if isinstance(rule_config[-1], dict):
            self.rule_options = rule_config[-1]
            rule_config = rule_config[:-1]

        # Extract value from front, if rule has a value
        if self.ruleset.valuespec():
            self.value = rule_config[0]
            rule_config = rule_config[1:]
        else:
            if rule_config[0] == NEGATE:
                self.value = False
                rule_config = rule_config[1:]
            else:
                self.value = True

        # Extract liste of items from back, if rule has items
        if self.ruleset.item_type():
            self.item_list = rule_config[-1]
            rule_config = rule_config[:-1]

        # Rest is host list or tag list + host list
        if len(rule_config) == 1:
            tag_specs = []
            self.host_list = rule_config[0]
        else:
            tag_specs = rule_config[0]
            self.host_list = rule_config[1]

        # Remove folder tag from tag list
        self.tag_specs = [t for t in tag_specs if not t.startswith("/")]

    def to_config(self):
        content = "  ( "

        if self.ruleset.valuespec():
            content += repr(self.value) + ", "
        elif not self.value:
            content += "NEGATE, "

        content += "["
        for tag in self.tag_specs:
            content += repr(tag)
            content += ", "

        if not self.folder.is_root():
            content += "'/' + FOLDER_PATH + '/+'"

        content += "], "

        if self.host_list and self.host_list[-1] == ALL_HOSTS[0]:
            if len(self.host_list) > 1:
                content += repr(self.host_list[:-1])
                content += " + ALL_HOSTS"
            else:
                content += "ALL_HOSTS"
        else:
            content += repr(self.host_list)

        if self.ruleset.item_type():
            content += ", "
            if self.item_list == ALL_SERVICES:
                content += "ALL_SERVICES"
            else:
                if self.item_list[-1] == ALL_SERVICES[0]:
                    content += repr(self.item_list[:-1])
                    content += " + ALL_SERVICES"
                else:
                    content += repr(self.item_list)

        if self.rule_options:
            content += ", %r" % self._rule_options_to_config()

        content += " ),\n"

        return content

    def to_dict_config(self):
        result = {"conditions": {}}

        result["path"] = self.folder.path()
        result["options"] = self._rule_options_to_config()

        if self.ruleset.valuespec():
            result["value"] = self.value
        else:
            if self.value:
                result["negate"] = False
            else:
                result["negate"] = True

        result["conditions"]["host_specs"] = self.host_list
        result["conditions"]["host_tags"] = self.tag_specs

        if self.ruleset.item_type():
            result["conditions"]["service_specs"] = self.item_list

        return result

    def _format_rule(self):
        if self.ruleset.valuespec():
            rule = [self.value]
        elif not self.value:
            rule = [NEGATE]
        else:
            rule = []

        if self.tag_specs != []:
            rule.append(self.tag_specs)

        rule.append(self.host_list)
        if self.item_list != None:
            rule.append(self.item_list)

        ro = self._rule_options_to_config()

        if ro:
            rule.append(ro)

        return tuple(rule)

    # Append rule options, but only if they are not trivial. That way we
    # keep as close as possible to the original Check_MK in rules.mk so that
    # command line users will feel at home...
    def _rule_options_to_config(self):
        ro = {}
        if self.rule_options.get("disabled"):
            ro["disabled"] = True
        if self.rule_options.get("description"):
            ro["description"] = self.rule_options["description"]
        if self.rule_options.get("comment"):
            ro["comment"] = self.rule_options["comment"]
        if self.rule_options.get("docu_url"):
            ro["docu_url"] = self.rule_options["docu_url"]

        # Preserve other keys that we do not know of
        for k, v in self.rule_options.items():
            if k not in ["disabled", "description", "comment", "docu_url"]:
                ro[k] = v

        return ro

    def is_ineffective(self):
        hosts = Host.all()
        for host_name, host in hosts.items():
            if self.matches_host_and_item(host.folder(), host_name, NO_ITEM):
                return False
        return True

    def matches_host_and_item(self, host_folder, hostname, item):
        """Whether or not the given folder/host/item matches this rule"""
        return not any(True for _r in self.get_mismatch_reasons(host_folder, hostname, item))

    def get_mismatch_reasons(self, host_folder, hostname, item):
        """A generator that provides the reasons why a given folder/host/item not matches this rule"""
        host = host_folder.host(hostname)

        if not self._matches_hostname(hostname):
            yield _("The host name does not match.")

        host_tags = host.tags()
        for tag in self.tag_specs:
            if tag[0] != '/' and tag[0] != '!' and tag not in host_tags:
                yield _("The host is missing the tag %s") % tag
            elif tag[0] == '!' and tag[1:] in host_tags:
                yield _("The host has the tag %s") % tag

        if not self.folder.is_transitive_parent_of(host_folder):
            yield _("The rule does not apply to the folder of the host.")

        if item != NO_ITEM and self.ruleset.item_type():
            if not self.matches_item(item):
                yield _("The %s \"%s\" does not match this rule.") % \
                                      (self.ruleset.item_name(), item)

    def _matches_hostname(self, hostname):
        if not self.host_list:
            return False  # empty list of explicit host does never match

        # Assume WATO conforming rule where either *all* or *none* of the
        # host expressions are negated.
        negate = self.host_list[0].startswith("!")

        for check_host in self.host_list:
            if check_host == "@all":
                return True

            if check_host[0] == '!':  # strip negate character
                check_host = check_host[1:]

            if check_host[0] == '~':
                check_host = check_host[1:]
                regex_match = True
            else:
                regex_match = False

            if not regex_match and hostname == check_host:
                return not negate

            elif regex_match and cmk.regex.regex(check_host).match(hostname):
                return not negate

        return negate

    def matches_item(self, item):
        for item_spec in self.item_list:
            do_negate = False
            compare_item = item_spec
            if compare_item and compare_item[0] == ENTRY_NEGATE_CHAR:
                compare_item = compare_item[1:]
                do_negate = True
            if re.match(compare_item, "%s" % item):
                return not do_negate
        return False

    def matches_search(self, search_options):
        if "rule_folder" in search_options and self.folder.name() not in self._get_search_folders(
                search_options):
            return False

        if "rule_disabled" in search_options and search_options[
                "rule_disabled"] != self.is_disabled():
            return False

        if "rule_ineffective" in search_options and search_options[
                "rule_ineffective"] != self.is_ineffective():
            return False

        if not match_search_expression(search_options, "rule_description", self.description()):
            return False

        if not match_search_expression(search_options, "rule_comment", self.comment()):
            return False

        if "rule_value" in search_options and not self.ruleset.valuespec():
            return False

        value_text = None
        if self.ruleset.valuespec():
            try:
                value_text = "%s" % self.ruleset.valuespec().value_to_text(self.value)
            except Exception, e:
                logger.exception()
                html.show_warning(
                    _("Failed to search rule of ruleset '%s' in folder '%s' (%s): %s") %
                    (self.ruleset.title(), self.folder.title(), self.to_config(), e))

        if value_text != None and not match_search_expression(search_options, "rule_value",
                                                              value_text):
            return False

        if not match_one_of_search_expression(search_options, "rule_host_list", self.host_list):
            return False

        if self.item_list and not match_one_of_search_expression(search_options, "rule_item_list",
                                                                 self.item_list):
            return False

        to_search = [
            self.comment(),
            self.description(),
        ] + self.host_list \
          + (self.item_list or [])

        if value_text != None:
            to_search.append(value_text)

        if not match_one_of_search_expression(search_options, "fulltext", to_search):
            return False

        searching_host_tags = search_options.get("rule_hosttags")
        if searching_host_tags:
            for host_tag in searching_host_tags:
                if host_tag not in self.tag_specs:
                    return False

        return True

    def _get_search_folders(self, search_options):
        current_folder, do_recursion = search_options["rule_folder"]
        current_folder = Folder.folder(current_folder)
        search_in_folders = [current_folder.name()]
        if do_recursion:
            search_in_folders = [
                x.split("/")[-1] for x, _y in current_folder.recursive_subfolder_choices()
            ]
        return search_in_folders

    def index(self):
        return self.ruleset.get_folder_rules(self.folder).index(self)

    def is_disabled(self):
        return self.rule_options.get("disabled", False)

    def description(self):
        return self.rule_options.get("description", "")

    def comment(self):
        return self.rule_options.get("comment", "")

    def is_discovery_rule_of(self, host):
        return self.host_list == [host.name()] \
               and self.tag_specs == [] \
               and all([ i.endswith("$") for i in self.item_list ]) \
               and self.folder.is_transitive_parent_of(host.folder())


def match_search_expression(search_options, attr_name, search_in):
    if attr_name not in search_options:
        return True  # not searched for this. Matching!

    return search_in and re.search(search_options[attr_name], search_in, re.I) != None


def match_one_of_search_expression(search_options, attr_name, search_in_list):
    for search_in in search_in_list:
        if match_search_expression(search_options, attr_name, search_in):
            return True
    return False


class RuleComment(TextAreaUnicode):
    def __init__(self, **kwargs):
        kwargs.setdefault("title", _("Comment"))
        kwargs.setdefault("help", _("An optional comment that explains the purpose of this rule."))
        kwargs.setdefault("rows", 4)
        kwargs.setdefault("cols", 80)
        super(RuleComment, self).__init__(**kwargs)

    def render_input(self, varprefix, value):
        html.open_div(style="white-space: nowrap;")

        super(RuleComment, self).render_input(varprefix, value)

        date_and_user = "%s %s: " % (time.strftime("%F", time.localtime()), config.user.id)

        html.nbsp()
        html.icon_button(
            None,
            title=_("Prefix date and your name to the comment"),
            icon="insertdate",
            onclick="vs_rule_comment_prefix_date_and_user(this, '%s');" % date_and_user)
        html.close_div()


#.
#   .--Read-Only-----------------------------------------------------------.
#   |           ____                _        ___        _                  |
#   |          |  _ \ ___  __ _  __| |      / _ \ _ __ | |_   _            |
#   |          | |_) / _ \/ _` |/ _` |_____| | | | '_ \| | | | |           |
#   |          |  _ <  __/ (_| | (_| |_____| |_| | | | | | |_| |           |
#   |          |_| \_\___|\__,_|\__,_|      \___/|_| |_|_|\__, |           |
#   |                                                     |___/            |
#   +----------------------------------------------------------------------+
#   | WATO can be set into read only mode manually.                        |
#   '----------------------------------------------------------------------'


def read_only_message():
    text = _("The configuration is currently in read only mode. ")

    if config.wato_read_only["enabled"] == True:
        text += _("The read only mode is enabled until it is turned of manually. ")

    elif isinstance(config.wato_read_only['enabled'], tuple):
        end_time = config.wato_read_only['enabled'][1]
        text += _("The read only mode is enabled until %s. ") % render.date_and_time(end_time)

    if may_override_read_only_mode():
        text += _("But you are allowed to make changes anyway. ")

    text += "<br><br>" + _("Reason: %s") % config.wato_read_only["message"]

    return text


def is_read_only_mode_enabled():
    if not config.wato_read_only:
        return False

    enabled = False
    if config.wato_read_only["enabled"] == True:
        enabled = True
    elif isinstance(config.wato_read_only['enabled'], tuple):
        start_time, end_time = config.wato_read_only['enabled']
        now = time.time()
        enabled = now >= start_time and now <= end_time

    if not enabled:
        return False

    return True


def may_override_read_only_mode():
    return config.user.id in config.wato_read_only["rw_users"] \
            or (html.var("mode") == "read_only" and config.user.may("wato.set_read_only"))


#.
#   .--Timeperiods---------------------------------------------------------.
#   |      _____ _                                _           _            |
#   |     |_   _(_)_ __ ___   ___ _ __   ___ _ __(_) ___   __| |___        |
#   |       | | | | '_ ` _ \ / _ \ '_ \ / _ \ '__| |/ _ \ / _` / __|       |
#   |       | | | | | | | | |  __/ |_) |  __/ |  | | (_) | (_| \__ \       |
#   |       |_| |_|_| |_| |_|\___| .__/ \___|_|  |_|\___/ \__,_|___/       |
#   |                            |_|                                       |
#   +----------------------------------------------------------------------+


def builtin_timeperiods():
    return {
        "24X7": {
            "alias": _("Always"),
            "monday": ("00:00", "24:00"),
            "tuesday": ("00:00", "24:00"),
            "wednesday": ("00:00", "24:00"),
            "thursday": ("00:00", "24:00"),
            "friday": ("00:00", "24:00"),
            "saturday": ("00:00", "24:00"),
            "sunday": ("00:00", "24:00"),
        }
    }


def load_timeperiods():
    timeperiods = store.load_from_mk_file(wato_root_dir + "timeperiods.mk", "timeperiods", {})
    timeperiods.update(builtin_timeperiods())
    return timeperiods


def save_timeperiods(timeperiods):
    store.mkdir(wato_root_dir)
    store.save_to_mk_file(
        wato_root_dir + "timeperiods.mk",
        "timeperiods",
        filter_builtin_timeperiods(timeperiods),
        pprint_value=config.wato_pprint_config)


def filter_builtin_timeperiods(timeperiods):
    builtin_keys = builtin_timeperiods().keys()
    return {k: v for k, v in timeperiods.items() if k not in builtin_keys}


class TimeperiodSelection(DropdownChoice):
    def __init__(self, **kwargs):
        kwargs.setdefault("no_preselect", True)
        kwargs.setdefault("no_preselect_title", _("Select a timeperiod"))
        DropdownChoice.__init__(self, choices=self._get_choices, **kwargs)

    def _get_choices(self):
        timeperiods = load_timeperiods()
        elements = [(name, "%s - %s" % (name, tp["alias"])) for (name, tp) in timeperiods.items()]

        always = ("24X7", _("Always"))
        if always not in elements:
            elements.insert(0, always)

        return sorted(elements, key=lambda x: x[1].lower())


#.
#   .--Groups--------------------------------------------------------------.
#   |                    ____                                              |
#   |                   / ___|_ __ ___  _   _ _ __  ___                    |
#   |                  | |  _| '__/ _ \| | | | '_ \/ __|                   |
#   |                  | |_| | | | (_) | |_| | |_) \__ \                   |
#   |                   \____|_|  \___/ \__,_| .__/|___/                   |
#   |                                        |_|                           |
#   +----------------------------------------------------------------------+


def is_alias_used(my_what, my_name, my_alias):
    # Host / Service / Contact groups
    all_groups = userdb.load_group_information()
    for what, groups in all_groups.items():
        for gid, group in groups.items():
            if group['alias'] == my_alias and (my_what != what or my_name != gid):
                return False, _("This alias is already used in the %s group %s.") % (what, gid)

    # Timeperiods
    timeperiods = load_timeperiods()
    for key, value in timeperiods.items():
        if value.get("alias") == my_alias and (my_what != "timeperiods" or my_name != key):
            return False, _("This alias is already used in timeperiod %s.") % key

    # Roles
    roles = userdb.load_roles()
    for key, value in roles.items():
        if value.get("alias") == my_alias and (my_what != "roles" or my_name != key):
            return False, _("This alias is already used in the role %s.") % key

    return True, None


def check_modify_group_permissions(group_type):
    required_permissions = {
        "contact": ["wato.users"],
        "host": ["wato.groups"],
        "service": ["wato.groups"],
    }

    # Check permissions
    for permission in required_permissions.get(group_type):
        if not config.user.may(permission):
            raise MKAuthException(config.permissions_by_name[permission]["title"])


def _set_group(all_groups, group_type, name, extra_info):
    # Check if this alias is used elsewhere
    alias = extra_info.get("alias")
    if not alias:
        raise MKUserError("alias", "Alias is missing")

    unique, info = is_alias_used(group_type, name, alias)
    if not unique:
        raise MKUserError("alias", info)

    all_groups.setdefault(group_type, {})
    all_groups[group_type].setdefault(name, {})
    all_groups[group_type][name] = extra_info
    save_group_information(all_groups)

    if group_type == "contact":
        call_hook_contactsgroups_saved(all_groups)


def add_group(name, group_type, extra_info):
    check_modify_group_permissions(group_type)
    all_groups = userdb.load_group_information()
    groups = all_groups.get(group_type, {})

    # Check group name
    if len(name) == 0:
        raise MKUserError("name", _("Please specify a name of the new group."))
    if ' ' in name:
        raise MKUserError("name", _("Sorry, spaces are not allowed in group names."))
    if not re.match(r"^[-a-z0-9A-Z_\.]*$", name):
        raise MKUserError(
            "name",
            _("Invalid group name. Only the characters a-z, A-Z, 0-9, _, . and - are allowed."))
    if name in groups:
        raise MKUserError("name", _("Sorry, there is already a group with that name"))

    _set_group(all_groups, group_type, name, extra_info)
    add_group_change(extra_info, "edit-%sgroups" % group_type,
                     _("Create new %s group %s") % (group_type, name))


def edit_group(name, group_type, extra_info):
    check_modify_group_permissions(group_type)
    all_groups = userdb.load_group_information()
    groups = all_groups.get(group_type, {})

    if name not in groups:
        raise MKUserError("name", _("Unknown group: %s") % name)

    old_group_backup = copy.deepcopy(groups[name])

    _set_group(all_groups, group_type, name, extra_info)
    if cmk.is_managed_edition():
        old_customer = managed.get_customer_id(old_group_backup)
        new_customer = managed.get_customer_id(extra_info)
        if old_customer != new_customer:
            add_group_change(
                old_group_backup, "edit-%sgroups" % group_type,
                _("Removed %sgroup %s from customer %s") %
                (group_type, name, managed.get_customer_name_by_id(old_customer)))
            add_group_change(
                extra_info, "edit-%sgroups" % group_type,
                _("Moved %sgroup %s to customer %s. Additional properties may have changed.") %
                (group_type, name, managed.get_customer_name_by_id(new_customer)))
        else:
            add_group_change(old_group_backup, "edit-%sgroups" % group_type,
                             _("Updated properties of %sgroup %s") % (group_type, name))
    else:
        add_group_change(extra_info, "edit-%sgroups" % group_type,
                         _("Updated properties of %s group %s") % (group_type, name))


def delete_group(name, group_type):
    check_modify_group_permissions(group_type)

    # Check if group exists
    all_groups = userdb.load_group_information()
    groups = all_groups.get(group_type, {})
    if name not in groups:
        raise MKUserError(None, _("Unknown %s group: %s") % (group_type, name))

    # Check if still used
    usages = find_usages_of_group(name, group_type)
    if usages:
        raise MKUserError(
            None,
            _("Unable to delete group. It is still in use by: %s") % ", ".join(
                [e[0] for e in usages]))

    # Delete group
    group = groups.pop(name)
    save_group_information(all_groups)
    add_group_change(group, "edit-%sgroups", _("Deleted %s group %s") % (group_type, name))


# TODO: Consolidate all group change related functions in a class that can be overriden
# by the CME code for better encapsulation.
def add_group_change(group, action_name, text):
    group_sites = None
    if cmk.is_managed_edition() and not managed.is_global(managed.get_customer_id(group)):
        group_sites = managed.get_sites_of_customer(managed.get_customer_id(group))

    add_change(action_name, text, sites=group_sites)


def save_group_information(all_groups, custom_default_config_dir=None):
    # Split groups data into Check_MK/Multisite parts
    check_mk_groups = {}
    multisite_groups = {}

    if custom_default_config_dir:
        check_mk_config_dir = "%s/conf.d/wato" % custom_default_config_dir
        multisite_config_dir = "%s/multisite.d/wato" % custom_default_config_dir
    else:
        check_mk_config_dir = "%s/conf.d/wato" % cmk.paths.default_config_dir
        multisite_config_dir = "%s/multisite.d/wato" % cmk.paths.default_config_dir

    for what, groups in all_groups.items():
        check_mk_groups[what] = {}
        for gid, group in groups.items():
            check_mk_groups[what][gid] = group['alias']

            for attr, value in group.items():
                if attr != 'alias':
                    multisite_groups.setdefault(what, {})
                    multisite_groups[what].setdefault(gid, {})
                    multisite_groups[what][gid][attr] = value

    # Save Check_MK world related parts
    store.mkdir(check_mk_config_dir)
    output = wato_fileheader()
    for what in ["host", "service", "contact"]:
        if check_mk_groups.get(what):
            output += "if type(define_%sgroups) != dict:\n    define_%sgroups = {}\n" % (what, what)
            output += "define_%sgroups.update(%s)\n\n" % (
                what, format_config_value(check_mk_groups[what]))
    cmk.store.save_file("%s/groups.mk" % check_mk_config_dir, output)

    # Users with passwords for Multisite
    store.mkdir(multisite_config_dir)
    output = wato_fileheader()
    for what in ["host", "service", "contact"]:
        if multisite_groups.get(what):
            output += "multisite_%sgroups = \\\n%s\n\n" % (
                what, format_config_value(multisite_groups[what]))
    cmk.store.save_file("%s/groups.mk" % multisite_config_dir, output)


def find_usages_of_group(name, group_type):
    usages = []
    if group_type == 'contact':
        usages = find_usages_of_contact_group(name)
    elif group_type == 'host':
        usages = find_usages_of_host_group(name)
    elif group_type == 'service':
        usages = find_usages_of_service_group(name)
    return usages


def find_usages_of_group_in_rules(name, varnames):
    used_in = []
    rulesets = AllRulesets()
    rulesets.load()
    for varname in varnames:
        ruleset = rulesets.get(varname)
        for _folder, _rulenr, rule in ruleset.get_rules():
            if rule.value == name:
                used_in.append(("%s: %s" % (_("Ruleset"), ruleset.title()),
                                folder_preserving_link([("mode", "edit_ruleset"),
                                                        ("varname", varname)])))
    return used_in


# Check if a group is currently in use and cannot be deleted
# Returns a list of occurrances.
# Possible usages:
# - 1. rules: host to contactgroups, services to contactgroups
# - 2. user memberships
def find_usages_of_contact_group(name):
    # Part 1: Rules
    used_in = find_usages_of_group_in_rules(name, ['host_contactgroups', 'service_contactgroups'])

    # Is the contactgroup assigned to a user?
    users = userdb.load_users()
    entries = users.items()
    for userid, user in sorted(entries, key=lambda x: x[1].get("alias", x[0])):
        cgs = user.get("contactgroups", [])
        if name in cgs:
            used_in.append(('%s: %s' % (_('User'), user.get('alias', userid)),
                            folder_preserving_link([('mode', 'edit_user'), ('edit', userid)])))

    global_config = load_configuration_settings()

    # Used in default_user_profile?
    (domain, valuespec, _need_restart, _allow_reset,
     _in_global_settings) = configvars()['default_user_profile']
    configured = global_config.get('default_user_profile', {})
    default_value = domain().default_globals()["default_user_profile"]
    if (configured and name in configured['contactgroups']) \
       or name in  default_value['contactgroups']:
        used_in.append(('%s' % (_('Default User Profile')),
                        folder_preserving_link([('mode', 'edit_configvar'),
                                                ('varname', 'default_user_profile')])))

    # Is the contactgroup used in mkeventd notify (if available)?
    if 'mkeventd_notify_contactgroup' in configvars():
        (domain, valuespec, _need_restart, _allow_reset,
         _in_global_settings) = configvars()['mkeventd_notify_contactgroup']
        configured = global_config.get('mkeventd_notify_contactgroup')
        default_value = domain().default_globals()["mkeventd_notify_contactgroup"]
        if (configured and name == configured) \
           or name == default_value:
            used_in.append(('%s' % (valuespec.title()),
                            folder_preserving_link([('mode', 'edit_configvar'),
                                                    ('varname', 'mkeventd_notify_contactgroup')])))

    return used_in


def find_usages_of_host_group(name):
    return find_usages_of_group_in_rules(name, ['host_groups'])


def find_usages_of_service_group(name):
    return find_usages_of_group_in_rules(name, ['service_groups'])


#.
#   .--Notifications-(Rule Based)------------------------------------------.
#   |       _   _       _   _  __ _           _   _                        |
#   |      | \ | | ___ | |_(_)/ _(_) ___ __ _| |_(_) ___  _ __  ___        |
#   |      |  \| |/ _ \| __| | |_| |/ __/ _` | __| |/ _ \| '_ \/ __|       |
#   |      | |\  | (_) | |_| |  _| | (_| (_| | |_| | (_) | | | \__ \       |
#   |      |_| \_|\___/ \__|_|_| |_|\___\__,_|\__|_|\___/|_| |_|___/       |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   |  Module for managing the new rule based notifications.               |
#   '----------------------------------------------------------------------'


def load_notification_rules(lock=False):
    filename = wato_root_dir + "notifications.mk"
    notification_rules = store.load_from_mk_file(filename, "notification_rules", [], lock=lock)

    # Convert to new plugin configuration format
    for rule in notification_rules:
        if "notify_method" in rule:
            method = rule["notify_method"]
            plugin = rule["notify_plugin"]
            del rule["notify_method"]
            rule["notify_plugin"] = (plugin, method)

    return notification_rules


def save_notification_rules(rules):
    store.mkdir(wato_root_dir)
    store.save_to_mk_file(
        wato_root_dir + "notifications.mk",
        "notification_rules",
        rules,
        pprint_value=config.wato_pprint_config)


#.
#   .--Users---------------------------------------------------------------.
#   |                       _   _                                          |
#   |                      | | | |___  ___ _ __ ___                        |
#   |                      | | | / __|/ _ \ '__/ __|                       |
#   |                      | |_| \__ \  __/ |  \__ \                       |
#   |                       \___/|___/\___|_|  |___/                       |
#   |                                                                      |
#   +----------------------------------------------------------------------+

# Registers notification parameters for a certain notification script,
# e.g. "mail" or "sms". This will create:
# - A WATO host rule
# - A parametrization of the not-script also in the RBN module
# Notification parameters are always expected to be of type Dictionary.
# The match type will be set to "dict".


def register_user_script_parameters(ruleset_dict, ruleset_dict_name, ruleset_group, scriptname,
                                    valuespec):
    script_title = notification_script_title(scriptname)
    title = _("Parameters for %s") % script_title
    valuespec._title = _("Call with the following parameters:")

    register_rule(
        ruleset_group,
        ruleset_dict_name + ":" + scriptname,
        valuespec,
        title,
        itemtype=None,
        match="dict")
    ruleset_dict[scriptname] = valuespec


g_notification_parameters = {}


def register_notification_parameters(scriptname, valuespec):
    register_user_script_parameters(g_notification_parameters, "notification_parameters",
                                    "monconf/" + _("Notifications"), scriptname, valuespec)


def verify_password_policy(password):
    min_len = config.password_policy.get('min_length')
    if min_len and len(password) < min_len:
        raise MKUserError(
            'password',
            _('The given password is too short. It must have at least %d characters.') % min_len)

    num_groups = config.password_policy.get('num_groups')
    if num_groups:
        groups = {}
        for c in password:
            if c in "abcdefghijklmnopqrstuvwxyz":
                groups['lcase'] = 1
            elif c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                groups['ucase'] = 1
            elif c in "0123456789":
                groups['numbers'] = 1
            else:
                groups['special'] = 1

        if sum(groups.values()) < num_groups:
            raise MKUserError(
                'password',
                _('The password does not use enough character groups. You need to '
                  'set a password which uses at least %d of them.') % num_groups)


def notification_script_choices():
    choices = []
    for choice in user_script_choices("notifications") + [(None, _("ASCII Email (legacy)"))]:
        notificaton_plugin_name, _notification_plugin_title = choice
        if config.user.may("notification_plugin.%s" % notificaton_plugin_name):
            choices.append(choice)
    return choices


def notification_script_choices_with_parameters():
    choices = []
    for script_name, title in notification_script_choices():
        if script_name in g_notification_parameters:
            vs = g_notification_parameters[script_name]
        else:
            vs = ListOfStrings(
                title=_("Call with the following parameters:"),
                help=
                _("The given parameters are available in scripts as NOTIFY_PARAMETER_1, NOTIFY_PARAMETER_2, etc."
                 ),
                valuespec=TextUnicode(size=24),
                orientation="horizontal",
            )

        vs_alternative = Alternative(
            style="dropdown",
            elements=[
                vs,
                FixedValue(
                    None,
                    totext=_("previous notifications of this type are cancelled"),
                    title=_("Cancel previous notifications")),
            ],
        )

        choices.append((script_name, title, vs_alternative))
    return choices


def notification_script_title(name):
    return user_script_title("notifications", name)


def service_levels():
    try:
        return config.mkeventd_service_levels
    except:
        return [(0, "(no service level)")]


def get_vs_flexible_notifications():
    # Make sure, that list is not trivially false
    def validate_only_services(value, varprefix):
        for s in value:
            if s and s[0] != '!':
                return
        raise MKUserError(varprefix + "_0", _("The list of services will never match"))

    return CascadingDropdown(
        title=_("Notification Method"),
        choices=[
            ("email", _("Plain Text Email (using configured templates)")),
            (
                "flexible",
                _("Flexible Custom Notifications"),
                ListOf(
                    Foldable(
                        Dictionary(
                            optional_keys=[
                                "service_blacklist", "only_hosts", "only_services", "escalation",
                                "match_sl"
                            ],
                            columns=1,
                            headers=True,
                            elements=[
                                (
                                    "plugin",
                                    DropdownChoice(
                                        title=_("Notification Plugin"),
                                        choices=notification_script_choices,
                                        default_value="mail",
                                    ),
                                ),
                                ("parameters",
                                 ListOfStrings(
                                     title=_("Plugin Arguments"),
                                     help=
                                     _("You can specify arguments to the notification plugin here. "
                                       "Please refer to the documentation about the plugin for what "
                                       "parameters are allowed or required here."),
                                 )),
                                ("disabled",
                                 Checkbox(
                                     title=_("Disabled"),
                                     label=_("Currently disable this notification"),
                                     default_value=False,
                                 )),
                                ("timeperiod",
                                 TimeperiodSelection(
                                     title=_("Timeperiod"),
                                     help=_("Do only notifiy alerts within this time period"),
                                 )),
                                (
                                    "escalation",
                                    Tuple(
                                        title=
                                        _("Restrict to n<sup>th</sup> to m<sup>th</sup> notification (escalation)"
                                         ),
                                        orientation="float",
                                        elements=[
                                            Integer(
                                                label=_("from"),
                                                help=
                                                _("Let through notifications counting from this number"
                                                 ),
                                                default_value=1,
                                                minvalue=1,
                                                maxvalue=999999,
                                            ),
                                            Integer(
                                                label=_("to"),
                                                help=
                                                _("Let through notifications counting upto this number"
                                                 ),
                                                default_value=999999,
                                                minvalue=1,
                                                maxvalue=999999,
                                            ),
                                        ],
                                    ),
                                ),
                                (
                                    "match_sl",
                                    Tuple(
                                        title=_("Match service level"),
                                        help=
                                        _("Host or Service must be in the following service level to get notification"
                                         ),
                                        orientation="horizontal",
                                        show_titles=False,
                                        elements=[
                                            DropdownChoice(
                                                label=_("from:"),
                                                choices=service_levels,
                                                prefix_values=True),
                                            DropdownChoice(
                                                label=_(" to:"),
                                                choices=service_levels,
                                                prefix_values=True),
                                        ],
                                    ),
                                ),
                                ("host_events",
                                 ListChoice(
                                     title=_("Host Events"),
                                     choices=[
                                         ('d', _("Host goes down")),
                                         ('u', _("Host gets unreachble")),
                                         ('r', _("Host goes up again")),
                                         ('f', _("Start or end of flapping state")),
                                         ('s', _("Start or end of a scheduled downtime ")),
                                         ('x', _("Acknowledgement of host problem")),
                                     ],
                                     default_value=['d', 'u', 'r', 'f', 's', 'x'],
                                 )),
                                ("service_events",
                                 ListChoice(
                                     title=_("Service Events"),
                                     choices=[
                                         ('w', _("Service goes into warning state")),
                                         ('u', _("Service goes into unknown state")),
                                         ('c', _("Service goes into critical state")),
                                         ('r', _("Service recovers to OK")),
                                         ('f', _("Start or end of flapping state")),
                                         ('s', _("Start or end of a scheduled downtime")),
                                         ('x', _("Acknowledgement of service problem")),
                                     ],
                                     default_value=['w', 'c', 'u', 'r', 'f', 's', 'x'],
                                 )),
                                (
                                    "only_hosts",
                                    ListOfStrings(
                                        title=_("Limit to the following hosts"),
                                        help=
                                        _("Configure the hosts for this notification. Without prefix, only exact, case sensitive matches, "
                                          "<tt>!</tt> for negation and <tt>~</tt> for regex matches."
                                         ),
                                        orientation="horizontal",
                                        # TODO: Clean this up to use an alternative between TextAscii() and RegExp(). Also handle the negation in a different way
                                        valuespec=TextAscii(size=20,),
                                    ),
                                ),
                                (
                                    "only_services",
                                    ListOfStrings(
                                        title=_("Limit to the following services"),
                                        help=
                                        _("Configure regular expressions that match the beginning of the service names here. Prefix an "
                                          "entry with <tt>!</tt> in order to <i>exclude</i> that service."
                                         ),
                                        orientation="horizontal",
                                        # TODO: Clean this up to use an alternative between TextAscii() and RegExp(). Also handle the negation in a different way
                                        valuespec=TextAscii(size=20,),
                                        validate=validate_only_services,
                                    ),
                                ),
                                (
                                    "service_blacklist",
                                    ListOfStrings(
                                        title=_("Blacklist the following services"),
                                        help=
                                        _("Configure regular expressions that match the beginning of the service names here."
                                         ),
                                        orientation="horizontal",
                                        valuespec=RegExp(
                                            size=20,
                                            mode=RegExp.prefix,
                                        ),
                                        validate=validate_only_services,
                                    ),
                                ),
                            ]),
                        title_function=
                        lambda v: _("Notify by: ") + notification_script_title(v["plugin"]),
                    ),
                    title=_("Flexible Custom Notifications"),
                    add_label=_("Add notification"),
                ),
            ),
        ])


def get_vs_notification_methods():
    return CascadingDropdown(
        title=_("Notification Method"),
        choices=notification_script_choices_with_parameters,
        default_value=("mail", {}))


def get_vs_user_idle_timeout():
    return Alternative(
        title=_("Session idle timeout"),
        elements=[
            FixedValue(
                None,
                title=_("Use the global configuration"),
                totext="",
            ),
            FixedValue(
                False,
                title=_("Disable the login timeout"),
                totext="",
            ),
            Age(
                title=_("Set an individual idle timeout"),
                display=["minutes", "hours", "days"],
                minvalue=60,
                default_value=3600,
            ),
        ],
        style="dropdown",
        orientation="horizontal",
    )


def validate_user_attributes(all_users, user_id, user_attrs, is_new_user=True):
    # Check user_id
    if is_new_user:
        if user_id in all_users:
            raise MKUserError("user_id", _("This username is already being used by another user."))
        vs_user_id = UserID(allow_empty=False)
        vs_user_id.validate_value(user_id, "user_id")
    else:
        if user_id not in all_users:
            raise MKUserError(None, _("The user you are trying to edit does not exist."))

    # Full name
    alias = user_attrs.get("alias")
    if not alias:
        raise MKUserError("alias",
                          _("Please specify a full name or descriptive alias for the user."))

    # Locking
    locked = user_attrs.get("locked")
    if user_id == config.user.id and locked:
        raise MKUserError("locked", _("You cannot lock your own account!"))

    # Authentication: Password or Secret
    if "automation_secret" in user_attrs:
        secret = user_attrs["automation_secret"]
        if len(secret) < 10:
            raise MKUserError('secret',
                              _("Please specify a secret of at least 10 characters length."))
    else:
        password = user_attrs.get("password")
        if password:
            verify_password_policy(password)

    # Email
    email = user_attrs.get("email")
    vs_email = EmailAddressUnicode()
    vs_email.validate_value(email, "email")

    # Idle timeout
    idle_timeout = user_attrs.get("idle_timeout")
    vs_user_idle_timeout = get_vs_user_idle_timeout()
    vs_user_idle_timeout.validate_value(idle_timeout, "idle_timeout")

    # Notification settings are only active if we do *not* have rule based notifications!
    rulebased_notifications = load_configuration_settings().get("enable_rulebased_notifications")
    if not rulebased_notifications:
        # Notifications
        notifications_enabled = user_attrs.get("notification_enabled")

        # Check if user can receive notifications
        if notifications_enabled:
            if not email:
                raise MKUserError(
                    "email",
                    _('You have enabled the notifications but missed to configure a '
                      'Email address. You need to configure your mail address in order '
                      'to be able to receive emails.'))

            contactgroups = user_attrs.get("contactgroups")
            if not contactgroups:
                raise MKUserError(
                    "notifications_enabled",
                    _('You have enabled the notifications but missed to make the '
                      'user member of at least one contact group. You need to make '
                      'the user member of a contact group which has hosts assigned '
                      'in order to be able to receive emails.'))

            roles = user_attrs.get("roles")
            if not roles:
                raise MKUserError("role_user",
                                  _("Your user has no roles. Please assign at least one role."))

        notification_method = user_attrs.get("notification_method")
        get_vs_flexible_notifications().validate_value(notification_method, "notification_method")
    else:
        fallback_contact = user_attrs.get("fallback_contact")
        if fallback_contact and not email:
            raise MKUserError(
                "email",
                _("You have enabled the fallback notifications but missed to configure an "
                  "email address. You need to configure your mail address in order "
                  "to be able to receive fallback notifications."))

    # Custom user attributes
    for name, attr in userdb.get_user_attributes():
        value = user_attrs.get(name)
        attr.valuespec().validate_value(value, "ua_" + name)


def delete_users(users_to_delete):
    if config.user.id in users_to_delete:
        raise MKUserError(None, _("You cannot delete your own account!"))

    all_users = userdb.load_users(lock=True)

    deleted_users = []
    for entry in users_to_delete:
        if entry in all_users:  # Silently ignore not existing users
            deleted_users.append(entry)
            del all_users[entry]
        else:
            raise MKUserError(None, _("Unknown user: %s") % entry)

    if deleted_users:
        add_change("edit-users", _("Deleted user: %s") % ", ".join(deleted_users))
        userdb.save_users(all_users)


def edit_users(changed_users):
    all_users = userdb.load_users(lock=True)
    new_users_info = []
    modified_users_info = []
    for user_id, settings in changed_users.items():
        user_attrs = settings.get("attributes")
        is_new_user = settings.get("is_new_user", True)
        validate_user_attributes(all_users, user_id, user_attrs, is_new_user=is_new_user)
        if is_new_user:
            new_users_info.append(user_id)
        else:
            modified_users_info.append(user_id)

        all_users[user_id] = user_attrs

    if new_users_info:
        add_change("edit-users", _("Created new user: %s") % ", ".join(new_users_info))
    if modified_users_info:
        add_change("edit-users", _("Modified user: %s") % ", ".join(modified_users_info))

    userdb.save_users(all_users)


#.
#   .--Network Scan--------------------------------------------------------.
#   |   _   _      _                      _      ____                      |
#   |  | \ | | ___| |___      _____  _ __| | __ / ___|  ___ __ _ _ __      |
#   |  |  \| |/ _ \ __\ \ /\ / / _ \| '__| |/ / \___ \ / __/ _` | '_ \     |
#   |  | |\  |  __/ |_ \ V  V / (_) | |  |   <   ___) | (_| (_| | | | |    |
#   |  |_| \_|\___|\__| \_/\_/ \___/|_|  |_|\_\ |____/ \___\__,_|_| |_|    |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | The WATO folders network scan for new hosts.                         |
#   '----------------------------------------------------------------------'


def do_network_scan_automation():
    folder_path = html.var("folder")
    if folder_path == None:
        raise MKGeneralException(_("Folder path is missing"))
    folder = Folder.folder(folder_path)

    return do_network_scan(folder)


automation_commands["network-scan"] = do_network_scan_automation


# This is executed in the site the host is assigned to.
# A list of tuples is returned where each tuple represents a new found host:
# [(hostname, ipaddress), ...]
def do_network_scan(folder):
    ip_addresses = _ip_addresses_to_scan(folder)
    return _scan_ip_addresses(folder, ip_addresses)


def _ip_addresses_to_scan(folder):
    ip_range_specs = folder.attribute("network_scan")["ip_ranges"]
    exclude_specs = folder.attribute("network_scan")["exclude_ranges"]

    to_scan = _ip_addresses_of_ranges(ip_range_specs)
    exclude = _ip_addresses_of_ranges(exclude_specs)

    # Remove excludes from to_scan list
    to_scan.difference_update(exclude)

    # Reduce by all known host addresses
    # FIXME/TODO: Shouldn't this filtering be done on the central site?
    to_scan.difference_update(_known_ip_addresses())

    # And now apply the IP regex patterns to exclude even more addresses
    to_scan.difference_update(_excludes_by_regexes(to_scan, exclude_specs))

    return to_scan


def _ip_addresses_of_ranges(ip_ranges):
    addresses = set([])

    for ty, spec in ip_ranges:
        if ty == "ip_range":
            addresses.update(_ip_addresses_of_range(spec))

        elif ty == "ip_network":
            addresses.update(_ip_addresses_of_network(spec))

        elif ty == "ip_list":
            addresses.update(spec)

    return addresses


FULL_IPV4 = (2**32) - 1


def _ip_addresses_of_range(spec):
    first_int, last_int = map(_ip_int_from_string, spec)

    addresses = []

    if first_int > last_int:
        return addresses  # skip wrong config

    while first_int <= last_int:
        addresses.append(_string_from_ip_int(first_int))
        first_int += 1
        if first_int - 1 == FULL_IPV4:  # stop on last IPv4 address
            break

    return addresses


def _ip_int_from_string(ip_str):
    packed_ip = 0
    octets = ip_str.split(".")
    for oc in octets:
        packed_ip = (packed_ip << 8) | int(oc)
    return packed_ip


def _string_from_ip_int(ip_int):
    octets = []
    for _ in xrange(4):
        octets.insert(0, str(ip_int & 0xFF))
        ip_int >>= 8
    return ".".join(octets)


def _ip_addresses_of_network(spec):
    net_addr, net_bits = spec

    ip_int = _ip_int_from_string(net_addr)
    mask_int = _mask_bits_to_int(int(net_bits))
    first = ip_int & (FULL_IPV4 ^ mask_int)
    last = ip_int | (1 << (32 - int(net_bits))) - 1

    return [_string_from_ip_int(i) for i in range(first + 1, last - 1)]


def _mask_bits_to_int(n):
    return (1 << (32 - n)) - 1


# This will not scale well. Do you have a better idea?
def _known_ip_addresses():
    addresses = (host.attribute("ipaddress") for host in Host.all().itervalues())
    return [address for address in addresses if address]


def _excludes_by_regexes(addresses, exclude_specs):
    patterns = []
    for ty, spec in exclude_specs:
        if ty == "ip_regex_list":
            for p in spec:
                patterns.append(re.compile(p))

    if not patterns:
        return []

    excludes = []
    for address in addresses:
        for p in patterns:
            if p.match(address):
                excludes.append(address)
                break  # one match is enough, exclude this.

    return excludes


# Start ping threads till max parallel pings let threads do their work till all are done.
# let threds also do name resolution. Return list of tuples (hostname, address).
def _scan_ip_addresses(folder, ip_addresses):
    num_addresses = len(ip_addresses)

    # dont start more threads than needed
    parallel_pings = min(
        folder.attribute("network_scan").get("max_parallel_pings", 100), num_addresses)

    # Initalize all workers
    threads = []
    found_hosts = []
    for _t_num in range(parallel_pings):
        t = threading.Thread(target=_ping_worker, args=[ip_addresses, found_hosts])
        t.daemon = True
        threads.append(t)
        t.start()

    # Now wait for all workers to finish
    for t in threads:
        t.join()

    return found_hosts


def _ping_worker(addresses, hosts):
    while True:
        try:
            ipaddress = addresses.pop()
        except KeyError:
            break

        if _ping(ipaddress):
            try:
                host_name = socket.gethostbyaddr(ipaddress)[0]
            except socket.error:
                host_name = ipaddress

            hosts.append((host_name, ipaddress))


def _ping(address):
    return subprocess.Popen(['ping', '-c2', '-w2', address],
                            stdout=open(os.devnull, "a"),
                            stderr=subprocess.STDOUT,
                            close_fds=True).wait() == 0


#.
#   .--Backups-------------------------------------------------------------.
#   |                ____             _                                    |
#   |               | __ )  __ _  ___| | ___   _ _ __  ___                 |
#   |               |  _ \ / _` |/ __| |/ / | | | '_ \/ __|                |
#   |               | |_) | (_| | (__|   <| |_| | |_) \__ \                |
#   |               |____/ \__,_|\___|_|\_\\__,_| .__/|___/                |
#   |                                           |_|                        |
#   +----------------------------------------------------------------------+
#   | Managing backup and restore of WATO                                  |
#   '----------------------------------------------------------------------'


class SiteBackupJobs(backup.Jobs):
    def __init__(self):
        super(SiteBackupJobs, self).__init__(backup.site_config_path())

    def _apply_cron_config(self):
        p = subprocess.Popen(["omd", "restart", "crontab"],
                             close_fds=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             stdin=open(os.devnull))
        if p.wait() != 0:
            raise MKGeneralException(_("Failed to apply the cronjob config: %s") % p.stdout.read())


#.
#   .--Best Practices------------------------------------------------------.
#   |   ____            _     ____                 _   _                   |
#   |  | __ )  ___  ___| |_  |  _ \ _ __ __ _  ___| |_(_) ___ ___  ___     |
#   |  |  _ \ / _ \/ __| __| | |_) | '__/ _` |/ __| __| |/ __/ _ \/ __|    |
#   |  | |_) |  __/\__ \ |_  |  __/| | | (_| | (__| |_| | (_|  __/\__ \    |
#   |  |____/ \___||___/\__| |_|   |_|  \__,_|\___|\__|_|\___\___||___/    |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | Provides the user with hints about his setup. Performs different     |
#   | checks and tells the user what could be improved.                    |
#   '----------------------------------------------------------------------'


class ACResult(object):
    status = None

    def __init__(self, text):
        super(ACResult, self).__init__()
        self.text = text
        self.site_id = config.omd_site()

    def from_test(self, test):
        self.test_id = test.id()
        self.category = test.category()
        self.title = test.title()
        self.help = test.help()

    @classmethod
    def merge(cls, *results):
        """Create a new result object from the given result objects.

        a) use the worst state
        b) concatenate the texts
        """
        texts, worst_cls = [], ACResultOK
        for result in results:
            text = result.text
            if result.status != 0:
                text += " (%s)" % ("!" * result.status)
            texts.append(text)

            if result.status > worst_cls.status:
                worst_cls = result.__class__

        return worst_cls(", ".join(texts))

    def status_name(self):
        return cmk.defines.short_service_state_name(self.status)

    @classmethod
    def from_repr(cls, repr_data):
        result_class_name = repr_data.pop("class_name")
        result = globals()[result_class_name](repr_data["text"])

        for key, val in repr_data.items():
            setattr(result, key, val)

        return result

    def __repr__(self):
        return repr({
            "site_id": self.site_id,
            "class_name": self.__class__.__name__,
            "text": self.text,
            # These fields are be static - at least for the current version, but
            # we transfer them to the central system to be able to handle test
            # results of tests not known to the central site.
            "test_id": self.test_id,
            "category": self.category,
            "title": self.title,
            "help": self.help,
        })


class ACResultNone(ACResult):
    status = -1


class ACResultCRIT(ACResult):
    status = 2


class ACResultWARN(ACResult):
    status = 1


class ACResultOK(ACResult):
    status = 0


class ACTestCategories(object):
    usability = "usability"
    performance = "performance"
    security = "security"
    reliability = "reliability"
    deprecations = "deprecations"

    @classmethod
    def title(cls, ident):
        return {
            "usability": _("Usability"),
            "performance": _("Performance"),
            "security": _("Security"),
            "reliability": _("Reliability"),
            "deprecations": _("Deprecations"),
        }[ident]


class ACTest(object):
    def __init__(self):
        self._executed = False
        self._results = []

    def id(self):
        return self.__class__.__name__

    def category(self):
        """Return the internal name of the category the BP test is associated with"""
        raise NotImplementedError()

    def title(self):
        raise NotImplementedError()

    def help(self):
        raise NotImplementedError()

    def is_relevant(self):
        """A test can check whether or not is relevant for the current evnironment.
        In case this method returns False, the check will not be executed and not
        be shown to the user."""
        raise NotImplementedError()

    def execute(self):
        """Implement the test logic here. The method needs to add one or more test
        results like this:

        yield ACResultOK(_("it's fine"))
        """
        raise NotImplementedError()

    def run(self):
        self._executed = True
        try:
            # Do not merge results that have been gathered on one site for different sites
            results = list(self.execute())
            num_sites = len(set(r.site_id for r in results))
            if num_sites > 1:
                for result in results:
                    result.from_test(self)
                    yield result
                return

            # Merge multiple results produced for a single site
            total_result = ACResult.merge(*list(self.execute()))
            total_result.from_test(self)
            yield total_result
        except Exception:
            logger.exception()
            result = ACResultCRIT(
                "<pre>%s</pre>" % _("Failed to execute the test %s: %s") % (html.attrencode(
                    self.__class__.__name__), traceback.format_exc()))
            result.from_test(self)
            yield result

    def status(self):
        return max([0] + [r.status for r in self.results])

    def status_name(self):
        return cmk.defines.short_service_state_name(self.status())

    @property
    def results(self):
        if not self._executed:
            raise MKGeneralException(_("The test has not been executed yet"))
        return self._results

    def _uses_microcore(self):
        """Whether or not the local site is using the CMC"""
        local_connection = sites.livestatus.LocalConnection()
        version = local_connection.query_value("GET status\nColumns: program_version\n", deflt="")
        return version.startswith("Check_MK")

    def _get_effective_global_setting(self, varname):
        global_settings = load_configuration_settings()
        default_values = ConfigDomain().get_all_default_globals()

        if is_wato_slave_site():
            current_settings = load_configuration_settings(site_specific=True)
        else:
            sites = SiteManagementFactory.factory().load_sites()
            current_settings = sites[config.omd_site()].get("globals", {})

        if varname in current_settings:
            value = current_settings[varname]
        elif varname in global_settings:
            value = global_settings[varname]
        else:
            value = default_values[varname]

        return value


class ACTestRegistry(cmk.plugin_registry.ClassRegistry):
    def plugin_base_class(self):
        return ACTest

    def _register(self, plugin_class):
        self._entries[plugin_class.__name__] = plugin_class


ac_test_registry = ACTestRegistry()


def check_analyze_config():
    results = []
    for test_cls in ac_test_registry.values():
        test = test_cls()

        if not test.is_relevant():
            continue

        for result in test.run():
            results.append(result)

    return results


automation_commands["check-analyze-config"] = check_analyze_config


def site_is_using_livestatus_proxy(site_id):
    sites = SiteManagementFactory().factory().load_sites()
    site = sites[site_id]

    socket = site.get("socket")
    if not socket:
        return False  # local site

    return isinstance(socket, tuple) and socket[0] == "proxy"


#.
#   .--MIXED STUFF---------------------------------------------------------.
#   |     __  __ _____  _______ ____    ____ _____ _   _ _____ _____       |
#   |    |  \/  |_ _\ \/ / ____|  _ \  / ___|_   _| | | |  ___|  ___|      |
#   |    | |\/| || | \  /|  _| | | | | \___ \ | | | | | | |_  | |_         |
#   |    | |  | || | /  \| |___| |_| |  ___) || | | |_| |  _| |  _|        |
#   |    |_|  |_|___/_/\_\_____|____/  |____/ |_|  \___/|_|   |_|          |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | CLEAN THIS UP LATER                                                  |
#   '----------------------------------------------------------------------'


class PasswordStore(object):
    def _load(self, lock=False):
        return store.load_from_mk_file(
            wato_root_dir + "/passwords.mk", key="stored_passwords", default={}, lock=lock)

    def _load_for_modification(self):
        return self._load(lock=True)

    def _owned_passwords(self):
        if config.user.may("wato.edit_all_passwords"):
            return self._load()

        user_groups = userdb.contactgroups_of_user(config.user.id)
        return dict([(k, v) for k, v in self._load().items() if v["owned_by"] in user_groups])

    def usable_passwords(self):
        if config.user.may("wato.edit_all_passwords"):
            return self._load()

        user_groups = userdb.contactgroups_of_user(config.user.id)

        passwords = self._owned_passwords()
        passwords.update(
            dict([(k, v) for k, v in self._load().items() if v["shared_with"] in user_groups]))
        return passwords

    def _save(self, value):
        return store.save_to_mk_file(
            wato_root_dir + "/passwords.mk",
            key="stored_passwords",
            value=value,
            pprint_value=config.wato_pprint_config)


class UserSelection(DropdownChoice):
    """Dropdown for choosing a multisite user"""

    def __init__(self, **kwargs):
        only_contacts = kwargs.get("only_contacts", False)
        kwargs["choices"] = self._generate_wato_users_elements_function(
            kwargs.get("none"), only_contacts=only_contacts)
        kwargs["invalid_choice"] = "complain"  # handle vanished users correctly!
        DropdownChoice.__init__(self, **kwargs)

    def _generate_wato_users_elements_function(self, none_value, only_contacts=False):
        def get_wato_users(nv):
            users = userdb.load_users()
            elements = [(name, "%s - %s" % (name, us.get("alias", name)))
                        for (name, us) in users.items()
                        if (not only_contacts or us.get("contactgroups"))]
            elements.sort()
            if nv != None:
                elements = [(None, none_value)] + elements
            return elements

        return lambda: get_wato_users(none_value)

    def value_to_text(self, value):
        text = DropdownChoice.value_to_text(self, value)
        return text.split(" - ")[-1]


def multifolder_host_rule_match_conditions():
    return [_site_rule_match_condition(),
            _multi_folder_rule_match_condition()] + _common_host_rule_match_conditions()


def _site_rule_match_condition():
    return (
        "match_site",
        DualListChoice(
            title=_("Match site"),
            help=_("This condition makes the rule match only hosts of "
                   "the selected sites."),
            choices=config.site_attribute_choices,
        ),
    )


def _multi_folder_rule_match_condition():
    return (
        "match_folders",
        ListOf(
            FullPathFolderChoice(
                title=_("Folder"),
                help=_("This condition makes the rule match only hosts that are managed "
                       "via WATO and that are contained in this folder - either directly "
                       "or in one of its subfolders."),
            ),
            add_label=_("Add additional folder"),
            title=_("Match folders"),
            movable=False),
    )


def _common_host_rule_match_conditions():
    return [
        ("match_hosttags", HostTagCondition(title=_("Match Host Tags"))),
        ("match_hostgroups",
         userdb.GroupChoice(
             "host",
             title=_("Match Host Groups"),
             help=_("The host must be in one of the selected host groups"),
             allow_empty=False,
         )),
        ("match_hosts",
         ListOfStrings(
             title=_("Match only the following hosts"),
             size=24,
             orientation="horizontal",
             allow_empty=False,
             empty_text=
             _("Please specify at least one host. Disable the option if you want to allow all hosts."
              ),
         )),
        ("match_exclude_hosts",
         ListOfStrings(
             title=_("Exclude the following hosts"),
             size=24,
             orientation="horizontal",
         ))
    ]


def simple_host_rule_match_conditions():
    return [_site_rule_match_condition(),
            _single_folder_rule_match_condition()] + _common_host_rule_match_conditions()


def _single_folder_rule_match_condition():
    return (
        "match_folder",
        FolderChoice(
            title=_("Match folder"),
            help=_("This condition makes the rule match only hosts that are managed "
                   "via WATO and that are contained in this folder - either directly "
                   "or in one of its subfolders."),
        ),
    )


class FolderChoice(DropdownChoice):
    def __init__(self, **kwargs):
        kwargs["choices"] = Folder.folder_choices
        kwargs.setdefault("title", _("Folder"))
        DropdownChoice.__init__(self, **kwargs)


class FullPathFolderChoice(DropdownChoice):
    def __init__(self, **kwargs):
        kwargs["choices"] = Folder.folder_choices_fulltitle
        kwargs.setdefault("title", _("Folder"))
        DropdownChoice.__init__(self, **kwargs)


def transform_simple_to_multi_host_rule_match_conditions(value):
    if value and "match_folder" in value:
        value["match_folders"] = [value.pop("match_folder")]
    return value


class WatoBackgroundProcess(gui_background_job.GUIBackgroundProcess):
    def initialize_environment(self):
        super(WatoBackgroundProcess, self).initialize_environment()

        if self._jobstatus.get_status().get("lock_wato"):
            cmk.store.release_all_locks()
            lock_exclusive()


class WatoBackgroundJob(gui_background_job.GUIBackgroundJob):
    _background_process_class = WatoBackgroundProcess


def add_replication_paths(paths):
    replication_paths.extend(paths)


def register_automation_command(cmd, func):
    automation_commands[cmd] = func


def automation_command_exists(cmd):
    return cmd in automation_commands


def execute_automation_command(cmd):
    return automation_commands[cmd]()


def site_neutral_path(path):
    if path.startswith('/omd'):
        parts = path.split('/')
        parts[3] = '[SITE_ID]'
        return '/'.join(parts)
    return path


def has_agent_bakery():
    try:
        # The suppression below is OK, we just want to check if the module is there.
        import cmk.gui.cee.agent_bakery  # pylint: disable=unused-variable
        return True
    except ImportError:
        return False


def get_folder_cgconf_from_attributes(attributes):
    v = attributes.get("contactgroups", (False, []))
    cgconf = convert_cgroups_from_tuple(v)
    return cgconf


# Checks if a valuespec is a Checkbox
def is_a_checkbox(vs):
    if isinstance(vs, Checkbox):
        return True
    elif isinstance(vs, Transform):
        return is_a_checkbox(vs._valuespec)
    return False


def get_search_expression():
    search = html.get_unicode_input("search")
    if search != None:
        search = search.strip().lower()
    return search


# This hook is called in order to determine the errors of the given
# hostnames. These informations are used for displaying warning
# symbols in the host list and the host detail view
# Returns dictionary { hostname: [errors] }
def validate_all_hosts(hostnames, force_all=False):
    if hooks.registered('validate-all-hosts') and (len(hostnames) > 0 or force_all):
        hosts_errors = {}
        all_hosts = collect_hosts(Folder.root_folder())

        if force_all:
            hostnames = all_hosts.keys()

        for name in hostnames:
            eff = all_hosts[name]
            errors = []
            for hk in hooks.get('validate-all-hosts'):
                try:
                    hk(eff, all_hosts)
                except MKUserError, e:
                    errors.append("%s" % e)
            hosts_errors[name] = errors
        return hosts_errors
    else:
        return {}


def wato_fileheader():
    return "# Created by WATO\n# encoding: utf-8\n\n"


g_need_sidebar_reload = None


def need_sidebar_reload():
    global g_need_sidebar_reload
    g_need_sidebar_reload = id(html)


def is_sidebar_reload_needed():
    return g_need_sidebar_reload == id(html)


def folder_preserving_link(add_vars):
    return Folder.current().url(add_vars)


def make_action_link(vars_):
    return folder_preserving_link(vars_ + [("_transid", html.transaction_manager.get())])


def lock_exclusive():
    store.aquire_lock(cmk.paths.default_config_dir + "/multisite.mk")


def unlock_exclusive():
    store.release_lock(cmk.paths.default_config_dir + "/multisite.mk")


def git_command(args):
    command = ["git"] + [a.encode("utf-8") for a in args]
    logger.debug(
        "GIT: Execute in %s: %s" % (cmk.paths.default_config_dir, subprocess.list2cmdline(command)))
    try:
        p = subprocess.Popen(
            command,
            cwd=cmk.paths.default_config_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
    except OSError, e:
        if e.errno == 2:
            raise MKGeneralException(
                _("Error executing GIT command <tt>%s</tt>:<br><br>%s") %
                (subprocess.list2cmdline(command), e))
        else:
            raise

    status = p.wait()
    if status != 0:
        raise MKGeneralException(
            _("Error executing GIT command <tt>%s</tt>:<br><br>%s") %
            (subprocess.list2cmdline(command), p.stdout.read().replace("\n", "<br>\n")))


def prepare_git_commit():
    global g_git_messages
    g_git_messages = []


def do_git_commit():
    author = "%s <%s>" % (config.user.id, config.user.email)
    git_dir = cmk.paths.default_config_dir + "/.git"
    if not os.path.exists(git_dir):
        logger.debug("GIT: Initializing")
        git_command(["init"])

        # Set git repo global user/mail. seems to be needed to prevent warning message
        # on at least ubuntu 15.04: "Please tell me who you are. Run git config ..."
        # The individual commits by users override the author on their own
        git_command(["config", "user.email", "check_mk"])
        git_command(["config", "user.name", "check_mk"])

        write_gitignore_files()
        git_add_files()
        git_command([
            "commit", "--untracked-files=no", "--author", author, "-m",
            _("Initialized GIT for Check_MK")
        ])

    if git_has_pending_changes():
        logger.debug("GIT: Found pending changes - Update gitignore file")
        write_gitignore_files()

    # Writing the gitignore files might have reverted the change. So better re-check.
    if git_has_pending_changes():
        logger.debug("GIT: Still has pending changes")
        git_add_files()

        message = ", ".join(g_git_messages)
        if not message:
            message = _("Unknown configuration change")

        git_command(["commit", "--author", author, "-m", message])


def git_add_files():
    path_pattern = os.path.join(cmk.paths.default_config_dir, "*.d/wato")
    rel_paths = [os.path.relpath(p, cmk.paths.default_config_dir) for p in glob.glob(path_pattern)]
    git_command(["add", "--all", ".gitignore"] + rel_paths)


def git_has_pending_changes():
    try:
        return subprocess.Popen(["git", "status", "--porcelain"],
                                cwd=cmk.paths.default_config_dir,
                                stdout=subprocess.PIPE).stdout.read() != ""
    except OSError, e:
        if e.errno == 2:
            return False  # ignore missing git command
        else:
            raise


# Make sure that .gitignore-files are present and uptodate. Only files below the "wato" directories
# should be under git control. The files in etc/check_mk/*.mk should not be put under control.
def write_gitignore_files():
    file(cmk.paths.default_config_dir + "/.gitignore",
         "w").write("# This file is under control of Check_MK. Please don't modify it.\n"
                    "# Your changes will be overwritten.\n"
                    "\n"
                    "*\n"
                    "!*.d\n"
                    "!.gitignore\n"
                    "*swp\n"
                    "*.mk.new\n")

    for subdir in os.listdir(cmk.paths.default_config_dir):
        if subdir.endswith(".d"):
            file(cmk.paths.default_config_dir + "/" + subdir + "/.gitignore", "w").write("*\n"
                                                                                         "!wato\n")

            if os.path.exists(cmk.paths.default_config_dir + "/" + subdir + "/wato"):
                file(cmk.paths.default_config_dir + "/" + subdir + "/wato/.gitignore",
                     "w").write("!*\n")


# Make sure that the user is in all of cgs contact groups.
# This is needed when the user assigns contact groups to
# objects. He may only assign such groups he is member himself.
def must_be_in_contactgroups(cgspec):
    if config.user.may("wato.all_folders"):
        return

    # No contact groups specified
    if cgspec == None:
        return

    cgconf = convert_cgroups_from_tuple(cgspec)
    cgs = cgconf["groups"]
    users = userdb.load_users()
    if config.user.id not in users:
        user_cgs = []
    else:
        user_cgs = users[config.user.id]["contactgroups"]
    for c in cgs:
        if c not in user_cgs:
            raise MKAuthException(
                _("Sorry, you cannot assign the contact group '<b>%s</b>' "
                  "because you are not member in that group. Your groups are: <b>%s</b>") %
                (c, ", ".join(user_cgs)))


def may_edit_configvar(varname):
    if varname in ["actions"]:
        return config.user.may("wato.add_or_modify_executables")
    return True


# TODO: Move to Folder()?
def check_wato_foldername(htmlvarname, name, just_name=False):
    if not just_name and Folder.current().has_subfolder(name):
        raise MKUserError(htmlvarname, _("A folder with that name already exists."))

    if not name:
        raise MKUserError(htmlvarname, _("Please specify a name."))

    if not re.match("^[-a-z0-9A-Z_]*$", name):
        raise MKUserError(
            htmlvarname,
            _("Invalid folder name. Only the characters a-z, A-Z, 0-9, _ and - are allowed."))


# TODO: Move to Folder()?
def create_wato_foldername(title, in_folder=None):
    if in_folder == None:
        in_folder = Folder.current()

    basename = convert_title_to_filename(title)
    c = 1
    name = basename
    while True:
        if not in_folder.has_subfolder(name):
            break
        c += 1
        name = "%s-%d" % (basename, c)
    return name


# TODO: Move to Folder()?
def convert_title_to_filename(title):
    converted = ""
    for c in title.lower():
        if c == u'ä':
            converted += 'ae'
        elif c == u'ö':
            converted += 'oe'
        elif c == u'ü':
            converted += 'ue'
        elif c == u'ß':
            converted += 'ss'
        elif c in "abcdefghijklmnopqrstuvwxyz0123456789-_":
            converted += c
        else:
            converted += "_"
    return str(converted)


def rename_host_in_list(thelist, oldname, newname):
    did_rename = False
    for nr, element in enumerate(thelist):
        if element == oldname:
            thelist[nr] = newname
            did_rename = True
        elif element == '!' + oldname:
            thelist[nr] = '!' + newname
            did_rename = True
    return did_rename


# TODO: Deprecate this legacy format with 1.4.0 or later?!
def mk_eval(s):
    try:
        if not config.wato_legacy_eval:
            return ast.literal_eval(base64.b64decode(s))
        return pickle.loads(base64.b64decode(s))
    except:
        raise MKGeneralException(_('Unable to parse provided data: %s') % html.render_text(repr(s)))


def mk_repr(s):
    if not config.wato_legacy_eval:
        return base64.b64encode(repr(s))
    return base64.b64encode(pickle.dumps(s))


def format_config_value(value):
    format_func = pprint.pformat if config.wato_pprint_config else repr
    return format_func(value)


class LivestatusViaTCP(Dictionary):
    def __init__(self, **kwargs):
        kwargs["elements"] = [
            ("port",
             Integer(
                 title=_("TCP port"),
                 minvalue=1,
                 maxvalue=65535,
                 default_value=kwargs.get("tcp_port", 6557),
             )),
            ("only_from",
             ListOfStrings(
                 title=_("Restrict access to IP addresses"),
                 help=_("The access to Livestatus via TCP will only be allowed from the "
                        "configured source IP addresses. You can either configure specific "
                        "IP addresses or networks in the syntax <tt>10.3.3.0/24</tt>."),
                 valuespec=IPv4Network(),
                 orientation="horizontal",
                 allow_empty=False,
             )),
        ]
        kwargs["optional_keys"] = ["only_from"]
        super(LivestatusViaTCP, self).__init__(**kwargs)


def get_hostnames_from_checkboxes(filterfunc=None):
    """Create list of all host names that are select with checkboxes in the current file.
    This is needed for bulk operations."""
    show_checkboxes = html.var("show_checkboxes") == "1"
    if show_checkboxes:
        selected = weblib.get_rowselection('wato-folder-/' + Folder.current().path())
    search_text = html.var("search")

    selected_host_names = []
    for host_name, host in sorted(Folder.current().hosts().items()):
        if (not search_text or (search_text.lower() in host_name.lower())) \
            and (not show_checkboxes or ('_c_' + host_name) in selected):
            if filterfunc == None or \
               filterfunc(host):
                selected_host_names.append(host_name)
    return selected_host_names


def get_hosts_from_checkboxes(filterfunc=None):
    """Create list of all host objects that are select with checkboxes in the current file.
    This is needed for bulk operations."""
    folder = Folder.current()
    return [folder.host(host_name) for host_name in get_hostnames_from_checkboxes(filterfunc)]


#.
#   .--CME-----------------------------------------------------------------.
#   |                          ____ __  __ _____                           |
#   |                         / ___|  \/  | ____|                          |
#   |                        | |   | |\/| |  _|                            |
#   |                        | |___| |  | | |___                           |
#   |                         \____|_|  |_|_____|                          |
#   |                                                                      |
#   +----------------------------------------------------------------------+
#   | Managed Services Edition specific things                             |
#   '----------------------------------------------------------------------'
# TODO: This has been moved directly into watolib because it was not easily possible
# to extract Folder/Host dependencies to a separate module. As soon as we have untied
# this we should re-establish a watolib plugin hierarchy and move this to a CME
# specific watolib plugin


class CMEFolder(CREFolder):
    def edit(self, new_title, new_attributes):
        if "site" in new_attributes:
            site_id = new_attributes["site"]
            if not self.is_root():
                self.parent()._check_parent_customer_conflicts(site_id)
            self._check_childs_customer_conflicts(site_id)

        super(CMEFolder, self).edit(new_title, new_attributes)

    def _check_parent_customer_conflicts(self, site_id):
        new_customer_id = managed.get_customer_of_site(site_id)
        customer_id = self._get_customer_id()

        if new_customer_id == managed.default_customer_id() and\
           customer_id     != managed.default_customer_id():
            raise MKUserError(
                None,
                _("The configured target site refers to the default customer <i>%s</i>. The parent folder however, "
                  "already have the specific customer <i>%s</i> set. This violates the CME folder hierarchy."
                 ) % (managed.get_customer_name_by_id(managed.default_customer_id()),
                      managed.get_customer_name_by_id(customer_id)))

        # The parents customer id may be the default customer or the same customer
        customer_id = self._get_customer_id()
        if customer_id not in [managed.default_customer_id(), new_customer_id]:
            folder_sites = ", ".join(managed.get_sites_of_customer(customer_id))
            raise MKUserError(None, _("The configured target site <i>%s</i> for this folder is invalid. The folder <i>%s</i> already belongs "
                                      "to the customer <i>%s</i>. This violates the CME folder hierarchy. You may choose the "\
                                      "following sites <i>%s</i>.") % (config.allsites()[site_id]["alias"],
                                                                       self.title(),
                                                                       managed.get_customer_name_by_id(customer_id),
                                                                       folder_sites))

    def _check_childs_customer_conflicts(self, site_id):
        customer_id = managed.get_customer_of_site(site_id)
        # Check hosts
        self._check_hosts_customer_conflicts(site_id)

        # Check subfolders
        for subfolder in self.all_subfolders().values():
            subfolder_explicit_site = subfolder.attributes().get("site")
            if subfolder_explicit_site:
                subfolder_customer = subfolder._get_customer_id()
                if subfolder_customer != customer_id:
                    raise MKUserError(None, _("The subfolder <i>%s</i> has the explicit site <i>%s</i> set, which belongs to "
                                              "customer <i>%s</i>. This violates the CME folder hierarchy.") %\
                                              (subfolder.title(),
                                               config.allsites()[subfolder_explicit_site]["alias"],
                                               managed.get_customer_name_by_id(subfolder_customer)))

            subfolder._check_childs_customer_conflicts(site_id)

    def _check_hosts_customer_conflicts(self, site_id):
        customer_id = managed.get_customer_of_site(site_id)
        for host in self.hosts().values():
            host_explicit_site = host.attributes().get("site")
            if host_explicit_site:
                host_customer = managed.get_customer_of_site(host_explicit_site)
                if host_customer != customer_id:
                    raise MKUserError(None, _("The host <i>%s</i> has the explicit site <i>%s</i> set, which belongs to "
                                              "customer <i>%s</i>. This violates the CME folder hierarchy.") %\
                                              (host.name(),
                                               config.allsites()[host_explicit_site]["alias"],
                                               managed.get_customer_name_by_id(host_customer)))

    def create_subfolder(self, name, title, attributes):
        if "site" in attributes:
            self._check_parent_customer_conflicts(attributes["site"])
        return super(CMEFolder, self).create_subfolder(name, title, attributes)

    def move_subfolder_to(self, subfolder, target_folder):
        target_folder_customer = target_folder._get_customer_id()
        if target_folder_customer != managed.default_customer_id():
            result_dict = {
                "explicit_host_sites": {},  # May be used later on to
                "explicit_folder_sites": {},  # improve error message
                "involved_customers": set()
            }
            subfolder._determine_involved_customers(result_dict)
            other_customers = result_dict["involved_customers"] - set([target_folder_customer])
            if other_customers:
                other_customers_text = ", ".join(
                    map(managed.get_customer_name_by_id, other_customers))
                raise MKUserError(
                    None,
                    _("Cannot move folder. Some of its elements have specifically other customers set (<i>%s</i>). "
                      "This violates the CME folder hierarchy.") % other_customers_text)

        # The site attribute is not explicitely set. The new inheritance might brake something..
        super(CMEFolder, self).move_subfolder_to(subfolder, target_folder)

    def create_hosts(self, entries):
        customer_id = self._get_customer_id()
        if customer_id != managed.default_customer_id():
            for hostname, attributes, _cluster_nodes in entries:
                self.check_modify_host(hostname, attributes)

        super(CMEFolder, self).create_hosts(entries)

    def check_modify_host(self, hostname, attributes):
        if "site" not in attributes:
            return

        customer_id = self._get_customer_id()
        if customer_id != managed.default_customer_id():
            host_customer_id = managed.get_customer_of_site(attributes["site"])
            if host_customer_id != customer_id:
                folder_sites = ", ".join(managed.get_sites_of_customer(customer_id))
                raise MKUserError(
                    None,
                    _("Unable to modify host <i>%s</i>. Its site id <i>%s</i> conflicts with the customer <i>%s</i>, "
                      "which owns this folder. This violates the CME folder hierarchy. You may "
                      "choose the sites: %s") %
                    (hostname, config.allsites()[attributes["site"]]["alias"], customer_id,
                     folder_sites))

    def move_hosts(self, host_names, target_folder):
        # Check if the target folder may have this host
        # A host from customerA is not allowed in a customerB folder
        target_site_id = target_folder.site_id()

        # Check if the hosts are moved to a provider folder
        target_customer_id = managed.get_customer_of_site(target_site_id)
        if target_customer_id != managed.default_customer_id():
            allowed_sites = managed.get_sites_of_customer(target_customer_id)
            for hostname in host_names:
                host = self.host(hostname)
                host_site = host.attributes().get("site")
                if not host_site:
                    continue
                if host_site not in allowed_sites:
                    raise MKUserError(None, _("Unable to move host <i>%s</i>. Its explicit set site attribute <i>%s</i> "\
                                              "belongs to customer <i>%s</i>. The target folder however, belongs to customer <i>%s</i>. "\
                                              "This violates the folder CME folder hierarchy.") % \
                                              (hostname, config.allsites()[host_site]["alias"],
                                                managed.get_customer_of_site(host_site),
                                                managed.get_customer_of_site(target_site_id)))

        super(CMEFolder, self).move_hosts(host_names, target_folder)

    def _get_customer_id(self):
        customer_id = managed.get_customer_of_site(self.site_id())
        return customer_id

    def _determine_involved_customers(self, result_dict):
        self._determine_explicit_set_site_ids(result_dict)
        result_dict["involved_customers"].update(
            set(map(managed.get_customer_of_site, result_dict["explicit_host_sites"].keys())))
        result_dict["involved_customers"].update(
            map(managed.get_customer_of_site, result_dict["explicit_folder_sites"].keys()))

    def _determine_explicit_set_site_ids(self, result_dict):
        for host in self.hosts().values():
            host_explicit_site = host.attributes().get("site")
            if host_explicit_site:
                result_dict["explicit_host_sites"].setdefault(host_explicit_site,
                                                              []).append(host.name())

        for subfolder in self.all_subfolders().values():
            subfolder_explicit_site = subfolder.attributes().get("site")
            if subfolder_explicit_site:
                result_dict["explicit_folder_sites"].setdefault(subfolder_explicit_site,
                                                                []).append(subfolder.title())
            subfolder._determine_explicit_set_site_ids(result_dict)

        return result_dict


class CMEHost(CREHost):
    def edit(self, attributes, cluster_nodes):
        self.folder().check_modify_host(self.name(), attributes)
        super(CMEHost, self).edit(attributes, cluster_nodes)


if cmk.is_managed_edition():
    Folder = CMEFolder
    Host = CMEHost
else:
    Folder = CREFolder
    Host = CREHost
