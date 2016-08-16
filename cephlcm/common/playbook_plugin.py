# -*- coding: utf-8 -*-
"""Base plugin structure for playbook."""


import abc
import contextlib
import copy
import os
import shutil
import subprocess
import sys

import pkg_resources

try:
    import simplejson as json
except ImportError:
    import json

import toml

from cephlcm.common import config
from cephlcm.common import log


CONF = config.make_controller_config()
"""Config."""

LOG = log.getLogger(__name__)
"""Logger."""

ENV_ENTRY_POINT = "CEPHLCM_ENTRYPOINT"
ENV_TASK_ID = "CEPHLCM_TASK_ID"
DYNAMIC_INVENTORY_PATH = shutil.which("cephlcm-inventory")


class Base(metaclass=abc.ABCMeta):

    NAME = None
    PLAYBOOK_FILENAME = None
    CONFIG_FILENAME = None
    DESCRIPTION = ""
    PUBLIC = True
    PROCESS_STDOUT = subprocess.PIPE
    PROCESS_STDERR = subprocess.PIPE
    PROCESS_STDIN = subprocess.DEVNULL

    def __init__(self, entry_point, module_name):
        self.NAME = self.NAME or entry_point
        self.PLAYBOOK_FILENAME = self.PLAYBOOK_FILENAME or "playbook.yaml"
        self.CONFIG_FILENAME = self.CONFIG_FILENAME or "config.toml"

        self.module_name = module_name
        self.entry_point = entry_point
        self.config = self.load_config(self.CONFIG_FILENAME)

    def get_filename(self, filename):
        return pkg_resources.resource_filename(self.module_name, filename)

    def load_config(self, config):
        return toml.load(self.get_filename(config or self.CONFIG_FILENAME))

    def get_extra_vars(self):
        return {}

    def get_environment_variables(self, task):
        new_env = copy.deepcopy(os.environ)

        new_env[ENV_ENTRY_POINT] = self.entry_point
        new_env[ENV_TASK_ID] = str(task._id)
        new_env["ANSIBLE_CONFIG"] = str(CONF.CONTROLLER_ANSIBLE_CONFIG)

        return new_env

    @abc.abstractmethod
    def get_dynamic_inventory(self, task_id):
        raise NotImplementedError()

    @contextlib.contextmanager
    def execute(self, task):
        LOG.info("Execute pre-run step for %s", self.entry_point)
        self.on_pre_execute(task)
        LOG.info("Finish execution of pre-run step for %s", self.entry_point)

        commandline = self.compose_command(task)
        env = self.get_environment_variables(task)

        LOG.info("Execute %s for %s",
                 subprocess.list2cmdline(commandline), self.entry_point)

        process = None
        try:
            process = self.run(commandline, env)
        finally:
            if process:
                if self.PROCESS_STDOUT is subprocess.PIPE:
                    LOG.debug("STDOUT of %d: %s",
                              process.pid, process.stdout.read())
                if self.PROCESS_STDERR is subprocess.PIPE:
                    LOG.debug("STDERR of %d: %s",
                              process.pid, process.stderr.read())
            LOG.info("Execute post-run step for %s", self.entry_point)
            self.on_post_execute(task, *sys.exc_info())
            LOG.info("Finish execution of post-run step for %s",
                     self.entry_point)

        LOG.info("Finish execute %s for %s",
                 subprocess.list2cmdline(commandline), self.entry_point)

    def on_pre_execute(self, task):
        pass

    def on_post_execute(self, task, *exc_info):
        pass

    @abc.abstractmethod
    def compose_command(self, task):
        pass

    def run(self, commandline, env):
        return subprocess.Popen(
            commandline, env=env,
            stdout=self.PROCESS_STDOUT, stdin=self.PROCESS_STDIN,
            stderr=self.PROCESS_STDERR
        )


class Ansible(Base):

    ANSIBLE_CMD = shutil.which("ansible")
    MODULE = None

    @abc.abstractmethod
    def compose_command(self, task):
        if not self.ANSIBLE_CMD:
            # TODO(Sergey Arkhipov): Proper exception class
            raise Exception
        if not self.MODULE:
            # TODO(Sergey Arkhipov): Proper exception class
            raise Exception

        cmdline = [self.ANSIBLE_CMD]
        cmdline.extend(["--inventory-file", DYNAMIC_INVENTORY_PATH])
        cmdline.extend(["--module-name", self.MODULE])

        extra = self.get_extra_vars()
        if extra:
            cmdline.extend(["--extra-vars", json.dumps(extra)])

        return cmdline


class Playbook(Base, metaclass=abc.ABCMeta):
    pass