#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (C) 2019 tribe29 GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

import functools
import sys
import traceback

import flask
import werkzeug

if sys.version_info[0] >= 3:
    from pathlib import Path  # pylint: disable=import-error
else:
    from pathlib2 import Path  # pylint: disable=import-error

from connexion import FlaskApi, AbstractApp, RestyResolver, problem  # type: ignore[import]
from connexion.apps.flask_app import FlaskJSONEncoder  # type: ignore[import]

from cmk.gui.wsgi.auth import with_user
from cmk.utils import paths


def openapi_spec_dir():
    return paths.web_dir + "/htdocs/openapi"


class CheckmkApi(FlaskApi):
    pass


def wrap_result(function_resolver, result_wrap):
    """Wrap the result of a resolver with another function.

    """
    @functools.wraps(function_resolver)
    def wrapper(*args, **kw):
        return result_wrap(function_resolver(*args, **kw))

    return wrapper


class CheckmkApiApp(AbstractApp):
    def __init__(self, import_name, **kwargs):
        resolver = RestyResolver('cmk.gui.plugins.openapi.endpoints')
        resolver.function_resolver = wrap_result(resolver.function_resolver, with_user)

        kwargs.setdefault('resolver', resolver)
        super(CheckmkApiApp, self).__init__(import_name, api_cls=CheckmkApi, **kwargs)

    def create_app(self):
        """Will be persisted on self.app, where __call__ will dispatch to."""
        app = flask.Flask(self.import_name)
        app.json_encoder = FlaskJSONEncoder
        return app

    def get_root_path(self):
        return Path(self.app.root_path)

    def add_api_blueprint(self, specification, **kwargs):
        api = self.add_api(specification, **kwargs)  # type: CheckmkApi
        api.add_swagger_ui()
        self.app.register_blueprint(api.blueprint)
        return api

    def log_error(self, exception):
        _, exc_val, exc_tb = sys.exc_info()
        if hasattr(exception, 'name'):
            resp = problem(
                title=exception.name,
                detail=exception.description,
                status=exception.code,
            )
        else:
            resp = problem(
                title=repr(exc_val),
                detail=''.join(traceback.format_tb(exc_tb)),
                status=500,
            )
        return FlaskApi.get_response(resp)

    def set_errors_handlers(self):
        for error_code in werkzeug.exceptions.default_exceptions:
            self.app.register_error_handler(error_code, self.log_error)
        self.app.register_error_handler(Exception, self.log_error)

    def run(self, port=None, server=None, debug=None, host=None, **options):
        raise NotImplementedError()
