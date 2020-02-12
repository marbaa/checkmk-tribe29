#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

r"""
Send notification messages to PagerDuty
=======================================

"""
from __future__ import unicode_literals

from typing import Dict  # pylint: disable=unused-import

from cmk.notification_plugins.utils import host_url_from_context, service_url_from_context, retrieve_from_passwordstore


def pagerduty_event_type(event):
    return {
        "PROBLEM": "trigger",
        "ACKNOWLEDGEMENT": "acknowledge",
        "RECOVERY": "resolve",
        "FLAPPINGSTART": "trigger",
        "FLAPPINGSTOP": "resolve",
    }[event]


def pagerduty_severity(state):
    return {
        "CRITICAL": "critical",
        "DOWN": "critical",
        "WARNING": "warning",
        "OK": "info",
        "UP": "info",
        "UNKNOWN": "error",
        "UNREACHABLE": "error",
    }[state]


def pagerduty_msg(context):
    # type: (Dict) -> Dict
    """Build the PagerDuty incident payload"""

    if context.get('WHAT', None) == "SERVICE":
        state = context["SERVICESTATE"]
        incident_key = '{SERVICEDESC}/{HOSTNAME}:{HOSTADDRESS}'.format(**context).replace(" ", "")
        incident = "{SERVICESTATE}: {SERVICEDESC} on {HOSTNAME}".format(**context)
        output = context["SERVICEOUTPUT"]
        incident_url = service_url_from_context(context)
    else:
        state = context["HOSTSTATE"]
        incident_key = '{HOSTNAME}:{HOSTADDRESS}'.format(**context).replace(" ", "")
        incident = '{HOSTNAME} is {HOSTSTATE}'.format(**context)
        output = context["HOSTOUTPUT"]
        incident_url = host_url_from_context(context)

    msg_payload = {
        "routing_key": retrieve_from_passwordstore(context.get('PARAMETER_ROUTING_KEY')),
        "event_action": pagerduty_event_type(context.get('NOTIFICATIONTYPE')),
        "dedup_key": incident_key,
        "payload": {
            "summary": incident,
            "source": context.get('HOSTADDRESS',
                                  context.get('HOSTNAME', 'Undeclared Host identifier')),
            "severity": pagerduty_severity(state),
            "custom_details": {
                "info": output,
                "host": context.get('HOSTNAME'),
                "host_address": context.get('HOSTADDRESS'),
            }
        }
    }
    if incident_url:
        msg_payload.update({"client": "Check_MK", "client_url": incident_url})

    return msg_payload
