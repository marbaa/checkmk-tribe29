#!/usr/bin/env python
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

# needs to issue a command like
# ssh USER@HOSTNAME 'echo \<\<\<ibm_svc_host:sep\(58\)\>\>\>; lshost -delim :; echo \<\<\<ibm_svc_license:sep\(58\)\>\>\>; lslicense -delim :; echo \<\<\<ibm_svc_mdisk:sep\(58\)\>\>\>; lsmdisk -delim :; echo \<\<\<ibm_svc_mdiskgrp:sep\(58\)\>\>\>; lsmdiskgrp -delim :; echo \<\<\<ibm_svc_node:sep\(58\)\>\>\>; lsnode -delim :; echo \<\<\<ibm_svc_nodestats:sep\(58\)\>\>\>; lsnodestats -delim :; echo \<\<\<ibm_svc_system:sep\(58\)\>\>\>; lssystem -delim :; echo \<\<\<ibm_svc_systemstats:sep\(58\)\>\>\>; lssystemstats -delim :'

from __future__ import print_function
import os
import sys
import getopt
import cmk.utils.cmk_subprocess as subprocess


def usage():
    sys.stderr.write("""Check_MK SVC / V7000 Agent

USAGE: agent_ibmsvc [OPTIONS] HOST
       agent_ibmsvc -h

ARGUMENTS:
  HOST                          Host name or IP address of the target device

OPTIONS:
  -h, --help                    Show this help message and exit
  -u USER, --user USER          Username for EMC VNX login

                                We try to use SSH key authentification.
                                Private key must be pre-created in ~/.ssh/

  -k, --accept-any-hostkey      Accept any SSH Host Key
                                Please note: This might be a security issue because
                                man-in-the-middle attacks are not recognized

  --debug                       Debug mode: write some debug messages,
                                let Python exceptions come through

  --profile                     Enable performance profiling in Python source code

  -i MODULES, --modules MODULES Modules to query. This is a comma separated list of
                                which may contain the keywords "lshost", "lslicense",
                                "lsmdisk", "lsmdiskgrp", "lsnode", "lsnodestats",
                                "lssystem", "lssystemstats", "lseventlog", "lsportfc"
                                "lsenclosure", "lsenclosurestats", "lsarray", "lsportsas"
                                or "all" to define which information should be queried
                                from the device.
                                You can define to use only view of them to optimize
                                performance. The default is "all".

""")


#############################################################################
# command line options
#############################################################################


