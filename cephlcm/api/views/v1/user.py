# -*- coding: utf-8 -*-
"""This module contains view for /v1/user API."""


from __future__ import absolute_import
from __future__ import unicode_literals

import flask
import six

# from cephlcm.api import auth
from cephlcm.api import exceptions
from cephlcm.api import validators
from cephlcm.api.views import generic
from cephlcm.common.models import user


DATA_SCHEMA = {
    "login": {"$ref": "#/definitions/non_empty_string"},
    "email": {"$ref": "#/definitions/email"},
    "full_name": {"$ref": "#/definitions/non_empty_string"},
    "role_ids": {"$ref": "#/definitions/uuid4_array"}
}
"""Schema for the payload."""

MODEL_SCHEMA = validators.create_model_schema("user", DATA_SCHEMA)
"""Schema for the model with optional data fields."""

POST_SCHEMA = validators.create_data_schema(DATA_SCHEMA, True)
"""Schema for the new model request."""


class UserView(generic.VersionedCRUDView):
    """Implementation of view for /v1/user/."""

    # decorators = [auth.require_authentication]

    NAME = "user"
    MODEL_NAME = "user"
    ENDPOINT = "/user/"
    PARAMETER_TYPE = "uuid"

    @property
    def initiator_id(self):
        token = getattr(flask.g, "token", None)
        user_id = getattr(token, "user_id", None)

        return user_id

    def get_all(self):
        return user.UserModel.list_models(self.pagination)

    @validators.with_model(user.UserModel)
    def get_item(self, item_id, item, *args):
        return item

    def get_versions(self, item_id):
        return user.UserModel.list_versions(str(item_id), self.pagination)

    def get_version(self, item_id, version):
        model = user.UserModel.find_version(str(item_id), int(version))

        if not model:
            raise exceptions.NotFound

        return model

    @validators.with_model(user.UserModel)
    @validators.require_schema(MODEL_SCHEMA)
    def put(self, item_id, item):
        for key, value in six.iteritems(self.request_json["data"]):
            setattr(item, key, value)
        item.initiator_id = self.initiator_id

        item.save()

        return item

    @validators.require_schema(POST_SCHEMA)
    def post(self):
        user_model = user.UserModel.make_user(
            self.request_json["login"],
            # TODO(Sergey Arkhipov): Password!
            "PASSWORD",
            self.request_json["email"],
            self.request_json["full_name"],
            self.request_json["role_ids"],
            initiator_id=self.initiator_id
        )

        return user_model