def main(sys_argv=None):
    if sys_argv is None:
        sys_argv = sys.argv[1:]

    short_options = 'hu:p:t:m:i:k'
    long_options = [
        'help', 'user=', 'debug', 'timeout=', 'profile', 'modules=', 'accept-any-hostkey'
    ]

    try:
        opts, args = getopt.getopt(sys_argv, short_options, long_options)
    except getopt.GetoptError as err:
        sys.stderr.write("%s\n" % err)
        return 1

    opt_debug = False
    opt_timeout = 10
    opt_any_hostkey = ""

    g_profile = None
    g_profile_path = "ibmsvc_profile.out"

    host_address = None
    user = None
    mortypes = ['all']

    command_options = {
        "lshost": {
            "section_header": "ibm_svc_host",
            "active": False,
            "command": "lshost -delim :"
        },
        "lslicense": {
            "section_header": "ibm_svc_license",
            "active": False,
            "command": "lslicense -delim :"
        },
        "lsmdisk": {
            "section_header": "ibm_svc_mdisk",
            "active": False,
            "command": "lsmdisk -delim :"
        },
        "lsmdiskgrp": {
            "section_header": "ibm_svc_mdiskgrp",
            "active": False,
            "command": "lsmdiskgrp -delim :"
        },
        "lsnode": {
            "section_header": "ibm_svc_node",
            "active": False,
            "command": "lsnode -delim :"
        },
        "lsnodestats": {
            "section_header": "ibm_svc_nodestats",
            "active": False,
            "command": "lsnodestats -delim :"
        },
        "lssystem": {
            "section_header": "ibm_svc_system",
            "active": False,
            "command": "lssystem -delim :"
        },
        "lssystemstats": {
            "section_header": "ibm_svc_systemstats",
            "active": False,
            "command": "lssystemstats -delim :"
        },
        "lseventlog": {
            "section_header": "ibm_svc_eventlog",
            "active": False,
            "command": "lseventlog -expired no -fixed no -monitoring no -order severity -message no -delim : -nohdr"
        },
        "lsportfc": {
            "section_header": "ibm_svc_portfc",
            "active": False,
            "command": "lsportfc -delim :"
        },
        "lsenclosure": {
            "section_header": "ibm_svc_enclosure",
            "active": False,
            "command": "lsenclosure -delim :"
        },
        "lsenclosurestats": {
            "section_header": "ibm_svc_enclosurestats",
            "active": False,
            "command": "lsenclosurestats -delim :"
        },
        "lsarray": {
            "section_header": "ibm_svc_array",
            "active": False,
            "command": "lsarray -delim :"
        },
        "lsportsas": {
            "section_header": "ibm_svc_portsas",
            "active": False,
            "command": "lsportsas -delim :"
        },
        "disks": {
            "section_header": "ibm_svc_disks",
            "active": False,
            "command": "svcinfo lsdrive -delim :"
        },
    }

    for o, a in opts:
        if o in ['--debug']:
            opt_debug = True
        elif o in ['--profile']:
            import cProfile
            g_profile = cProfile.Profile()
            g_profile.enable()
        elif o in ['-u', '--user']:
            user = a
        elif o in ['-i', '--modules']:
            mortypes = a.split(',')
        elif o in ['-t', '--timeout']:
            opt_timeout = int(a)
        elif o in ['-k', '--accept-any-hostkey']:
            opt_any_hostkey = "-o StrictHostKeyChecking=no"
        elif o in ['-h', '--help']:
            usage()
            sys.exit(0)

    if len(args) == 1:
        host_address = args[0]
    elif not args:
        sys.stderr.write("ERROR: No host given.\n")
        return 1
    else:
        sys.stderr.write("ERROR: Please specify exactly one host.\n")
        return 1

    if user is None:
        sys.stderr.write("ERROR: No user name given.\n")
        return 1

    for module in command_options:
        try:
            if mortypes.index("all") >= 0:
                command_options[module]["active"] = True
        except ValueError:
            pass

        try:
            if mortypes.index(module) >= 0:
                command_options[module]["active"] = True
        except ValueError:
            pass

    #############################################################################
    # fetch information by ssh
    #############################################################################

    cmd = "ssh -o ConnectTimeout=%s %s %s@%s '" % (opt_timeout, opt_any_hostkey, user, host_address)

    for module in command_options:
        if command_options[module]["active"]:
            cmd += r"echo \<\<\<%s:sep\(58\)\>\>\>;" % command_options[module]["section_header"]
            cmd += "%s || true;" % command_options[module]["command"]
    cmd += "'"

    if opt_debug:
        sys.stderr.write("executing external command: %s\n" % cmd)

    result = subprocess.Popen(  # nosec
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=None,
        encoding="utf-8",
    )
    stdout, stderr = result.communicate()
    exit_code = result.wait()

    if exit_code not in [0, 1]:
        msg = "Error connecting via ssh: %s\n" % stderr
        sys.stderr.write(msg.encode("utf-8"))
        sys.exit(2)

    lines = stdout.split('\n')

    if lines[0].startswith("CMMVC7016E") or (len(lines) > 1 and lines[1].startswith("CMMVC7016E")):
        sys.stderr.write(stdout.encode("utf-8"))
        sys.exit(2)

    # Quite strange.. Why not simply print stdout?
    for line in lines:
        print(line)

    if g_profile:
        g_profile.dump_stats(g_profile_path)
        show_profile = os.path.join(os.path.dirname(g_profile_path), 'show_profile.py')
        open(show_profile, "w")\
            .write("#!/usr/bin/python\n"
                   "import pstats\n"
                   "stats = pstats.Stats('%s')\n"
                   "stats.sort_stats('time').print_stats()\n" % g_profile_path)
        os.chmod(show_profile, 0o755)

        sys.stderr.write("Profile '%s' written. Please run %s.\n" % (g_profile_path, show_profile))
